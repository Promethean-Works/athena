"""Host-wide settings in `<data-dir>/athena.json` (docs/specs/settings-file.md).

The file is meant to be fixed in any editor when a setting keeps Athena from starting or
locks the admin out. So it's read strictly, once, at startup: a syntax error, an unknown
key or a bad value stops the server with a message naming the problem, instead of quietly
falling back to defaults (which could turn a disabled terminal back on). Missing sections
and fields take their defaults.

The parsed copy stays in memory, so hand edits made while Athena runs apply on the next
restart. A save re-reads the file and replaces only its own section, so hand edits to the
other sections survive; it refuses to overwrite a file that no longer parses.
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from athena.assistant.settings import AiSettings
from athena.files.webdav import WebDavConfig
from athena.https.settings import HttpsSettings
from athena.system_settings import SystemSettings

log = logging.getLogger(__name__)

FILE_NAME = "athena.json"
SCHEMA_NAME = "athena.schema.json"
BACKUP_SUFFIX = ".bak"
SCHEMA_KEY = "$schema"

Section = Literal["system", "https", "ai", "webdav"]

# Read-only fields the API fills in; never written to the file.
_WRITE_EXCLUDE: dict[str, Any] = {
    "system": {"tunnel_secrets_set"},
    "https": {"letsencrypt": {"dns_secrets_set"}},
}

# os.replace fails on Windows while another program (an editor, an antivirus scan) has
# the file open; it usually lets go within a moment.
_REPLACE_TRIES = 10
_REPLACE_WAIT = 0.1


class AthenaConfig(BaseModel):
    """Everything in athena.json. Each section is the model its feature already uses."""

    model_config = ConfigDict(extra="forbid")

    system: SystemSettings = Field(default_factory=SystemSettings)
    """Terminal and remote access (Settings → System)."""
    https: HttpsSettings = Field(default_factory=HttpsSettings)
    """HTTPS for Athena itself (Settings → HTTPS)."""
    ai: AiSettings = Field(default_factory=AiSettings)
    """The AI assistant (Settings → AI)."""
    webdav: WebDavConfig = Field(default_factory=WebDavConfig)
    """WebDAV access to the file locations."""


class SettingsFileError(Exception):
    """athena.json can't be read. `problems` holds one readable line per problem."""

    def __init__(self, path: Path, problems: list[str]) -> None:
        self.path = path
        self.problems = problems
        super().__init__("\n".join(problems))


def _position(text: str, loc: tuple[int | str, ...]) -> tuple[int, int] | None:
    """Line and column of the key a validation error is about, found by following its
    keys through the text (each searched after the one before). Stops at a list index,
    pointing at the list's key, since items aren't told apart."""
    pos, found = 0, None
    for part in loc:
        if not isinstance(part, str):
            break
        quoted = json.dumps(part)
        at = text.find(quoted, pos)
        while at != -1 and not text[at + len(quoted) :].lstrip().startswith(":"):
            at = text.find(quoted, at + 1)
        if at == -1:
            break
        found, pos = at, at + len(quoted)
    if found is None:
        return None
    line = text.count("\n", 0, found) + 1
    return line, found - (text.rfind("\n", 0, found) + 1) + 1


def _problems(path: Path, text: str, exc: ValidationError) -> list[str]:
    # Only the location and message: input values may be secrets or password hashes.
    out = []
    for error in exc.errors(include_url=False, include_input=False):
        where = ".".join(str(part) for part in error["loc"])
        at = _position(text, error["loc"])
        prefix = f"{path.name}:{at[0]}:{at[1]}" if at else path.name
        out.append(f"{prefix}: {where}: {error['msg']}")
    return out


def parse(path: Path, text: str) -> AthenaConfig:
    """Validate athena.json's text. Raises `SettingsFileError`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        problem = f"{path.name}:{exc.lineno}:{exc.colno}: {exc.msg}"
        raise SettingsFileError(path, [problem]) from None
    if not isinstance(data, dict):
        problem = f"{path.name}: the file must hold one JSON object {{...}}"
        raise SettingsFileError(path, [problem])
    data.pop(SCHEMA_KEY, None)
    try:
        return AthenaConfig.model_validate(data, extra="forbid")
    except ValidationError as exc:
        raise SettingsFileError(path, _problems(path, text, exc)) from None


def dump(config: AthenaConfig) -> str:
    """athena.json's text: pretty-printed, keys in model order, read-only fields left out."""
    data: dict[str, Any] = {SCHEMA_KEY: f"./{SCHEMA_NAME}"}
    for name in AthenaConfig.model_fields:
        section: BaseModel = getattr(config, name)
        data[name] = section.model_dump(mode="json", exclude=_WRITE_EXCLUDE.get(name))
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _write_private(path: Path, text: str) -> None:
    """Write `text` to a new `path` (mode 0600 on POSIX), flushed to disk."""
    path.unlink(missing_ok=True)  # O_CREAT keeps a leftover file's mode
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def _write_atomic(path: Path, text: str) -> None:
    """Replace `path` with `text` atomically, private, keeping the old file's owner
    (so `sudo athena https off` doesn't hand a per-user service a root-owned file)."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        _write_private(tmp, text)
        if os.name == "posix" and os.geteuid() == 0 and path.exists():
            old = path.stat()
            os.chown(tmp, old.st_uid, old.st_gid)
        _replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _replace(src: Path, dst: Path) -> None:
    for attempt in range(_REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_TRIES - 1:
                raise
            time.sleep(_REPLACE_WAIT)


class SettingsFile:
    """athena.json in a data dir: read once by `load()`, then saved section by section."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / FILE_NAME
        self.schema_path = data_dir / SCHEMA_NAME
        self.backup_path = data_dir / (FILE_NAME + BACKUP_SUFFIX)
        self._config: AthenaConfig | None = None
        self._lock = threading.Lock()

    def check(self) -> None:
        """Raise `SettingsFileError` if a save would be refused (the file doesn't parse).
        Call it before changing anything live that the save would record."""
        self.read()

    def read(self) -> AthenaConfig:
        """The file as it is on disk now (defaults if it's missing). Raises
        `SettingsFileError`. Doesn't change what `get()` returns."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return AthenaConfig()
        return parse(self.path, text)

    def load(self) -> AthenaConfig:
        """Read the file for this run. Writes it (with every default) when it's missing,
        so the admin can find it, and refreshes the JSON schema next to it.
        Raises `SettingsFileError`."""
        with self._lock:
            self._config = self.read()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self._write(dump(self._config))
            elif os.name == "posix":
                os.chmod(self.path, 0o600)  # a hand-made file may be world-readable
            self._write_schema()
            return self._config

    def get(self) -> AthenaConfig:
        """The settings this run uses. Don't change them in place: use `section()`."""
        if self._config is None:
            raise RuntimeError("SettingsFile.load() wasn't called")
        return self._config

    def section(self, name: Section) -> Any:
        """A copy of one section, safe to change before `save()`: if the save fails,
        the running settings stay as they were."""
        return getattr(self.get(), name).model_copy(deep=True)

    def save(self, name: Section, section: BaseModel) -> None:
        """Store one section, keeping the file's other sections as they are on disk.

        Raises `SettingsFileError` when the file on disk no longer parses, rather than
        overwriting the admin's half-done edit.
        """
        with self._lock:
            on_disk = self.read()
            current = self._config or AthenaConfig()
            if any(
                getattr(on_disk, other) != getattr(current, other)
                for other in AthenaConfig.model_fields
                if other != name
            ):
                log.warning("%s was edited by hand; those edits apply on restart", self.path)
            stored = section.model_copy(deep=True)  # later changes by the caller don't leak in
            self._write(dump(on_disk.model_copy(update={name: stored})))
            self._config = current.model_copy(update={name: stored})

    def _write(self, text: str) -> None:
        """Replace the file atomically, keeping the previous version as `.bak`."""
        if self.path.exists():
            _write_atomic(self.backup_path, self.path.read_text(encoding="utf-8"))
        _write_atomic(self.path, text)

    def _write_schema(self) -> None:
        schema = AthenaConfig.model_json_schema()
        schema["properties"] = {SCHEMA_KEY: {"type": "string"}, **schema["properties"]}
        text = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        try:
            if self.schema_path.read_text(encoding="utf-8") == text:
                return
        except FileNotFoundError:
            pass
        tmp = self.schema_path.with_name(self.schema_path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        _replace(tmp, self.schema_path)

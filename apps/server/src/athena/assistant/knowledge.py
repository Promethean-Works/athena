"""What the assistant keeps between chats (docs/design/assistant.md, part D stage 2).

- `Memory`: a notebook the model writes with `write_memory` and reads back with
  `read_memory` and `search_memory`, in `<data-dir>/assistant/memory.db` (`SqliteMemoryStore`,
  safe with two chats writing at once). Each admin has their own notes (the namespace is the
  user id, never a tool argument). A short excerpt of `MEMORY.md` goes into each request,
  attached to the admin's message so the cached prefix stays put. Off with the "Remember
  across chats" switch in Settings → AI.
- `Skills`: `<data-dir>/assistant/skills/<name>/SKILL.md`. The model sees each skill's name
  and description and loads the body with `load_capability` when it needs it.
- `AuditingScanner`: the harness `ArtifactScanner` on both, since memory and skills are text a
  later chat reads as instructions. A flagged memory write is refused, a flagged memory file is
  withheld and a flagged skill is left out. Each finding writes one `assistant.injection` audit
  row (the injected `MEMORY.md` is scanned on every request, so repeats are left out).
"""

import asyncio
import hashlib
import logging
import posixpath
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.workspaces import FileEntry, WorkspaceRef
from pydantic_ai_harness import ArtifactScanner, Memory, Skills
from pydantic_ai_harness.artifact_scanning import ArtifactScanResult
from pydantic_ai_harness.memory import SqliteMemoryStore

log = logging.getLogger(__name__)

MAX_AUDITED = 1_000
"""Findings remembered so the same one isn't audited twice (cleared when full)."""

_audited: set[str] = set()


def memory_db(data_dir: Path) -> Path:
    return data_dir / "assistant" / "memory.db"


def skills_dir(data_dir: Path) -> Path:
    return data_dir / "assistant" / "skills"


SKILLS_ROOT = "/skills"
"""Where `SkillsFolder` shows the skills folder to the harness, on every OS."""


class SkillsFolder:
    """A read-only workspace backend over the skills folder, for `Skills(workspace=...)`.

    The harness `LocalWorkspaceBackend` refuses to start on Windows (its commands need process
    groups) and workspace paths are POSIX, so the folder is shown as `/skills` and each path is
    mapped onto it. Paths can't leave the folder; writes are refused.
    """

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._ref = WorkspaceRef(provider="athena-skills", id="skills")

    @property
    def ref(self) -> WorkspaceRef:
        return self._ref

    async def working_dir(self) -> str:
        return SKILLS_ROOT

    def _host(self, path: str) -> Path:
        clean = posixpath.normpath(path)
        if clean == SKILLS_ROOT:
            return self._folder
        if not clean.startswith(SKILLS_ROOT + "/"):
            raise PermissionError(f"outside the skills folder: {path!r}")
        return self._folder.joinpath(*clean[len(SKILLS_ROOT) + 1 :].split("/"))

    async def read_bytes(self, path: str) -> bytes:
        target = self._host(path)

        def read() -> bytes:
            if target.is_dir():
                raise IsADirectoryError(path)
            return target.read_bytes()

        return await asyncio.to_thread(read)

    async def stat(self, path: str) -> FileEntry:
        target = self._host(path)

        def info() -> FileEntry:
            is_dir = target.is_dir()
            size = None if is_dir else target.stat().st_size
            return FileEntry(name=posixpath.basename(path), path=path, is_dir=is_dir, size=size)

        return await asyncio.to_thread(info)

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        target = self._host(path)
        base = posixpath.normpath(path)

        def entries() -> list[FileEntry]:
            found = []
            for child in sorted(target.iterdir(), key=lambda c: c.name):
                is_dir = child.is_dir()
                size = None if is_dir else child.stat().st_size
                found.append(
                    FileEntry(
                        name=child.name,
                        path=posixpath.join(base, child.name),
                        is_dir=is_dir,
                        size=size,
                    )
                )
            return found

        return await asyncio.to_thread(entries)

    async def exists(self, path: str) -> bool:
        try:
            target = self._host(path)
        except PermissionError:
            return False
        return await asyncio.to_thread(target.exists)

    async def realpath(self, path: str) -> str:
        return posixpath.normpath(path)

    async def write_bytes(self, path: str, data: bytes) -> None:
        raise PermissionError("the skills folder is read-only here")

    async def make_dir(self, path: str) -> None:
        raise PermissionError("the skills folder is read-only here")

    async def remove(self, path: str) -> None:
        raise PermissionError("the skills folder is read-only here")


class AuditingScanner(ArtifactScanner):
    """`ArtifactScanner` that reports each new finding to `record(source, summary)`."""

    def __init__(self, record: Callable[[str, str], None]) -> None:
        super().__init__()
        self._record = record

    def scan(self, content: str, *, source: str = "") -> ArtifactScanResult:
        result = super().scan(content, source=source)
        if result.flagged:
            digest = hashlib.sha256(f"{source}\0{content}".encode()).hexdigest()
            if digest not in _audited:
                if len(_audited) >= MAX_AUDITED:
                    _audited.clear()
                _audited.add(digest)
                try:
                    self._record(source, result.summary())
                except Exception as exc:  # an audit failure mustn't break the chat
                    log.warning("couldn't audit a flagged %s: %s", source, exc)
        return result


def knowledge_capabilities(
    data_dir: Path,
    *,
    user_id: int,
    memory: bool,
    record: Callable[[str, str], None],
) -> list[AbstractCapability[Any]]:
    scanner = AuditingScanner(record)
    folder = skills_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    found: list[AbstractCapability[Any]] = [
        Skills(
            SKILLS_ROOT,
            workspace=SkillsFolder(folder),
            missing_directories="skip",
            duplicate_names="keep_first",
            scanner=scanner,
        )
    ]
    if memory:
        found.append(
            Memory(
                SqliteMemoryStore(database=memory_db(data_dir)),
                namespace=f"user-{user_id}",
                scanner=scanner,
            )
        )
    return found

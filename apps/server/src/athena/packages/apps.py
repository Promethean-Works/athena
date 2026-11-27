"""App-level package managers: Homebrew (macOS and Linux), Flatpak and Snap (Linux)."""

import asyncio
import json
import re
from html import unescape
from typing import ClassVar

from athena.packages import http
from athena.packages.aliases import abbreviation_match, match_rank, normalize
from athena.packages.base import (
    SEARCH_LIMIT,
    InstalledPackage,
    PackageDetails,
    PackageError,
    PackageField,
    PackageManager,
    PackageRef,
    UpgradablePackage,
    column_table,
    human_kib,
    nonblank,
    parse_fields,
)

# ------------------------------------------------------------------ Homebrew

ABBREVIATION_LIMIT = 20
BREW_INFO_LIMIT = 30  # `brew info` adds versions and descriptions for the top results


def parse_brew_search(text: str) -> list[str]:
    """Names from `brew search` (piped: formulae, a blank line, then casks)."""
    return [line.strip() for line in nonblank(text) if not line.startswith("==>")]


def _json(text: str, what: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PackageError(f"{what} returned something that isn't JSON") from exc
    return data if isinstance(data, dict) else {}


def parse_brew_info(text: str) -> list[PackageRef]:
    """`brew info --json=v2 names…` → search results with versions and descriptions."""
    data = _json(text, "brew info")
    out = []
    for f in data.get("formulae", []):
        out.append(
            PackageRef(
                name=f["name"],
                version=(f.get("versions") or {}).get("stable"),
                description=f.get("desc"),
                source="formula",
                installed=bool(f.get("installed")),
            )
        )
    for c in data.get("casks", []):
        names = c.get("name") or []
        out.append(
            PackageRef(
                name=c["token"],
                title=names[0] if names and names[0] != c["token"] else None,
                version=c.get("version"),
                description=c.get("desc"),
                source="cask",
                installed=bool(c.get("installed")),
            )
        )
    return out


def parse_brew_installed(text: str) -> list[InstalledPackage]:
    data = _json(text, "brew info")
    out = []
    for f in data.get("formulae", []):
        versions = [i.get("version") for i in f.get("installed") or [] if i.get("version")]
        out.append(
            InstalledPackage(
                name=f["name"],
                version=versions[-1] if versions else None,
                description=f.get("desc"),
                source="formula",
            )
        )
    for c in data.get("casks", []):
        names = c.get("name") or []
        installed = c.get("installed")
        out.append(
            InstalledPackage(
                name=c["token"],
                title=names[0] if names and names[0] != c["token"] else None,
                version=installed if isinstance(installed, str) else None,
                description=c.get("desc"),
                source="cask",
            )
        )
    return out


def parse_brew_outdated(text: str) -> list[UpgradablePackage]:
    data = _json(text, "brew outdated")
    out = []
    for item in [*data.get("formulae", []), *data.get("casks", [])]:
        installed = item.get("installed_versions") or []
        out.append(
            UpgradablePackage(
                name=item["name"],
                version=installed[-1] if installed else None,
                latest=item.get("current_version"),
            )
        )
    return out


def parse_brew_details(text: str, source: str | None = None) -> PackageDetails:
    """`brew info --json=v2 --formula|--cask name` (Homebrew has no icons)."""
    data = _json(text, "brew info")
    formulae, casks = data.get("formulae") or [], data.get("casks") or []
    if source == "cask" or (source is None and not formulae):
        if not casks:
            raise PackageError("Homebrew doesn't know that package")
        c = casks[0]
        names = c.get("name") or []
        installed = c.get("installed")
        extra = [
            PackageField(label="tap", value=c["tap"]) if c.get("tap") else None,
            PackageField(label="updates itself", value="yes") if c.get("auto_updates") else None,
            PackageField(label="deprecated", value=c.get("deprecation_reason") or "yes")
            if c.get("deprecated")
            else None,
            PackageField(label="caveats", value=c["caveats"]) if c.get("caveats") else None,
        ]
        return PackageDetails(
            name=c["token"],
            title=names[0] if names and names[0] != c["token"] else None,
            version=c.get("version"),
            summary=c.get("desc"),
            homepage=c.get("homepage"),
            source="cask",
            installed=bool(installed),
            installed_version=installed if isinstance(installed, str) else None,
            extra=[e for e in extra if e],
        )
    if not formulae:
        raise PackageError("Homebrew doesn't know that package")
    f = formulae[0]
    keg = [i.get("version") for i in f.get("installed") or [] if i.get("version")]
    extra = [
        PackageField(label="tap", value=f["tap"]) if f.get("tap") else None,
        PackageField(label="keg-only", value=f.get("keg_only_reason", {}).get("reason") or "yes")
        if f.get("keg_only")
        else None,
        PackageField(label="deprecated", value=f.get("deprecation_reason") or "yes")
        if f.get("deprecated")
        else None,
        PackageField(label="caveats", value=f["caveats"]) if f.get("caveats") else None,
    ]
    return PackageDetails(
        name=f["name"],
        version=(f.get("versions") or {}).get("stable"),
        summary=f.get("desc"),
        homepage=f.get("homepage"),
        license=f.get("license"),
        source="formula",
        installed=bool(keg),
        installed_version=keg[-1] if keg else None,
        dependencies=f.get("dependencies") or [],
        extra=[e for e in extra if e],
    )


class Brew(PackageManager):
    id = "brew"
    label = "Homebrew"
    logo_url = "https://brew.sh/assets/img/homebrew-256x256.png"
    can_refresh = True
    env: ClassVar[dict[str, str]] = {
        "NONINTERACTIVE": "1",
        "HOMEBREW_NO_ENV_HINTS": "1",
        "HOMEBREW_NO_COLOR": "1",
    }

    async def search(self, query: str) -> list[PackageRef]:
        # Exit code 1 means "no formulae or casks found".
        found = parse_brew_search(await self.run(["brew", "search", query], "brew search", (0, 1)))
        # `brew search` only matches names as typed: add what the local lists match by
        # abbreviation (vscode -> visual-studio-code), then rank everything by how it matches.
        extra = await self._abbreviations(query)
        names = list(dict.fromkeys([*found, *extra]))
        ranks = {n: match_rank(query, n) for n in names}
        names = sorted(names, key=lambda n: (ranks[n], len(n)))[:SEARCH_LIMIT]
        if not names:
            return []
        top = names[:BREW_INFO_LIMIT]
        detailed = {
            r.name: r
            for r in parse_brew_info(
                await self.run(["brew", "info", "--json=v2", *top], "brew info")
            )
        }
        results = [detailed.get(n) or PackageRef(name=n) for n in names]
        # The display name ("VS Code") can match better than the token: rank again with it.
        results.sort(
            key=lambda r: (min(ranks[r.name], match_rank(query, r.name, r.title)), len(r.name))
        )
        return results

    async def _abbreviations(self, query: str) -> list[str]:
        """Formulae and casks whose words abbreviate to the query (both lists are local)."""
        if len(normalize(query)) < 3:
            return []
        out: list[str] = []
        for cmd in ("formulae", "casks"):
            result = await self._run(["brew", cmd], self.env)
            if result.code == 0:
                out += [n for n in nonblank(result.stdout) if abbreviation_match(query, n.strip())]
        return out[:ABBREVIATION_LIMIT]

    async def details(self, name: str, source: str | None = None) -> PackageDetails:
        kind = {"cask": ["--cask"], "formula": ["--formula"]}.get(source or "", [])
        out = await self.run(["brew", "info", "--json=v2", *kind, name], "brew info")
        return parse_brew_details(out, source)

    async def installed(self) -> list[InstalledPackage]:
        out = await self.run(["brew", "info", "--json=v2", "--installed"], "brew info")
        return parse_brew_installed(out)

    async def upgradable(self) -> list[UpgradablePackage]:
        return parse_brew_outdated(
            await self.run(["brew", "outdated", "--json=v2"], "brew outdated")
        )

    def install_argv(self, name: str, source: str | None = None) -> list[str]:
        return ["brew", "install", *(["--cask"] if source == "cask" else []), name]

    def uninstall_argv(self, name: str) -> list[str]:
        return ["brew", "uninstall", name]

    def upgrade_argv(self, name: str | None) -> list[str]:
        return ["brew", "upgrade", *([name] if name else [])]

    def refresh_argv(self) -> list[str]:
        return ["brew", "update"]


# ------------------------------------------------------------------ Flatpak


def parse_flatpak_search(text: str) -> list[PackageRef]:
    """`flatpak search --columns=application,name,version,description,remotes`."""
    out = []
    for line in nonblank(text):
        cells = line.split("\t")
        if len(cells) < 5:  # "No matches found"
            continue
        app_id, name, version, desc, remotes = cells[:5]
        out.append(
            PackageRef(
                name=app_id,
                title=name or None,
                version=version or None,
                description=desc or None,
                source=remotes.split(",")[0] or None,
            )
        )
    return out


def parse_flatpak_installed(text: str) -> list[InstalledPackage]:
    """`flatpak list --app --columns=application,name,version,origin`."""
    out = []
    for line in nonblank(text):
        cells = (line.split("\t") + [""] * 4)[:4]
        if cells[0]:
            out.append(
                InstalledPackage(
                    name=cells[0],
                    title=cells[1] or None,
                    version=cells[2] or None,
                    source=cells[3] or None,
                )
            )
    return out


def parse_flatpak_updates(text: str) -> list[UpgradablePackage]:
    """`flatpak remote-ls --updates --app --columns=application,version`."""
    out = []
    for line in nonblank(text):
        cells = [*line.split("\t"), ""][:2]
        if cells[0]:
            out.append(UpgradablePackage(name=cells[0], latest=cells[1] or None))
    return out


FLATPAK_FIELDS = {
    "id", "ref", "arch", "branch", "version", "license", "collection", "download size",
    "installed size", "runtime", "sdk", "date", "subject", "origin",
}  # fmt: skip
FLATHUB_API = "https://flathub.org/api/v2/appstream/{name}"


def html_text(html: str | None) -> str | None:
    """AppStream descriptions are small HTML (paragraphs and lists): keep the text."""
    if not html:
        return None
    text = re.sub(r"</p>|</ul>|</ol>", "\n\n", html)
    text = re.sub(r"<li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [" ".join(line.split()) for line in unescape(text).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def parse_flatpak_info(
    text: str, name: str, remote: str | None, store: dict | None = None
) -> PackageDetails:
    """`flatpak remote-info remote id` (indented `Key: value` lines), plus what Flathub's own
    AppStream data says (name, summary, license, links and the icon) when it has the app."""
    f = parse_fields(text, FLATPAK_FIELDS)
    store = store or {}
    urls = store.get("urls") or {}
    return PackageDetails(
        name=f.get("id") or name,
        title=store.get("name"),
        version=f.get("version"),
        summary=store.get("summary"),
        description=html_text(store.get("description")),
        homepage=urls.get("homepage") or urls.get("help"),
        license=f.get("license") or store.get("project_license"),
        source=remote,
        size=f.get("installed size") or f.get("download size"),
        maintainer=store.get("developer_name"),
        extra=[
            PackageField(label=label, value=f[key])
            for label, key in (("branch", "branch"), ("runtime", "runtime"), ("date", "date"))
            if f.get(key)
        ],
        icon_url=store.get("icon"),
    )


class Flatpak(PackageManager):
    id = "flatpak"
    label = "Flatpak"
    logo_url = "https://flatpak.org/favicon.ico"
    icon_hosts = ("flathub.org",)
    can_refresh = True
    _Y = ("-y", "--noninteractive")

    async def search(self, query: str) -> list[PackageRef]:
        cols = "--columns=application,name,version,description,remotes"
        results, installed = await asyncio.gather(
            self.run(["flatpak", "search", cols, query], "flatpak search"), self.installed()
        )
        found = parse_flatpak_search(results)[:SEARCH_LIMIT]
        names = {p.name for p in installed}
        for r in found:
            r.installed = r.name in names
        return found

    async def details(self, name: str, source: str | None = None) -> PackageDetails:
        remote = source or "flathub"
        out = await self.run(["flatpak", "remote-info", remote, name], "flatpak remote-info")
        store = None
        if remote == "flathub":  # Flathub's store has the summary, license and icon
            try:
                store = await http.fetch_json(FLATHUB_API.format(name=name))
            except PackageError:
                store = None
        return parse_flatpak_info(out, name, remote, store)

    async def installed(self) -> list[InstalledPackage]:
        out = await self.run(
            ["flatpak", "list", "--app", "--columns=application,name,version,origin"],
            "flatpak list",
        )
        return parse_flatpak_installed(out)

    async def upgradable(self) -> list[UpgradablePackage]:
        out, installed = await asyncio.gather(
            self.run(
                ["flatpak", "remote-ls", "--updates", "--app", "--columns=application,version"],
                "flatpak remote-ls",
            ),
            self.installed(),
        )
        current = {p.name: p.version for p in installed}
        ups = parse_flatpak_updates(out)
        for u in ups:
            u.version = current.get(u.name)
        return ups

    def install_argv(self, name: str, source: str | None = None) -> list[str]:
        return ["flatpak", "install", *self._Y, source or "flathub", name]

    def uninstall_argv(self, name: str) -> list[str]:
        return ["flatpak", "uninstall", *self._Y, name]

    def upgrade_argv(self, name: str | None) -> list[str]:
        return ["flatpak", "update", *self._Y, *([name] if name else [])]

    def refresh_argv(self) -> list[str]:
        return ["flatpak", "update", "--appstream", "-y"]


# ------------------------------------------------------------------ Snap

_VERIFIED = re.compile(r"(\*\*|✓|✪)$")


def parse_snap_find(text: str) -> list[PackageRef]:
    """`snap find`: Name, Version, Publisher, Notes, Summary."""
    out = []
    for cells in column_table(text, min_columns=5):
        if len(cells) >= 5 and cells[0]:
            out.append(
                PackageRef(
                    name=cells[0],
                    version=cells[1] or None,
                    description=cells[4] or None,
                    source=_VERIFIED.sub("", cells[2]) or None,
                )
            )
    return out


def parse_snap_list(text: str) -> list[InstalledPackage]:
    """`snap list`: Name, Version, Rev, Tracking, Publisher, Notes."""
    out = []
    for cells in column_table(text, min_columns=5):
        if cells and cells[0]:
            out.append(
                InstalledPackage(
                    name=cells[0],
                    version=cells[1] or None,
                    source=_VERIFIED.sub("", cells[4]) if len(cells) > 4 else None,
                )
            )
    return out


def parse_snap_refresh_list(text: str) -> list[UpgradablePackage]:
    """`snap refresh --list`: Name, Version, Rev, Size, Publisher, Notes."""
    return [
        UpgradablePackage(name=cells[0], latest=cells[1] or None)
        for cells in column_table(text, min_columns=5)
        if cells and cells[0]
    ]


SNAP_API = "https://api.snapcraft.io/v2/snaps/info/{name}"
SNAP_FIELDS = "summary,description,license,website,contact,publisher,media,version,download"


def parse_snap_store(data: dict, name: str) -> PackageDetails:
    """The Snap Store's `v2/snaps/info` answer: the same source `snap info` reads."""
    snap = data.get("snap") or {}
    publisher = snap.get("publisher") or {}
    channels = data.get("channel-map") or []
    stable = next(
        (
            c
            for c in channels
            if (c.get("channel") or {}).get("track") == "latest"
            and (c.get("channel") or {}).get("risk") == "stable"
        ),
        None,
    )
    size = ((stable or {}).get("download") or {}).get("size")
    icon = next((m.get("url") for m in snap.get("media") or [] if m.get("type") == "icon"), None)
    summary = snap.get("summary")
    return PackageDetails(
        name=data.get("name") or name,
        title=snap.get("title"),
        version=(stable or {}).get("version"),
        summary=summary,
        description=snap.get("description"),
        homepage=snap.get("website") or snap.get("contact"),
        license=snap.get("license"),
        source=publisher.get("display-name"),
        size=human_kib(size / 1024) if isinstance(size, int) else None,
        maintainer=publisher.get("display-name"),
        extra=[PackageField(label="publisher", value=publisher["validation"])]
        if publisher.get("validation")
        else [],
        icon_url=icon,
    )


class Snap(PackageManager):
    id = "snap"
    label = "Snap"
    logo_url = "https://snapcraft.io/favicon.ico"
    icon_hosts = ("snapcraft.io",)

    async def search(self, query: str) -> list[PackageRef]:
        found, installed = await asyncio.gather(
            self.run(["snap", "find", query], "snap find"), self.installed()
        )
        results = parse_snap_find(found)[:SEARCH_LIMIT]
        names = {p.name for p in installed}
        for r in results:
            r.installed = r.name in names
        return results

    async def details(self, name: str, source: str | None = None) -> PackageDetails:
        data = await http.fetch_json(
            SNAP_API.format(name=name) + f"?fields={SNAP_FIELDS}",
            {"Snap-Device-Series": "16"},
        )
        return parse_snap_store(data, name)

    async def installed(self) -> list[InstalledPackage]:
        return parse_snap_list(await self.run(["snap", "list"], "snap list"))

    async def upgradable(self) -> list[UpgradablePackage]:
        out, installed = await asyncio.gather(
            self.run(["snap", "refresh", "--list"], "snap refresh --list"), self.installed()
        )
        current = {p.name: p.version for p in installed}
        ups = parse_snap_refresh_list(out)
        for u in ups:
            u.version = current.get(u.name)
        return ups

    def install_argv(self, name: str, source: str | None = None) -> list[str]:
        return ["snap", "install", name]

    def uninstall_argv(self, name: str) -> list[str]:
        return ["snap", "remove", name]

    def upgrade_argv(self, name: str | None) -> list[str]:
        return ["snap", "refresh", *([name] if name else [])]

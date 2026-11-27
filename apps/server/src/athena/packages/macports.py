"""MacPorts (macOS): `port` search, installed, outdated and the install/upgrade jobs.

Reads work as the logged-in user. Changes install into /opt/local and need root: Athena
runs them through `sudo` with the admin's password (docs/design/platform.md, privilege
model). The fixtures are hand-written from MacPorts' documented output; replace them
with real captures when a Mac with MacPorts is available.
"""

import re

from athena.packages.base import (
    SEARCH_LIMIT,
    InstalledPackage,
    PackageDetails,
    PackageError,
    PackageField,
    PackageManager,
    PackageRef,
    UpgradablePackage,
    clean_dependencies,
    parse_fields,
)

_SEARCH_HEAD = re.compile(r"^(?P<name>\S+)\s+@(?P<version>\S+)(?:\s+\((?P<category>[^)]*)\))?\s*$")
_INSTALLED = re.compile(r"^\s*(?P<name>\S+)\s+@(?P<version>\S+)(?P<active>\s+\(active\))?\s*$")
_OUTDATED = re.compile(r"^(?P<name>\S+)\s+(?P<old>\S+)\s+<\s+(?P<new>\S+)\s*$")


def parse_port_search(text: str) -> list[PackageRef]:
    """`port -q search --name --glob '*q*'`: `name @version (category)`, then an indented
    description line, then a blank line."""
    out: list[PackageRef] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0].isspace():
            if out and out[-1].description is None:
                out[-1].description = line.strip()
        elif m := _SEARCH_HEAD.match(line):
            out.append(
                PackageRef(name=m["name"], version=m["version"], source=m["category"] or None)
            )
    return out


def parse_port_installed(text: str) -> list[InstalledPackage]:
    """`port -q installed`: every installed version; the `(active)` one is the one in use."""
    active: dict[str, InstalledPackage] = {}
    other: dict[str, InstalledPackage] = {}
    for line in text.splitlines():
        if m := _INSTALLED.match(line):
            pkg = InstalledPackage(name=m["name"], version=m["version"])
            (active if m["active"] else other).setdefault(m["name"], pkg)
    return list({**other, **active}.values())


def parse_port_outdated(text: str) -> list[UpgradablePackage]:
    """`port -q outdated`: `name  installed < available`."""
    return [
        UpgradablePackage(name=m["name"], version=m["old"], latest=m["new"])
        for line in text.splitlines()
        if (m := _OUTDATED.match(line.strip()))
    ]


PORT_FIELDS = {
    "homepage", "library dependencies", "build dependencies", "runtime dependencies",
    "platforms", "license", "maintainers", "variants", "sub-ports", "conflicts with",
    "extract dependencies", "fetch dependencies", "patch dependencies", "replaced by",
}  # fmt: skip


def parse_port_info(text: str, name: str) -> PackageDetails:
    """`port info name`: a `name @version (category)` line, `Key:   value` lines (long values
    wrap onto indented lines), and the description as unindented lines between them."""
    lines = text.splitlines()
    head = next((m for line in lines if (m := _SEARCH_HEAD.match(line.strip()))), None)
    prose: list[str] = []
    fields: list[str] = []
    in_field = False
    for line in lines[1:] if head else lines:
        key = line.partition(":")[0].strip().lower()
        if ":" in line and not line[:1].isspace() and key in PORT_FIELDS:
            in_field = True
            fields.append(line)
        elif line[:1].isspace() and in_field and line.strip():
            fields.append(line)
        elif line.strip():
            in_field = False
            prose.append(line.strip())
        else:
            in_field = False
            prose.append("")
    f = parse_fields("\n".join(fields), PORT_FIELDS)
    description = re.sub(r"\n{3,}", "\n\n", "\n".join(prose)).strip() or None
    deps = f.get("library dependencies", "") + "," + f.get("runtime dependencies", "")
    return PackageDetails(
        name=head["name"] if head else name,
        version=head["version"] if head else None,
        summary=description.split("\n\n")[0].replace("\n", " ") if description else None,
        description=description if description and "\n\n" in description else None,
        homepage=f.get("homepage"),
        license=f.get("license"),
        source=(head["category"] if head else None) or None,
        dependencies=clean_dependencies([d for d in deps.replace(",", " ").split() if d]),
        maintainer=f.get("maintainers"),
        extra=[
            PackageField(label=label, value=f[key])
            for label, key in (("platforms", "platforms"), ("variants", "variants"))
            if f.get(key)
        ],
    )


class MacPorts(PackageManager):
    id = "macports"
    label = "MacPorts"
    logo_url = "https://www.macports.org/img/macports-logo.png"
    can_refresh = True
    note = "MacPorts installs into /opt/local. Changes ask for your computer's password."

    async def search(self, query: str) -> list[PackageRef]:
        glob = "*" + query.replace(" ", "*") + "*"
        # Exit code 1 means "no match".
        out = await self.run(
            ["port", "-q", "search", "--name", "--glob", glob], "port search", (0, 1)
        )
        found = parse_port_search(out)[:SEARCH_LIMIT]
        names = {p.name for p in await self._installed_safe()}
        for r in found:
            r.installed = r.name in names
        return found

    async def _installed_safe(self) -> list[InstalledPackage]:
        try:
            return await self.installed()
        except PackageError:
            return []

    async def installed(self) -> list[InstalledPackage]:
        return parse_port_installed(await self.run(["port", "-q", "installed"], "port installed"))

    async def upgradable(self) -> list[UpgradablePackage]:
        # Exit code 1 and "No installed ports are outdated" when everything is current.
        out = await self.run(["port", "-q", "outdated"], "port outdated", (0, 1))
        return parse_port_outdated(out)

    async def details(self, name: str, source: str | None = None) -> PackageDetails:
        return parse_port_info(await self.run(["port", "info", name], "port info"), name)

    def install_argv(self, name: str, source: str | None = None) -> list[str]:
        return ["port", "-N", "install", name]

    def uninstall_argv(self, name: str) -> list[str]:
        return ["port", "-N", "uninstall", name]

    def upgrade_argv(self, name: str | None) -> list[str]:
        return ["port", "-N", "upgrade", name or "outdated"]

    def refresh_argv(self) -> list[str]:
        return ["port", "-N", "selfupdate"]

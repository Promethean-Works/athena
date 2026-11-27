"""NFS shares: export a file location over the network from the host's NFS server.

Linux (Athena runs as root there): Athena owns `/etc/exports.d/athena.exports`, rewrites
it from its own table after every change and runs `exportfs -ra`. macOS (Athena as root):
Athena keeps a marked block in `/etc/exports` and runs `nfsd update`. Windows has no NFS
server outside Windows Server and reports `shares.nfs` as unsupported.

See docs/specs/network-shares.md.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from athena.db.models import FileLocation, NfsShare
from athena.files import netshare
from athena.files.locations import get as get_location
from athena.files.paths import BadPath, Conflict, NotFound

NFS_EXPORTS = Path("/etc/exports.d/athena.exports")
HOSTNAME = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
MAX_CLIENTS = 32
HEADER = "# Managed by Athena. Changes here are overwritten.\n"


MACOS_EXPORTS = Path("/etc/exports")
BEGIN = "# BEGIN athena (managed by Athena, don't edit between these lines)\n"
END = "# END athena\n"


class AlreadyExported(Conflict):
    """That location is already exported over NFS."""


@dataclass
class NfsShareEntry:
    id: int
    location_id: int
    location_name: str
    path: str
    folder: str
    clients: list[str]
    read_only: bool
    created_at: datetime


def clean_clients(clients: list[str]) -> list[str]:
    """Validate the allow-list: addresses, networks (CIDR) and host names. No wildcards,
    no empty list (an NFS export with no client list would be open to everyone)."""
    out: list[str] = []
    for raw in clients:
        item = raw.strip()
        if not item:
            continue
        try:
            net = ipaddress.ip_network(item, strict=False)
        except ValueError:
            if not HOSTNAME.fullmatch(item):
                raise BadPath(
                    f"{item!r} isn't an IP address, network (CIDR) or host name"
                ) from None
            value = item.lower()
        else:
            host = str(net.network_address)
            if net.version == 6:
                host = f"[{host}]"
            value = host if net.num_addresses == 1 else f"{host}/{net.prefixlen}"
        if value not in out:
            out.append(value)
    if not out:
        raise BadPath(
            "List at least one client: an IP address, a network like 192.168.1.0/24, or a host name"
        )
    if len(out) > MAX_CLIENTS:
        raise BadPath(f"At most {MAX_CLIENTS} clients per share")
    return out


def _escape(path: str) -> str:
    """exports(5) writes spaces, tabs, newlines and backslashes as octal escapes."""
    return "".join(f"\\{ord(c):03o}" if c in " \t\n\\" else c for c in path)


def render(shares: list[NfsShare]) -> str:
    """The whole exports file for `shares`."""
    lines = [HEADER]
    for share in sorted(shares, key=lambda s: s.path):
        mode = "ro" if share.read_only else "rw"
        opts = f"{mode},sync,no_subtree_check"
        clients = " ".join(f"{c}({opts})" for c in share.clients.split(","))
        lines.append(f"{_escape(share.path)} {clients}\n")
    return "".join(lines)


def _escape_macos(path: str) -> str:
    """exports(5) on macOS: spaces are escaped with a backslash (quotes are refused earlier)."""
    return path.replace(" ", "\\ ")


def _split_client(client: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | str:
    """A stored client as a network, or the host name."""
    try:
        return ipaddress.ip_network(client.replace("[", "").replace("]", ""), strict=False)
    except ValueError:
        return client


def render_macos_block(shares: list[NfsShare]) -> str:
    """The Athena block of /etc/exports: one line per host list and one per network."""
    if not shares:
        return ""
    lines = [BEGIN]
    for share in sorted(shares, key=lambda s: s.path):
        path = _escape_macos(os.path.realpath(share.path))
        ro = " -ro" if share.read_only else ""
        hosts: list[str] = []
        nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for client in share.clients.split(","):
            parsed = _split_client(client)
            if isinstance(parsed, str):
                hosts.append(parsed)
            elif parsed.version == 4 and parsed.num_addresses == 1:
                hosts.append(str(parsed.network_address))
            else:
                nets.append(parsed)
        if hosts:
            lines.append(f"{path}{ro} {' '.join(hosts)}\n")
        for net in nets:
            lines.append(f"{path}{ro} -network {net.network_address} -mask {net.netmask}\n")
    lines.append(END)
    return "".join(lines)


def merge_block(old: str | None, block: str) -> str:
    """`old` with the Athena block replaced by `block` (appended if there was none,
    dropped if `block` is empty). Lines outside the markers are never touched."""
    text = old or ""
    start = text.find(BEGIN)
    if start != -1:
        end = text.find(END, start)
        stop = len(text) if end == -1 else end + len(END)
        text = text[:start] + text[stop:]
    if not block:
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + block


@dataclass(frozen=True)
class Flavor:
    """How one operating system's NFS server is configured."""

    exports: Path
    render: Callable[[str | None, list[NfsShare]], str]
    """(current file text or None, every share) -> the new file text."""
    reload: Callable[[], None]


def _reload_linux() -> None:
    netshare.run_reload(["exportfs", "-ra"], "the NFS exports")


def _reload_macos() -> None:
    netshare.run_command(["nfsd", "checkexports"], "reload the NFS exports")
    netshare.run_command(["nfsd", "enable"], "start the NFS server")
    netshare.run_command(["nfsd", "update"], "reload the NFS exports")


LINUX = Flavor(NFS_EXPORTS, lambda _old, shares: render(shares), _reload_linux)
MACOS = Flavor(
    MACOS_EXPORTS, lambda old, shares: merge_block(old, render_macos_block(shares)), _reload_macos
)


def flavor_for(provider: str | None) -> Flavor:
    """The flavour for a `shares.nfs` capability's provider."""
    return MACOS if provider == "nfsd" else LINUX


def _entry(db: Session, share: NfsShare) -> NfsShareEntry:
    loc = db.get(FileLocation, share.location_id)
    return NfsShareEntry(
        id=share.id,  # type: ignore[arg-type]
        location_id=share.location_id,
        location_name=loc.name if loc else "(removed)",
        path=share.path,
        folder=netshare.subfolder_of(loc.path, share.path) if loc else "",
        clients=share.clients.split(","),
        read_only=share.read_only,
        created_at=share.created_at,
    )


def list_shares(db: Session) -> list[NfsShareEntry]:
    """The NFS shares Athena created, newest first."""
    rows = db.exec(select(NfsShare).order_by(NfsShare.id.desc())).all()  # type: ignore[union-attr]
    return [_entry(db, share) for share in rows]


def create_share(
    db: Session,
    location_id: int,
    clients: list[str],
    *,
    read_only: bool = False,
    flavor: Flavor = LINUX,
    exports: Path | None = None,
    reload: Callable[[], None] | None = None,
    folder: str = "",
) -> NfsShareEntry:
    """Export `location_id` (or a `folder` inside it) to `clients`.

    The caller has checked the `shares.nfs` capability."""
    loc = get_location(db, location_id)
    shared = netshare.shared_folder(loc.path, folder)
    allowed = clean_clients(clients)
    if any(c in shared for c in "\n\r") or (flavor is MACOS and any(c in shared for c in "'\"\\")):
        raise BadPath("This folder's path can't be exported")
    if db.exec(select(NfsShare).where(NfsShare.path == shared)).first() is not None:
        what = f"{loc.name}/{folder.strip('/')}" if folder.strip("/") else loc.name
        raise AlreadyExported(f"{what} is already shared over NFS")

    share = NfsShare(
        location_id=location_id, path=shared, clients=",".join(allowed), read_only=read_only
    )
    current = list(db.exec(select(NfsShare)).all())
    _apply(flavor, exports, reload, [*current, share])
    db.add(share)
    db.commit()
    db.refresh(share)
    return _entry(db, share)


def _apply(
    flavor: Flavor,
    exports: Path | None,
    reload: Callable[[], None] | None,
    shares: list[NfsShare],
) -> None:
    path = exports or flavor.exports
    old = path.read_text(encoding="utf-8") if path.exists() else None
    netshare.swap_config(path, flavor.render(old, shares), reload or flavor.reload)


def remove_share(
    db: Session,
    share_id: int,
    *,
    flavor: Flavor = LINUX,
    exports: Path | None = None,
    reload: Callable[[], None] | None = None,
) -> None:
    """Stop exporting a share and drop its tracking row."""
    share = db.get(NfsShare, share_id)
    if share is None:
        raise NotFound("No such NFS share")
    rest = [s for s in db.exec(select(NfsShare)).all() if s.id != share_id]
    _apply(flavor, exports, reload, rest)
    db.delete(share)
    db.commit()

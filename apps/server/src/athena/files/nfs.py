"""NFS shares: export a file location over the network from the host's NFS server.

Linux (Athena runs as root there): Athena owns `/etc/exports.d/athena.exports`, rewrites
it from its own table after every change and runs `exportfs -ra`. Other operating
systems report `shares.nfs` as unsupported until their providers exist.

See docs/specs/network-shares.md.
"""

from __future__ import annotations

import ipaddress
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


class AlreadyExported(Conflict):
    """That location is already exported over NFS."""


@dataclass
class NfsShareEntry:
    id: int
    location_id: int
    location_name: str
    path: str
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


def _entry(db: Session, share: NfsShare) -> NfsShareEntry:
    loc = db.get(FileLocation, share.location_id)
    return NfsShareEntry(
        id=share.id,  # type: ignore[arg-type]
        location_id=share.location_id,
        location_name=loc.name if loc else "(removed)",
        path=share.path,
        clients=share.clients.split(","),
        read_only=share.read_only,
        created_at=share.created_at,
    )


def list_shares(db: Session) -> list[NfsShareEntry]:
    """The NFS shares Athena created, newest first."""
    rows = db.exec(select(NfsShare).order_by(NfsShare.id.desc())).all()  # type: ignore[union-attr]
    return [_entry(db, share) for share in rows]


def _reload() -> None:
    netshare.run_reload(["exportfs", "-ra"], "the NFS exports")


def create_share(
    db: Session,
    location_id: int,
    clients: list[str],
    *,
    read_only: bool = False,
    exports: Path = NFS_EXPORTS,
    reload: Callable[[], None] = _reload,
) -> NfsShareEntry:
    """Export `location_id` to `clients`. The caller has checked the `shares.nfs` capability."""
    loc = get_location(db, location_id)
    allowed = clean_clients(clients)
    if "\n" in loc.path or "\r" in loc.path:
        raise BadPath("This folder's path can't be exported")
    if db.exec(select(NfsShare).where(NfsShare.path == loc.path)).first() is not None:
        raise AlreadyExported(f"{loc.name} is already shared over NFS")

    share = NfsShare(
        location_id=location_id, path=loc.path, clients=",".join(allowed), read_only=read_only
    )
    current = list(db.exec(select(NfsShare)).all())
    netshare.swap_config(exports, render([*current, share]), reload)
    db.add(share)
    db.commit()
    db.refresh(share)
    return _entry(db, share)


def remove_share(
    db: Session, share_id: int, *, exports: Path = NFS_EXPORTS, reload: Callable[[], None] = _reload
) -> None:
    """Stop exporting a share and drop its tracking row."""
    share = db.get(NfsShare, share_id)
    if share is None:
        raise NotFound("No such NFS share")
    rest = [s for s in db.exec(select(NfsShare)).all() if s.id != share_id]
    netshare.swap_config(exports, render(rest), reload)
    db.delete(share)
    db.commit()

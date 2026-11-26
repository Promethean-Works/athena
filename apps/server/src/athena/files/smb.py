"""SMB shares: publish a file location over the network via the host's Samba server.

Linux (Athena runs as a root systemd service there): Athena adds a share section to
/etc/samba/smb.conf and reloads smbd, so the folder is available as
\\\\server\\share on the LAN. macOS and Windows have SMB sharing built in, but
creating a share from Athena is wired on macOS (`sharing`, Athena as root); Windows isn't yet.
The API checks the `shares.smb` capability before calling in here and passes its provider.

See docs/design/files.md ("SMB/NFS where the OS supports it").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from athena.db.models import FileLocation, SmbShare
from athena.files import netshare
from athena.files.locations import get as get_location
from athena.files.paths import BadPath, Conflict, NotFound

SMB_CONF = Path("/etc/samba/smb.conf")
SHARE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


class ShareNameTaken(Conflict):
    """An SMB share with that name already exists."""


@dataclass
class SmbShareEntry:
    id: int
    name: str
    location_id: int
    location_name: str
    path: str
    read_only: bool
    guest_ok: bool
    created_at: datetime


# ------------------------------------------------------------------ entries


def _entry(db: Session, share: SmbShare) -> SmbShareEntry:
    loc = db.get(FileLocation, share.location_id)
    return SmbShareEntry(
        id=share.id,
        name=share.name,
        location_id=share.location_id,
        location_name=loc.name if loc else "(removed)",
        path=share.path,
        read_only=share.read_only,
        guest_ok=share.guest_ok,
        created_at=share.created_at,
    )


def list_shares(db: Session) -> list[SmbShareEntry]:
    """The SMB shares Athena created, newest first."""
    rows = db.exec(select(SmbShare).order_by(SmbShare.id.desc())).all()  # type: ignore[union-attr]
    return [_entry(db, share) for share in rows]


# ------------------------------------------------------------------ Samba config


def _reload_smbd() -> None:
    netshare.run_reload(["systemctl", "reload", "smbd"], "Samba")


def _with_share_section(
    text: str | None, name: str, share_path: str, read_only: bool, guest_ok: bool
) -> str:
    section = (
        "\n"
        f"[{name}]\n"
        f"   path = {share_path}\n"
        f"   read only = {'yes' if read_only else 'no'}\n"
        f"   guest ok = {'yes' if guest_ok else 'no'}\n"
        f"   comment = Athena share\n"
    )
    # smbd needs at least a [global] section; add a minimal one so a brand-new
    # smb.conf is valid.
    return ("[global]\n" if text is None else text) + section


def _without_share_section(text: str, name: str) -> str:
    marker = re.compile(r"\[" + re.escape(name) + r"\]")
    out: list[str] = []
    skip = False
    for line in text.splitlines(keepends=True):
        if skip:
            if line.startswith("[") and line.endswith("]\n"):
                skip = False
                out.append(line)
            continue
        if marker.match(line.strip()):
            skip = True
            continue
        out.append(line)
    return "".join(out)


def _macos_add(name: str, path: str, read_only: bool, guest_ok: bool) -> None:
    """macOS: `sharing -a` publishes a share point over SMB. The record name equals the
    share name, so `sharing -r <name>` removes it again."""
    argv = [
        "sharing",
        "-a",
        path,
        "-n",
        name,
        "-S",
        name,
        "-s",
        "001",
        "-g",
        "001" if guest_ok else "000",
        "-R",
        "1" if read_only else "0",
    ]
    netshare.run_command(argv, f"share {name}")


# ------------------------------------------------------------------ public API


def create_share(
    db: Session,
    location_id: int,
    name: str,
    *,
    read_only: bool = False,
    guest_ok: bool = False,
    provider: str = "samba",
    conf: Path = SMB_CONF,
) -> SmbShareEntry:
    """Create an SMB share for `location_id` and publish it through Samba.

    The caller has checked the `shares.smb` capability. If Samba refuses the new
    configuration it is rolled back and `ShareReloadFailed` is raised.
    """
    loc = get_location(db, location_id)
    if not SHARE_NAME.fullmatch(name):
        raise BadPath(
            "Use letters, digits, _, - and . (up to 63 chars), not starting with - or a space"
        )
    taken = db.exec(select(SmbShare).where(SmbShare.name == name)).first()
    if taken is not None:
        raise ShareNameTaken(f"An SMB share named {name} already exists")

    if provider == "sharing":
        _macos_add(name, loc.path, read_only, guest_ok)
    else:
        old = conf.read_text(encoding="utf-8") if conf.exists() else None
        new = _with_share_section(old, name, loc.path, read_only, guest_ok)
        netshare.swap_config(conf, new, _reload_smbd)

    share = SmbShare(
        name=name,
        location_id=location_id,
        path=loc.path,
        read_only=read_only,
        guest_ok=guest_ok,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return _entry(db, share)


def remove_share(
    db: Session,
    share_id: int,
    *,
    provider: str = "samba",
    conf: Path = SMB_CONF,
) -> None:
    """Remove an SMB share: drop its smb.conf section and the tracking row."""
    share = db.get(SmbShare, share_id)
    if share is None:
        raise NotFound("No such SMB share")

    if provider == "sharing":
        netshare.run_command(["sharing", "-r", share.name], f"remove the {share.name} share")
    elif conf.exists():
        new = _without_share_section(conf.read_text(encoding="utf-8"), share.name)
        netshare.swap_config(conf, new, _reload_smbd)

    db.delete(share)
    db.commit()

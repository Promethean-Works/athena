"""SMB shares: publish a file location over the network via the host's Samba server.

Linux (Athena runs as a root systemd service there): Athena adds a share section to
/etc/samba/smb.conf and reloads smbd, so the folder is available as
\\\\server\\share on the LAN. macOS and Windows have SMB sharing built in, but
creating a share from Athena isn't wired on those operating systems yet.

See docs/mvp-design.md §4.3 ("SMB/NFS where the OS supports it").
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from athena.db.models import FileLocation, SmbShare
from athena.files.locations import get as get_location
from athena.files.paths import BadPath, Conflict, FileError, NotFound

SMB_CONF = Path("/etc/samba/smb.conf")
SHARE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


class SmbUnsupported(FileError):
    """Creating or removing SMB shares isn't available on this operating system."""

    status = 501


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


def _on_linux() -> bool:
    return sys.platform.startswith("linux")


def _reload_smbd() -> None:
    """Tell Samba to pick up smb.conf changes. Best effort: a share works once
    smbd is reloaded or restarted, so a failed reload isn't fatal."""
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            ["systemctl", "reload", "smbd"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )


def _append_share_section(
    conf: Path, name: str, share_path: str, read_only: bool, guest_ok: bool
) -> None:
    section = (
        "\n"
        f"[{name}]\n"
        f"   path = {share_path}\n"
        f"   read only = {'yes' if read_only else 'no'}\n"
        f"   guest ok = {'yes' if guest_ok else 'no'}\n"
        f"   comment = Athena share\n"
    )
    if not conf.exists():
        # smbd needs at least a [global] section; add a minimal one so a brand-new
        # smb.conf is valid.
        conf.write_text("[global]\n" + section, encoding="utf-8")
    else:
        conf.write_text(conf.read_text(encoding="utf-8") + section, encoding="utf-8")


def _remove_share_section(conf: Path, name: str) -> None:
    if not conf.exists():
        return
    marker = re.compile(r"\[" + re.escape(name) + r"\]")
    lines = conf.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    skip = False
    for line in lines:
        if skip:
            if line.startswith("[") and line.endswith("]\n"):
                skip = False
                out.append(line)
            continue
        if marker.match(line.strip()):
            skip = True
            continue
        out.append(line)
    conf.write_text("".join(out), encoding="utf-8")


# ------------------------------------------------------------------ public API


def create_share(
    db: Session,
    location_id: int,
    name: str,
    *,
    read_only: bool = False,
    guest_ok: bool = False,
    conf: Path = SMB_CONF,
) -> SmbShareEntry:
    """Create an SMB share for `location_id` and publish it through Samba.

    Raises `SmbUnsupported` on operating systems where Athena can't create SMB
    shares yet (macOS, Windows).
    """
    loc = get_location(db, location_id)
    if not SHARE_NAME.fullmatch(name):
        raise BadPath(
            "Use letters, digits, _, - and . (up to 63 chars), not starting with - or a space"
        )
    taken = db.exec(select(SmbShare).where(SmbShare.name == name)).first()
    if taken is not None:
        raise ShareNameTaken(f"An SMB share named {name} already exists")

    if _on_linux():
        _append_share_section(conf, name, loc.path, read_only, guest_ok)
        _reload_smbd()
    else:
        raise SmbUnsupported(
            "Creating SMB shares from Athena isn't available on this operating system yet"
        )

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
    conf: Path = SMB_CONF,
) -> None:
    """Remove an SMB share: drop its smb.conf section and the tracking row."""
    share = db.get(SmbShare, share_id)
    if share is None:
        raise NotFound("No such SMB share")

    if _on_linux():
        _remove_share_section(conf, share.name)
        _reload_smbd()
    else:
        raise SmbUnsupported(
            "Removing SMB shares from Athena isn't available on this operating system yet"
        )

    db.delete(share)
    db.commit()

"""Cloud remotes mounted as folders, so they can be shared over SMB or NFS
(docs/specs/share-from-explorer.md).

Athena asks its own rclone sidecar to mount the remote (`mount/mount`) under
`<data-dir>/mounts/<id>` and keeps a hidden file location at the mount point. The SMB and
NFS code then shares that location like any other folder. The mount is released when the
last share on it goes, and mounted again when Athena starts.
"""

import logging
import shutil
from pathlib import Path

from sqlmodel import Session, select

from athena.cloud import remotes
from athena.cloud.rclone import Rclone, RcloneError
from athena.db.models import FileLocation, NfsShare, RemoteMount, SmbShare
from athena.files.paths import Conflict, FileError

log = logging.getLogger("athena.cloud.mounts")

VFS_CACHE_WRITES = 2
"""rclone's `--vfs-cache-mode writes`: files being written are cached, reads stream."""


class MountFailed(FileError):
    """rclone couldn't mount the remote (FUSE missing, remote unreachable, ...)."""

    status = 502


def mount_point(data_dir: Path, mount_id: int) -> Path:
    return data_dir / "mounts" / str(mount_id)


def list_mounts(db: Session) -> list[RemoteMount]:
    return list(db.exec(select(RemoteMount).order_by(RemoteMount.id)))  # type: ignore[arg-type]


def hidden_location_ids(db: Session) -> set[int]:
    """The locations that are mount points: kept out of the file manager's own list."""
    return {m.location_id for m in db.exec(select(RemoteMount))}


def shares_on(db: Session, location_id: int) -> int:
    """How many SMB and NFS shares use this location."""
    smb = db.exec(select(SmbShare).where(SmbShare.location_id == location_id)).all()
    nfs = db.exec(select(NfsShare).where(NfsShare.location_id == location_id)).all()
    return len(smb) + len(nfs)


async def _mount(rclone: Rclone, mount: RemoteMount, *, make_dir: bool) -> None:
    point = Path(mount.mount_point)
    if make_dir:
        point.mkdir(parents=True, exist_ok=True)
    try:
        await rclone.call(
            "mount/mount",
            {
                "fs": remotes.fs_of(mount.remote, mount.path),
                "mountPoint": mount.mount_point,
                "mountType": "mount",
                "vfsOpt": {"CacheMode": VFS_CACHE_WRITES, "ReadOnly": mount.read_only},
            },
            timeout=60,
        )
    except RcloneError as exc:
        raise MountFailed(f"Couldn't mount {mount.remote}: {exc.message}") from exc


async def _is_mounted(rclone: Rclone, mount: RemoteMount) -> bool:
    try:
        listed = await rclone.call("mount/listmounts")
    except RcloneError:
        return False
    return any(m.get("MountPoint") == mount.mount_point for m in listed.get("mountPoints", []))


async def ensure(
    db: Session,
    rclone: Rclone,
    data_dir: Path,
    remote: str,
    path: str,
    *,
    read_only: bool,
    provider: str | None = None,
) -> RemoteMount:
    """The mount for `remote:path`, created and mounted if it isn't yet."""
    path = remotes.check_path(path)
    remotes.check_remote_name(remote)
    existing = db.exec(
        select(RemoteMount).where(RemoteMount.remote == remote, RemoteMount.path == path)
    ).first()
    if existing is not None:
        if not await _is_mounted(rclone, existing):
            await _mount(rclone, existing, make_dir=provider != "winfsp")
        return existing

    # The row comes first so its id names the mount point; WinFsp wants the folder not to exist.
    placeholder = FileLocation(name=f"cloud-mount-{remote}:{path}"[:64], path=str(data_dir))
    db.add(placeholder)
    db.flush()
    row = RemoteMount(
        remote=remote,
        path=path,
        mount_point="",
        location_id=placeholder.id,  # type: ignore[arg-type]
        read_only=read_only,
    )
    db.add(row)
    db.flush()
    point = mount_point(data_dir, row.id)  # type: ignore[arg-type]
    row.mount_point = str(point)
    try:
        await _mount(rclone, row, make_dir=provider != "winfsp")
    except FileError:
        db.rollback()
        shutil.rmtree(point, ignore_errors=True)
        raise
    label = f"Cloud: {remote}" + (f"/{path}" if path else "")
    placeholder.name = f"{label[:55]} #{row.id}"
    placeholder.path = str(point.resolve())
    db.add(placeholder)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


async def unmount(db: Session, rclone: Rclone, mount: RemoteMount, *, force: bool = False) -> None:
    """Unmount and forget a mount. Refused while a share still uses it (unless `force`)."""
    if not force and shares_on(db, mount.location_id):
        raise Conflict("Remove the network shares on this cloud folder first")
    try:
        await rclone.call("mount/unmount", {"mountPoint": mount.mount_point}, timeout=30)
    except RcloneError as exc:
        if await _is_mounted(rclone, mount):
            raise MountFailed(f"Couldn't unmount {mount.remote}: {exc.message}") from exc
    loc = db.get(FileLocation, mount.location_id)
    db.delete(mount)
    db.flush()  # the mount row goes first: it points at the location
    if loc is not None:
        db.delete(loc)
    db.commit()
    shutil.rmtree(mount.mount_point, ignore_errors=True)


async def release_if_unused(db: Session, rclone: Rclone, location_id: int) -> None:
    """After a share is removed: unmount its cloud folder when nothing else uses it."""
    mount = db.exec(select(RemoteMount).where(RemoteMount.location_id == location_id)).first()
    if mount is None or shares_on(db, location_id):
        return
    try:
        await unmount(db, rclone, mount)
    except FileError as exc:
        log.warning("Couldn't release the mount for %s: %s", mount.remote, exc.message)


async def restore(db: Session, rclone: Rclone, provider: str | None = None) -> None:
    """Mount every saved cloud folder again (a restart drops them). Failures are logged."""
    for mount in list_mounts(db):
        try:
            if not await _is_mounted(rclone, mount):
                await _mount(rclone, mount, make_dir=provider != "winfsp")
        except Exception as exc:  # one broken remote must not stop the others
            log.warning("Couldn't mount %s again: %s", mount.remote, exc)

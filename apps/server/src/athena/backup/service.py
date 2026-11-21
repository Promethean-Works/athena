"""Shared pieces of the backup area: getting a verified restic and opening a destination."""

import asyncio
from pathlib import Path

from athena.backup.restic import Repository, Restic, ensure_restic
from athena.crypto import SecretBox
from athena.db.models import BackupDestination
from athena.downloads import Log, quiet


class ResticProvider:
    """Hands out a `Restic` backed by Athena's own pinned, checksum-verified binary."""

    def __init__(self, data_dir: Path, binary: Path | None = None) -> None:
        self.data_dir = data_dir
        self.binary = binary
        """Set by tests to use a restic they already have; production downloads one."""
        self._lock: asyncio.Lock | None = None

    async def get(self, log_line: Log = quiet) -> Restic:
        if self.binary is not None:
            path = self.binary
        else:
            if self._lock is None:
                self._lock = asyncio.Lock()
            async with self._lock:
                path = await ensure_restic(self.data_dir, log_line)
        return Restic(path, cache_dir=self.data_dir / "cache" / "restic")


def repository_of(row: BackupDestination, box: SecretBox) -> Repository:
    """The repository a destination row points at, with its decrypted password."""
    return Repository(location=row.location, password=box.decrypt(row.password))

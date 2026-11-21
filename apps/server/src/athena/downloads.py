"""Download a pinned release binary and check it against a known SHA-256 before use.

Shared by tools Athena fetches at runtime (lego for Let's Encrypt; cloudflared can move
here later). The checksum is pinned in Athena's code, not read from the same server as
the file, so a tampered download can't come with a matching checksum.
"""

import bz2
import hashlib
import io
import logging
import os
import tarfile
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx2

log = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 120.0
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024

Log = Callable[[str], Awaitable[None]]


class DownloadError(Exception):
    """A readable reason a download failed (shown to the admin as is)."""


async def quiet(_: str) -> None:
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_member(archive: bytes, name: str, member: str) -> bytes:
    """The bytes of `member` (a file at the archive's top level) from a .tar.gz or .zip."""
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(archive)) as zf:
                return zf.read(member)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            info = tar.getmember(member)
            if not info.isfile():
                raise DownloadError(f"{member} in {name} isn't a file")
            f = tar.extractfile(info)
            if f is None:
                raise DownloadError(f"{member} in {name} isn't a file")
            return f.read()
    except KeyError as exc:
        raise DownloadError(f"{name} has no {member}") from exc
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
        raise DownloadError(f"{name} isn't a valid archive: {exc}") from exc


def extract_single(archive: bytes, name: str) -> bytes:
    """The one program in a `.bz2` file, or in a `.zip` holding a single `.exe` (restic)."""
    try:
        if name.endswith(".bz2"):
            # Bounded, so a tiny file that expands to gigabytes can't fill the memory.
            data = bz2.BZ2Decompressor().decompress(archive, max_length=MAX_ARCHIVE_BYTES + 1)
            if len(data) > MAX_ARCHIVE_BYTES:
                raise DownloadError(f"{name} is larger than expected")
            return data
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            exes = [i for i in zf.infolist() if not i.is_dir() and i.filename.endswith(".exe")]
            if len(exes) != 1:
                raise DownloadError(f"{name} doesn't hold exactly one program")
            return zf.read(exes[0])
    except (OSError, EOFError, zipfile.BadZipFile) as exc:
        raise DownloadError(f"{name} isn't a valid archive: {exc}") from exc


def write_executable(path: Path, data: bytes) -> None:
    """Write atomically so a half-written binary is never run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    tmp.write_bytes(data)
    tmp.chmod(0o755)
    os.replace(tmp, path)


async def fetch_verified(
    url: str,
    sha256: str,
    *,
    log_line: Log = quiet,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> bytes:
    """The bytes at `url`, or `DownloadError` if they don't hash to `sha256`."""
    await log_line(f"Downloading {url}")
    try:
        async with httpx2.AsyncClient(
            timeout=DOWNLOAD_TIMEOUT, follow_redirects=True, transport=transport
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content
    except httpx2.HTTPError as exc:
        raise DownloadError(f"Couldn't download {url}: {exc}") from exc
    if len(data) > MAX_ARCHIVE_BYTES:
        raise DownloadError(f"{url} is larger than expected")
    actual = hashlib.sha256(data).hexdigest()
    if actual != sha256.lower():
        log.error("checksum mismatch for %s: expected %s, got %s", url, sha256, actual)
        raise DownloadError(
            f"The download from {url} doesn't match its published checksum, so it wasn't used."
        )
    await log_line("Checksum verified")
    return data

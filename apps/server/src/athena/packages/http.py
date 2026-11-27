"""Fetching from package stores: Snap Store details, and icons and logos for the UI.

Icons never come from a URL the browser sends: the server decides the URL from what the
manager's store said and only fetches https hosts the manager is allowed to use.
"""

import hashlib
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx2

from athena.packages.base import PackageError

TIMEOUT = 10.0
MAX_IMAGE_BYTES = 512 * 1024
CACHE_SECONDS = 24 * 3600
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/x-icon")
IMAGE_TYPES += ("image/vnd.microsoft.icon", "image/svg+xml")

_cache: dict[str, tuple[float, tuple[bytes, str]]] = {}


def host_allowed(url: str, hosts: tuple[str, ...]) -> bool:
    """https only, and the host is one of `hosts` or a subdomain of one."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in hosts)


async def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict:
    try:
        async with httpx2.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except (httpx2.HTTPError, ValueError) as exc:
        raise PackageError(f"The store didn't answer: {exc}") from exc
    return data if isinstance(data, dict) else {}


async def fetch_image(url: str, hosts: tuple[str, ...]) -> tuple[bytes, str]:
    """Image bytes and content type. Raises PackageError for a host that isn't allowed, a
    redirect to one, a type that isn't an image, or a body over the size cap."""
    if not host_allowed(url, hosts):
        raise PackageError("That icon isn't on one of the manager's own sites")
    if (hit := _cache.get(url)) and hit[0] > time.monotonic():
        return hit[1]
    try:
        async with httpx2.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            resp = await client.get(url)
            if resp.is_redirect and (target := resp.headers.get("location")):
                # One hop, and only to another allowed host.
                if not host_allowed(target, hosts):
                    raise PackageError("The icon moved somewhere that isn't allowed")
                resp = await client.get(target)
            resp.raise_for_status()
    except httpx2.HTTPError as exc:
        raise PackageError(f"The icon couldn't be fetched: {exc}") from exc
    kind = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind not in IMAGE_TYPES:
        raise PackageError("The store sent something that isn't an image")
    if len(resp.content) > MAX_IMAGE_BYTES:
        raise PackageError("The icon is too large")
    _cache[url] = (time.monotonic() + CACHE_SECONDS, (resp.content, kind))
    return resp.content, kind


MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_REDIRECTS = 4


async def download(url: str, dest: Path, hosts: tuple[str, ...], sha256: str | None = None) -> str:
    """Save `url` to `dest` and return its SHA-256. https only, every hop (redirects too) on an
    allowed host, a size cap, and the checksum must match when `sha256` is given."""
    digest = hashlib.sha256()
    size = 0
    try:
        async with httpx2.AsyncClient(timeout=60.0, follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                if not host_allowed(url, hosts):
                    raise PackageError(f"{urlsplit(url).hostname} isn't an allowed download site")
                async with client.stream("GET", url) as resp:
                    if resp.is_redirect and (target := resp.headers.get("location")):
                        url = str(resp.url.join(target))
                        continue
                    resp.raise_for_status()
                    with dest.open("wb") as out:
                        async for chunk in resp.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_DOWNLOAD_BYTES:
                                raise PackageError("The download is larger than expected")
                            digest.update(chunk)
                            out.write(chunk)
                    break
            else:
                raise PackageError("Too many redirects")
    except httpx2.HTTPError as exc:
        raise PackageError(f"The download failed: {exc}") from exc
    result = digest.hexdigest()
    if sha256 and result != sha256.lower():
        dest.unlink(missing_ok=True)
        raise PackageError("The download doesn't match the checksum the vendor published")
    return result

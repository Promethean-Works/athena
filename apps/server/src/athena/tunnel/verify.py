"""Checked downloads for tunnel clients.

A binary Athena downloads and runs must match a SHA-256 digest that came from somewhere
other than the file itself. Blocking: call from a worker thread.
"""

import hashlib
import hmac
import json
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/{repo}/releases/latest"
TIMEOUT = 60


class ChecksumError(Exception):
    """The download is missing a digest or doesn't match it."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    """Raises ChecksumError unless `path` has the SHA-256 `expected` (hex)."""
    actual = sha256_of(path)
    if not hmac.compare_digest(actual.encode(), expected.strip().lower().encode()):
        raise ChecksumError(f"{path.name} doesn't match its published checksum; not installing it")


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.load(resp)


def download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp, dest.open("wb") as out:
        while chunk := resp.read(1024 * 1024):
            out.write(chunk)


def github_asset(repo: str, name: str) -> tuple[str, str]:
    """(download URL, SHA-256 hex) of a release asset, both from the same release.

    The digest is the one GitHub records for the asset when it is uploaded.
    """
    release = fetch_json(GITHUB_API.format(repo=repo))
    for asset in release.get("assets", []):
        if asset.get("name") != name:
            continue
        digest = str(asset.get("digest") or "")
        url = str(asset.get("browser_download_url") or "")
        if not digest.startswith("sha256:") or not url.startswith("https://"):
            raise ChecksumError(f"{name} has no published SHA-256 checksum; not installing it")
        return url, digest.removeprefix("sha256:")
    raise ChecksumError(f"{repo} has no release asset named {name}")


def download_verified(repo: str, name: str, dest: Path) -> str:
    """Download a GitHub release asset to `dest`, verified. Returns the URL used."""
    url, digest = github_asset(repo, name)
    download(url, dest)
    try:
        verify_sha256(dest, digest)
    except ChecksumError:
        dest.unlink(missing_ok=True)
        raise
    return url

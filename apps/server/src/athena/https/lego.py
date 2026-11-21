"""The lego ACME client (MIT, github.com/go-acme/lego), downloaded on first use.

Athena pins one lego release and the SHA-256 of each archive it may download (from the
release's `lego_<version>_checksums.txt`). To move to a newer lego, update `VERSION` and
`CHECKSUMS` together, and check the CLI flags in `letsencrypt.py` still exist (lego v5
changed them from v4).
"""

import asyncio
import platform
import sys
from pathlib import Path

from athena.downloads import (
    DownloadError,
    Log,
    extract_member,
    fetch_verified,
    quiet,
    sha256_file,
    write_executable,
)

VERSION = "5.6.0"

# Archive name -> SHA-256, copied from lego_5.6.0_checksums.txt.
CHECKSUMS = {
    "lego_v5.6.0_darwin_amd64.tar.gz": (
        "0c2b5c5e65c20fbd28f28331de24bf315fa4a8669beb0d75fd7eae530d10e0f4"
    ),
    "lego_v5.6.0_darwin_arm64.tar.gz": (
        "37453b4e1ad7e5d55a969508765db004122b9acbcfe099b95cafb86d0025a383"
    ),
    "lego_v5.6.0_linux_amd64.tar.gz": (
        "f02fc11b6f56b97e387fa7caa0268f86f5a336953b22458e6430e4651fea439a"
    ),
    "lego_v5.6.0_linux_arm64.tar.gz": (
        "34d87a6552d69390c4a4560237045c47713a8e148d899e16db0e97040894ed1f"
    ),
    "lego_v5.6.0_linux_armv6.tar.gz": (
        "4fff0aeb9b4641f8314f325f43ddfba7d5f5c14696d073b7c3a96d8d1c237e7d"
    ),
    "lego_v5.6.0_linux_armv7.tar.gz": (
        "2cf63a16f080556e9b03c2b8aa049eabe9c986e65d46270726f86d5a376ef1b5"
    ),
    "lego_v5.6.0_windows_amd64.zip": (
        "9c4e5f77996ef2ebbcb1ea270fa7e94190b531057e02a645b124b38f66c12755"
    ),
    "lego_v5.6.0_windows_arm64.zip": (
        "fc17b5786d58a3291a20e38ccf9e2b0d3f701e203efbc92d8aa63f92f543d3fb"
    ),
}

_ARCH = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "armv7",
    "armv7": "armv7",
    "armv6l": "armv6",
    "armv6": "armv6",
}


def asset_for(system: str, machine: str) -> str:
    """The release archive for this OS and CPU, or `DownloadError`."""
    system = system.lower()
    arch = _ARCH.get(machine.lower())
    ext = "zip" if system == "windows" else "tar.gz"
    name = f"lego_v{VERSION}_{system}_{arch}.{ext}"
    if arch is None or name not in CHECKSUMS:
        raise DownloadError(f"lego has no release for {system} on {machine}")
    return name


def binary_path(data_dir: Path) -> Path:
    return data_dir / "bin" / ("lego.exe" if sys.platform == "win32" else "lego")


def _stamp(binary: Path) -> Path:
    """The binary's own SHA-256, written at install, checked before each run."""
    return binary.with_name(binary.name + ".sha256")


def _installed_ok(binary: Path) -> bool:
    stamp = _stamp(binary)
    if not binary.is_file() or not stamp.is_file():
        return False
    expected = stamp.read_text(encoding="utf-8").split()
    return len(expected) == 2 and expected[1] == VERSION and expected[0] == sha256_file(binary)


def _install(binary: Path, data: bytes) -> None:
    write_executable(binary, data)
    _stamp(binary).write_text(f"{sha256_file(binary)} {VERSION}\n", encoding="utf-8")


async def ensure_lego(data_dir: Path, log_line: Log = quiet) -> Path:
    """The path of a verified lego binary, downloading it if missing, changed or outdated."""
    binary = binary_path(data_dir)
    if await asyncio.to_thread(_installed_ok, binary):
        return binary
    asset = asset_for(platform.system(), platform.machine())
    url = f"https://github.com/go-acme/lego/releases/download/v{VERSION}/{asset}"
    archive = await fetch_verified(url, CHECKSUMS[asset], log_line=log_line)
    data = extract_member(archive, asset, binary.name)
    await asyncio.to_thread(_install, binary, data)
    await log_line(f"Installed lego {VERSION} at {binary}")
    return binary

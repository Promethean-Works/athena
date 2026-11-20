"""Which store apps run on this host's CPU.

A catalog app lists the image platforms it's published for (`x-athena.platforms`,
e.g. ``linux/amd64``). Containers run Linux images, so what matters is the CPU:
the host's ``platform.machine()`` mapped to a Docker platform. Docker Desktop on an
arm64 Mac or Windows PC runs amd64 images under emulation (Rosetta, or Windows'
own), so those apps still install there, only slower. Linux has no emulation
unless binfmt/qemu was set up by hand, so a mismatch there means the app won't run.
"""

from typing import Literal

Support = Literal["native", "emulated", "unsupported"]

KNOWN_PLATFORMS = ("linux/amd64", "linux/arm64", "linux/arm/v7")
"""The platforms the catalog tracks, in display order. Others (386, ppc64le, s390x,
riscv64, arm/v6) aren't hosts Athena installs on."""

_ARCH: dict[str, str] = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "x64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv8l": "arm/v7",
    "armv7l": "arm/v7",
    "armv7": "arm/v7",
    "armhf": "arm/v7",
}


def host_platform(arch: str) -> str | None:
    """``platform.machine()`` (lowercased) as a Docker platform, or None if unknown."""
    mapped = _ARCH.get(arch.strip().lower())
    return f"linux/{mapped}" if mapped else None


def normalize(platform: str) -> str:
    """``linux/arm`` and ``linux/arm64/v8`` as the catalog writes them."""
    value = platform.strip().lower()
    if value == "linux/arm":
        return "linux/arm/v7"
    if value == "linux/arm64/v8":
        return "linux/arm64"
    return value


def support(platforms: list[str], os: str, arch: str) -> Support:
    """Whether an app published for ``platforms`` runs on a host with ``os``/``arch``."""
    host = host_platform(arch)
    if host is None:
        return "native"  # an unknown CPU: don't block anything we can't judge
    published = {normalize(p) for p in platforms}
    if host in published:
        return "native"
    if os in ("darwin", "windows") and host == "linux/arm64" and "linux/amd64" in published:
        return "emulated"
    return "unsupported"

"""cloudflared install: the release asset per OS and CPU, and the download flow."""

import asyncio
import platform
import sys

import pytest

from athena.tunnel import cloudflare
from athena.tunnel.cloudflare import CloudflareTunnelProvider, release_asset


@pytest.mark.parametrize(
    ("system", "machine", "asset"),
    [
        ("Linux", "x86_64", "cloudflared-linux-amd64"),
        ("Linux", "aarch64", "cloudflared-linux-arm64"),
        ("Linux", "armv7l", "cloudflared-linux-arm"),
        ("Linux", "i686", "cloudflared-linux-386"),
        ("Darwin", "arm64", "cloudflared-darwin-arm64.tgz"),
        ("Darwin", "x86_64", "cloudflared-darwin-amd64.tgz"),
        ("Windows", "AMD64", "cloudflared-windows-amd64.exe"),
        ("Windows", "ARM64", "cloudflared-windows-amd64.exe"),
        ("Windows", "x86", "cloudflared-windows-386.exe"),
    ],
)
def test_release_asset(system: str, machine: str, asset: str) -> None:
    assert release_asset(system, machine) == asset


@pytest.mark.parametrize(("system", "machine"), [("Linux", "riscv64"), ("FreeBSD", "amd64")])
def test_release_asset_unsupported(system: str, machine: str) -> None:
    with pytest.raises(ValueError, match="no release"):
        release_asset(system, machine)


class _Job:
    def __init__(self) -> None:
        self.lines: list[str] = []

    async def log(self, line: str) -> None:
        self.lines.append(line)


def test_install_copies_bare_linux_binary(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(cloudflare.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cloudflare.os, "access", lambda *_: False)
    urls: list[str] = []

    def fake_retrieve(url: str, dest) -> None:
        urls.append(url)
        dest.write_bytes(b"binary")

    monkeypatch.setattr("urllib.request.urlretrieve", fake_retrieve)
    job = _Job()
    asyncio.run(CloudflareTunnelProvider().install(job))

    assert urls == [
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
    ]
    installed = tmp_path / ".local" / "bin" / "cloudflared"
    assert installed.read_bytes() == b"binary"
    if not sys.platform.startswith("win"):  # Windows has no exec bit
        assert installed.stat().st_mode & 0o111
    assert job.lines[-1] == f"Installed cloudflared to {installed}"

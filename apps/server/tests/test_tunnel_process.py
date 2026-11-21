"""Tunnel providers really start, report and stop their client process.

The client is a Python one-liner standing in for cloudflared or ngrok, so these run
the same on every OS.
"""

import asyncio
import re
import sys

import pytest

from athena.tunnel import cloudflare, ngrok, tailscale
from athena.tunnel.base import TunnelConfig
from athena.tunnel.process import TunnelProcess

QUICK_URL = "https://lucky-words-here.trycloudflare.com"
NGROK_URL = "https://abcd-1234.ngrok-free.app"


class FakeJob:
    def __init__(self) -> None:
        self.lines: list[str] = []

    async def log(self, line: str) -> None:
        self.lines.append(line)


def _script(*lines: str, then_sleep: bool = True) -> list[str]:
    body = "".join(f"print({line!r}, flush=True)\n" for line in lines)
    if then_sleep:
        body += "import time\ntime.sleep(60)\n"
    return [sys.executable, "-c", body]


def _fake_client(monkeypatch, module, script: list[str]) -> list[dict]:
    """Make `module` run `script` instead of the real client; returns the calls made."""
    calls: list[dict] = []

    def make(argv, env, ready):
        calls.append({"argv": argv, "env": env})
        return TunnelProcess(script, env, ready)

    monkeypatch.setattr(module, "TunnelProcess", make)
    monkeypatch.setattr(module, "find_binary", lambda name: f"/opt/{name}")
    return calls


def test_process_waits_for_the_ready_line() -> None:
    proc = TunnelProcess(_script("starting", f"visit {QUICK_URL} now"), {}, cloudflare._QUICK_URL)
    try:
        match = asyncio.run(proc.wait_ready(10))
        assert match.group(0) == QUICK_URL
        assert proc.alive
    finally:
        proc.stop()
    assert not proc.alive


def test_process_that_exits_reports_its_output() -> None:
    proc = TunnelProcess(_script("bad token", then_sleep=False), {}, re.compile("never"))
    with pytest.raises(RuntimeError, match="bad token"):
        asyncio.run(proc.wait_ready(10))


def test_process_that_hangs_times_out_and_is_stopped() -> None:
    proc = TunnelProcess(_script("still dialing"), {}, re.compile("never"))
    with pytest.raises(RuntimeError, match="still dialing"):
        asyncio.run(proc.wait_ready(0.5))
    assert not proc.alive


def test_cloudflare_quick_tunnel_runs_until_stopped(monkeypatch) -> None:
    calls = _fake_client(monkeypatch, cloudflare, _script(f"INF |  {QUICK_URL}  |"))
    monkeypatch.setattr(cloudflare, "_cloudflared_running", lambda: False)
    provider = cloudflare.CloudflareTunnelProvider()
    try:
        url = asyncio.run(provider.start(FakeJob(), TunnelConfig(port=8421)))
        assert url == QUICK_URL
        assert calls[0]["argv"][-2:] == ["--url", "http://localhost:8421"]
        status = provider.status()
        assert status.running
        assert status.public_url == QUICK_URL
        with pytest.raises(RuntimeError, match="already running"):
            asyncio.run(provider.start(FakeJob(), TunnelConfig(port=8421)))
        asyncio.run(provider.stop(FakeJob()))
        assert not provider.status().running
    finally:
        provider.shutdown()


def test_cloudflare_named_tunnel_keeps_the_token_out_of_argv(monkeypatch) -> None:
    calls = _fake_client(monkeypatch, cloudflare, _script("INF Registered tunnel connection"))
    provider = cloudflare.CloudflareTunnelProvider()
    config = TunnelConfig(
        port=8421,
        provider_config={
            "quick_tunnel": False,
            "api_token": "cf-secret",
            "tunnel_name": "home",
            "domain": "home.example.com",
        },
    )
    try:
        assert asyncio.run(provider.start(FakeJob(), config)) == "https://home.example.com"
        assert "cf-secret" not in calls[0]["argv"]
        assert calls[0]["env"]["TUNNEL_TOKEN"] == "cf-secret"
    finally:
        provider.shutdown()


def test_cloudflare_status_after_the_client_dies(monkeypatch) -> None:
    _fake_client(monkeypatch, cloudflare, _script(QUICK_URL, then_sleep=False))
    monkeypatch.setattr(cloudflare, "_cloudflared_running", lambda: False)
    provider = cloudflare.CloudflareTunnelProvider()
    asyncio.run(provider.start(FakeJob(), TunnelConfig(port=8421)))
    provider._process.proc.wait(timeout=10)
    status = provider.status()
    assert not status.running
    assert "exited" in (status.detail or "")


def test_ngrok_parses_the_started_line(monkeypatch) -> None:
    line = (
        't=2026-11-20T10:00:00+0000 lvl=info msg="started tunnel" obj=tunnels '
        f"name=command_line addr=http://localhost:8421 url={NGROK_URL}"
    )
    calls = _fake_client(monkeypatch, ngrok, _script(line))
    monkeypatch.setattr(ngrok, "_api_url", lambda: None)
    provider = ngrok.NgrokTunnelProvider()
    config = TunnelConfig(port=8421, provider_config={"auth_token": "ng-secret"})
    try:
        assert asyncio.run(provider.start(FakeJob(), config)) == NGROK_URL
        assert "ng-secret" not in calls[0]["argv"]
        assert calls[0]["env"]["NGROK_AUTHTOKEN"] == "ng-secret"
        assert provider.status().public_url == NGROK_URL
        asyncio.run(provider.stop(FakeJob()))
        assert not provider.status().running
    finally:
        provider.shutdown()


@pytest.mark.parametrize(
    ("config", "url"),
    [
        ({}, None),
        ({"AllowFunnel": {"box.tail1234.ts.net:443": True}}, "https://box.tail1234.ts.net"),
        ({"AllowFunnel": {"box.tail1234.ts.net:8443": True}}, "https://box.tail1234.ts.net:8443"),
        ({"AllowFunnel": {"box.tail1234.ts.net:443": False}}, None),
    ],
)
def test_tailscale_funnel_url(config: dict, url: str | None) -> None:
    assert tailscale.funnel_url_from(config) == url

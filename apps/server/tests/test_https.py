import ipaddress
import os
import socket
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from conftest import ADMIN, signed_in
from cryptography import x509
from fake_probe import FakeProbe
from fastapi.testclient import TestClient

from athena.cli import main as cli_main
from athena.config import Settings
from athena.https import local_ca
from athena.https.redirect import location
from athena.main import create_app
from athena.platform.detect import detect
from athena.platform.store import CapabilityStore


def _app(tmp_path: Path):
    # Port set explicitly: `athena serve` tests leave ATHENA_PORT in the environment.
    settings = Settings(
        host="127.0.0.1", port=8420, data_dir=tmp_path / "data", web_dir=tmp_path / "no-web"
    )
    store = CapabilityStore(detector=lambda: detect(FakeProbe(os="darwin")))
    return create_app(settings, capability_store=store)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ssl_context(ca: Path) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(ca))


def _served_cert(port: int, ca: Path) -> x509.Certificate:
    """The certificate the HTTPS listener presents (verified against `ca`)."""
    with (
        socket.create_connection(("127.0.0.1", port), timeout=5) as raw,
        _ssl_context(ca).wrap_socket(raw, server_hostname="127.0.0.1") as tls,
    ):
        der = tls.getpeercert(binary_form=True)
    assert der is not None
    return x509.load_der_x509_certificate(der)


# ---------------------------------------------------------------- local CA


def test_server_cert_is_signed_by_the_ca_and_covers_the_host(tmp_path):
    paths = local_ca.tls_paths(tmp_path)
    assert local_ca.ensure_server_cert(paths, ["nas.home.lan", "10.9.8.7"]) is True
    ca = local_ca.load_cert(paths.ca_cert)
    cert = local_ca.load_cert(paths.cert)
    assert ca is not None and cert is not None
    cert.verify_directly_issued_by(ca)
    dns, ips = local_ca.cert_names(cert)
    assert {"localhost", "nas.home.lan"} <= dns
    assert {ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("10.9.8.7")} <= ips
    assert cert.not_valid_after_utc - cert.not_valid_before_utc <= timedelta(days=366)
    basic = ca.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert basic.ca is True
    if os.name == "posix":
        assert paths.key.stat().st_mode & 0o777 == 0o600
        assert paths.ca_key.stat().st_mode & 0o777 == 0o600


def test_server_cert_is_kept_until_it_must_change(tmp_path):
    paths = local_ca.tls_paths(tmp_path)
    local_ca.ensure_server_cert(paths, [])
    first = paths.cert.read_bytes()
    assert local_ca.ensure_server_cert(paths, []) is False
    assert paths.cert.read_bytes() == first
    # A new name reissues; the CA stays.
    ca = paths.ca_cert.read_bytes()
    assert local_ca.ensure_server_cert(paths, ["new.home.lan"]) is True
    assert paths.ca_cert.read_bytes() == ca
    # Dropping a name doesn't (a superset is fine).
    assert local_ca.ensure_server_cert(paths, []) is False
    # Near expiry does.
    later = datetime.now(UTC) + timedelta(days=340)
    assert local_ca.ensure_server_cert(paths, [], now=later) is True


def test_rotating_the_ca_reissues_the_server_cert(tmp_path):
    paths = local_ca.tls_paths(tmp_path)
    local_ca.ensure_server_cert(paths, [])
    old_ca = local_ca.load_cert(paths.ca_cert)
    local_ca.rotate_ca(paths)
    assert local_ca.ensure_server_cert(paths, []) is True
    new_ca = local_ca.load_cert(paths.ca_cert)
    cert = local_ca.load_cert(paths.cert)
    assert old_ca is not None and new_ca is not None and cert is not None
    assert old_ca.fingerprint(old_ca.signature_hash_algorithm) != new_ca.fingerprint(
        new_ca.signature_hash_algorithm
    )
    cert.verify_directly_issued_by(new_ca)


def test_a_cert_from_another_ca_is_reissued(tmp_path):
    a, b = local_ca.tls_paths(tmp_path / "a"), local_ca.tls_paths(tmp_path / "b")
    local_ca.ensure_server_cert(a, [])
    local_ca.ensure_server_cert(b, [])
    b.cert.write_bytes(a.cert.read_bytes())
    b.key.write_bytes(a.key.read_bytes())
    assert local_ca.ensure_server_cert(b, []) is True


# ---------------------------------------------------------------- redirect


def _scope(host: str = "nas.local:8420", client: str = "192.168.1.20", **extra) -> dict:
    headers = [(b"host", host.encode()), (b"sec-fetch-mode", b"navigate")]
    extra_headers = extra.pop("headers", {})
    headers = [h for h in headers if h[0].decode() not in extra_headers]
    headers += [(k.encode(), v.encode()) for k, v in extra_headers.items() if v is not None]
    return {
        "type": "http",
        "scheme": "http",
        "method": extra.get("method", "GET"),
        "path": extra.get("path", "/apps"),
        "raw_path": extra.get("path", "/apps").encode(),
        "query_string": extra.get("query", b""),
        "headers": headers,
        "client": (client, 50000),
    }


def test_redirect_target():
    assert location(_scope(), 8443) == "https://nas.local:8443/apps"
    assert location(_scope(query=b"a=1"), 8443) == "https://nas.local:8443/apps?a=1"
    assert location(_scope(host="192.168.1.5:8420"), 443) == "https://192.168.1.5/apps"
    assert location(_scope(host="[fe80::1]:8420"), 8443) == "https://[fe80::1]:8443/apps"
    assert location(_scope(method="HEAD"), 8443) == "https://nas.local:8443/apps"
    # An old browser without Sec-Fetch-Mode, asking for a page.
    old = _scope(headers={"sec-fetch-mode": None, "accept": "text/html,*/*"})
    assert location(old, 8443) == "https://nas.local:8443/apps"


@pytest.mark.parametrize(
    "scope",
    [
        _scope(client="127.0.0.1"),
        _scope(client="::1"),
        _scope(headers={"x-forwarded-for": "1.2.3.4"}),
        _scope(headers={"x-forwarded-proto": "https"}),
        _scope(path="/api/health"),
        _scope(path="/api/apps"),
        _scope(path="/api/mcp"),
        _scope(path="/api/automation/webhook/abc"),
        _scope(path="/dav/Documents/"),
        _scope(path="/dav"),
        _scope(method="POST"),
        _scope(method="PROPFIND"),
        _scope(headers={"sec-fetch-mode": "cors"}),
        _scope(headers={"sec-fetch-mode": None, "accept": "application/json"}),
        _scope(host="evil.example/path"),
        _scope(host="bad host"),
        _scope(host=""),
    ],
)
def test_redirect_skips(scope):
    assert location(scope, 8443) is None


# ---------------------------------------------------------------- API


def test_https_needs_a_session(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.get("/api/https").status_code == 401
        assert client.put("/api/https", json={"mode": "off"}).status_code == 401
        assert client.get("/api/https/ca.crt").status_code == 401


def test_https_is_off_by_default(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        body = client.get("/api/https").json()
        assert body["settings"]["mode"] == "off"
        assert body["listening"] is False
        assert body["certificate"] is None
        assert client.get("/api/https/ca.crt").status_code == 404
        caps = {c["id"] for c in client.get("/api/system/capabilities").json()["capabilities"]}
        assert "https" in caps


def test_self_signed_serves_https_redirects_and_turns_off(tmp_path):
    port = _free_port()
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        r = client.put("/api/https", json={"mode": "self_signed", "port": port})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["listening"] is True
        assert body["last_error"] is None
        assert any(u.endswith(f":{port}") for u in body["urls"])
        assert "127.0.0.1" in body["certificate"]["names"]

        ca = tmp_path / "ca.crt"
        download = client.get("/api/https/ca.crt")
        assert download.status_code == 200
        assert b"BEGIN CERTIFICATE" in download.content
        assert b"PRIVATE KEY" not in download.content
        ca.write_bytes(download.content)

        # A real TLS request against the listener, trusting only the downloaded CA.
        health = httpx.get(f"https://127.0.0.1:{port}/api/health", verify=_ssl_context(ca))
        assert health.status_code == 200
        # Login over HTTPS sets a Secure cookie.
        with httpx.Client(base_url=f"https://127.0.0.1:{port}", verify=_ssl_context(ca)) as tls:
            login = tls.post("/api/auth/login", json=ADMIN)
            assert login.status_code == 200, login.text
            assert "secure" in login.headers["set-cookie"].lower()

        # The HTTP side sends a LAN browser to HTTPS.
        r = client.get(
            "/apps",
            headers={"host": "nas.local:8420", "sec-fetch-mode": "navigate"},
            follow_redirects=False,
        )
        assert r.status_code == 307
        assert r.headers["location"] == f"https://nas.local:{port}/apps"
        assert client.get("/api/health", follow_redirects=False).status_code == 200

        # API calls on the HTTP port aren't redirected (a page open over HTTP keeps working).
        r = client.put("/api/https", json={"mode": "off", "port": port}, follow_redirects=False)
        assert r.status_code == 200, r.text
        assert r.json()["listening"] is False
        with pytest.raises(httpx.ConnectError):
            httpx.get(f"https://127.0.0.1:{port}/api/health", verify=_ssl_context(ca), timeout=2)


def test_new_names_are_served_without_a_restart(tmp_path):
    port = _free_port()
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        assert client.put("/api/https", json={"mode": "self_signed", "port": port}).is_success
        ca = tmp_path / "data" / "tls" / "ca.crt"
        before = _served_cert(port, ca)
        r = client.put(
            "/api/https",
            json={"mode": "self_signed", "port": port, "extra_names": ["Nas.Home.Lan."]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["settings"]["extra_names"] == ["nas.home.lan"]
        after = _served_cert(port, ca)
        assert after.serial_number != before.serial_number
        assert "nas.home.lan" in local_ca.cert_names(after)[0]


def test_a_port_in_use_is_refused_and_nothing_changes(tmp_path):
    with socket.socket() as busy, TestClient(_app(tmp_path)) as client:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        signed_in(client)
        r = client.put("/api/https", json={"mode": "self_signed", "port": port})
        assert r.status_code == 409
        assert "in use" in r.json()["detail"]
        body = client.get("/api/https").json()
        assert body["settings"]["mode"] == "off"
        assert body["last_error"] is not None


def test_http_port_and_bad_names_are_refused(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        r = client.put("/api/https", json={"mode": "self_signed", "port": 8420})
        assert r.status_code == 409
        for name in ("bad name", "-x.lan", "a..b", "x" * 64):
            r = client.put(
                "/api/https", json={"mode": "self_signed", "port": 1, "extra_names": [name]}
            )
            assert r.status_code == 422, name
        assert client.put("/api/https", json={"mode": "self_signed", "port": 0}).status_code == 422


def test_rotate_ca_serves_a_cert_from_the_new_ca(tmp_path):
    port = _free_port()
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        first = client.put("/api/https", json={"mode": "self_signed", "port": port}).json()
        r = client.post("/api/https/ca/rotate")
        assert r.status_code == 200, r.text
        assert r.json()["ca"]["sha256"] != first["ca"]["sha256"]
        _served_cert(port, tmp_path / "data" / "tls" / "ca.crt")  # verifies with the new CA


def test_https_settings_survive_a_restart(tmp_path):
    port = _free_port()
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        assert client.put("/api/https", json={"mode": "self_signed", "port": port}).is_success
    with TestClient(_app(tmp_path)) as client:
        client.post("/api/auth/login", json=ADMIN)
        health = httpx.get(
            f"https://127.0.0.1:{port}/api/health",
            verify=_ssl_context(tmp_path / "data" / "tls" / "ca.crt"),
        )
        assert health.status_code == 200


def test_cli_https_off(tmp_path, capsys):
    port = _free_port()
    data = tmp_path / "data"
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        assert client.put("/api/https", json={"mode": "self_signed", "port": port}).is_success
    assert cli_main(["https", "status", "--data-dir", str(data)]) == 0
    assert "self_signed" in capsys.readouterr().out
    assert cli_main(["https", "off", "--data-dir", str(data)]) == 0
    assert cli_main(["https", "status", "--data-dir", str(data)]) == 0
    assert "mode:     off" in capsys.readouterr().out
    with TestClient(_app(tmp_path)) as client:
        r = client.get("/apps", headers={"sec-fetch-mode": "navigate"}, follow_redirects=False)
        assert r.status_code != 307


def test_cli_https_needs_a_database(tmp_path):
    assert cli_main(["https", "status", "--data-dir", str(tmp_path / "none")]) == 1


def test_virtual_interfaces_stay_out_of_the_certificate(monkeypatch):
    from types import SimpleNamespace

    def addr(ip):
        return SimpleNamespace(family=socket.AF_INET, address=ip)

    monkeypatch.setattr(
        local_ca.psutil,
        "net_if_addrs",
        lambda: {
            "en0": [addr("192.168.1.5")],
            "tailscale0": [addr("100.101.102.103")],
            "docker0": [addr("172.17.0.1")],
            "br-1a2b3c": [addr("172.18.0.1")],
            "vEthernet (WSL)": [addr("172.20.0.1")],
            "en9": [addr("10.0.0.9")],
        },
    )
    monkeypatch.setattr(
        local_ca.psutil,
        "net_if_stats",
        lambda: {"en9": SimpleNamespace(isup=False), "en0": SimpleNamespace(isup=True)},
    )
    got = {str(ip) for ip in local_ca.host_addresses()}
    assert got == {"127.0.0.1", "::1", "192.168.1.5", "100.101.102.103"}


def test_a_key_that_doesnt_match_the_cert_is_repaired(tmp_path):
    paths = local_ca.tls_paths(tmp_path)
    local_ca.ensure_server_cert(paths, [])
    other = local_ca.tls_paths(tmp_path / "other")
    local_ca.ensure_server_cert(other, [])
    paths.key.write_bytes(other.key.read_bytes())  # as if a crash hit between the writes
    assert local_ca.ensure_server_cert(paths, []) is True
    cert = local_ca.load_cert(paths.cert)
    assert cert is not None and local_ca._key_matches(paths.key, cert)


def test_a_stale_temp_file_doesnt_loosen_key_permissions(tmp_path):
    paths = local_ca.tls_paths(tmp_path)
    paths.dir.mkdir(parents=True)
    stale = paths.dir / "server.key.tmp"
    stale.write_bytes(b"junk")
    stale.chmod(0o644)
    local_ca.ensure_server_cert(paths, [])
    assert not stale.exists()
    if os.name == "posix":
        assert paths.key.stat().st_mode & 0o777 == 0o600


def test_a_failed_port_change_keeps_the_old_listener(tmp_path):
    port = _free_port()
    with socket.socket() as busy, TestClient(_app(tmp_path)) as client:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        signed_in(client)
        assert client.put("/api/https", json={"mode": "self_signed", "port": port}).is_success
        r = client.put("/api/https", json={"mode": "self_signed", "port": busy.getsockname()[1]})
        assert r.status_code == 409
        body = client.get("/api/https").json()
        assert body["settings"]["port"] == port
        assert body["listening"] is True
        _served_cert(port, tmp_path / "data" / "tls" / "ca.crt")
    # And the database still has the old port.
    with TestClient(_app(tmp_path)):
        _served_cert(port, tmp_path / "data" / "tls" / "ca.crt")

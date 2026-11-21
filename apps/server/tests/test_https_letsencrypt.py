"""Let's Encrypt for Athena's HTTPS (docs/specs/https.md, part 3).

lego itself is replaced by tests/fixtures/fake_lego.py except in the Pebble test, which
runs the real lego against Pebble (Let's Encrypt's test server) when CI provides one.
"""

import asyncio
import hashlib
import io
import json
import os
import socket
import ssl
import sys
import tarfile
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from conftest import signed_in
from cryptography import x509
from fastapi.testclient import TestClient
from sqlmodel import select
from test_https import _app, _free_port

from athena.db.models import AuditEntry
from athena.downloads import DownloadError, extract_member, fetch_verified
from athena.https import lego, letsencrypt, local_ca
from athena.https import manager as manager_mod
from athena.https.settings import LetsEncryptSettings
from athena.jobs import Job

FAKE_LEGO = Path(__file__).parent / "fixtures" / "fake_lego.py"
TOKEN = "cf-secret-token-123"


# ---------------------------------------------------------------- download


def test_lego_asset_for_each_supported_host():
    assert lego.asset_for("Linux", "x86_64") == "lego_v5.6.0_linux_amd64.tar.gz"
    assert lego.asset_for("Linux", "aarch64") == "lego_v5.6.0_linux_arm64.tar.gz"
    assert lego.asset_for("Linux", "armv7l") == "lego_v5.6.0_linux_armv7.tar.gz"
    assert lego.asset_for("Linux", "armv6l") == "lego_v5.6.0_linux_armv6.tar.gz"
    assert lego.asset_for("Darwin", "arm64") == "lego_v5.6.0_darwin_arm64.tar.gz"
    assert lego.asset_for("Windows", "AMD64") == "lego_v5.6.0_windows_amd64.zip"
    assert lego.asset_for("Windows", "ARM64") == "lego_v5.6.0_windows_arm64.zip"
    for asset in lego.CHECKSUMS:
        assert asset.startswith(f"lego_v{lego.VERSION}_")
    with pytest.raises(DownloadError):
        lego.asset_for("Linux", "mips")


def _tar(member: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(member)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _zip(member: str, data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, data)
    return buf.getvalue()


def test_extract_member_from_tar_and_zip():
    assert extract_member(_tar("lego", b"bin"), "x.tar.gz", "lego") == b"bin"
    assert extract_member(_zip("lego.exe", b"exe"), "x.zip", "lego.exe") == b"exe"
    with pytest.raises(DownloadError):
        extract_member(_tar("other", b"bin"), "x.tar.gz", "lego")


def test_a_download_must_match_its_pinned_checksum():
    body = b"archive bytes"
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, content=body))
    good = hashlib.sha256(body).hexdigest()
    data = asyncio.run(fetch_verified("https://example.test/a", good, transport=transport))
    assert data == body
    with pytest.raises(DownloadError, match="checksum"):
        asyncio.run(fetch_verified("https://example.test/a", "0" * 64, transport=transport))


def test_ensure_lego_installs_once_and_reinstalls_a_changed_binary(tmp_path, monkeypatch):
    member = lego.binary_path(tmp_path).name
    asset = "lego_test.tar.gz"
    downloads: list[str] = []

    async def fake_fetch(url, sha256, *, log_line, transport=None):
        downloads.append(url)
        return _tar(member, b"#!lego")

    monkeypatch.setattr(lego, "asset_for", lambda system, machine: asset)
    monkeypatch.setattr(lego, "CHECKSUMS", {asset: "unused"})
    monkeypatch.setattr(lego, "fetch_verified", fake_fetch)
    binary = asyncio.run(lego.ensure_lego(tmp_path))
    assert binary.read_bytes() == b"#!lego"
    asyncio.run(lego.ensure_lego(tmp_path))
    assert len(downloads) == 1  # verified and kept
    binary.write_bytes(b"tampered")
    asyncio.run(lego.ensure_lego(tmp_path))
    assert len(downloads) == 2
    assert binary.read_bytes() == b"#!lego"


# ---------------------------------------------------------------- settings and command


def test_email_check_is_linear_and_bounded():
    start = time.monotonic()
    with pytest.raises(ValueError):
        LetsEncryptSettings(email="a@" + "." * 200 + "@")
    with pytest.raises(ValueError):
        LetsEncryptSettings(email="a@" + "b" * 300 + ".com")  # over 254
    assert time.monotonic() - start < 1
    assert LetsEncryptSettings(email=" me@example.com ").email == "me@example.com"


def test_changed_domains_need_a_new_certificate(tmp_path, fake_lego):
    port = _free_port()
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        job = client.post("/api/https/certificate", json=LE_BODY).json()
        assert _wait_job(client, job["id"])["status"] == "succeeded"
        other = {**LE_BODY, "domains": ["other.example.com"], "dns_config": {}}
        r = client.put(
            "/api/https", json={"mode": "letsencrypt", "port": port, "letsencrypt": other}
        )
        assert r.status_code == 409
        assert "these domains" in r.json()["detail"]
        # An admin's request always asks for a new certificate.
        assert "--renew-force" in json.loads(fake_lego.read_text())["argv"]


def test_settings_validation():
    le = LetsEncryptSettings(domains=["Nas.Example.com.", "nas.example.com"], email="a@b.co")
    assert le.domains == ["nas.example.com"]
    assert le.problem() is None
    assert LetsEncryptSettings(domains=["*.example.com"], email="a@b.co").problem() == (
        "Wildcard domains need the DNS challenge."
    )
    assert LetsEncryptSettings(email="a@b.co").problem() == "Add at least one domain."
    dns = LetsEncryptSettings(domains=["a.example.com"], email="a@b.co", challenge="dns")
    assert dns.problem() == "Pick a DNS provider."
    for bad in (["nas"], ["bad_name.example.com"]):
        with pytest.raises(ValueError):
            LetsEncryptSettings(domains=bad)
    with pytest.raises(ValueError):
        LetsEncryptSettings(email="not-an-email")


def test_command_http_challenge(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGO_SERVER", "https://evil.example/directory")
    monkeypatch.delenv(letsencrypt.ACME_DIRECTORY_ENV, raising=False)
    monkeypatch.delenv(letsencrypt.HTTP_ADDRESS_ENV, raising=False)
    monkeypatch.delenv(letsencrypt.ACME_CA_ENV, raising=False)  # set in CI for Pebble
    paths = local_ca.tls_paths(tmp_path)
    le = LetsEncryptSettings(domains=["nas.example.com"], email="me@example.com", staging=True)
    cmd = letsencrypt.build_command(Path("lego"), paths, le, {})
    argv = cmd.argv
    assert argv[:2] == ["lego", "run"]
    assert argv[argv.index("--server") + 1] == "letsencrypt-staging"
    assert argv[argv.index("--http.address") + 1] == ":80"
    assert "--renew-force" not in argv
    assert not any(k.startswith("LEGO_") for k in cmd.env)  # nothing leaks in


def test_command_dns_challenge_keeps_the_token_out_of_argv(tmp_path):
    paths = local_ca.tls_paths(tmp_path)
    le = LetsEncryptSettings(
        domains=["*.example.com"],
        email="me@example.com",
        challenge="dns",
        dns_provider="cloudflare",
    )
    cmd = letsencrypt.build_command(Path("lego"), paths, le, {"api_token": TOKEN}, force=True)
    assert cmd.argv[cmd.argv.index("--dns") + 1] == "cloudflare"
    assert TOKEN not in " ".join(cmd.argv)
    assert cmd.env["CLOUDFLARE_DNS_API_TOKEN"] == TOKEN
    assert "--renew-force" in cmd.argv
    with pytest.raises(ValueError, match="API token"):
        letsencrypt.build_command(Path("lego"), paths, le, {})


# ---------------------------------------------------------------- API with a fake lego


@pytest.fixture
def fake_lego(tmp_path, monkeypatch) -> Path:
    """lego replaced by fake_lego.py; returns the file it records its argv and env to."""
    record = tmp_path / "lego-run.json"
    real = letsencrypt.build_command

    async def no_download(data_dir, log_line=None):
        return Path("lego")

    def build(binary, paths, le, values, *, force=False):
        cmd = real(binary, paths, le, values, force=force)
        cmd.env["FAKE_LEGO_RECORD"] = str(record)
        for key in ("FAKE_LEGO_EXIT", "FAKE_LEGO_DAYS"):
            if key in os.environ:
                cmd.env[key] = os.environ[key]
        cmd.env["PYTHONPATH"] = os.pathsep.join(sys.path)
        cmd.argv = [sys.executable, str(FAKE_LEGO), *cmd.argv[1:]]
        return cmd

    monkeypatch.setattr(lego, "ensure_lego", no_download)
    monkeypatch.setattr(letsencrypt, "build_command", build)
    return record


def _wait_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job didn't finish")


def _served(port: int) -> x509.Certificate:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with (
        socket.create_connection(("127.0.0.1", port), timeout=5) as raw,
        ctx.wrap_socket(raw, server_hostname="nas.example.com") as tls,
    ):
        der = tls.getpeercert(binary_form=True)
    assert der is not None
    return x509.load_der_x509_certificate(der)


LE_BODY = {
    "domains": ["nas.example.com"],
    "email": "me@example.com",
    "challenge": "dns",
    "dns_provider": "cloudflare",
    "dns_config": {"api_token": TOKEN},
}


def test_get_a_certificate_serve_it_and_keep_it_when_renewal_fails(
    tmp_path, fake_lego, monkeypatch
):
    port = _free_port()
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        # Let's Encrypt mode needs a certificate first.
        r = client.put("/api/https", json={"mode": "letsencrypt", "port": port})
        assert r.status_code == 409, r.text
        assert "certificate first" in r.json()["detail"]

        r = client.post("/api/https/certificate", json=LE_BODY)
        assert r.status_code == 202, r.text
        job = _wait_job(client, r.json()["id"])
        assert job["status"] == "succeeded", job
        assert not any(TOKEN in line for line in job["lines"])
        ran = json.loads(fake_lego.read_text())
        assert TOKEN not in " ".join(ran["argv"])
        assert ran["env"]["CLOUDFLARE_DNS_API_TOKEN"] == TOKEN

        status = client.get("/api/https").json()
        assert status["settings"]["mode"] == "off"  # the admin turns it on
        assert status["letsencrypt_certificate"]["names"] == ["nas.example.com"]
        le = status["settings"]["letsencrypt"]
        assert le["dns_config"] == {}
        assert le["dns_secrets_set"] == ["api_token"]
        assert status["renewal_error"] is None
        assert status["last_renewal"] is not None

        # The token is stored encrypted and an empty one keeps it.
        r = client.put(
            "/api/https",
            json={
                "mode": "letsencrypt",
                "port": port,
                "letsencrypt": {**LE_BODY, "dns_config": {"api_token": ""}},
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["listening"] is True
        assert r.json()["urls"] == [f"https://nas.example.com:{port}"]
        app = client.app
        stored = app.state.settings_file.path.read_text(encoding="utf-8")  # type: ignore[attr-defined]
        assert TOKEN not in stored
        assert '"api_token":"enc:' in stored.replace(" ", "")
        first = _served(port)
        assert first.subject.rfc4514_string() == "CN=nas.example.com"

        # A failed renewal keeps the old certificate and says why.
        monkeypatch.setenv("FAKE_LEGO_EXIT", "1")
        r = client.post("/api/https/certificate", json={**LE_BODY, "dns_config": {}})
        assert r.status_code == 202, r.text
        job = _wait_job(client, r.json()["id"])
        assert job["status"] == "failed"
        assert any("acme:error:connection" in line for line in job["lines"])
        status = client.get("/api/https").json()
        assert "exit code 1" in status["renewal_error"]
        assert "acme:error:connection" in status["renewal_error"]
        assert _served(port).serial_number == first.serial_number

        for db in app.state.db.session():  # type: ignore[attr-defined]
            actions = [e.action for e in db.exec(select(AuditEntry)).all()]
            assert "https.certificate_issued" in actions
            assert "https.renewal_failed" in actions

        client.put("/api/https", json={"mode": "off", "port": port})


def test_the_daily_check_renews_a_certificate_close_to_expiry(tmp_path, fake_lego, monkeypatch):
    port = _free_port()
    monkeypatch.setenv("FAKE_LEGO_DAYS", "10")
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        job = client.post("/api/https/certificate", json=LE_BODY).json()
        assert _wait_job(client, job["id"])["status"] == "succeeded"
        r = client.put("/api/https", json={"mode": "letsencrypt", "port": port})
        assert r.status_code == 200, r.text
        before = _served(port)
        assert before.not_valid_after_utc - datetime.now(UTC) < timedelta(days=11)

        monkeypatch.setenv("FAKE_LEGO_DAYS", "90")
        manager = client.app.state.https  # type: ignore[attr-defined]
        assert client.portal.call(manager.check_certificate) is True  # type: ignore[union-attr]
        after = _served(port)
        assert after.serial_number != before.serial_number  # served without a restart
        # The PUT above had no `letsencrypt`: the stored token must reach lego unchanged.
        assert json.loads(fake_lego.read_text())["env"]["CLOUDFLARE_DNS_API_TOKEN"] == TOKEN
        assert client.portal.call(manager.check_certificate) is False  # type: ignore[union-attr]
        client.put("/api/https", json={"mode": "off", "port": port})


def test_lego_failure_shows_the_error_value_not_a_cut_log_line():
    job = Job("t")
    cause = "listen tcp :80: bind: address already in use"
    job.lines.append(
        'time=2026-11-21T10:05:32Z level=ERROR msg=Error error="renew certificate: could not '
        'obtain the certificate for \\"athena\\": ' + "x" * 400 + f' {cause}]"'
    )
    text = manager_mod._lego_failure(job, 1)
    assert text.startswith("lego failed (exit code 1): …")
    assert text.endswith(f"{cause}]")
    assert "level=" not in text
    assert len(text) < 360

    job = Job("t")
    job.lines.append('level=ERROR msg=Error error="obtain: \\"nas\\" failed"')
    assert manager_mod._lego_failure(job, 2) == 'lego failed (exit code 2): obtain: "nas" failed'


def test_http_challenge_fails_fast_when_port80_is_taken(tmp_path, fake_lego, monkeypatch):
    monkeypatch.delenv(letsencrypt.HTTP_ADDRESS_ENV, raising=False)
    monkeypatch.setattr(manager_mod, "port80_problem", lambda: "Port 80 is already in use.")
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        body = {"domains": ["nas.example.com"], "email": "me@example.com", "challenge": "http"}
        r = client.post("/api/https/certificate", json=body)
        assert r.status_code == 202, r.text
        job = _wait_job(client, r.json()["id"])
        assert job["status"] == "failed"
        assert not fake_lego.exists()  # lego never ran
        assert client.get("/api/https").json()["renewal_error"] == "Port 80 is already in use."


def test_issue_refuses_incomplete_settings(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        r = client.post("/api/https/certificate", json={**LE_BODY, "dns_config": {}})
        assert r.status_code == 422
        assert "API token" in r.json()["detail"]
        r = client.post("/api/https/certificate", json={"domains": [], "email": "a@b.co"})
        assert r.status_code == 422


def test_status_lists_dns_providers_and_port80(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        body = client.get("/api/https").json()
        assert [p["id"] for p in body["dns_providers"]] == ["cloudflare"]
        token = body["dns_providers"][0]["fields"][0]
        assert token["secret"] is True
        assert isinstance(body["port80_free"], bool)


# ---------------------------------------------------------------- real lego + Pebble


@pytest.mark.skipif(
    not os.environ.get(letsencrypt.ACME_DIRECTORY_ENV),
    reason="needs Pebble (CI sets ATHENA_ACME_DIRECTORY)",
)
def test_real_lego_gets_a_certificate_from_pebble(tmp_path):
    """CI runs Pebble with validation always passing, so this covers the download and
    checksum, lego's flags, the ACME flow and installing the result, not port 80."""
    port = _free_port()
    with TestClient(_app(tmp_path)) as client:
        signed_in(client)
        body = {"domains": ["nas.example.com"], "email": "me@example.com", "challenge": "http"}
        r = client.post("/api/https/certificate", json=body)
        assert r.status_code == 202, r.text
        job = _wait_job_long(client, r.json()["id"])
        assert job["status"] == "succeeded", "\n".join(job["lines"])
        r = client.put("/api/https", json={"mode": "letsencrypt", "port": port})
        assert r.status_code == 200, r.text
        dns, _ = local_ca.cert_names(_served(port))
        assert dns == {"nas.example.com"}
        client.put("/api/https", json={"mode": "off", "port": port})


def _wait_job_long(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.5)
    raise AssertionError("job didn't finish")

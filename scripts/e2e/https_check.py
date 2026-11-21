# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1", "cryptography>=44"]
# ///
"""Self-signed HTTPS check against an installed Athena (docs/specs/https.md, part 4).

Run it on the host itself; the service restarts between the steps:

    uv run scripts/e2e/https_check.py on  --out e2e-out    # turn on self-signed, check
    <restart the service>
    uv run scripts/e2e/https_check.py check --out e2e-out  # still on after the restart
    athena https off --data-dir <dir>; <restart the service>
    uv run scripts/e2e/https_check.py off --out e2e-out    # plain HTTP again

`on` signs in (or creates the admin on a fresh data dir), saves mode `self_signed` and
downloads the CA to <out>/athena-ca.crt. `on` and `check` then verify:
- https://localhost:<port> answers with a certificate signed by that CA (strict verify);
- the certificate names the hostname and the host's LAN address;
- signing in over HTTPS sets a `Secure` cookie;
- a page load on the HTTP port from the LAN address redirects (307) to HTTPS, one from
  127.0.0.1 doesn't, and /api/health is never redirected.
`off` checks the HTTPS port is closed and HTTP still serves the UI.

Exits non-zero on the first failure. Writes <out>/https.json with what it saw.
"""

import argparse
import ipaddress
import json
import socket
import ssl
import sys
import time
from pathlib import Path

import httpx
from cryptography import x509

USER = "admin"
PASSWORD = "e2e-test-pass-1234"  # the same throwaway admin as smoke.py
PAGE = {"Accept": "text/html", "Sec-Fetch-Mode": "navigate"}


def fail(msg: str) -> None:
    sys.exit(f"FAIL: {msg}")


def ok(msg: str) -> None:
    print(f"ok: {msg}")


def lan_ip() -> str | None:
    """The address the host uses to reach other machines (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return None if ipaddress.ip_address(ip).is_loopback else ip


def wait_healthy(url: str, timeout: float = 120, **kw) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/api/health", timeout=5, **kw).status_code == 200:
                return
        except httpx.HTTPError as e:
            last = str(e)
        time.sleep(2)
    fail(f"{url} not healthy after {timeout:.0f}s: {last}")


def sign_in(client: httpx.Client) -> str:
    """The CSRF token of a new session; creates the admin on a fresh data dir."""
    status = client.get("/api/auth/status").raise_for_status().json()
    body = {"username": USER, "password": PASSWORD}
    path = "/api/auth/setup" if status["setup_required"] else "/api/auth/login"
    r = client.post(path, json=body)
    if r.status_code not in (200, 201):
        fail(f"{path}: {r.status_code} {r.text}")
    return r.json()["csrf_token"]


def turn_on(http: str, port: int, out: Path) -> None:
    with httpx.Client(base_url=http, timeout=30) as c:
        csrf = sign_in(c)
        body = {"mode": "self_signed", "port": port, "redirect": True, "extra_names": []}
        r = c.put("/api/https", json=body, headers={"X-CSRF-Token": csrf})
        if r.status_code != 200:
            fail(f"PUT /api/https: {r.status_code} {r.text}")
        st = r.json()
        if not st["listening"]:
            fail(f"HTTPS saved but not listening: {st['last_error']}")
        ok(f"self-signed on, listening on {port}: {st['urls']}")
        ca = c.get("/api/https/ca.crt").raise_for_status()
        (out / "athena-ca.crt").write_bytes(ca.content)
        ok("downloaded the CA")


def check_on(http: str, port: int, out: Path) -> None:
    ca_file = out / "athena-ca.crt"
    https = f"https://localhost:{port}"
    ctx = ssl.create_default_context(cafile=str(ca_file))  # only Athena's CA, hostname checked
    wait_healthy(https, verify=ctx)
    ok(f"{https} verifies against the downloaded CA")

    pem = ssl.get_server_certificate(("localhost", port))
    cert = x509.load_pem_x509_certificate(pem.encode())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    dns = san.get_values_for_type(x509.DNSName)
    ips = [str(i) for i in san.get_values_for_type(x509.IPAddress)]
    host = socket.gethostname().lower().removesuffix(".local")
    lan = lan_ip()
    seen = {"dns": dns, "ips": ips, "hostname": host, "lan_ip": lan, "serial": cert.serial_number}
    if host.split(".")[0] not in [d.split(".")[0] for d in dns]:
        fail(f"hostname {host} not in the certificate's names {dns}")
    if "127.0.0.1" not in ips:
        fail(f"127.0.0.1 not in the certificate's addresses {ips}")
    if lan and lan not in ips:
        fail(f"LAN address {lan} not in the certificate's addresses {ips}")
    ok(f"certificate names {dns} and {ips}")

    with httpx.Client(base_url=https, verify=ctx, timeout=30) as c:
        sign_in(c)
        cookie = next((h for h in c.cookies.jar if h.name == "athena_session"), None)
        if cookie is None or not cookie.secure:
            fail(f"sign-in over HTTPS didn't set a Secure session cookie: {cookie}")
        ok("sign-in over HTTPS sets a Secure cookie")

    r = httpx.get(f"{http}/", headers=PAGE, timeout=10)
    if r.status_code != 200:
        fail(f"page load from 127.0.0.1 got {r.status_code}, want 200 (no redirect)")
    ok("loopback page loads aren't redirected")
    if lan:
        lan_http = http.replace("localhost", lan).replace("127.0.0.1", lan)
        r = httpx.get(f"{lan_http}/", headers=PAGE, timeout=10)
        want = f"https://{lan}:{port}/"
        if r.status_code != 307 or r.headers.get("location") != want:
            got = f"{r.status_code} {r.headers.get('location')}"
            fail(f"page load from {lan}: {got}, want 307 {want}")
        r = httpx.get(f"{lan_http}/api/health", headers=PAGE, timeout=10)
        if r.status_code != 200:
            fail(f"/api/health from {lan} got {r.status_code}, want 200")
        ok(f"LAN page loads redirect to {want}; /api/health doesn't")
        seen["redirect"] = want
    else:
        print("skip: no LAN address, redirect not checked")
    (out / "https.json").write_text(json.dumps(seen, indent=2))


def check_off(http: str, port: int) -> None:
    wait_healthy(http)
    try:
        socket.create_connection(("127.0.0.1", port), timeout=3).close()
    except OSError:
        ok(f"port {port} is closed")
    else:
        fail(f"port {port} still accepts connections after `athena https off`")
    r = httpx.get(f"{http}/", headers=PAGE, timeout=10)
    if r.status_code != 200:
        fail(f"HTTP page load got {r.status_code}")
    ok("plain HTTP serves the UI")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("step", choices=["on", "check", "off"])
    p.add_argument("--url", default="http://localhost:8420", help="the HTTP address")
    p.add_argument("--https-port", type=int, default=8443)
    p.add_argument("--out", type=Path, default=Path("e2e-out"))
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    if a.step == "off":
        check_off(a.url, a.https_port)
        return
    wait_healthy(a.url)
    if a.step == "on":
        turn_on(a.url, a.https_port, a.out)
    check_on(a.url, a.https_port, a.out)


if __name__ == "__main__":
    main()

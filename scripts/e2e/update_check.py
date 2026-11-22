#!/usr/bin/env python3
"""End-to-end check of `athena update` against a local fake release (docs/specs/self-update.md).

Standard library only. Run it against an Athena installed with the installer from wheel A
(`install.sh --wheel`), on Linux, macOS or Windows:

    python3 scripts/e2e/update_check.py --wheel dist/athena_server-0.0.0-py3-none-any.whl \
        --athena /usr/local/bin/athena --data-dir /var/lib/athena [--sudo]

It builds variants of the wheel with other versions (A 0.1.0, B 0.2.0, a broken C 0.3.0 whose
server exits at start, D 0.4.0 whose checksum is wrong), serves them as a fake GitHub release
through ATHENA_UPDATE_CHECK_URL, then asserts:

1. A is running; an admin and a marker file exist. `athena update` moves it to B on the same
   port, with the data intact.
2. Updating to the broken C rolls back to B with the database as it was (exit code 2).
3. Updating to D (wrong checksum) fails before anything is stopped: the running server's
   start time never changes (exit code 1).

Wheel A must be what is installed first: run with `--build-only` (it prints the variants'
paths), install A with `install.sh --wheel <A>`, then run the full check.
"""

import argparse
import base64
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

PASSWORD = "e2e-test-pass-1234"  # throwaway; the data dir is deleted afterwards
VERSIONS = {"a": "0.1.0", "b": "0.2.0", "c": "0.3.0", "d": "0.4.0"}


# ---------------------------------------------------------------- building the variants


def record_hash(data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"sha256={digest}"


def rewrite_wheel(source: Path, target: Path, version: str, *, broken: bool = False) -> None:
    """Copy a wheel under another version. `broken` makes `athena serve` exit at once."""
    with zipfile.ZipFile(source) as zin:
        meta = next(n for n in zin.namelist() if n.endswith(".dist-info/METADATA"))
        old_info = meta.split("/")[0]
        old_version = old_info.removeprefix("athena_server-").removesuffix(".dist-info")
        new_info = f"athena_server-{version}.dist-info"
        files: dict[str, bytes] = {}
        for item in zin.infolist():
            if item.filename.endswith("/RECORD"):
                continue
            name = item.filename.replace(old_info + "/", new_info + "/", 1)
            data = zin.read(item.filename)
            if name == f"{new_info}/METADATA":
                data = data.replace(
                    f"Version: {old_version}".encode(), f"Version: {version}".encode(), 1
                )
            if broken and name == "athena/cli.py":
                marker = b"def _serve(args: argparse.Namespace) -> int:\n"
                assert marker in data, "cli.py changed: update this patch"
                data = data.replace(marker, marker + b"    return 1  # e2e: a broken release\n", 1)
            files[name] = data
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        record = []
        for name, data in files.items():
            zout.writestr(name, data)
            record.append(f"{name},{record_hash(data)},{len(data)}")
        record.append(f"{new_info}/RECORD,,")
        zout.writestr(f"{new_info}/RECORD", "\n".join(record) + "\n")


def build_variants(wheel: Path, out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, version in VERSIONS.items():
        target = out / f"athena_server-{version}-py3-none-any.whl"
        rewrite_wheel(wheel, target, version, broken=key == "c")
        paths[key] = target
    return paths


# ---------------------------------------------------------------- the fake release


class Release:
    """Serves `releases/latest`, `releases/tags/v<ver>` and the files, like GitHub."""

    def __init__(self, wheels: dict[str, Path]) -> None:
        self.wheels = {VERSIONS[k]: p for k, p in wheels.items()}
        self.latest = VERSIONS["b"]
        self.bad_sums: set[str] = set()
        release = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = self.path.split("?")[0]
                base = f"http://127.0.0.1:{release.port}"
                if path == "/releases/latest":
                    return self.json(release.describe(release.latest, base))
                if path.startswith("/releases/tags/v"):
                    version = path.removeprefix("/releases/tags/v")
                    if version in release.wheels:
                        return self.json(release.describe(version, base))
                    return self.reply(404, b"{}")
                if path.startswith("/dl/v"):
                    version, _, name = path.removeprefix("/dl/v").partition("/")
                    if name == "SHA256SUMS" and version in release.wheels:
                        return self.reply(200, release.sums(version).encode())
                    if version in release.wheels and name == release.wheels[version].name:
                        return self.reply(200, release.wheels[version].read_bytes())
                self.reply(404, b"not found")

            def json(self, body: dict) -> None:
                self.reply(200, json.dumps(body).encode())

            def reply(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                return None

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def check_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/releases/latest"

    def sums(self, version: str) -> str:
        wheel = self.wheels[version]
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if version in self.bad_sums:
            digest = "0" * 64
        return f"{digest}  {wheel.name}\n"

    def describe(self, version: str, base: str) -> dict:
        name = self.wheels[version].name
        return {
            "tag_name": f"v{version}",
            "html_url": f"{base}/release/v{version}",
            "assets": [
                {"name": name, "browser_download_url": f"{base}/dl/v{version}/{name}"},
                {
                    "name": "SHA256SUMS",
                    "browser_download_url": f"{base}/dl/v{version}/SHA256SUMS",
                },
            ],
        }


# ---------------------------------------------------------------- driving Athena


def api(base: str, path: str, body: dict | None = None, cookie: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method="POST" if data else "GET")
    request.add_header("Content-Type", "application/json")
    if cookie:
        request.add_header("Cookie", cookie)
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read()
        return json.loads(raw) if raw else None, response.headers.get("Set-Cookie")


def health(base: str) -> dict | None:
    try:
        return api(base, "/api/health")[0]
    except OSError:
        return None


def wait_for(what: str, ok, timeout: float = 150) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ok():
            return
        time.sleep(1)
    sys.exit(f"timed out waiting for {what}")


def sign_in(base: str) -> str:
    _, cookie = api(base, "/api/auth/login", {"username": "admin", "password": PASSWORD})
    assert cookie, "sign-in set no cookie"
    return cookie.split(";")[0]


def run_update(args: argparse.Namespace, check_url: str, *extra: str) -> int:
    env = {**os.environ, "ATHENA_UPDATE_CHECK_URL": check_url}
    prefix = ["sudo", "env", f"ATHENA_UPDATE_CHECK_URL={check_url}"] if args.sudo else []
    argv = [*prefix, *args.athena, "update", "--yes", "--data-dir", str(args.data_dir), *extra]
    print("$", " ".join(argv), flush=True)
    return subprocess.run(argv, env=env, check=False).returncode


def update_state(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / "updates" / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def settle(args: argparse.Namespace, started: float, phases: tuple[str, ...]) -> dict:
    """Wait for the helper's state to end (on Windows `athena update` returns at once)."""

    def finished() -> bool:
        state = update_state(args.data_dir)
        return state.get("phase") in phases and state.get("started_at", "") >= started_iso(started)

    wait_for(f"the update to end as {phases}", finished)
    return update_state(args.data_dir)


def started_iso(timestamp: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(timestamp - 5, UTC).isoformat()


def leftover_helpers() -> list[str]:
    if os.name == "nt":
        return []
    out = subprocess.run(["pgrep", "-fl", "update_helper.py"], capture_output=True, text=True)
    return out.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wheel", type=Path, required=True, help="the built wheel (any version)")
    parser.add_argument("--athena", required=True, help="the installed `athena` command")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--sudo", action="store_true", help="run `athena update` through sudo")
    parser.add_argument("--build-only", action="store_true", help="only build the variants")
    parser.add_argument("--out", type=Path, default=Path("dist") / "update-wheels")
    args = parser.parse_args()
    args.athena = [args.athena]
    wheels = build_variants(args.wheel, args.out)
    if args.build_only:
        for key, path in wheels.items():
            print(key, path.resolve())
        return 0

    base = f"http://127.0.0.1:{args.port}"
    release = Release(wheels)
    first = health(base)
    assert first is not None, f"no Athena answers on {base}"
    assert first["version"] == VERSIONS["a"], f"install wheel A first, found {first['version']}"

    # Data that has to survive: an admin account and a file next to the database.
    api(base, "/api/auth/setup", {"username": "admin", "password": PASSWORD})
    sign_in(base)
    marker = args.data_dir / "update-e2e-marker.txt"
    writer = [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('kept')"]
    subprocess.run([*(["sudo"] if args.sudo else []), *writer], check=True)

    print("--> update A to B")
    began = time.time()
    code = run_update(args, release.check_url)
    assert code == 0, f"athena update exited {code}"
    state = settle(args, began, ("done", "failed", "rolled_back"))
    assert state["phase"] == "done", state
    wait_for("B to answer", lambda: (health(base) or {}).get("version") == VERSIONS["b"])
    after = health(base)
    assert after["started_at"] != first["started_at"]
    sign_in(base)  # the account survived
    assert marker.exists()
    assert not leftover_helpers(), leftover_helpers()

    print("--> update to the broken C rolls back to B")
    release.latest = VERSIONS["c"]
    began = time.time()
    code = run_update(args, release.check_url)
    state = settle(args, began, ("done", "failed", "rolled_back"))
    assert state["phase"] == "rolled_back", state
    if os.name != "nt":  # on Windows `athena update` returns before the helper ends
        assert code == 2, f"athena update exited {code}, expected 2"
    wait_for("B to answer again", lambda: (health(base) or {}).get("version") == VERSIONS["b"])
    sign_in(base)
    assert not leftover_helpers(), leftover_helpers()

    print("--> a wrong checksum never stops the service")
    release.latest = VERSIONS["d"]
    release.bad_sums.add(VERSIONS["d"])
    before = health(base)
    code = run_update(args, release.check_url)
    assert code == 1, f"athena update exited {code}, expected 1"
    again = health(base)
    assert again and again["started_at"] == before["started_at"], "the service was restarted"
    assert not (args.data_dir / "updates" / VERSIONS["d"]).exists(), "the bad wheel was kept"

    print("update e2e: all good")
    shutil.rmtree(args.out, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

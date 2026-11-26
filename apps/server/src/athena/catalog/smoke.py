"""Install store apps for real and check they start: the catalog's runtime smoke test.

    cd apps/server
    uv run python -m athena.catalog.smoke jellyfin gitea     # some apps
    uv run python -m athena.catalog.smoke --changed           # apps changed vs origin/main
    uv run python -m athena.catalog.smoke --all --jobs 2      # every app (hours, many GB)

For each app (and with ``--variants`` each compose variant) it writes the compose file
and a ``.env`` from the install form's defaults into a temporary folder, with every
port field moved to a free port and every path field moved inside that folder. Then
it pulls the images, runs ``compose up``, and waits until the web port answers over
HTTP(S) with a status below 500 (``x-athena.smoke: web``, the default), or until the
containers have kept running for a while (``smoke: start``). Apps marked
``smoke: skip`` and apps whose images don't run on this CPU are skipped.

Only compose projects named ``athena-test-*`` are touched. Afterwards the project is
taken down with its volumes, and the images it pulled are removed (images that were
already on the host before the test are kept). Results go to ``--out``:
``results.json``, ``summary.md`` and ``logs/<app>.log`` for each failure. The exit code
is 1 when any app failed.

Before each app it checks the disk: below ``--min-free-gb`` (default 20) it stops
starting apps and marks the rest skipped. On Colima it runs ``fstrim`` in the VM after
each app, since its disk file doesn't shrink when images are removed.
"""

import argparse
import contextlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import httpx2

from athena.apps.store import parse_compose, seed_files
from athena.catalog.loader import builtin_catalog_dir, env_file, load_catalog, resolve_values
from athena.catalog.model import CatalogApp, CatalogAppVariant
from athena.catalog.platforms import support

Status = Literal["passed", "failed", "skipped"]

PREFIX = "athena-test-"
PULL_TIMEOUT = 30 * 60
UP_TIMEOUT = 10 * 60
STABLE_FOR = 30
"""Seconds every container must keep running for a ``smoke: start`` app to pass."""
POLL = 3.0
CLEANUP_IMAGE = "busybox:1.37"
"""Deletes the root-owned files containers leave in a test folder on Linux. Kept after
the run (it's about 4 MB), so it's pulled once."""


@dataclass
class Result:
    app: str
    variant: str
    status: Status
    stage: str = ""
    """Where it stopped: pull, up, crashed, unhealthy, web, timeout, or the skip reason."""
    detail: str = ""
    seconds: float = 0.0
    check: str = "web"
    emulated: bool = False
    url: str = ""
    log: str = ""

    @property
    def label(self) -> str:
        return self.app if self.variant == "default" else f"{self.app} ({self.variant})"


@dataclass
class Target:
    app: CatalogApp
    variant: CatalogAppVariant
    project: str = field(init=False)

    def __post_init__(self) -> None:
        suffix = "" if self.variant.slug == "default" else f"-{self.variant.slug}"
        self.project = f"{PREFIX}{self.app.id}{suffix}"[:63].rstrip("-_")


# ---------------------------------------------------------------- engine


class Engine:
    def __init__(self, cli: list[str]) -> None:
        self.cli = cli
        self._ports_lock = threading.Lock()
        self._ports: set[int] = set()

    def run(
        self, *args: str, timeout: float = 120, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [*self.cli, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            return subprocess.CompletedProcess(exc.cmd, 124, out, f"timed out after {timeout}s")

    def arch(self) -> str:
        res = self.run("info", "--format", "{{.Architecture}}")
        return res.stdout.strip() or platform.machine()

    def trim(self) -> None:
        """Give the space of removed images back to the host. Colima's VM disk only grows
        otherwise, so a long run fills the Mac's disk even though each image is removed."""
        if any(".colima" in part for part in self.cli) and shutil.which("colima"):
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ["colima", "ssh", "--", "sudo", "fstrim", "-a"],
                    capture_output=True,
                    timeout=300,
                    check=False,
                )

    def remove_tree(self, folder: Path) -> None:
        """Delete a test folder, including files the containers wrote as root (Linux)."""
        shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():
            # Mount the parent and delete the child, so the folder itself goes too.
            self.run(
                "run", "--rm", "--volume", f"{folder.parent}:/parent",
                CLEANUP_IMAGE, "rm", "-rf", f"/parent/{folder.name}",
                timeout=300,
            )  # fmt: skip

    def has_image(self, ref: str) -> bool:
        return self.run("image", "inspect", "--format", "{{.Id}}", ref).returncode == 0

    def free_port(self) -> int:
        with self._ports_lock:
            while True:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", 0))
                    port = s.getsockname()[1]
                if port not in self._ports:
                    self._ports.add(port)
                    return port


def find_engine() -> Engine | None:
    from athena.containers.runtime import RuntimeUnavailableError, runtime_from
    from athena.platform.detect import detect

    try:
        return Engine(list(runtime_from(detect().get("containers")).cli))
    except RuntimeUnavailableError:
        return None


# ---------------------------------------------------------------- one app


def _tail(text: str, lines: int = 15) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _web_port(variant: CatalogAppVariant, app: CatalogApp, values: dict[str, str]) -> int | None:
    port = variant.web_port if variant.web_port is not None else app.meta.web_port
    if isinstance(port, int):
        return port
    if isinstance(port, str) and values.get(port, "").isdigit():
        return int(values[port])
    return None


def _uses_host_network(compose: str) -> bool:
    services = parse_compose(compose).get("services") or {}
    return any(isinstance(s, dict) and s.get("network_mode") == "host" for s in services.values())


def install_values(target: Target, folder: Path, engine: Engine) -> dict[str, str]:
    """The install form's defaults, with ports moved to free ones and paths into ``folder``."""
    fields = target.variant.env
    submitted: dict[str, str] = {}
    for f in fields:
        if f.type == "port":
            submitted[f.key] = str(engine.free_port())
        elif f.type == "path":
            default = (f.default or "").strip()
            if default.startswith("@app_data"):
                continue  # already inside the app's data folder
            existing = Path(default) if default.startswith("/") else None
            if existing is not None and existing.exists() and not existing.is_dir():
                continue  # a socket or device such as /var/run/docker.sock
            path = folder / "paths" / f.key.lower()
            path.mkdir(parents=True, exist_ok=True)
            submitted[f.key] = str(path)
    return resolve_values(fields, submitted, folder / "data")


def _containers(engine: Engine, compose: list[str], env: dict[str, str]) -> list[dict]:
    # ``env`` matters: compose re-reads the file, and an unset ATHENA_APP_DATA can make it invalid.
    res = engine.run(*compose, "ps", "--all", "--format", "json", env=env)
    text = res.stdout.strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _name(container: dict) -> str:
    return container.get("Service") or container.get("Name") or "?"


def _probe(client: httpx2.Client, port: int, path: str) -> tuple[int | None, str, str]:
    """(status, url, error) for the first scheme that answers."""
    errors: list[str] = []
    for scheme in ("http", "https"):
        url = f"{scheme}://127.0.0.1:{port}{path}"
        try:
            return client.get(url).status_code, url, ""
        except httpx2.HTTPError as exc:
            errors.append(f"{scheme}: {type(exc).__name__}: {str(exc)[:80]}")
    return None, "", "; ".join(errors)


def _wait(
    engine: Engine,
    target: Target,
    compose: list[str],
    check: str,
    port: int | None,
    timeout: float,
    env: dict[str, str],
) -> tuple[Status, str, str, str]:
    """Wait for the app to come up: (status, stage, detail, url)."""
    deadline = time.monotonic() + timeout
    running_since: float | None = None
    crashed_before = False
    last = "containers never started"
    path = target.app.meta.web_path or "/"
    with httpx2.Client(verify=False, timeout=5.0, follow_redirects=False) as client:
        while time.monotonic() < deadline:
            containers = _containers(engine, compose, env)
            running = [c for c in containers if c.get("State") == "running"]
            restarting = [_name(c) for c in containers if c.get("State") == "restarting"]
            unhealthy = [_name(c) for c in containers if c.get("Health") == "unhealthy"]
            dead = [
                f"{_name(c)} exited with code {c.get('ExitCode')}"
                for c in containers
                if c.get("State") in ("exited", "dead") and c.get("ExitCode", 0) != 0
            ]
            # A container that stays exited for two polls in a row has crashed for good
            # (one with a restart policy would be restarting or running by then).
            if dead and crashed_before:
                return "failed", "crashed", "; ".join(dead), ""
            crashed_before = bool(dead)

            if restarting:
                last = f"restarting: {', '.join(restarting)}"
            elif unhealthy:
                last = f"unhealthy: {', '.join(unhealthy)}"

            if check == "web" and port is not None:
                code, url, error = _probe(client, port, path)
                if code is not None and code < 500:
                    return "passed", "web", f"HTTP {code}", url
                if code is not None:
                    last = f"HTTP {code} from {url}"
                elif not restarting and not unhealthy:
                    last = f"web port {port} not answering ({error})"
            elif running and not (restarting or unhealthy or dead):
                running_since = running_since or time.monotonic()
                if time.monotonic() - running_since >= STABLE_FOR:
                    return "passed", "start", f"running for {STABLE_FOR}s", ""
                last = "running"
            else:
                running_since = None
            time.sleep(POLL)
    if last.startswith("restarting"):
        stage = "crashed"
    elif last.startswith("unhealthy"):
        stage = "unhealthy"
    else:
        stage = "timeout"
    return "failed", stage, f"after {int(timeout)}s: {last}", ""


def run_one(
    target: Target, engine: Engine, work: Path, out: Path, os_name: str, arch: str, opts
) -> Result:
    app, variant = target.app, target.variant
    result = Result(app.id, variant.slug, "skipped", check=app.meta.smoke)
    if app.meta.smoke == "skip":
        result.stage, result.detail = "marked skip", app.meta.smoke_note or ""
        return result
    fit = support(app.meta.platforms, os_name, arch)
    if fit == "unsupported":
        result.stage = "unsupported CPU"
        result.detail = f"published for {', '.join(app.meta.platforms)}, host is {arch}"
        return result
    result.emulated = fit == "emulated"
    check = app.meta.smoke
    if check == "web" and _uses_host_network(variant.compose):
        check, result.detail = "start", "host networking"
    result.check = check

    started = time.monotonic()
    folder = work / target.project
    folder.mkdir(parents=True, exist_ok=True)
    compose_path = folder / "compose.yaml"
    compose_path.write_text(variant.compose, encoding="utf-8")
    values = install_values(target, folder, engine)
    (folder / ".env").write_text(env_file(values), encoding="utf-8")
    seed_files(folder, target.app.files)
    env = {**os.environ, "ATHENA_APP_DATA": str(folder / "data")}
    compose = ["compose", "--project-name", target.project, "--file", str(compose_path)]
    port = _web_port(variant, app, values)
    if check == "web" and port is None:
        check = result.check = "start"
    images = [
        line.strip()
        for line in engine.run(*compose, "config", "--images", env=env).stdout.splitlines()
        if line.strip()
    ]
    already = {ref for ref in images if engine.has_image(ref)}
    log: list[str] = []

    def finish(status: Status, stage: str, detail: str) -> Result:
        result.status, result.stage = status, stage
        result.detail = "; ".join(x for x in (result.detail, detail) if x)
        result.seconds = round(time.monotonic() - started, 1)
        if status == "failed":
            logs = engine.run(*compose, "logs", "--no-color", "--tail", "200", env=env)
            log.append("== compose logs ==\n" + logs.stdout + logs.stderr)
            (out / "logs").mkdir(parents=True, exist_ok=True)
            path = out / "logs" / f"{target.project.removeprefix(PREFIX)}.log"
            path.write_text("\n\n".join(log), encoding="utf-8")
            result.log = str(path)
        return result

    try:
        pull = engine.run(*compose, "pull", "--quiet", timeout=PULL_TIMEOUT, env=env)
        if pull.returncode != 0:
            log.append("== pull ==\n" + pull.stderr)
            return finish("failed", "pull", _tail(pull.stderr, 3))
        up = engine.run(*compose, "up", "--detach", "--remove-orphans", timeout=UP_TIMEOUT, env=env)
        if up.returncode != 0:
            log.append("== up ==\n" + up.stderr)
            return finish("failed", "up", _tail(up.stderr, 3))
        timeout = opts.timeout * (2 if result.emulated else 1)
        status, stage, detail, url = _wait(engine, target, compose, check, port, timeout, env)
        result.url = url
        return finish(status, stage, detail)
    finally:
        if not opts.keep:
            engine.run(
                *compose,
                "down",
                "--volumes",
                "--remove-orphans",
                "--timeout",
                "10",
                timeout=300,
                env=env,
            )
            if not opts.keep_images:
                for ref in images:
                    if ref not in already:
                        engine.run("image", "rm", ref)
                engine.trim()
            engine.remove_tree(folder)


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


# ---------------------------------------------------------------- selection


def changed_apps(root: Path, base: str) -> set[str]:
    """App ids with a file changed against ``base`` (committed, staged or untracked)."""
    repo = root.parent
    ids: set[str] = set()
    commands = [
        ["git", "diff", "--name-only", f"{base}...HEAD", "--", "catalog/apps"],
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "catalog/apps"],
    ]
    for cmd in commands:
        res = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise SystemExit(f"{' '.join(cmd)} failed: {res.stderr.strip()}")
        for line in res.stdout.splitlines():
            path = line[3:] if cmd[1] == "status" else line
            parts = path.strip().strip('"').split("/")
            if len(parts) >= 3 and parts[:2] == ["catalog", "apps"]:
                ids.add(parts[2])
    return ids


def select(
    apps: list[CatalogApp], ids: Iterable[str], variants: bool, shard: tuple[int, int] | None
) -> list[Target]:
    wanted = set(ids)
    chosen = [a for a in apps if a.id in wanted] if wanted else list(apps)
    targets = [Target(a, v) for a in chosen for v in (a.variants if variants else a.variants[:1])]
    if shard:
        index, count = shard
        targets = targets[index - 1 :: count]
    return targets


def _shard(value: str) -> tuple[int, int]:
    index, _, count = value.partition("/")
    if not (index.isdigit() and count.isdigit() and 1 <= int(index) <= int(count)):
        raise argparse.ArgumentTypeError("use K/N, e.g. 2/6")
    return int(index), int(count)


# ---------------------------------------------------------------- report


def summary(results: list[Result], arch: str, os_name: str) -> str:
    counts = {s: sum(r.status == s for r in results) for s in ("passed", "failed", "skipped")}
    lines = [
        f"# Catalog smoke test ({os_name}, {arch})",
        "",
        f"{counts['passed']} passed, {counts['failed']} failed, {counts['skipped']} skipped.",
        "",
        "| App | Result | Stage | Detail | Seconds |",
        "|---|---|---|---|---|",
    ]
    order = {"failed": 0, "passed": 1, "skipped": 2}
    for r in sorted(results, key=lambda r: (order[r.status], r.label)):
        detail = r.detail.replace("|", "\\|").replace("\n", " ")[:200]
        mark = {"passed": "✅", "failed": "❌", "skipped": "⏭️"}[r.status]
        emulated = " (emulated)" if r.emulated else ""
        lines.append(
            f"| {r.label}{emulated} | {mark} {r.status} | {r.stage} | {detail} | {r.seconds} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("apps", nargs="*", help="app ids")
    pick = parser.add_mutually_exclusive_group()
    pick.add_argument("--all", action="store_true", help="test every built-in app")
    pick.add_argument(
        "--changed",
        nargs="?",
        const="origin/main",
        metavar="BASE",
        help="test the apps changed against BASE (default origin/main), including uncommitted",
    )
    parser.add_argument("--variants", action="store_true", help="test every compose variant")
    parser.add_argument("--shard", type=_shard, help="run part K of N, e.g. 2/6 (for CI)")
    parser.add_argument("--jobs", type=int, default=1, help="apps tested at once (default 1)")
    parser.add_argument(
        "--timeout", type=int, default=180, help="seconds to wait for an app to come up"
    )
    parser.add_argument("--keep", action="store_true", help="leave apps running to inspect")
    parser.add_argument("--keep-images", action="store_true", help="don't remove pulled images")
    parser.add_argument(
        "--out", type=Path, default=Path("catalog-smoke-report"), help="report folder"
    )
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=20,
        help="stop starting apps when the disk has less free space (default 20)",
    )
    args = parser.parse_args(argv)

    root = builtin_catalog_dir()
    if root is None:
        print("catalog/ not found", file=sys.stderr)
        return 2
    apps, errors = load_catalog(root, "builtin")
    if errors:
        print("\n".join(errors), file=sys.stderr)
    known = {a.id for a in apps}
    ids: set[str] = set(args.apps)
    if args.changed:
        ids |= changed_apps(root, args.changed) & known
        if not ids:
            print(f"no catalog apps changed against {args.changed}")
            return 0
    elif not ids and not args.all:
        parser.error("name some apps, or pass --changed or --all")
    if missing := ids - known:
        print(f"unknown apps: {', '.join(sorted(missing))}", file=sys.stderr)
        return 2
    targets = select(apps, ids, args.variants, args.shard)

    engine = find_engine()
    if engine is None:
        print("no container engine is running", file=sys.stderr)
        return 2
    arch = engine.arch()
    os_name = platform.system().lower()
    args.out.mkdir(parents=True, exist_ok=True)
    # Inside --out rather than the system temp folder: Colima and Docker Desktop share the
    # home folder with their VM, but not always /var/folders or /tmp.
    (args.out / "work").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=PREFIX, dir=(args.out / "work").resolve()))
    print(f"testing {len(targets)} app(s) on {os_name}/{arch}, {args.jobs} at a time")

    results: list[Result] = []
    lock = threading.Lock()
    low_disk = threading.Event()

    def write_report() -> None:
        with contextlib.suppress(OSError):
            (args.out / "results.json").write_text(
                json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8"
            )
            (args.out / "summary.md").write_text(summary(results, arch, os_name), encoding="utf-8")

    def task(target: Target) -> Result:
        free = free_gb(work)
        if free < args.min_free_gb:
            engine.trim()
            free = free_gb(work)
        if low_disk.is_set() or free < args.min_free_gb:
            low_disk.set()
            result = Result(
                target.app.id,
                target.variant.slug,
                "skipped",
                "low disk",
                f"{free:.0f} GB free, --min-free-gb is {args.min_free_gb:g}",
            )
        else:
            try:
                result = run_one(target, engine, work, args.out, os_name, arch, args)
            except Exception as exc:  # one broken app mustn't stop the run
                result = Result(target.app.id, target.variant.slug, "failed", "error", repr(exc))
        with lock:
            results.append(result)
            write_report()
            print(
                f"[{len(results)}/{len(targets)}] {result.label}: {result.status}"
                f" {result.stage} {result.seconds}s {result.detail[:160]}".rstrip(),
                flush=True,
            )
        return result

    try:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            list(pool.map(task, targets))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        with contextlib.suppress(OSError):
            (args.out / "work").rmdir()
        write_report()
    failed = sum(r.status == "failed" for r in results)
    print(f"report: {args.out / 'summary.md'}")
    if low_disk.is_set():
        print("stopped early: the disk is low on space (see --min-free-gb)", file=sys.stderr)
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

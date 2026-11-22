"""`athena update`: the checks and downloads before the swap, and the plan the helper runs."""

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx2
import pytest

from athena import self_update
from athena.cli import main
from athena.self_update import Options, Paths, ToolEnv, UpdateError
from athena.service.plan import Run
from athena.updates import Release

CHECK_URL = "https://api.github.com/repos/o/r/releases/latest"
BASE = "https://github.com/o/r/releases/download/v0.2.0"
OLD_BASE = "https://github.com/o/r/releases/download/v0.1.0"
WHEEL_NAME = "athena_server-0.2.0-py3-none-any.whl"
WHEEL = b"the new wheel"
OLD_WHEEL = b"the old wheel"


def release(version: str = "0.2.0") -> Release:
    base = f"https://github.com/o/r/releases/download/v{version}"
    name = f"athena_server-{version}-py3-none-any.whl"
    return Release(
        tag=f"v{version}",
        version=version,
        wheel_name=name,
        wheel_url=f"{base}/{name}",
        sums_url=f"{base}/SHA256SUMS",
        html_url=None,
    )


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def transport(files: dict[str, bytes]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = files.get(str(request.url))
        return httpx2.Response(200, content=body) if body is not None else httpx2.Response(404)

    return httpx2.MockTransport(handler)


def make_tool(tmp_path: Path, name: str = "athena-server") -> Path:
    venv = tmp_path / "opt" / "tools" / name
    venv.mkdir(parents=True)
    athena_bin = (tmp_path / "bin" / "athena").as_posix()
    (venv / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "athena-server" }]\n'
        f'entrypoints = [{{ name = "athena", install-path = "{athena_bin}" }}]\n',
        encoding="utf-8",
    )
    (tmp_path / "opt" / "python").mkdir()
    return venv


def tools_for(tmp_path: Path) -> ToolEnv:
    return self_update.tool_env(make_tool(tmp_path))


# ---------------------------------------------------------------- the install we run from


def test_tool_env_reads_the_uv_receipt(tmp_path: Path) -> None:
    tools = tools_for(tmp_path)
    assert tools.tool_dir == tmp_path / "opt" / "tools"
    assert tools.bin_dir == tmp_path / "bin"
    assert tools.python_dir == tmp_path / "opt" / "python"
    assert tools.env() == {
        "UV_TOOL_DIR": str(tmp_path / "opt" / "tools"),
        "UV_NO_PROGRESS": "1",
        "UV_TOOL_BIN_DIR": str(tmp_path / "bin"),
        "UV_PYTHON_INSTALL_DIR": str(tmp_path / "opt" / "python"),
    }


def test_tool_env_refuses_a_non_uv_install(tmp_path: Path) -> None:
    (tmp_path / "venv").mkdir()
    with pytest.raises(UpdateError, match="wasn't installed with the installer"):
        self_update.tool_env(tmp_path / "venv")


def test_tool_env_refuses_another_tools_receipt(tmp_path: Path) -> None:
    with pytest.raises(UpdateError, match="isn't the athena-server"):
        self_update.tool_env(make_tool(tmp_path, "other-tool"))


def test_find_uv_prefers_path_then_the_install_root(tmp_path: Path) -> None:
    tools = tools_for(tmp_path)
    assert self_update.find_uv(tools, which=lambda n: "/usr/bin/uv") == "/usr/bin/uv"
    (tmp_path / "opt" / "bin").mkdir()
    exe = "uv.exe" if self_update.os.name == "nt" else "uv"
    (tmp_path / "opt" / "bin" / exe).write_text("")
    assert self_update.find_uv(tools, which=lambda n: None) == str(tmp_path / "opt" / "bin" / exe)


def test_not_ready_says_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A source or pip install has no receipt.
    assert "wasn't installed with the installer" in (self_update.not_ready_reason(tmp_path) or "")
    tools = tools_for(tmp_path)
    monkeypatch.setattr(self_update, "tool_env", lambda: tools)
    monkeypatch.setattr(self_update, "__version__", "0.1.0")
    assert self_update.not_ready_reason(tmp_path, uv="/bin/uv") is None
    monkeypatch.setattr(self_update, "find_uv", lambda tools: None)
    assert "uv wasn't found" in (self_update.not_ready_reason(tmp_path, uv=None) or "")
    monkeypatch.setattr(self_update, "__version__", "0.0.0")
    assert "no release to go back to" in (
        self_update.not_ready_reason(tmp_path, uv="/bin/uv") or ""
    )


# ---------------------------------------------------------------- download and verify


def test_sums_parsing() -> None:
    good = sha(b"x")
    text = f"{good}  {WHEEL_NAME}\n{sha(b'y')} *other.whl\n"
    assert self_update.parse_sums(text, WHEEL_NAME) == good
    assert self_update.parse_sums(text, "other.whl") == sha(b"y")
    assert self_update.parse_sums(text, "missing.whl") is None
    assert self_update.parse_sums(f"nothex  {WHEEL_NAME}\n", WHEEL_NAME) is None


async def download(tmp_path: Path, files: dict[str, bytes]):
    rel = release()
    return await self_update.download_release(
        rel, tmp_path / "0.2.0", CHECK_URL, lambda _: None, transport(files)
    )


def test_a_matching_download_is_kept(tmp_path: Path) -> None:
    files = {
        f"{BASE}/{WHEEL_NAME}": WHEEL,
        f"{BASE}/SHA256SUMS": f"{sha(WHEEL)}  {WHEEL_NAME}\n".encode(),
    }
    path, digest = asyncio.run(download(tmp_path, files))
    assert path.read_bytes() == WHEEL and digest == sha(WHEEL)
    assert (tmp_path / "0.2.0" / "SHA256SUMS").is_file()
    assert not list((tmp_path / "0.2.0").glob("*.part"))


def test_a_checksum_mismatch_deletes_the_files(tmp_path: Path) -> None:
    files = {
        f"{BASE}/{WHEEL_NAME}": WHEEL,
        f"{BASE}/SHA256SUMS": f"{sha(b'other')}  {WHEEL_NAME}\n".encode(),
    }
    with pytest.raises(UpdateError, match="doesn't match its published checksum"):
        asyncio.run(download(tmp_path, files))
    assert not (tmp_path / "0.2.0").exists()


def test_a_missing_sums_entry_deletes_the_files(tmp_path: Path) -> None:
    files = {
        f"{BASE}/{WHEEL_NAME}": WHEEL,
        f"{BASE}/SHA256SUMS": f"{sha(WHEEL)}  other.whl\n".encode(),
    }
    with pytest.raises(UpdateError, match="refusing to install an unverified wheel"):
        asyncio.run(download(tmp_path, files))
    assert not (tmp_path / "0.2.0").exists()


def test_a_redirect_to_another_host_is_refused(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "github.com":
            return httpx2.Response(302, headers={"location": "https://evil.example/x"})
        return httpx2.Response(200, content=b"x")

    with pytest.raises(UpdateError, match="isn't an allowed host"):
        asyncio.run(
            self_update.download_release(
                release(),
                tmp_path / "0.2.0",
                CHECK_URL,
                lambda _: None,
                httpx2.MockTransport(handler),
            )
        )


# ---------------------------------------------------------------- the plan


def plan_for(tmp_path: Path, platform: str, **over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "paths": Paths(tmp_path / "data"),
        "tools": tools_for(tmp_path),
        "uv": "/bin/uv",
        "release": release(),
        "wheel_sha": sha(WHEEL),
        "previous": (tmp_path / "data" / "updates" / "previous" / "old.whl", sha(OLD_WHEEL)),
        "current": "0.1.0",
        "health_url": "http://127.0.0.1:8420/api/health",
        "port": 8420,
        "old_started_at": "t0",
        "manage_service": True,
        "platform": platform,
    }
    args.update(over)
    return self_update.build_plan(**args)


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_the_plan_is_built_on_any_host(tmp_path: Path, platform: str) -> None:
    plan = plan_for(tmp_path, platform)
    json.dumps(plan)  # plain data: the helper reads it as JSON
    assert plan["from"] == "0.1.0" and plan["to"] == "0.2.0"
    # Install is offline (pre-flight cached the dependencies) and takes the verified wheel.
    argv = plan["install"][0]["argv"]
    assert argv[:4] == ["/bin/uv", "tool", "install", "--force"]
    assert "--offline" in argv and argv[argv.index("--python") + 1] == "3.13"
    assert argv[-1] == str(tmp_path / "data" / "updates" / "0.2.0" / WHEEL_NAME)
    assert plan["wheel"]["sha256"] == sha(WHEEL)
    # Start is `service install` from the (same-path) venv, which rewrites and restarts.
    assert plan["start"][0]["argv"][1:5] == ["-m", "athena", "service", "install"]
    assert plan["start"][0]["argv"][0].startswith(str(tmp_path / "opt" / "tools" / "athena-server"))
    assert plan["stop"] and plan["fallback_start"]
    back = plan["rollback"]
    assert back["install"][0]["argv"][-1].endswith("old.whl")
    assert {Path(r["dst"]).name for r in back["restore"]} == {
        "athena.db",
        "athena.json",
        "secret.key",
    }
    assert plan["env"]["UV_TOOL_DIR"] == str(tmp_path / "opt" / "tools")


def test_the_plan_stops_with_the_service_commands(tmp_path: Path) -> None:
    from athena.service import build_stop

    plan = plan_for(tmp_path, "linux")
    assert plan["stop"] == [
        {"argv": s.argv, "ignore_errors": s.ignore_errors}
        for s in build_stop("linux").steps
        if isinstance(s, Run)
    ]


def test_without_a_service_nothing_is_stopped_started_or_waited_for(tmp_path: Path) -> None:
    plan = plan_for(tmp_path, "linux", manage_service=False)
    assert plan["stop"] == plan["start"] == plan["fallback_start"] == []
    assert plan["health_url"] is None and plan["port"] is None
    assert any("restart Athena yourself" in line for line in self_update.describe_plan(plan))


def test_no_rollback_leaves_nothing_to_go_back_to(tmp_path: Path) -> None:
    plan = plan_for(tmp_path, "linux", previous=None)
    assert plan["rollback"]["install"] == []
    assert "No rollback" in "\n".join(self_update.describe_plan(plan))


def test_the_saved_state_is_a_consistent_copy(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    db = sqlite3.connect(data / "athena.db")
    db.execute("create table t (v text)")
    db.execute("insert into t values ('kept')")
    db.commit()
    db.close()
    (data / "athena.json").write_text("{}", encoding="utf-8")
    (data / "secret.key").write_bytes(b"k")
    paths = Paths(data)
    self_update.save_for_rollback(paths, "0.1.0")
    saved = paths.saved("0.1.0")
    copy = sqlite3.connect(saved / "athena.db")
    assert copy.execute("select v from t").fetchall() == [("kept",)]
    copy.close()
    assert (saved / "secret.key").read_bytes() == b"k"
    assert (saved / "athena.json").is_file()


# ---------------------------------------------------------------- the flow


class Flow:
    """`update()` with the network, uv and the helper faked."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.data = tmp_path / "data"
        self.data.mkdir()
        self.tools = tools_for(tmp_path)
        self.started: list[dict] = []
        self.helper_exit: int | None = 0
        self.files = {
            f"{BASE}/{WHEEL_NAME}": WHEEL,
            f"{BASE}/SHA256SUMS": f"{sha(WHEEL)}  {WHEEL_NAME}\n".encode(),
            f"{OLD_BASE}/athena_server-0.1.0-py3-none-any.whl": OLD_WHEEL,
            f"{OLD_BASE}/SHA256SUMS": (
                f"{sha(OLD_WHEEL)}  athena_server-0.1.0-py3-none-any.whl\n".encode()
            ),
        }
        monkeypatch.setattr(self_update, "__version__", "0.1.0")
        monkeypatch.setattr(self_update, "tool_env", lambda prefix=None: self.tools)
        monkeypatch.setattr(self_update, "find_uv", lambda tools: "/bin/uv")
        monkeypatch.setattr(self_update, "preflight", lambda *a, **k: None)
        monkeypatch.setattr(self_update, "service_installed", lambda: True)
        monkeypatch.setattr(self_update, "server_address", lambda d: ("127.0.0.1", 8420))
        monkeypatch.setattr(self_update, "health_of", lambda url: {"started_at": "t0"})
        monkeypatch.setattr(self_update.updates_module, "resolve", self.resolve)
        monkeypatch.setattr(
            self_update,
            "start_helper",
            lambda plan, *a: self.started.append(plan) or self.helper_exit,
        )
        self.real_download = self_update.download_release
        monkeypatch.setattr(self_update, "download_release", self.download)
        (self.data / "athena.db").write_bytes(b"")
        self.latest = "0.2.0"

    def resolve(self, url, version=None, **kw):
        return release(version or self.latest)

    async def download(self, rel, folder, check_url, say, transport_=None):
        return await self.real_download(rel, folder, check_url, say, transport(self.files))

    def run(self, **over: Any) -> tuple[int, list[str]]:
        lines: list[str] = []
        opts = Options(data_dir=self.data, check_url=CHECK_URL, yes=True, **over)
        return self_update.update(opts, lines.append), lines


@pytest.fixture
def flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Flow:
    return Flow(tmp_path, monkeypatch)


def test_update_downloads_verifies_then_hands_the_plan_over(flow: Flow) -> None:
    code, lines = flow.run()
    assert code == 0
    assert len(flow.started) == 1
    plan = flow.started[0]
    assert (plan["from"], plan["to"], plan["old_started_at"]) == ("0.1.0", "0.2.0", "t0")
    assert Path(plan["wheel"]["path"]).read_bytes() == WHEEL
    assert Path(plan["rollback"]["wheel"]["path"]).read_bytes() == OLD_WHEEL
    assert (flow.data / "updates" / "pre-0.1.0").is_dir()
    assert any("Checksum verified" in line for line in lines)


def test_a_bad_checksum_never_stops_anything(flow: Flow, capsys: pytest.CaptureFixture) -> None:
    flow.files[f"{BASE}/SHA256SUMS"] = f"{sha(b'other')}  {WHEEL_NAME}\n".encode()
    code, _ = flow.run()
    assert code == 1
    assert flow.started == []
    assert "doesn't match its published checksum" in capsys.readouterr().err
    assert not (flow.data / "updates" / "0.2.0").exists()


def test_already_current_does_nothing(flow: Flow) -> None:
    flow.latest = "0.1.0"
    code, lines = flow.run()
    assert code == 0 and flow.started == []
    assert "is the latest version" in lines[0]


def test_a_downgrade_needs_the_flag(flow: Flow, capsys: pytest.CaptureFixture) -> None:
    flow.latest = "0.0.5"
    code, _ = flow.run()
    assert code == 1 and flow.started == []
    assert "--allow-downgrade" in capsys.readouterr().err


def test_a_source_build_cannot_update_without_no_rollback(
    flow: Flow, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(self_update, "__version__", "0.0.0")
    code, _ = flow.run(version="0.2.0")
    assert code == 1 and flow.started == []
    assert "--no-rollback" in capsys.readouterr().err


def test_no_rollback_skips_the_old_wheel_and_the_saved_copy(flow: Flow) -> None:
    code, _ = flow.run(no_rollback=True)
    assert code == 0
    assert flow.started[0]["rollback"]["install"] == []
    assert not (flow.data / "updates" / "previous").exists()


def test_a_missing_current_release_stops_before_the_swap(
    flow: Flow, capsys: pytest.CaptureFixture
) -> None:
    del flow.files[f"{OLD_BASE}/SHA256SUMS"]
    code, _ = flow.run()
    assert code == 1 and flow.started == []
    assert "No release of the current version 0.1.0" in capsys.readouterr().err


@pytest.mark.parametrize(("helper_exit", "expected"), [(2, 2), (3, 3), (1, 1)])
def test_the_helper_exit_code_is_ours(flow: Flow, helper_exit: int, expected: int) -> None:
    flow.helper_exit = helper_exit
    assert flow.run()[0] == expected


def test_a_second_update_is_refused_while_one_runs(flow: Flow) -> None:
    import os

    (flow.data / "updates").mkdir()
    (flow.data / "updates" / "lock").write_text(str(os.getpid()))
    code, _ = flow.run()
    assert code == 1 and flow.started == []


def test_a_stale_lock_is_ignored(flow: Flow) -> None:
    (flow.data / "updates").mkdir()
    (flow.data / "updates" / "lock").write_text("999999999")
    assert flow.run()[0] == 0


def test_dry_run_prints_the_plan_and_downloads_nothing(flow: Flow) -> None:
    code, lines = flow.run(dry_run=True)
    text = "\n".join(lines)
    assert code == 0 and flow.started == []
    assert "Dry run" in text and "tool install --force --offline" in text
    assert not (flow.data / "updates").exists()


def test_without_yes_a_non_terminal_asks_for_it(
    flow: Flow, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    opts = Options(data_dir=flow.data, check_url=CHECK_URL)
    assert self_update.update(opts, lambda _: None) == 1
    assert "pass --yes" in capsys.readouterr().err
    assert flow.started == []


def test_check_reports_current_latest_and_readiness(
    flow: Flow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(self_update, "not_ready_reason", lambda d: "uv wasn't found")
    lines: list[str] = []
    assert self_update.check(Options(data_dir=flow.data, check_url=CHECK_URL), lines.append) == 0
    assert lines == [
        "Current version: 0.1.0",
        "Latest release: 0.2.0 (newer)",
        "This host can't update itself: uv wasn't found",
    ]


def test_the_cli_wires_update_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Options] = []
    monkeypatch.setattr(self_update, "update", lambda opts, say=print: seen.append(opts) or 7)
    monkeypatch.setenv("ATHENA_UPDATE_CHECK_URL", CHECK_URL)
    code = main(
        [
            "update",
            "--version",
            "0.2.0-rc.1",
            "--pre",
            "--yes",
            "--no-rollback",
            "--allow-downgrade",
            "--dry-run",
            "--data-dir",
            str(tmp_path),
        ]
    )
    assert code == 7
    opts = seen[0]
    assert (opts.version, opts.pre, opts.yes, opts.no_rollback, opts.allow_downgrade) == (
        "0.2.0-rc.1",
        True,
        True,
        True,
        True,
    )
    assert opts.dry_run and opts.data_dir == tmp_path and opts.check_url == CHECK_URL


def test_the_helper_is_copied_out_of_the_venv(tmp_path: Path) -> None:
    paths = Paths(tmp_path)
    [helper] = self_update.helper_command(paths)
    assert Path(helper).parent == tmp_path / "updates" / "run"
    assert Path(helper).read_text(encoding="utf-8").startswith('"""The self-update helper')

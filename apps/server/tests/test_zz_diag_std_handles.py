# ruff: noqa: E501
"""TEMPORARY diagnostic (remove before merge): what happens to the std handles."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

CHILD = r"""
import gc, json, subprocess, sys, time, traceback
import _winapi
out, mode = sys.argv[1], sys.argv[2]
log = []

def handles():
    res = {}
    for name, sid in (("in", -10), ("out", -11), ("err", -12)):
        try:
            h = _winapi.GetStdHandle(sid)
        except OSError as e:
            res[name] = f"GetStdHandle err {e.winerror}"; continue
        if not h:
            res[name] = "NULL"; continue
        p = _winapi.GetCurrentProcess()
        try:
            c = _winapi.DuplicateHandle(p, h, p, 0, 1, _winapi.DUPLICATE_SAME_ACCESS)
            _winapi.CloseHandle(c); ok = "dup ok"
        except OSError as e:
            ok = f"dup err {e.winerror}"
        res[name] = f"{h:#x} {ok}"
    try:
        r = subprocess.run(["cmd", "/c", "echo", "x"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        res["probe"] = r.stdout.decode().strip()
    except OSError as e:
        res["probe"] = f"winerror {e.winerror}"
    return res

def note(stage):
    log.append([stage, handles()])
    with open(out, "w") as f: json.dump({"exe": sys.executable, "log": log}, f, indent=1)

try:
    note("start")
    if mode == "athena":
        from athena.terminal.pty import _Windows
        pty = _Windows(["powershell.exe", "-NoLogo"], 80, 24, None, None)
    else:
        from athena.terminal import pty as P
        from winpty import PtyProcess
        class W(P._Windows):
            def __init__(s, argv):
                s.proc = PtyProcess.spawn(argv, dimensions=(24, 80)); s.pid = s.proc.pid
        pty = W(["powershell.exe", "-NoLogo"])
    note("spawned")
    time.sleep(2); pty.read(); note("read")
    pty.terminate(); note("terminated")
    del pty; gc.collect(); time.sleep(2); note("dropped")
except Exception:
    log.append(["exception", traceback.format_exc()])
    with open(out, "w") as f: json.dump({"exe": sys.executable, "log": log}, f, indent=1)
"""


@pytest.mark.skipif(sys.platform != "win32", reason="diag")
@pytest.mark.parametrize("mode", ["raw", "athena"])
@pytest.mark.parametrize("how", ["python-detached", "pythonw-detached", "pythonw-schtasks"])
def test_diag(tmp_path, mode, how):
    script = tmp_path / "child.py"
    script.write_text(CHILD)
    out = tmp_path / "out.json"
    exe = Path(sys.executable)
    if how.startswith("pythonw"):
        exe = exe.with_name("pythonw.exe")
    argv = [str(exe), str(script), str(out), mode]
    if how == "pythonw-schtasks":
        name = f"athena-test-diag-{mode}"
        tr = " ".join(f'"{a}"' for a in argv)
        subprocess.run(
            [
                "schtasks",
                "/Create",
                "/TN",
                name,
                "/TR",
                tr,
                "/SC",
                "ONLOGON",
                "/RL",
                "LIMITED",
                "/F",
            ],
            check=True,
        )
        subprocess.run(["schtasks", "/Run", "/TN", name], check=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if (out.exists() and '"dropped"' in out.read_text()) or (
                out.exists() and "exception" in out.read_text()
            ):
                break
            time.sleep(1)
        subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"])
    else:
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESTDHANDLES
        info.hStdInput = info.hStdOutput = info.hStdError = 0
        subprocess.Popen(argv, startupinfo=info, creationflags=0x8).wait(timeout=90)
    text = out.read_text() if out.exists() else "no output"
    pytest.fail("DIAG " + how + " " + mode + "\n" + text)

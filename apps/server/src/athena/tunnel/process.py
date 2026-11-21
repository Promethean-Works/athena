"""A tunnel client (cloudflared, ngrok) that Athena runs and owns.

The process must outlive the job that starts it, whose event loop closes when the
job ends, so it runs under `subprocess.Popen` with a reader thread instead of an
asyncio subprocess. The thread keeps the last lines of output and signals when a
line matches what the caller waits for (the public URL, or "connected").
"""

import asyncio
import collections
import contextlib
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

_TAIL = 50


def find_binary(name: str) -> str | None:
    """`name` on PATH, or where the providers' `install()` puts it (maybe not on PATH)."""
    if found := shutil.which(name):
        return found
    for candidate in (
        Path("/usr/local/bin") / name,
        Path.home() / ".local" / "bin" / name,
        Path.home() / "scoop" / "shims" / f"{name}.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


class TunnelProcess:
    def __init__(self, argv: list[str], env: dict[str, str], ready: re.Pattern[str]) -> None:
        self._ready = ready
        self._event = threading.Event()
        self.match: re.Match[str] | None = None
        self.lines: collections.deque[str] = collections.deque(maxlen=_TAIL)
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self.proc = subprocess.Popen(
            argv,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )
        threading.Thread(target=self._read, daemon=True, name="tunnel-output").start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.rstrip()
            self.lines.append(line)
            if self.match is None and (m := self._ready.search(line)):
                self.match = m
                self._event.set()
        self._event.set()  # Exited: wake the waiter so it can report why.

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    async def wait_ready(self, timeout: float) -> re.Match[str]:
        """The matching line, or RuntimeError with the output if it exits or times out."""
        ok = await asyncio.to_thread(self._event.wait, timeout)
        if self.match is not None:
            return self.match
        output = "\n".join(self.lines) or "(no output)"
        self.stop()
        if not ok:
            raise RuntimeError(f"Tunnel didn't come up within {timeout:.0f} s:\n{output}")
        raise RuntimeError(f"Tunnel exited (code {self.proc.returncode}):\n{output}")

    def stop(self, grace: float = 5.0) -> None:
        if not self.alive:
            return
        self.proc.terminate()
        deadline = time.monotonic() + grace
        while self.alive and time.monotonic() < deadline:
            time.sleep(0.05)
        if self.alive:
            with contextlib.suppress(OSError):
                self.proc.kill()
            self.proc.wait(timeout=grace)

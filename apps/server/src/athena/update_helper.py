"""The self-update helper: swaps Athena's install while the server is stopped.

Standard library only, and it never imports `athena`. Before every update `athena` copies
this file to `<data-dir>/updates/run/` and starts it with `python -I` using the *base*
interpreter, so nothing it runs lives inside the tool venv that is being replaced (Windows
locks those files, and the service manager kills the server's whole process tree).

The helper is dumb on purpose: `athena` writes `plan.json` (argv lists for stop, install and
start, the health URL, the expected version, the rollback steps) and the helper only runs it.
Progress goes to `state.json` (written atomically), the log file and stdout.

Exit codes: 0 updated, 1 aborted before anything was stopped, 2 rolled back to the old
version, 3 failed and not running.
See docs/specs/self-update.md.
"""

import contextlib
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXIT_DONE = 0
EXIT_ABORTED = 1
EXIT_ROLLED_BACK = 2
EXIT_FAILED = 3

LOG_TAIL_LINES = 30
PORT_FREE_SECONDS = 30.0
KEEP_VERSIONS = 2
PREVIOUS_DAYS = 7


class StepFailed(Exception):
    """A step of the swap failed; the reason is shown to the admin."""


class Helper:
    def __init__(self, plan: dict[str, Any], out: Any = None) -> None:
        self.plan = plan
        self.out = out if out is not None else sys.stdout
        self.state_file = Path(plan["state_file"])
        self.log_file = Path(plan["log_file"])
        self.lock_file = Path(plan["lock_file"])
        self.started_at = datetime.now(UTC).isoformat()
        self.tail: list[str] = []
        self.env = {**os.environ, **plan.get("env", {})}
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_file.open("a", encoding="utf-8", errors="replace")

    # ------------------------------------------------------------ reporting

    def say(self, line: str) -> None:
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        self.tail = [*self.tail, line][-LOG_TAIL_LINES:]
        self._log.write(f"{stamp} {line}\n")
        self._log.flush()
        with contextlib.suppress(OSError, ValueError):  # no console under pythonw.exe
            print(line, file=self.out, flush=True)

    def write_state(self, phase: str, step: str, error: str | None = None) -> None:
        state = {
            "phase": phase,
            "step": step,
            "from": self.plan["from"],
            "to": self.plan["to"],
            "started_at": self.started_at,
            "error": error,
            "log_tail": self.tail,
        }
        tmp = self.state_file.with_name(self.state_file.name + ".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_file)

    def step(self, phase: str, text: str) -> None:
        self.say(f"==> {text}")
        self.write_state(phase, text)

    # ------------------------------------------------------------ building blocks

    def run_argv(self, argv: list[str], ignore_errors: bool = False) -> None:
        self.say("$ " + " ".join(f'"{a}"' if " " in a else a for a in argv))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            done = subprocess.run(
                argv,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                check=False,
            )
        except OSError as exc:
            if ignore_errors:
                self.say(f"(ignored) {exc}")
                return
            raise StepFailed(f"can't run {argv[0]}: {exc}") from exc
        for line in done.stdout.decode("utf-8", errors="replace").splitlines():
            if line.strip():
                self.say("  " + line.rstrip())
        if done.returncode != 0 and not ignore_errors:
            raise StepFailed(f"{Path(argv[0]).name} failed with exit code {done.returncode}")

    def run_steps(self, steps: list[dict[str, Any]]) -> None:
        for step in steps:
            self.run_argv(step["argv"], bool(step.get("ignore_errors")))

    def wait_port_free(self) -> None:
        port = self.plan.get("port")
        if not port:
            return
        deadline = time.monotonic() + PORT_FREE_SECONDS
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                probe.settimeout(0.5)
                if probe.connect_ex(("127.0.0.1", int(port))) != 0:
                    return
            time.sleep(0.5)
        raise StepFailed(f"port {port} is still in use {PORT_FREE_SECONDS:.0f} s after stopping")

    def check_wheel(self, wheel: dict[str, str]) -> None:
        path = Path(wheel["path"])
        if not path.is_file():
            raise StepFailed(f"{path} is missing")
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != wheel["sha256"].lower():
            raise StepFailed(f"{path.name} changed after it was checked; refusing to install it")

    def health(self, version: str) -> None:
        """Wait until the new server answers with `version` and a new start time."""
        url = self.plan.get("health_url")
        if not url:  # no service is installed: nothing to wait for
            return
        old_started = self.plan.get("old_started_at")
        deadline = time.monotonic() + float(self.plan.get("health_timeout", 90))
        poll = float(self.plan.get("poll_interval", 1.0))
        seen = "no answer"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    data = json.loads(response.read(65536))
                seen = f"version {data.get('version')}"
                if data.get("version") == version and data.get("started_at") != old_started:
                    self.say(f"Athena {version} is answering")
                    return
            except (OSError, ValueError):
                pass
            time.sleep(poll)
        raise StepFailed(f"Athena {version} didn't come up in time (last answer: {seen})")

    def restore(self, files: list[dict[str, str]]) -> None:
        for item in files:
            src, dst = Path(item["src"]), Path(item["dst"])
            if not src.is_file():
                continue
            if dst.name == "athena.db":  # a stale WAL would be replayed over the old database
                for suffix in ("-wal", "-shm"):
                    Path(str(dst) + suffix).unlink(missing_ok=True)
            tmp = dst.with_name(dst.name + ".restore")
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
            self.say(f"Restored {dst.name}")

    # ------------------------------------------------------------ the sequence

    def swap(self) -> None:
        plan = self.plan
        self.step("stopping", "Stopping Athena")
        self.run_steps(plan["stop"])
        self.wait_port_free()
        self.step("installing", f"Installing Athena {plan['to']}")
        self.check_wheel(plan["wheel"])
        self.run_steps(plan["install"])
        self.step("starting", "Starting Athena")
        self.run_steps(plan["start"])
        self.step("checking", "Waiting for Athena to answer")
        self.health(plan["to"])

    def roll_back(self) -> bool:
        """Put the old version back. True when it answers again."""
        back = self.plan["rollback"]
        self.step("rolling_back", f"Going back to Athena {self.plan['from']}")
        try:
            if not back["install"]:
                raise StepFailed("no rollback was prepared (--no-rollback)")
            self.run_steps(self.plan["stop"])
            self.wait_port_free()
            self.restore(back["restore"])
            self.check_wheel(back["wheel"])
            self.run_steps(back["install"])
            self.run_steps(self.plan["start"])
            self.health(self.plan["from"])
            return True
        except StepFailed as exc:
            self.say(f"Rolling back failed: {exc}")
        # Never leave the service stopped without trying to start something.
        try:
            self.run_steps(self.plan.get("fallback_start", []))
        except StepFailed as exc:
            self.say(f"Starting failed too: {exc}")
        return False

    def finish(self) -> int:
        plan = self.plan
        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self.lock_file.write_text(str(os.getpid()), encoding="utf-8")
            try:
                self.check_wheel(plan["wheel"])
            except StepFailed as exc:  # nothing is stopped yet, so there is nothing to undo
                self.say(f"Update aborted before stopping Athena: {exc}")
                self.write_state("aborted", "Aborted", str(exc))
                return EXIT_ABORTED
            try:
                self.swap()
            except StepFailed as exc:
                reason = str(exc)
                self.say(f"Update failed: {reason}")
                if self.roll_back():
                    self.say(f"Rolled back to Athena {plan['from']}")
                    self.write_state("rolled_back", "Rolled back", reason)
                    return EXIT_ROLLED_BACK
                self.say(
                    "Athena isn't running. Run the installer one-liner again to repair it "
                    "(see the Athena README)."
                )
                self.write_state("failed", "Failed", reason)
                return EXIT_FAILED
            self.say(f"Updated to Athena {plan['to']}")
            self.write_state("done", "Updated")
            self.prune()
            return EXIT_DONE
        finally:
            self.lock_file.unlink(missing_ok=True)
            self._log.close()

    def prune(self) -> None:
        """Keep the last two downloaded versions; drop the old version's wheel after a week."""
        updates = Path(self.plan["updates_dir"])
        versions = sorted(
            (p for p in updates.iterdir() if p.is_dir() and p.name[:1].isdigit()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in versions[KEEP_VERSIONS:]:
            shutil.rmtree(old, ignore_errors=True)
        previous = updates / "previous"
        if previous.is_dir() and time.time() - previous.stat().st_mtime > PREVIOUS_DAYS * 86400:
            shutil.rmtree(previous, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: update_helper.py <plan.json>", file=sys.stderr)
        return 1
    plan = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    return Helper(plan).finish()


if __name__ == "__main__":
    sys.exit(main())

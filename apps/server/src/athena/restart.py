"""Restart Athena (docs/specs/backup.md → Restart Athena).

`athena serve` runs the server in a child process and starts a new one when the child
exits with `RESTART_EXIT_CODE`. That works the same under systemd, launchd, the Windows
scheduled task and a terminal, because none of them has to restart anything.

This module is the child's side: the server registers itself, a request handler asks
for a restart, and `athena serve` reads `requested()` after the server stops.
"""

from typing import Protocol

RESTART_EXIT_CODE = 75
"""EX_TEMPFAIL from sysexits.h: "try again". Nothing else in Athena exits with it."""

CHILD_ENV = "ATHENA_SERVE_CHILD"
"""Set to "1" in the environment of the supervised server process."""


class Stoppable(Protocol):
    should_exit: bool


_server: Stoppable | None = None
_requested = False


def register(server: Stoppable | None) -> None:
    """Tell this module which server to stop (None forgets it, for tests)."""
    global _server, _requested
    _server = server
    _requested = False


def available() -> bool:
    """Whether a supervisor will start the server again after it stops."""
    return _server is not None


def request() -> bool:
    """Stop the server so the supervisor starts a new one. False if it can't."""
    global _requested
    if _server is None:
        return False
    _requested = True
    _server.should_exit = True
    return True


def requested() -> bool:
    return _requested

"""LazyMCPApp: one shared start, recovery after failures, and a shutdown that never raises."""

import asyncio
import contextlib

import pytest

from athena.mcp import server
from athena.mcp.lazy import LazyMCPApp


class FakeMCP:
    """Stands in for fastmcp's http_app: counts lifespans and can fail on demand."""

    def __init__(self, state: dict) -> None:
        self.state = state

    @contextlib.asynccontextmanager
    async def lifespan(self, app):
        self.state["started"] += 1
        if self.state.get("fail_start"):
            raise RuntimeError("lifespan failed")
        await asyncio.sleep(self.state.get("start_delay", 0))
        self.state["running"] += 1
        try:
            yield
        finally:
            self.state["running"] -= 1
            if self.state.get("fail_stop"):
                raise RuntimeError("stop failed")

    async def __call__(self, scope, receive, send) -> None:
        self.state["served"] += 1


@pytest.fixture
def state(monkeypatch) -> dict:
    st = {"started": 0, "running": 0, "served": 0}

    class Built:
        def http_app(self, **_):
            return FakeMCP(st)

    monkeypatch.setattr(server, "build_mcp_server", lambda app: Built())
    return st


async def _call(lazy: LazyMCPApp) -> None:
    await lazy({"type": "http", "path": "/"}, None, None)


def test_concurrent_first_requests_share_one_start(state) -> None:
    async def main() -> None:
        lazy = LazyMCPApp(None)
        await asyncio.gather(*(_call(lazy) for _ in range(5)))
        assert (state["started"], state["served"]) == (1, 5)
        await lazy.aclose()
        assert state["running"] == 0

    asyncio.run(main())


def test_a_cancelled_first_request_does_not_start_a_second_server(state) -> None:
    state["start_delay"] = 0.2

    async def main() -> None:
        lazy = LazyMCPApp(None)
        first = asyncio.create_task(_call(lazy))
        await asyncio.sleep(0.05)
        first.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await first
        await _call(lazy)
        assert state["started"] == 1
        await lazy.aclose()
        assert state["running"] == 0

    asyncio.run(main())


def test_a_failed_start_is_retried(state) -> None:
    async def main() -> None:
        lazy = LazyMCPApp(None)
        state["fail_start"] = True
        with pytest.raises(RuntimeError, match="lifespan failed"):
            await _call(lazy)
        state["fail_start"] = False
        await _call(lazy)
        assert (state["started"], state["served"]) == (2, 1)
        await lazy.aclose()

    asyncio.run(main())


def test_aclose_never_raises_and_a_later_lifespan_starts_fresh(state) -> None:
    lazy = LazyMCPApp(None)

    async def run_once() -> None:
        await _call(lazy)
        await lazy.aclose()  # fail_stop: logged, not raised

    state["fail_stop"] = True
    asyncio.run(run_once())
    asyncio.run(run_once())  # a new event loop, as in a second TestClient block
    assert (state["started"], state["served"], state["running"]) == (2, 2, 0)


def test_aclose_before_any_request_is_a_no_op(state) -> None:
    asyncio.run(LazyMCPApp(None).aclose())
    assert state["started"] == 0

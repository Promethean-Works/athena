"""Shared helpers for Athena e2e tests.

Each test script runs against an installed Athena service (the release build served
by `athena serve`, not `next dev`). It creates the admin account through /setup,
signs in, exercises a feature area, and writes a `summary.json` to --out.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

USER = "admin"
PASSWORD = "e2e-test-pass-1234"  # throwaway; the data dir is deleted afterwards


def wait_healthy(url: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=5) as r:
                if r.status == 200:
                    print(f"healthy: {r.read().decode()}")
                    return
        except OSError as e:
            last = str(e)
        time.sleep(2)
    sys.exit(f"server at {url} not healthy after {timeout:.0f}s: {last}")


class Checks:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.errors: list[str] = []
        self.console: list[str] = []
        self.server_errors: list[str] = []

    def attach(self, page: Page) -> None:
        page.on(
            "console",
            lambda m: self.console.append(f"{page.url}: {m.text}")
            if m.type == "error"
            else None,
        )
        page.on("pageerror", lambda e: self.console.append(f"{page.url}: {e}"))
        page.on(
            "response",
            lambda r: self.server_errors.append(f"{r.status} {r.request.method} {r.url}")
            if r.status >= 500
            else None,
        )

    def shot(self, page: Page, name: str) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=self.out / f"{name}.png", full_page=True)

    def step(self, name: str, fn) -> None:
        print(f"--> {name}")
        try:
            fn()
        except Exception as e:
            self.errors.append(f"{name}: {e}")
            print(f"    FAILED: {e}")

    def drain(self, where: str) -> None:
        for line in self.console:
            self.errors.append(f"{where}: console error: {line}")
        for line in self.server_errors:
            self.errors.append(f"{where}: server error: {line}")
        self.console.clear()
        self.server_errors.clear()


def sign_in(page: Page, password: str = PASSWORD) -> None:
    page.get_by_label("Username").fill(USER)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in").click()


def setup_admin(page: Page, base: str, skip_ai: bool = True) -> None:
    """First-run setup: create the admin account and reach the dashboard."""
    page.goto(f"{base}/setup/")
    page.get_by_label("Username").fill(USER)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_label("Confirm password").fill(PASSWORD)
    page.get_by_role("button", name="Create account").click()
    if skip_ai:
        # The setup wizard's AI step is optional: skip it to reach the dashboard.
        page.get_by_role("button", name="Skip for now").click()
    page.wait_for_url(f"{base}/")
    # Every signed-in page shows the sidebar; a crash shows Next's error page.
    page.get_by_role("link", name="Dashboard").first.wait_for()


def capabilities(base: str, page: Page) -> dict:
    r = page.request.get(f"{base}/api/system/capabilities")
    assert r.ok, f"GET capabilities: {r.status}"
    manifest = r.json()
    return manifest


def ready_capabilities(manifest: dict) -> set[str]:
    return {cap["id"] for cap in manifest.get("capabilities", []) if cap.get("available")}


def requires_capability(cap_id: str):
    """Decorator: skip a step if a capability isn't ready."""

    def decorator(fn):
        def wrapper(page: Page, manifest: dict, *args, **kwargs):
            if cap_id not in ready_capabilities(manifest):
                print(f"    SKIPPED: {cap_id} not available")
                return
            return fn(page, manifest, *args, **kwargs)

        return wrapper

    return decorator


def summary(out: Path, os_name: str, errors: list[str]) -> int:
    (out / "summary.json").write_text(json.dumps({"os": os_name, "errors": errors}, indent=2))
    if errors:
        print("\nFAILED:\n  " + "\n  ".join(errors))
        return 1
    print("\nall checks passed")
    return 0

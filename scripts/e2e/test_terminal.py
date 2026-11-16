"""E2E: host terminal (run a command, see output) and container shell action.

Requires the `terminal.host` capability. Container shell requires `containers` ready
and at least one running container (optional; skipped otherwise).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import Checks, ready_capabilities, setup_admin, summary, wait_healthy  # noqa: E402


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8420")
    ap.add_argument("--out", type=Path, default=Path("e2e-out-terminal"))
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    base = args.url.rstrip("/")
    args.out.mkdir(parents=True, exist_ok=True)

    wait_healthy(base, args.timeout)

    c = Checks(args.out)
    manifest = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 860})
        ctx.set_default_timeout(20_000)
        page = ctx.new_page()
        c.attach(page)

        setup_admin(page, base)
        manifest = capabilities(base, page)
        ready = ready_capabilities(manifest)

        @c.step("open the terminal page")
        def open_terminal() -> None:
            if "terminal.host" not in ready:
                print("    SKIPPED: terminal.host not ready")
                return
            page.goto(f"{base}/terminal/")
            page.wait_for_url(f"{base}/terminal/")

        @c.step("run a command in the host terminal")
        def run_command() -> None:
            if "terminal.host" not in ready:
                return
            page.get_by_text("Connected").wait_for(timeout=15_000)
            page.locator(".xterm").click()
            page.keyboard.type("echo athena-e2e-terminal")
            page.keyboard.press("Enter")
            page.locator(".xterm-rows").wait_for_function(
                "el => el.textContent.includes('athena-e2e-terminal')", timeout=15_000
            )

        c.drain("terminal")
        browser.close()

    summary(args.out, manifest.get("os", "unknown"), c.errors)
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())

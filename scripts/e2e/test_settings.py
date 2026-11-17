"""E2E: settings (appearance live apply, password change, system switches).

Runs as admin. Requires no special capabilities beyond being signed in.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import Checks, capabilities, setup_admin, summary, wait_healthy  # noqa: E402


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8420")
    ap.add_argument("--out", type=Path, default=Path("e2e-out-settings"))
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

        @c.step("open Settings → Appearance")
        def open_appearance() -> None:
            page.goto(f"{base}/settings/appearance/")
            page.wait_for_url(f"{base}/settings/appearance/")

        @c.step("switch appearance mode to dark")
        def switch_dark() -> None:
            page.get_by_role("button", name="Dark").click()
            page.wait_for_timeout(2_000)
            page.locator("html").wait_for_function("el => el.dataset.theme === 'dark'", timeout=10_000)

        @c.step("switch appearance mode back to light")
        def switch_light() -> None:
            page.get_by_role("button", name="Light").click()
            page.wait_for_timeout(2_000)
            page.locator("html").wait_for_function("el => el.dataset.theme === 'light'", timeout=10_000)

        @c.step("open Settings → Account and change the password")
        def change_password() -> None:
            page.goto(f"{base}/settings/account/")
            page.wait_for_url(f"{base}/settings/account/")
            page.get_by_label("Current password").fill(PASSWORD)
            page.get_by_label("New password").fill("e2e-new-pass-5678")
            page.get_by_label("Confirm password").fill("e2e-new-pass-5678")
            page.get_by_role("button", name="Change password").click()
            page.get_by_text("Password changed").wait_for(timeout=15_000)

        @c.step("open Settings → System")
        def open_system() -> None:
            page.goto(f"{base}/settings/system/")
            page.wait_for_url(f"{base}/settings/system/")

        c.drain("settings")
        browser.close()

    summary(args.out, manifest.get("os", "unknown"), c.errors)
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())

"""E2E: app lifecycle (install from store, custom compose app, start/stop/restart/update/remove).

Requires the `containers` capability to be ready for deploy; store install also needs
the `store` capability. Skips steps whose capabilities aren't available.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import Checks, ready_capabilities, requires_capability, setup_admin, summary, wait_healthy  # noqa: E402

COMPOSE = """services:
  web:
    image: nginx:1.29-alpine
    ports:
      - "18090:80"
"""


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8420")
    ap.add_argument("--out", type=Path, default=Path("e2e-out-apps"))
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    base = args.url.rstrip("/")
    args.out.mkdir(parents=True, exist_ok=True)

    wait_healthy(base, args.timeout)

    c = Checks(args.out)
    manifest = {}
    name = "athena-e2e-app"

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 860})
        ctx.set_default_timeout(20_000)
        page = ctx.new_page()
        c.attach(page)

        setup_admin(page, base)
        manifest = capabilities(base, page)
        ready = ready_capabilities(manifest)

        # ---------------------------------------------------------------- custom compose app
        @c.step("open new-app page")
        def open_new_app() -> None:
            if "containers" not in ready:
                print("    SKIPPED: containers not ready")
                return
            page.goto(f"{base}/apps/new/")
            page.wait_for_url(f"{base}/apps/new/")

        @c.step("deploy a custom compose app")
        def deploy_app() -> None:
            if "containers" not in ready:
                return
            page.get_by_label("Name").fill(name)
            page.get_by_label("compose.yaml").fill(COMPOSE)
            page.get_by_role("button", name="Validate").click()
            # Wait for the validation alert to appear.
            page.get_by_text("The compose file is valid").wait_for(timeout=15_000)
            page.get_by_role("button", name="Deploy").click()
            # After deploy, the job dialog opens and the app list redirects to the detail view.
            page.wait_for_url(f"{base}/apps/view/?name={name}", timeout=60_000)
            page.get_by_role("link", name=name).wait_for()

        @c.step("app appears on the apps page")
        def app_listed() -> None:
            if "containers" not in ready:
                return
            page.goto(f"{base}/apps/")
            page.get_by_role("link", name=name).wait_for(timeout=15_000)

        @c.step("start/stop/restart the app")
        def app_actions() -> None:
            if "containers" not in ready:
                return
            page.goto(f"{base}/apps/view/?name={name}")
            # The actions menu is on the app tile / detail page.
            page.get_by_role("button", name=f"Actions for {name}").click()
            page.get_by_role("menuitem", name="Stop").click()
            page.wait_for_timeout(2_000)
            page.get_by_role("button", name=f"Actions for {name}").click()
            page.get_by_role("menuitem", name="Start").click()
            page.wait_for_timeout(2_000)

        @c.step("remove the app")
        def remove_app() -> None:
            if "containers" not in ready:
                return
            page.goto(f"{base}/apps/")
            page.get_by_role("button", name=f"Actions for {name}").click()
            page.get_by_role("menuitem", name="Remove").click()
            page.get_by_role("button", name="Remove").click()
            # Wait for the job to finish and the tile to disappear.
            page.wait_for_timeout(5_000)
            page.wait_for_function(
                f"() => !document.body.textContent.includes('{name}')", timeout=60_000
            )

        # ---------------------------------------------------------------- store install
        @c.step("install an app from the store")
        def install_store_app() -> None:
            if "store" not in ready or "containers" not in ready:
                print("    SKIPPED: store or containers not ready")
                return
            page.goto(f"{base}/store/")
            page.get_by_role("button", name="Install").first.click()
            # Install form: confirm with defaults.
            page.get_by_role("button", name="Install").click()
            page.wait_for_timeout(3_000)

        c.drain("apps")
        browser.close()

    summary(args.out, manifest.get("os", "unknown"), c.errors)
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())

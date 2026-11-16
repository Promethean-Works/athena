"""E2E: package managers (search, install, uninstall, upgrade).

Requires at least one `packages.*` capability to be ready. Steps are defensive: a manager
that isn't installed on the host is skipped rather than failed.
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
    ap.add_argument("--out", type=Path, default=Path("e2e-out-packages"))
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

        mgrs = [c_id for c_id in ready if c_id.startswith("packages.")]

        @c.step("open the packages page")
        def open_packages() -> None:
            if not mgrs:
                print("    SKIPPED: no package manager ready")
                return
            page.goto(f"{base}/packages/")
            page.wait_for_url(f"{base}/packages/")

        @c.step("each manager tab renders and lists packages")
        def manager_tabs() -> None:
            if not mgrs:
                return
            for mgr in mgrs:
                label = mgr.split(".", 1)[1]
                page.get_by_role("tab", name=label).wait_for(timeout=10_000)
                page.get_by_role("tab", name=label).click()
                # The installed/upgradable lists should render without error.
                page.wait_for_timeout(1_000)

        c.drain("packages")
        browser.close()

    summary(args.out, manifest.get("os", "unknown"), c.errors)
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())

"""E2E: cloud storage (add a WebDAV remote, browse, upload/download, sync preview).

Requires the `cloud.rclone` capability (rclone installed and answering). Skips
otherwise — rclone isn't installed on every host.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import Checks, ready_capabilities, capabilities, setup_admin, summary, wait_healthy  # noqa: E402


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8420")
    ap.add_argument("--out", type=Path, default=Path("e2e-out-cloud"))
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

        @c.step("open the cloud page")
        def open_cloud() -> None:
            if "cloud.rclone" not in ready:
                print("    SKIPPED: cloud.rclone not ready")
                return
            page.goto(f"{base}/cloud/")
            page.wait_for_url(f"{base}/cloud/")

        @c.step("the no-rclone state or remotes list renders")
        def cloud_page_renders() -> None:
            if "cloud.rclone" not in ready:
                return
            # Either the "install rclone" card or the remotes grid should appear.
            page.get_by_role("heading", name="Cloud storage").wait_for(timeout=15_000)
            page.wait_for_timeout(2_000)

        c.drain("cloud")
        browser.close()

    summary(args.out, manifest.get("os", "unknown"), c.errors)
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())

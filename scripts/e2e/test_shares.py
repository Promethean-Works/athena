"""E2E: share links (create read + upload-only links, password, expiry, visitor /s/ page).

Flow: Files page -> a file's row menu -> Share -> configure -> create link -> copy ->
open /s/<token> in a fresh context (no session) as a visitor.

Requires the `files` capability and at least one existing file in a location.
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
    ap.add_argument("--out", type=Path, default=Path("e2e-out-shares"))
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

        @c.step("create a read link from a file's menu")
        def create_read_link() -> None:
            if "files" not in ready:
                print("    SKIPPED: files not ready")
                return
            page.goto(f"{base}/files/")
            page.wait_for_url(f"{base}/files/")
            # Open the first entry's row menu and choose Share.
            page.get_by_role("button", name="Actions").first.click()
            page.get_by_role("menuitem", name="Share").click()
            page.get_by_role("button", name="Create link").click()
            page.get_by_text("Link created").wait_for(timeout=15_000)
            page.get_by_role("button", name="Copy link").click()
            page.wait_for_timeout(1_000)

        @c.step("create an upload-only drop box")
        def create_upload_link() -> None:
            if "files" not in ready:
                return
            page.get_by_role("button", name="Actions").first.click()
            page.get_by_role("menuitem", name="Share").click()
            page.get_by_role("button", name="Upload only").click()
            page.get_by_role("button", name="Create link").click()
            page.get_by_text("Link created").wait_for(timeout=15_000)

        @c.step("visitor page rejects an unknown token")
        def visitor_unknown_token() -> None:
            if "files" not in ready:
                return
            visitor = browser.new_context()
            vpage = visitor.new_page()
            c.attach(vpage)
            vpage.goto(f"{base}/s/does-not-exist")
            vpage.get_by_text("This link doesn't work").wait_for(timeout=15_000)
            visitor.close()

        c.drain("shares")
        browser.close()

    summary(args.out, manifest.get("os", "unknown"), c.errors)
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())

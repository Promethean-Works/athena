"""E2E: AI assistant chat with a read-only tool call and approval cards.

Requires an AI provider to be configured (Settings → AI) and at least one read-only
tool capability (containers, files, packages.* or store). Skips when no provider
is set up, since the chat won't have a model to call.
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
    ap.add_argument("--out", type=Path, default=Path("e2e-out-assistant"))
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

        has_provider = any(c_id.startswith("assistant.provider") or c_id == "ai.ollama" for c_id in ready)

        @c.step("open the assistant page")
        def open_assistant() -> None:
            if not has_provider:
                print("    SKIPPED: no AI provider configured")
                return
            page.goto(f"{base}/assistant/")
            page.wait_for_url(f"{base}/assistant/")

        @c.step("send a message that triggers a read-only tool call")
        def send_message() -> None:
            if not has_provider:
                return
            page.get_by_label("Message").fill("What apps are installed on this server?")
            page.get_by_role("button", name="Send").click()
            # Wait for a reply or an approval card (a tool call needs approval for mutating
            # tools, but read-only tools run freely).
            page.wait_for_timeout(8_000)

        @c.step("approval card appears for a mutating tool and can be denied")
        def deny_approval() -> None:
            if not has_provider:
                return
            # Ask the assistant to do something mutating that needs approval.
            page.get_by_label("Message").fill("Create a folder named athena-e2e-assistant in the app data location.")
            page.get_by_role("button", name="Send").click()
            # Wait for an approval card.
            page.get_by_role("button", name="Deny").wait_for(timeout=20_000)
            page.get_by_role("button", name="Deny").click()
            page.wait_for_timeout(2_000)

        c.drain("assistant")
        browser.close()

    summary(args.out, manifest.get("os", "unknown"), c.errors)
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())

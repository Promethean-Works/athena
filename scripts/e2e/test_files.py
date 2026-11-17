"""E2E: file manager (browse, create folder, upload, edit text, rename, copy/move, delete/trash).

Requires the `files` capability. All operations happen inside the default Home or App data
location so nothing outside the data dir is touched.
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
    ap.add_argument("--out", type=Path, default=Path("e2e-out-files"))
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    base = args.url.rstrip("/")
    args.out.mkdir(parents=True, exist_ok=True)

    wait_healthy(base, args.timeout)

    c = Checks(args.out)
    manifest = {}
    name = "athena-e2e-file.txt"
    folder = "athena-e2e-folder"

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 860})
        ctx.set_default_timeout(20_000)
        page = ctx.new_page()
        c.attach(page)

        setup_admin(page, base)
        manifest = capabilities(base, page)
        ready = ready_capabilities(manifest)

        @c.step("open the file manager")
        def open_files() -> None:
            if "files" not in ready:
                print("    SKIPPED: files not ready")
                return
            page.goto(f"{base}/files/")
            page.wait_for_url(f"{base}/files/")

        @c.step("create a folder")
        def create_folder() -> None:
            if "files" not in ready:
                return
            page.get_by_role("button", name="New folder").click()
            page.get_by_label("Name").fill(folder)
            page.get_by_role("button", name="Create").click()
            page.get_by_text(folder).wait_for(timeout=15_000)

        @c.step("upload a file")
        def upload_file() -> None:
            if "files" not in ready:
                return
            page.get_by_role("button", name="Upload").click()
            # Upload input is hidden; set_files targets it directly.
            page.set_input_files("input[type=file]", Path(__file__).parent / ".." / "README.md")
            page.wait_for_timeout(2_000)

        @c.step("edit a text file and save")
        def edit_text_file() -> None:
            if "files" not in ready:
                return
            page.get_by_role("link", name="README.md").click()
            page.get_by_role("button", name="Edit").click()
            editor = page.get_by_label("Editor")
            editor.fill("athena-e2e-edit-marker")
            page.get_by_role("button", name="Save").click()
            page.get_by_text("Saved").wait_for(timeout=15_000)

        @c.step("rename the file")
        def rename_file() -> None:
            if "files" not in ready:
                return
            page.goto(f"{base}/files/")
            page.get_by_role("button", name=f"Actions for {name}").click()
            page.get_by_role("menuitem", name="Rename").click()
            page.get_by_label("Name").fill("athena-e2e-renamed.txt")
            page.get_by_role("button", name="Rename").click()
            page.get_by_text("athena-e2e-renamed.txt").wait_for(timeout=15_000)

        @c.step("copy the file into the folder")
        def copy_file() -> None:
            if "files" not in ready:
                return
            page.get_by_role("button", name=f"Actions for athena-e2e-renamed.txt").click()
            page.get_by_role("menuitem", name="Copy").click()
            page.get_by_role("button", name="Choose destination").click()
            page.get_by_text(folder).click()
            page.get_by_role("button", name="Copy").click()
            page.wait_for_timeout(2_000)

        @c.step("delete the file to trash")
        def delete_file() -> None:
            if "files" not in ready:
                return
            page.get_by_role("button", name=f"Actions for athena-e2e-renamed.txt").click()
            page.get_by_role("menuitem", name="Delete").click()
            page.get_by_role("button", name="Move to trash").click()
            page.wait_for_timeout(2_000)

        c.drain("files")
        browser.close()

    summary(args.out, manifest.get("os", "unknown"), c.errors)
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())

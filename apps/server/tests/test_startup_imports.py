"""Startup stays light: the assistant and MCP stacks load on first use, not at import.

They are most of Athena's startup memory (about 100 MB), which matters on a 1 GB board.
Runs in a fresh interpreter, since other tests import them.
"""

import subprocess
import sys

HEAVY = ("pydantic_ai", "pydantic_ai_harness", "fastmcp", "mcp", "openai", "exa_py", "pgtask")

CODE = f"""
import sys, tempfile
from pathlib import Path
from athena.config import Settings
from athena.main import create_app
data = Path(tempfile.mkdtemp())
create_app(Settings(data_dir=data, web_dir=data / "no-web", log_to_file=False))
print(" ".join(m for m in {HEAVY!r} if m in sys.modules))
"""


def test_create_app_does_not_import_the_assistant_or_mcp_stacks() -> None:
    out = subprocess.run(
        [sys.executable, "-c", CODE], capture_output=True, text=True, check=True, timeout=120
    )
    assert out.stdout.strip() == "", f"loaded at startup: {out.stdout.strip()}"

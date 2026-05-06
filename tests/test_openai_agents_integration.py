from __future__ import annotations

import py_compile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAI_AGENTS_DIR = REPO_ROOT / "src" / "celesto" / "integrations" / "openai_agents"


def test_openai_agents_integration_compiles_without_optional_dependencies() -> None:
    """The optional integration should parse even when extras are not installed."""
    for name in ["common.py", "hosted.py", "smolvm.py", "__init__.py"]:
        py_compile.compile(str(OPENAI_AGENTS_DIR / name), doraise=True)

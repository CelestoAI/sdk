from __future__ import annotations

import py_compile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_openai_agents_integration_compiles_without_optional_dependencies() -> None:
    """The optional integration should parse even when extras are not installed."""
    py_compile.compile(
        str(
            REPO_ROOT
            / "src"
            / "celesto"
            / "integrations"
            / "openai_agents"
            / "sandbox.py"
        ),
        doraise=True,
    )

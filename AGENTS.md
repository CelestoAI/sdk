# Celesto SDK - GitHub Copilot Instructions

## Project Overview

Celesto SDK is a Python client + CLI for the Celesto AI platform. It provides:
- A typed Python SDK (`CelestoSDK`) for Deployments and GateKeeper.
- A CLI (`celesto`) for deployment and A2A utilities.

## Repository Structure

```
celesto-sdk/
├── src/celesto/       # SDK + CLI source code
│   ├── sdk/               # SDK client, exceptions, types
│   ├── main.py            # CLI app entrypoint (typer)
│   ├── deployment.py      # CLI deployment helpers
│   ├── a2a.py              # CLI A2A helpers
│   └── proxy.py           # CLI MCP proxy helper
├── tests/                 # Test suite
├── pyproject.toml         # Project metadata and dependencies
└── README.md              # Usage and install docs
```

## Development Setup

- Python >= 3.10
- Install deps with uv (recommended):

```bash
pip install uv
uv venv
uv sync
```

Or with pip:

```bash
pip install -e .
```

## Code Style and Linting

- **Ruff** is the linter and formatter.

```bash
uv run ruff check .
uv run ruff format .
```

## Tests

```bash
uv run pytest
```

## Development Guidelines

- Make minimal, targeted changes.
- Keep functions focused and well-documented.
- Avoid placeholders like `# ... rest of code ...`.
- Prefer clear, explicit error messages.
- Maintain backwards compatibility where possible (public SDK/CLI).

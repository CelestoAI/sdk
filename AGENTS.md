# Celesto SDK - GitHub Copilot Instructions

## Project Overview

Celesto SDK is a Python client + CLI for the Celesto AI platform. It provides:
- A typed Python SDK (`Celesto`) for Deployments and GateKeeper.
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

## CLI Design

- New CLI commands should follow a **NOUN-VERB** structure: `celesto <noun> <verb>`.
- The noun names the resource, such as a computer, deployment, connection, or template.
- The verb names the action, such as `create`, `list`, `start`, `stop`, or `delete`.
- When adding a new resource, register it as a top-level subcommand and put its actions underneath instead of overloading a global verb.
- Keep backwards compatibility for existing public CLI commands. Known exception: `celesto computer templates` is accepted for listing computer templates.

## User-Facing Writing Principles

- Follow progressive disclosure of complexity.
- Lead with outcomes, not implementation details.
- The first paragraph of every documentation page should be plain English with no jargon.
- Assume the reader may be a beginner engineer or a non-developer.
- Do not assume prior knowledge.
- Explain what the user can do and why it matters before explaining how it works.
- Do not introduce a new concept unless the page truly needs it.
- If a technical term is necessary, explain it immediately in simple language.
- Prefer short, concrete sentences over dense explanations.

## User-Facing Errors and Warnings

Error and warning messages are UX, not stack traces. Every user-facing message
in CLI output, panels, JSON `error` payloads, and JSON `warnings` entries should:

- State the fact in plain English.
- Avoid internal vocabulary when possible, even if that vocabulary appears in flag names.
- Name the recovery with the exact command or API call the user can run.
- Include the actual resource name or ID when available.
- Stay short: one sentence is best, two sentences is acceptable.
- Skip consequences that cannot be guaranteed in the current state.

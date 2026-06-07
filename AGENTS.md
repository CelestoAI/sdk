# Celesto SDK - GitHub Copilot Instructions

## Project Overview

Celesto SDK is a Python client + CLI for the Celesto AI platform. It provides:
- A typed Python SDK (`Celesto`) for cloud computers, deployments, and Gatekeeper.
- A CLI (`celesto`) for signing in and managing cloud computers.
- Optional integrations for running OpenAI agents in Celesto or local SmolVM sandboxes.

## Repository Structure

```
celesto-sdk/
├── src/celesto/       # SDK + CLI source code
│   ├── sdk/               # SDK client, exceptions, types
│   ├── main.py            # CLI app entrypoint (typer)
│   ├── auth.py            # CLI authentication helpers
│   ├── computer.py        # CLI computer helpers
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
- Capability first, motivation second.
- The first paragraph of every documentation page should be plain English with no jargon.
- Assume the reader may be a beginner engineer or a non-developer.
- Do not assume prior knowledge.
- Explain what the user can do and why it matters before explaining how it works.
- Do not introduce a new concept unless the page truly needs it.
- If a technical term is necessary, explain it immediately in simple language.
- Prefer short, concrete sentences over dense explanations.
- Define product terms where they first appear. Useful definitions: an AI agent
  is software that can plan and run tasks; a harness is code that starts,
  tests, or supervises an agent; a sandbox is a separate computer where an
  agent can work; a session is one running connection to that computer.
- For top-level docs, make sure a new reader can quickly understand what
  Celesto is, what they can do with it, and where to start next.
- Cover both SDK and CLI paths when both are part of the product surface.

## Documentation Examples and Commands

- Every code sample must be copy-pasteable and consistent with the current codebase.
- Every command must be runnable as written, with correct filenames, flags,
  prerequisites, and working-directory assumptions.
- If a command depends on being in the repository, say so before using repo-relative paths.
- Introduce required keys, IDs, names, or variables before using them in commands or code.
- Keep quickstarts minimal: install, configure, then one working end-to-end action.
- Do not make templates part of the default quickstart path. Celesto uses the
  `scratch` template by default, which is basic minimal Ubuntu.
- Introduce templates as a separate add-on concept for preinstalled tools. For
  example, `coding-agent` can appear in a dedicated templates section, not as
  the first way to create a computer.
- Use one concept per code sample. If an example needs setup, execution, and
  cleanup, split those steps or explain the variable that connects them.
- Prefer examples that show the real user outcome, such as creating a computer
  and running a command, over examples that expose internal mechanics.
- When documenting CLI JSON output, explain that `--json` prints structured data
  for scripts and automation.
- When using generated resource names in CLI docs, show how the name is created
  or say that it comes from `celesto computer create` or
  `celesto computer list`.
- When documenting OpenAI Agents examples, include both `CELESTO_API_KEY` and
  `OPENAI_API_KEY` prerequisites before the Python example.
- Avoid repeating the same link in the intro and footer unless the repeated link
  materially improves navigation.

## User-Facing Errors and Warnings

Error and warning messages are UX, not stack traces. Every user-facing message
in CLI output, panels, JSON `error` payloads, and JSON `warnings` entries should:

- State the fact in plain English.
- Avoid internal vocabulary when possible, even if that vocabulary appears in flag names.
- Name the recovery with the exact command or API call the user can run.
- Include the actual resource name or ID when available.
- Stay short: one sentence is best, two sentences is acceptable.
- Skip consequences that cannot be guaranteed in the current state.

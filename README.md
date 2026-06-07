# Celesto

[![PyPI version](https://badge.fury.io/py/celesto.svg)](https://pypi.org/project/celesto/)
[![npm version](https://img.shields.io/npm/v/@celestoai/sdk.svg)](https://www.npmjs.com/package/@celestoai/sdk)
[![Python](https://img.shields.io/pypi/pyversions/celesto.svg)](https://pypi.org/project/celesto/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Celesto runs AI agents and harnesses in a cloud computer. A harness is the code
that starts, tests, or supervises an agent. They can run commands, write files,
and use tools without touching your machine.

Use Celesto when you want to:

- Run an AI agent or harness in a clean computer.
- Run shell commands from Python, JavaScript, TypeScript, or the command line.
- Keep agent work separate from your laptop, server, or production system.
- Manage the full computer lifecycle: create, list, run commands, stop, start,
  and delete.

This README covers the Python SDK and CLI. The JavaScript and TypeScript SDK is
also available as [`@celestoai/sdk`](./js/README.md).

## Install

Install the Python package to get both the SDK and the `celesto` command:

```bash
pip install celesto
```

Celesto requires Python 3.10 or newer.

For JavaScript and TypeScript projects, install the npm package:

```bash
npm install @celestoai/sdk
```

## Get an API Key

An API key is a secret token that lets Celesto know a request is yours. Create
one in [Celesto Settings](https://celesto.ai) under **Settings > Security**.

For SDK code, set the key in your shell before running your program:

```bash
export CELESTO_API_KEY="your-api-key"
```

For CLI commands, you can save the key once:

```bash
celesto auth login
```

The CLI stores the key in your operating system's secure credential store. SDK
code does not read that saved CLI key; it reads `CELESTO_API_KEY` or the
`api_key` value you pass to `Celesto`.

## Create a Computer from Python

This example creates a computer from the `coding-agent` template, runs one
command, prints the output, and deletes the computer.

A template is a ready-made setup. The `coding-agent` template includes common
tools for coding tasks.

```python
from celesto import Celesto

with Celesto() as client:
    computer = client.computers.create(template_id="coding-agent")
    try:
        print(f"Computer ready: {computer['name']}")

        result = client.computers.exec(computer["id"], "uname -a")
        print(result["stdout"])
    finally:
        client.computers.delete(computer["id"])
```

To pass the key directly instead of using `CELESTO_API_KEY`:

```python
from celesto import Celesto

with Celesto(api_key="your-api-key") as client:
    templates = client.computers.list_templates()
    print(templates[0]["id"])
```

## Manage Computers from the CLI

Run this in a macOS or Linux shell after `celesto auth login`.

```bash
COMPUTER_NAME=$(celesto computer create --template coding-agent --json | python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])')
celesto computer run "$COMPUTER_NAME" "uname -a"
celesto computer delete --force "$COMPUTER_NAME"
```

To open an interactive terminal, create a computer and connect to it. After you
exit the terminal with `Ctrl+]`, delete the computer.

```bash
COMPUTER_NAME=$(celesto computer create --template coding-agent --json | python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])')
celesto computer ssh "$COMPUTER_NAME"
celesto computer delete --force "$COMPUTER_NAME"
```

Use `celesto computer list` to see the computers in your account.

## Manage Computers from JavaScript or TypeScript

In an ESM or TypeScript file:

```ts
import { Celesto } from "@celestoai/sdk";

const celesto = new Celesto({ token: process.env.CELESTO_API_KEY });

const computer = await celesto.computers.create({ templateId: "coding-agent" });
try {
  console.log(`Computer ready: ${computer.name}`);

  const result = await celesto.computers.exec(computer.id, "uname -a");
  console.log(result.stdout);
} finally {
  await celesto.computers.delete(computer.id);
}
```

See the [JavaScript and TypeScript README](./js/README.md) for Node.js
requirements, Gatekeeper examples, and terminal connection details.

## Python Computers API

Use the Python SDK when you want Celesto inside an app, script, or agent.

### Create

```python
from celesto import Celesto

with Celesto() as client:
    computer = client.computers.create(
        template_id="coding-agent",
        cpus=2,
        memory=2048,
        disk_size_mb=15360,
    )
    try:
        print(computer["name"])
    finally:
        client.computers.delete(computer["id"])
```

Omit CPU, memory, or disk fields to use the selected template defaults.

### List Templates

```python
from celesto import Celesto

with Celesto() as client:
    templates = client.computers.list_templates()
    for template in templates:
        print(template["id"], template["default_ram_mb"])
```

### Run a Command

```python
from celesto import Celesto

with Celesto() as client:
    computer = client.computers.create(
        template_id="coding-agent",
    )
    try:
        result = client.computers.exec(computer["id"], "ls -la", timeout=60)
        print(result["exit_code"])
        print(result["stdout"])
        print(result["stderr"])
    finally:
        client.computers.delete(computer["id"])
```

### List, Stop, Start, and Delete

| Method | What it does |
| --- | --- |
| `client.computers.list()` | List computers in your account |
| `client.computers.get(computer_id)` | Get one computer by name or ID |
| `client.computers.stop(computer_id)` | Stop a running computer |
| `client.computers.start(computer_id)` | Start a stopped computer |
| `client.computers.delete(computer_id)` | Delete a computer |

## CLI Commands

| Command | What it does |
| --- | --- |
| `celesto auth login` | Save your API key for CLI commands |
| `celesto auth status` | Check whether an API key is saved |
| `celesto auth logout` | Remove your saved API key |
| `celesto computer create [--template ID] [--cpus N] [--memory MB] [--disk-size-mb MB]` | Create a computer |
| `celesto computer templates` | List available computer templates |
| `celesto computer list` | List your computers |
| `celesto computer run NAME "command"` | Run a command on a computer |
| `celesto computer ssh NAME` | Open an interactive terminal |
| `celesto computer stop NAME` | Stop a computer |
| `celesto computer start NAME` | Start a stopped computer |
| `celesto computer delete [--force] NAME` | Delete a computer |

Most computer commands support `--json` for scripts and automation:

```bash
celesto computer list --json
celesto computer templates --json
celesto computer create --template coding-agent --disk-size-mb 15360 --json
```

`celesto computer ssh` is interactive and does not support JSON output.

## Other Python SDK APIs

The Python SDK also includes:

- `client.deployment` for deploying agents to Celesto.
- `client.gatekeeper` for connecting user-approved external resources, such as
  Google Drive.

See the [full documentation](https://docs.celesto.ai/celesto-sdk) for these
advanced APIs.

## OpenAI Agents SDK Sandboxes

OpenAI agents can use Celesto as their working computer. This lets the agent
read files, run commands, and create artifacts in a separate place.

Install the optional dependencies:

```bash
pip install "celesto[openai-agents]"
```

Then create a sandbox session for the agent:

```python
import asyncio

from agents import Runner
from agents.run import RunConfig
from agents.sandbox import SandboxAgent, SandboxRunConfig
from celesto.integrations.openai_agents import (
    CelestoSandboxClient,
    CelestoSandboxClientOptions,
)


async def main() -> None:
    agent = SandboxAgent(
        name="Workspace analyst",
        instructions="Inspect the sandbox workspace before answering.",
    )

    client = CelestoSandboxClient()
    session = await client.create(
        options=CelestoSandboxClientOptions(template_id="coding-agent")
    )

    try:
        async with session:
            result = await Runner.run(
                agent,
                "Run `uname -a` in the sandbox and summarize the result.",
                run_config=RunConfig(sandbox=SandboxRunConfig(session=session)),
            )
            print(result.final_output)
    finally:
        await client.delete(session)


asyncio.run(main())
```

For local sandbox runs, use `SmolVMSandboxClient` and
`SmolVMSandboxClientOptions` from `celesto.integrations.openai_agents`.

## Handle Errors in Python

Catch Celesto exceptions when your app needs custom recovery behavior.

```python
from celesto.sdk.exceptions import (
    CelestoAuthenticationError,
    CelestoNetworkError,
    CelestoNotFoundError,
    CelestoRateLimitError,
    CelestoServerError,
    CelestoValidationError,
)
```

`CelestoRateLimitError` includes a `retry_after` value when the API sends one.

## Develop Locally

If you are contributing and have `uv` installed, run these commands from the
repository root:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Links

- [Documentation](https://docs.celesto.ai/celesto-sdk)
- [JavaScript and TypeScript SDK](./js/README.md)
- [Celesto Platform](https://celesto.ai)
- [GitHub Repository](https://github.com/CelestoAI/sdk)

## License

Apache License 2.0

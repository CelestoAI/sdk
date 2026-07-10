# Celesto

[![PyPI version](https://badge.fury.io/py/celesto.svg)](https://pypi.org/project/celesto/)
[![npm version](https://img.shields.io/npm/v/@celestoai/sdk.svg)](https://www.npmjs.com/package/@celestoai/sdk)
[![Python](https://img.shields.io/pypi/pyversions/celesto.svg)](https://pypi.org/project/celesto/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Celesto runs AI agents and harnesses in a cloud computer. An AI agent is
software that can plan and run tasks. A harness is the code that starts, tests,
or supervises an agent. They can run commands, write files, and use tools
without touching your machine.

Use Celesto when you want to:

- Run an AI agent or harness in a clean computer.
- Run shell commands from Python, JavaScript, TypeScript, or the command line.
- Keep agent work separate from your laptop, server, or production system.
- Manage a computer from start to finish: create, list, run commands, stop,
  start, and delete.

This README covers the Python SDK, which is a code package, and the CLI, which
is the `celesto` command. The JavaScript and TypeScript SDK is also available as
[`@celestoai/sdk`](./ts/README.md).

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

The CLI stores the key in your operating system's secure credential store. On
Linux machines without a credential store, it saves the key in
`$XDG_CONFIG_HOME/celesto/credentials.json` when `XDG_CONFIG_HOME` is set, or
`~/.config/celesto/credentials.json` otherwise, with user-only file
permissions. SDK code does not read that saved CLI key; it reads
`CELESTO_API_KEY` or the `api_key` value you pass to `Computer`.

## Create a Computer from Python

This example creates a minimal Ubuntu computer, runs one command, prints the
output, and deletes the computer. Celesto uses the `scratch` template by
default.

```python
from celesto import Computer

computer = Computer()
try:
    print(f"Computer ready: {computer.name}")

    result = computer.run("uname -a")
    print(result["stdout"])
finally:
    computer.delete()
```

To pass the key directly instead of using `CELESTO_API_KEY`:

```python
from celesto import Computer

computer = Computer(api_key="your-api-key")
try:
    result = computer.run("uname -a")
    print(result["stdout"])
finally:
    computer.delete()
```

## Manage Computers from the CLI

Run these commands in a macOS or Linux shell after `celesto auth login`. The
first command creates a computer with the default `scratch` template.

```bash
celesto computer create
#   Name:   curie
#   ID:     cmp_123
#   Status: creating
```

For later examples, save the generated name in `COMPUTER_NAME`. The command
uses `--json` so Python can read the output.

```bash
COMPUTER_NAME=$(
  celesto computer create --json |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])'
)
```

Inspect that computer by name or ID:

```bash
celesto computer get "$COMPUTER_NAME"
#   Name:   curie
#   ID:     cmp_123
#   Status: running
```

List your computers:

```bash
celesto computer list
```

Filter the list by status:

```bash
celesto computer list --status running
```

Filter the list by template. Template IDs come from `celesto computer templates`;
`browser-agent` is one ready-made template.

```bash
celesto computer list --template browser-agent
```

Filter the list by project. Replace `proj_123` with a project ID from your
Celesto workspace.

```bash
celesto computer list --project proj_123
```

Limit the number of computers returned:

```bash
celesto computer list --limit 10
```

Run a command in the computer:

```bash
celesto computer run "$COMPUTER_NAME" "uname -a"
```

Use a longer timeout for slow commands. The value is in seconds and must be
between 1 and 300.

```bash
celesto computer run "$COMPUTER_NAME" "sleep 10 && echo done" --timeout 30
```

Stream output while a command is still running:

```bash
celesto computer run "$COMPUTER_NAME" "for i in 1 2 3; do echo $i; sleep 1; done" --stream
# 1
# 2
# 3
```

`celesto computer run --json` prints one JSON object for scripts and exits with
the same exit code as the remote command. `celesto computer run --stream --json`
prints one compact JSON event per line.

Current caveat: commands run as the computer image's default exec user. The CLI
and SDK do not yet expose a `--user` option. Run `whoami` first if your script
depends on a specific home directory or file permission.

List templates when you want a computer with tools already installed:

```bash
celesto computer templates
```

Create a computer from a template:

```bash
celesto computer create --template coding-agent
```

Publish port 8000 when a process in the computer needs a public URL:

```bash
celesto computer port publish "$COMPUTER_NAME" --port 8000
# https://p-test.celesto.ai
```

List published ports:

```bash
celesto computer port list "$COMPUTER_NAME"
```

Unpublish the port when you are done:

```bash
celesto computer port unpublish "$COMPUTER_NAME" --port 8000
```

To open an interactive terminal through Celesto's fast terminal gateway, connect
to the same computer. Your account needs write access to that computer:

```bash
celesto computer ssh "$COMPUTER_NAME"
```

Press `Ctrl+]` to exit the terminal, then delete the computer:

```bash
celesto computer delete --force "$COMPUTER_NAME"
```

Use `celesto computer list` to see the computers in your account.

## Manage Computers from JavaScript or TypeScript

In an ESM or TypeScript file:

```ts
import { Computer } from "@celestoai/sdk";

const computer = await Computer.create();
try {
  console.log(`Computer ready: ${computer.name}`);

  const result = await computer.run("uname -a");
  console.log(result.stdout);
} finally {
  await computer.delete();
}
```

See the [JavaScript and TypeScript README](./ts/README.md) for Node.js
requirements, Gatekeeper examples, and terminal connection details.

## Run Pi in a Celesto Computer

[Pi](https://github.com/earendil-works/pi) is a coding agent that works from
your terminal. The Celesto extension runs Pi's coding tools in a separate
computer while the interface, conversation history, and model credentials stay
on your machine.

You need Node.js 22.19 or newer and Pi configured with a model provider. Sign
in with `celesto auth login`, export `CELESTO_API_KEY`, or add the key to the
project's local `.env` file. Install the extension once:

```bash
pi install npm:@celestoai/pi
```

From the project you want to work on, start Pi with Celesto:

```bash
pi --celesto
```

Pi copies the project to `$HOME/workspace` and runs its read, write, edit, and
shell tools there. Copy the resulting changes back to your local project from inside
Pi:

```text
/celesto sync
```

Use `/celesto status` to see the active computer or `/celesto keep` to preserve
an extension-created computer after Pi exits. See the [Pi extension guide](./pi/README.md)
for reuse and file-exclusion options.

## Python Computers API

Use the Python SDK when you want Celesto inside an app, script, or agent.

### Create

```python
from celesto import Computer

computer = Computer(cpus=2, memory=2048, disk="15gb")
try:
    print(computer.name, computer["name"])
finally:
    computer.delete()
```

Omit CPU, memory, or disk fields to use the default size. `disk` accepts MB as
an integer or strings such as `"2gb"`.

### Templates

By default, Celesto uses `scratch`, a minimal Ubuntu computer. Use a template
when you want a computer that already has extra tools installed. For example,
`coding-agent` includes common tools for coding tasks.

List available templates:

```python
from celesto import Computer

templates = Computer.list_templates()
for template in templates:
    print(template["id"], template.get("preinstalled_tools", []))
```

Template responses may include metadata such as aliases, capabilities,
preinstalled tools, recommended uses, default published ports, and browser
support flags. Older template records may omit those fields, so use `.get()`
when your code can run against multiple API versions.

Create a computer from a template:

```python
from celesto import Computer

computer = Computer(template_id="coding-agent")
try:
    print(computer.name)
finally:
    computer.delete()
```

### Run a Command

```python
from celesto import Computer

computer = Computer()
try:
    result = computer.run("ls -la", timeout=60)
    print(result["exit_code"])
    print(result["stdout"])
    print(result["stderr"])
finally:
    computer.delete()
```

The `timeout` value is the remote command timeout in seconds. The SDK gives the
HTTP request a little more time than the command itself so slow command output
can still return cleanly.

Current caveat: `run()` and `exec()` run as the computer image's default exec
user. The SDK does not yet expose a user selector.

### Create a Terminal Session

Create a terminal session when your application needs an interactive shell. The
returned `url` connects directly to Celesto's fast terminal gateway and contains
a short-lived secret token. Creating a terminal session requires write access to
the computer.

```python
from celesto import Computer

computer = Computer.get("curie")
session = computer.create_terminal_session()
print(session["terminal_id"], session["expires_at"])
```

Pass `session["url"]` directly to a WebSocket client before it expires. Do not
log or share the URL because it includes the terminal token.

### List, Stop, Start, and Delete

`computer_id` can be `computer.id` from `Computer()` or a computer name shown by
`celesto computer list`.

Filter a list when you only want matching computers:

```python
from celesto import Computer

computers = Computer.list(status="running", template_id="browser-agent")
for computer in computers:
    print(computer["name"])
```

| Method | What it does |
| --- | --- |
| `Computer.list()` | List computers in your account |
| `Computer.list(status="running", template_id="browser-agent", project_id="proj_123", limit=10)` | List matching computers |
| `Computer.get(computer_id)` | Get one computer by name or ID |
| `computer.create_terminal_session()` | Create a short-lived fast terminal connection |
| `computer.stop()` | Stop a running computer |
| `computer.start()` | Start a stopped computer |
| `computer.delete()` | Delete a computer |

### Publish Ports

Publish a port when a service inside the computer needs a public URL:

```python
from celesto import Computer

computer = Computer.get("curie")
url = computer.publish_port(8000)
print(url)
```

List and remove published ports:

```python
from celesto import Computer

computer = Computer.get("curie")
print(computer.list_published_ports())
computer.unpublish_port(8000)
```

## CLI Commands

| Command | What it does |
| --- | --- |
| `celesto auth login` | Save your API key for CLI commands |
| `celesto auth status` | Check whether an API key is saved |
| `celesto auth logout` | Remove your saved API key |
| `celesto computer create [--cpus N] [--memory MB] [--disk-size-mb MB] [--template ID]` | Create a computer |
| `celesto computer templates` | List templates with preinstalled tools |
| `celesto computer list` | List your computers |
| `celesto computer list [--status STATUS] [--template ID] [--project ID] [--limit N]` | List matching computers |
| `celesto computer get NAME` | Get one computer by name or ID |
| `celesto computer run NAME "command" [--timeout N]` | Run a command on a computer |
| `celesto computer run NAME "command" --stream` | Stream command output while it runs |
| `celesto computer ssh NAME` | Open an interactive terminal |
| `celesto computer port publish NAME --port 8000` | Publish a computer port |
| `celesto computer port list NAME` | List published ports |
| `celesto computer port unpublish NAME --port 8000` | Unpublish a computer port |
| `celesto computer stop NAME` | Stop a computer |
| `celesto computer start NAME` | Start a stopped computer |
| `celesto computer delete [--force] NAME` | Delete a computer |

Most computer commands support `--json`, which prints structured data for
scripts and automation:

```bash
celesto computer list --json
celesto computer templates --json
celesto computer create --disk-size-mb 15360 --json
```

`celesto computer ssh` is interactive and does not support JSON output.

## Other Python SDK APIs

The high-level SDK now exposes computers directly through `Computer`. Deployment
and Gatekeeper helpers are still available from the CLI while their direct SDK
resource APIs are being updated to match this style.

## OpenAI Agents SDK Sandboxes

OpenAI agents can use Celesto as their working computer. This lets the agent
read files, run commands, and create artifacts in a separate place.

A sandbox is a separate computer where an agent can work. A session is one
running connection to that computer.

Install the optional dependencies:

```bash
pip install "celesto[openai-agents]"
```

Set both API keys before running the example. Celesto uses `CELESTO_API_KEY` to
create the computer. The OpenAI Agents SDK uses `OPENAI_API_KEY` to run the
agent.

```bash
export CELESTO_API_KEY="your-celesto-api-key"
export OPENAI_API_KEY="your-openai-api-key"
```

Then create a sandbox session for the agent:

```python
import asyncio

from agents import Runner
from agents.run import RunConfig
from agents.sandbox import SandboxAgent, SandboxRunConfig
from celesto.integrations.openai_agents import CelestoSandboxClient


async def main() -> None:
    agent = SandboxAgent(
        name="Workspace analyst",
        instructions="Inspect the sandbox workspace before answering.",
    )

    client = CelestoSandboxClient()
    session = await client.create()

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

If your agent needs common coding tools preinstalled, pass
`options=CelestoSandboxClientOptions(template_id="coding-agent")` when you call
`client.create()`. Import `CelestoSandboxClientOptions` from
`celesto.integrations.openai_agents`.

For local sandbox runs, use `SmolVMSandboxClient` and
`SmolVMSandboxClientOptions` from `celesto.integrations.openai_agents`. SmolVM
is a local tool for running a separate sandbox on your own machine.

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
- [Celesto Platform](https://celesto.ai)
- [GitHub Repository](https://github.com/CelestoAI/sdk)

## License

Apache License 2.0

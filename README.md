# Celesto

[![PyPI version](https://badge.fury.io/py/celesto.svg)](https://pypi.org/project/celesto/)
[![Python](https://img.shields.io/pypi/pyversions/celesto.svg)](https://pypi.org/project/celesto/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Sandboxed cloud computers for AI agents. Spin up isolated computers in seconds, run workflows/commands or long-running agents -- all from Python, JavaScript/TypeScript, or the CLI.

```bash
pip install celesto        # Python SDK + CLI
npm install @celestoai/sdk # JavaScript/TypeScript SDK
```

## Quick Start

**Python:**

```python
from celesto import Celesto

client = Celesto()

computer = client.computers.create(cpus=2, memory=2048)
print(f"Computer ready: {computer['name']}")

result = client.computers.exec(computer["id"], "uname -a")
print(result["stdout"])

client.computers.delete(computer["id"])
```

**JavaScript / TypeScript:**

```ts
import { Celesto } from "@celestoai/sdk";

const celesto = new Celesto({ token: process.env.CELESTO_API_KEY });

const computer = await celesto.computers.create({ cpus: 2, memory: 2048 });
console.log(`Computer ready: ${computer.name}`);

const result = await celesto.computers.exec(computer.id, "uname -a");
console.log(result.stdout);

await celesto.computers.delete(computer.id);
```

**CLI:**

```bash
export CELESTO_API_KEY="your-api-key"

celesto computer create --cpus 2 --memory 2048
celesto computer run einstein "ls -la"
celesto computer ssh einstein       # interactive shell
celesto computer delete einstein
```

## Why Celesto?

- **Fast** -- computers boot in seconds via Firecracker microVMs
- **Isolated** -- every sandbox is a real VM, not a container
- **Simple** -- three API calls: create, exec, delete
- **Built for agents** -- give your AI full computer access without risking your host

## Installation

```bash
pip install celesto
```

Requires Python 3.10+.

## Authentication

Get your API key from [celesto.ai](https://celesto.ai) under **Settings > Security**.

```bash
export CELESTO_API_KEY="your-api-key"
```

Or pass it directly:

```python
client = Celesto(api_key="your-api-key")
```

## Computers API

### Create

```python
computer = client.computers.create(cpus=2, memory=2048)
print(computer["name"])  # e.g., "einstein"
```

### Execute commands

```python
result = client.computers.exec(computer["id"], "apt-get update && apt-get install -y curl")
print(result["stdout"])
print(result["exit_code"])
```

### Lifecycle

```python
client.computers.stop(computer_id)
client.computers.start(computer_id)
client.computers.delete(computer_id)
```

### List

```python
result = client.computers.list()
for vm in result["computers"]:
    print(f"{vm['name']}: {vm['status']}")
```

## CLI

| Command | Description |
|---|---|
| `celesto computer create [--cpus N] [--memory MB]` | Create a computer |
| `celesto computer list` | List all computers |
| `celesto computer run <name> "command"` | Execute a command |
| `celesto computer ssh <name>` | Interactive shell |
| `celesto computer stop <name>` | Stop a computer |
| `celesto computer start <name>` | Start a stopped computer |
| `celesto computer delete <name> [--force]` | Delete a computer |

### JSON output

All commands support `--json` for machine-readable output:

```bash
celesto computer list --json
celesto computer create --cpus 2 --memory 2048 --json
celesto computer run einstein "uname -a" --json
```

## Error Handling

```python
from celesto.sdk.exceptions import (
    CelestoAuthenticationError,  # 401/403
    CelestoNotFoundError,        # 404
    CelestoValidationError,      # 400/422
    CelestoRateLimitError,       # 429 -- has retry_after attribute
    CelestoServerError,          # 5xx
    CelestoNetworkError,         # connection failures
)
```

## Links

- [Documentation](https://docs.celesto.ai/celesto-sdk)
- [JS/TS SDK docs](js/README.md)
- [Platform](https://celesto.ai)
- [GitHub](https://github.com/CelestoAI/sdk)

## License

Apache License 2.0

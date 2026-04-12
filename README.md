# Celesto

[![PyPI version](https://badge.fury.io/py/celesto.svg)](https://pypi.org/project/celesto/)
[![Python](https://img.shields.io/pypi/pyversions/celesto.svg)](https://pypi.org/project/celesto/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Sandboxed cloud computers for AI agents. Spin up isolated computers in seconds, run workflows/commands or long running agents -- all from Python or the CLI.

```bash
pip install celesto
```

## Quick Start

```python
from celesto.sdk import CelestoSDK

with CelestoSDK() as client:
    # Spin up a sandbox
    computer = client.computers.create(cpus=2, memory=2048)
    print(f"Computer ready: {computer['id']}")

    # Run anything
    result = client.computers.exec(computer["id"], "uname -a")
    print(result["stdout"])

    # Clean up
    client.computers.delete(computer["id"])
```

Or from the command line:

```bash
export CELESTO_API_KEY="your-api-key"

celesto computer create --cpus 2 --memory 2048
celesto computer run <id> "ls -la"
celesto computer ssh <id>       # interactive shell
celesto computer delete <id>
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
client = CelestoSDK(api_key="your-api-key")
```

## Computers API

### Create a computer

```python
computer = client.computers.create(
    cpus=2,        # 1-16 CPUs
    memory=2048,   # 512-32768 MB
)
```

### Execute commands

```python
result = client.computers.exec(computer["id"], "apt-get update && apt-get install -y curl")
print(result["stdout"])
print(result["exit_code"])
```

Set a timeout (default 30s, max 300s):

```python
result = client.computers.exec(computer["id"], "long-running-script.sh", timeout=120)
```

### Lifecycle

```python
client.computers.stop(computer_id)     # pause the VM
client.computers.start(computer_id)    # resume it
client.computers.delete(computer_id)   # destroy it
```

### List computers

```python
result = client.computers.list()
for vm in result["computers"]:
    print(f"{vm['id']}: {vm['status']}")
```

## CLI

| Command | Description |
|---|---|
| `celesto computer create [--cpus N] [--memory MB]` | Create a computer |
| `celesto computer list` | List all computers |
| `celesto computer run <id> "command"` | Execute a command |
| `celesto computer ssh <id>` | Interactive shell |
| `celesto computer delete <id> [--force]` | Destroy a computer |

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

try:
    result = client.computers.create()
except CelestoAuthenticationError:
    print("Bad API key -- check https://celesto.ai > Settings > Security")
except CelestoRateLimitError as e:
    print(f"Rate limited. Retry in {e.retry_after}s")
```

## Links

- [Documentation](https://docs.celesto.ai/celesto-sdk)
- [Platform](https://celesto.ai)
- [GitHub](https://github.com/CelestoAI/sdk)
- [Issues](https://github.com/CelestoAI/sdk/issues)

## License

Apache License 2.0

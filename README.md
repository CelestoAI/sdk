# Celesto

[![PyPI version](https://badge.fury.io/py/celesto.svg)](https://pypi.org/project/celesto/)
[![Python](https://img.shields.io/pypi/pyversions/celesto.svg)](https://pypi.org/project/celesto/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Sandboxed cloud computers for AI agents. Spin up isolated Ubuntu VMs in seconds, run commands, and tear them down -- all from Python or the CLI.

```bash
pip install celesto
```

## Quick Start

```python
from celesto.sdk import CelestoSDK

with CelestoSDK() as client:
    # Spin up a sandbox
    computer = client.computers.create(vcpus=2, ram_mb=2048)
    print(f"VM ready: {computer['id']}")

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

- **Fast** -- VMs boot in seconds via Firecracker microVMs
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

### Create a sandbox

```python
computer = client.computers.create(
    vcpus=2,        # 1-16 CPUs
    ram_mb=2048,    # 512-32768 MB
    image="ubuntu-desktop-24.04"
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

### Lifecycle management

```python
client.computers.stop(computer_id)     # pause the VM
client.computers.start(computer_id)    # resume it
client.computers.delete(computer_id)   # destroy it
```

### List sandboxes

```python
result = client.computers.list()
for vm in result["computers"]:
    print(f"{vm['id']}: {vm['status']}")
```

## CLI Reference

```bash
celesto computer create [--cpus N] [--memory MB]    # create a sandbox
celesto computer list                                # list all sandboxes
celesto computer run <id> "command"                  # execute a command
celesto computer ssh <id>                            # interactive SSH session
celesto computer delete <id> [--force]               # destroy a sandbox
```

## Agent Deployment

Deploy AI agents as serverless endpoints with automatic scaling.

```python
from celesto.sdk import CelestoSDK
from pathlib import Path

with CelestoSDK() as client:
    result = client.deployment.deploy(
        folder=Path("./my-agent"),
        name="my-agent",
        description="My AI assistant",
        envs={"OPENAI_API_KEY": "sk-..."},
        project_name="My Project"
    )
    print(f"Status: {result['status']}")
```

```bash
celesto deploy --project "My Project"
celesto ls                              # list deployments
```

Exclude files from the deployment bundle with a `.celestoignore` file (same syntax as `.gitignore`).

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

## Advanced

### Custom API endpoint

```python
client = CelestoSDK(base_url="https://custom-api.example.com/v1")
```

Or via environment:

```bash
export CELESTO_BASE_URL="https://custom-api.example.com/v1"
```

### Resource cleanup

Use the context manager to ensure connections are closed:

```python
with CelestoSDK() as client:
    # ... your code ...
    pass  # automatically cleaned up
```

## Links

- [Documentation](https://docs.celesto.ai/celesto-sdk)
- [Platform](https://celesto.ai)
- [GitHub](https://github.com/CelestoAI/sdk)
- [Issues](https://github.com/CelestoAI/sdk/issues)

## License

Apache License 2.0

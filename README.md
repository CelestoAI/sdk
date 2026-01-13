# Celesto SDK

Python SDK and CLI for the Celesto AI platform.

## Install

```bash
pip install celesto
```

## Configure

Set your API key in the environment:

```bash
export CELESTO_API_KEY="your-key"
```

## CLI

```bash
celesto deploy
celesto ls
celesto a2a get-card --agent http://localhost:8000
```

## SDK

```python
from celesto_sdk.sdk import CelestoSDK

client = CelestoSDK()
print(client.deployment.list())
```

"""Run OpenAI agents on Celesto computers or local SmolVM sandboxes.

Import this module when you want OpenAI's ``SandboxAgent`` to use Celesto or
SmolVM as its working computer.
"""

from .hosted import (
    CelestoSandboxClient,
    CelestoSandboxClientOptions,
    CelestoSandboxSession,
    CelestoSandboxSessionState,
)
from .smolvm import (
    SmolVMSandboxClient,
    SmolVMSandboxClientOptions,
    SmolVMSandboxSession,
    SmolVMSandboxSessionState,
)

__all__ = [
    "CelestoSandboxClient",
    "CelestoSandboxClientOptions",
    "CelestoSandboxSession",
    "CelestoSandboxSessionState",
    "SmolVMSandboxClient",
    "SmolVMSandboxClientOptions",
    "SmolVMSandboxSession",
    "SmolVMSandboxSessionState",
]

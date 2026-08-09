"""Celesto SDK package."""

from .main import app
from .sdk import Computer, ManagedAgentsClient, RunEvent

__version__ = "0.0.11"

__all__ = ["app", "Computer", "ManagedAgentsClient", "RunEvent", "__version__"]

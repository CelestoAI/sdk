"""Money crosses the wire as a decimal string, and stays exact here.

The API sends every amount as a fixed-scale decimal string — ``"0.000450"``,
not ``0.00045``. A generation can cost a few millionths of a dollar, and a
binary float cannot represent those cents exactly; summing a month of them as
floats drifts. So:

- Reading: strings become :class:`decimal.Decimal`.
- Writing: :class:`~decimal.Decimal`, ``int`` and ``str`` are sent as strings.
  A ``float`` is accepted for convenience and converted through its shortest
  string form, which is what you typed.

Never call ``float()`` on these values.
"""

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

MoneyInput = Any
"""Anything you can hand the SDK as an amount: Decimal, str, int, or float."""


def to_decimal(value: Any) -> Decimal | None:
    """Parse an API money value into a Decimal. ``None`` stays ``None``."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def to_money_string(value: Any) -> str:
    """Serialize an amount for the API without ever going through a float."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        raise TypeError("Budget amounts must be a number, not a boolean.")
    if isinstance(value, (int, str)):
        return str(value).strip()
    if isinstance(value, float):
        # repr() of a float is its shortest round-tripping form: 0.5 -> "0.5".
        return format(Decimal(repr(value)), "f")
    raise TypeError(
        f"Budget amounts must be a Decimal, string, or number, got {type(value).__name__}."
    )


def decimalize(payload: Any, fields: Iterable[str]) -> Any:
    """Return ``payload`` with the named keys parsed as Decimal, recursively."""
    names = frozenset(fields)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            result: dict[str, Any] = {}
            for key, value in node.items():
                result[key] = to_decimal(value) if key in names else walk(value)
            return result
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(payload)


MONEY_FIELDS = frozenset(
    {
        "cost_usd",
        "cap_usd",
        "spent_usd",
        "remaining_usd",
        "default_end_user_budget_usd",
    }
)
"""Every response field that carries money."""


def parse_money_fields(payload: Any) -> Any:
    """Parse every known money field in an API response into a Decimal."""
    return decimalize(payload, MONEY_FIELDS)


__all__ = [
    "MONEY_FIELDS",
    "MoneyInput",
    "decimalize",
    "parse_money_fields",
    "to_decimal",
    "to_money_string",
]

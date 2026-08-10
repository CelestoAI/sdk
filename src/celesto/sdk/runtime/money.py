"""Money crosses the wire as a decimal string, and stays exact here.

The API sends every amount as a fixed-scale decimal string — ``"0.000450"``,
not ``0.00045``. A generation can cost a few millionths of a dollar, and a
binary float cannot represent those cents exactly; summing a month of them as
floats drifts. So:

- Reading: strings become :class:`decimal.Decimal`.
- Writing: :class:`~decimal.Decimal`, ``int`` and ``str`` are sent as strings.
  A ``float`` is refused.

Refusing the float is the whole point. It used to be accepted "for
convenience", converted through ``repr()`` — so ``0.1 + 0.2`` was faithfully
transmitted as ``"0.30000000000000004"`` and ``1e-7`` as ``"1e-7"``, which the
API rejects outright. The convenience was to send the caller's rounding error
somewhere it could not be undone. The API now accepts only decimal strings, so
a float cannot succeed anyway; failing here names the fix instead of returning
a 422 from three layers down.

Never call ``float()`` on these values.
"""

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

MoneyInput = Decimal | str | int
"""Anything you can hand the SDK as an amount. Not ``float``: see the module
docstring. ``None`` and ``UNSET`` are spelled out where they are accepted,
because there they mean "clear this" and "leave it alone" rather than an
amount."""

#: The shape the API accepts: up to eight digits, then at most the column's six
#: decimals. No sign, no exponent. Mirrors MONEY_IN_PATTERN server-side, so a
#: refusal here is the same refusal the API would have made.
#:
#: ``[0-9]`` rather than ``\d``: Python's ``\d`` matches every Unicode decimal
#: digit, so ``"١٢"`` passed this pattern and was sent to an API that reads
#: ASCII only.
MONEY_PATTERN = re.compile(r"^[0-9]{1,8}(\.[0-9]{1,6})?$")

#: Largest exponent we will format. `format(Decimal("1E+999999999"), "f")`
#: builds a one-gigabyte string before anything gets to reject it, so magnitude
#: is checked before formatting, not after.
_MAX_INTEGER_DIGITS = 8
_MAX_DECIMAL_PLACES = 6


def to_decimal(value: Any) -> Decimal | None:
    """Parse an API money value into a Decimal. ``None`` stays ``None``.

    NaN and the infinities come back as ``None`` rather than as themselves: a
    non-finite Decimal poisons every sum it touches, and silently returning one
    from a field named ``spent_usd`` moves the failure far from its cause.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _checked(text: str, *, original: Any) -> str:
    """The wire form, or a ValueError naming what is wrong with it.

    Every accepted type funnels through here, so the string path cannot skip
    the check the float path exists to enforce. Refusing a float and then
    waving through ``"1e-7"`` — the exact form the API rejects — left the front
    door open on a locked window.
    """
    if not MONEY_PATTERN.fullmatch(text):
        raise ValueError(
            f"{original!r} is not a valid amount. Use a plain decimal amount with at "
            'most 8 digits before the point and 6 after, like "5.00" — no sign, no '
            "exponent, no currency symbol."
        )
    return text


def _decimal_to_text(value: Decimal, *, original: Any) -> str:
    """Format a Decimal for the wire, refusing what cannot be formatted safely.

    Magnitude is checked *before* ``format``: ``Decimal("1E+999999999")``
    formats to a one-gigabyte string, so validating the output would mean
    allocating a gigabyte to discover the value was never acceptable.
    ``_checked`` still has the final say on shape.
    """
    if not value.is_finite():
        raise ValueError(
            f"{original!r} is not a valid amount: NaN and infinity are not amounts."
        )
    exponent = value.as_tuple().exponent
    if value.adjusted() >= _MAX_INTEGER_DIGITS or exponent < -_MAX_DECIMAL_PLACES:
        raise ValueError(
            f"{original!r} is not a valid amount. Use a plain decimal amount with at "
            f"most {_MAX_INTEGER_DIGITS} digits before the point and "
            f"{_MAX_DECIMAL_PLACES} after."
        )
    return _checked(format(value, "f"), original=original)


def to_money_string(value: Any) -> str:
    """Serialize an amount for the API without ever going through a float."""
    if isinstance(value, bool):
        # Before the int branch: bool is an int, and True would otherwise
        # serialize as "1".
        raise TypeError("Budget amounts must be a number, not a boolean.")
    if isinstance(value, Decimal):
        return _decimal_to_text(value, original=value)
    if isinstance(value, float):
        # Called out separately, and before the int branch, because float is
        # the case worth explaining rather than lumping into "unsupported
        # type". The message deliberately does NOT echo the value back as a
        # suggestion: repr(0.1 + 0.2) is "0.30000000000000004", so quoting it
        # would recommend the caller's own rounding error.
        raise TypeError(
            f"Budget amounts cannot be a float ({value!r}): a float cannot hold these "
            "amounts exactly. Pass the amount you mean as a Decimal or a string — "
            'Decimal("5.00") or "5.00", not 5.0.'
        )
    if isinstance(value, (int, str)):
        return _checked(str(value).strip(), original=value)
    raise TypeError(
        f"Budget amounts must be a Decimal, string, or int, got {type(value).__name__}."
    )


def decimalize(
    payload: Any, fields: Iterable[str], *, opaque: Iterable[str] = ()
) -> Any:
    """Return ``payload`` with the named keys parsed as Decimal, recursively.

    ``opaque`` names keys whose values are yours, not ours, and are copied
    through untouched. Without it this walked into free-form JSON and rewrote
    anything that happened to share a name with a money field: metadata
    ``{"cost_usd": "not-money"}`` came back as ``{"cost_usd": None}`` — the
    caller's own value destroyed — and any metadata it *did* convert stopped
    being JSON-serializable.
    """
    names = frozenset(fields)
    untouched = frozenset(opaque)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            result: dict[str, Any] = {}
            for key, value in node.items():
                if key in untouched:
                    result[key] = value
                elif key in names:
                    result[key] = to_decimal(value)
                else:
                    result[key] = walk(value)
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

OPAQUE_FIELDS = frozenset(
    {
        "metadata",  # end-user metadata: the caller's own JSON
        "input",  # a run's stored request body
        "item",  # a session message, verbatim
        "args",  # tool-call arguments
        "result",  # tool-call results
        "config",  # an agent's generation settings
    }
)
"""Response fields holding free-form JSON that is the caller's, not ours.

Money never appears inside these, and a key inside them that happens to be
spelled ``cost_usd`` means whatever the caller meant by it.
"""


def parse_money_fields(payload: Any) -> Any:
    """Parse every known money field in an API response into a Decimal."""
    return decimalize(payload, MONEY_FIELDS, opaque=OPAQUE_FIELDS)


__all__ = [
    "MONEY_FIELDS",
    "OPAQUE_FIELDS",
    "MoneyInput",
    "decimalize",
    "parse_money_fields",
    "to_decimal",
    "to_money_string",
]

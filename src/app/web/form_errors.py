"""Turn a rejection into a message beside the right form field.

Nothing here validates anything. The rules live in one place — `SimulationForm`
for shape and `StakingConfig.__post_init__` for the plan itself. This module only
decides which input to point at, and phrases the domain's message in the units
the form uses.
"""

from collections.abc import Mapping

from pydantic import ValidationError

# The domain names the field it rejected, except for the one message that covers
# both manual entries at once.
_ENTRY_FIELDS = ("entry_1a", "entry_1b")

# The form asks for a payout percentage; the domain rejects a ratio. Same single
# check, restated in the units the reader typed.
_PAYOUT_MESSAGE = "Payout must be above 0% and no more than 100%."

# Same pattern for the target: the form asks for a percentage of capital, the
# domain rejects an absolute dollar amount that resolved negative.
_TARGET_PROFIT_MESSAGE = "Target profit can't be negative."


def from_validation(exc: ValidationError) -> dict[str, str]:
    """Field messages for a malformed submission — text in a number field, and so on."""
    errors: dict[str, str] = {}
    for error in exc.errors():
        field = str(error["loc"][0]) if error["loc"] else "__form__"
        errors.setdefault(field, _readable(error))
    return errors


def _readable(error: Mapping[str, object]) -> str:
    match error.get("type"):
        case "float_parsing" | "int_parsing" | "float_type" | "int_type":
            return "Enter a number."
        case "missing":
            return "This field is required."
        case "too_short":
            return "Choose at least one strategy."
        case _:
            return str(error.get("msg", "Invalid value."))


def from_domain(exc: ValueError, submitted: Mapping[str, str]) -> dict[str, str]:
    """Field messages for a plan the simulator refused to run."""
    message = str(exc)

    if "payout_ratio" in message:
        return {"payout_percent": _PAYOUT_MESSAGE}
    if "capital" in message:
        return {"capital": message.capitalize() + "."}
    if "target_profit" in message:
        return {"target_profit_percent": _TARGET_PROFIT_MESSAGE}
    if "must all be positive" in message:
        return {_offending_entry(submitted): "Enter an amount above zero."}
    if "strategy must be one of" in message:
        # Reachable only by a hand-crafted request — the checkboxes only ever
        # post the names the template itself renders.
        return {"strategies": "Choose a valid strategy."}
    return {"__form__": message}


def _offending_entry(submitted: Mapping[str, str]) -> str:
    """Which of the two manual entries the domain was objecting to.

    The domain rejects them with one shared message, so the field is identified
    by looking at what was submitted — not by re-checking the rule.
    """
    for field in _ENTRY_FIELDS:
        try:
            if float(submitted.get(field, "")) <= 0:
                return field
        except ValueError:
            continue
    return "entry_1a"

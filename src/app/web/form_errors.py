"""Turn a rejection into a message beside the right form field.

Nothing here validates anything. The rules live in one place — `SimulationForm`
for shape and `StakingConfig.__post_init__` for the plan itself. This module only
decides which input to point at, and phrases the domain's message in the units
the form uses.
"""

from collections.abc import Mapping

from pydantic import ValidationError

from ..domain.staking_simulator import InvalidStakingConfig

# Where the form names a field differently from the domain, because it asks in
# different units (a percentage) or collects several values (checkboxes).
_FORM_FIELD = {
    "payout_ratio": "payout_percent",
    "target_profit": "target_profit_percent",
    "strategy": "strategies",
}

# The domain's refusal, restated in the form's own terms. The rule is not restated.
_MESSAGE = {
    "capital": "Capital must be positive.",
    "entry_1a": "Enter an amount above zero.",
    "entry_1b": "Enter an amount above zero.",
    "payout_percent": "Payout must be above 0% and no more than 100%.",
    "target_profit_percent": "Target profit can't be negative.",
    # Reachable only by a hand-crafted request — the checkboxes only ever
    # post the names the template itself renders.
    "strategies": "Choose a valid strategy.",
}


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


def from_domain(exc: ValueError) -> dict[str, str]:
    """Field messages for a plan the simulator refused to run.

    The domain names the field it refused, so nothing here reads the message
    text to find it. A single-opener plan reaches the domain with `entry_1b` as
    None, which is never checked — so an error can't point at the hidden field.
    """
    if not isinstance(exc, InvalidStakingConfig):
        return {"__form__": str(exc)}
    field = _FORM_FIELD.get(exc.field, exc.field)
    return {field: _MESSAGE.get(field, str(exc))}

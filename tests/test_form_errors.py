"""Unit tests for `web/form_errors.py` — no HTTP round trip.

The domain names the field it refused (`InvalidStakingConfig.field`); these pin
where each refusal lands on the form and how it is phrased there.
"""

import pytest

from app.domain.staking_simulator import StakingConfig
from app.web.form_errors import from_domain


def _rejection(**fields: object) -> ValueError:
    with pytest.raises(ValueError) as caught:
        StakingConfig(**fields)
    return caught.value


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"capital": 0.0}, {"capital": "Capital must be positive."}),
        ({"entry_1a": 0.0}, {"entry_1a": "Enter an amount above zero."}),
        ({"entry_1b": -3.0}, {"entry_1b": "Enter an amount above zero."}),
        (
            {"payout_ratio": 1.5},
            {"payout_percent": "Payout must be above 0% and no more than 100%."},
        ),
        ({"target_profit": -1.0}, {"target_profit_percent": "Target profit can't be negative."}),
        ({"strategy": "triple"}, {"strategies": "Choose a valid strategy."}),
    ],
)
def test_a_domain_rejection_lands_on_the_form_field_it_names(
    fields: dict[str, object], expected: dict[str, str]
) -> None:
    assert from_domain(_rejection(**fields)) == expected


def test_both_entries_non_positive_points_at_entry_1a_first() -> None:
    assert from_domain(_rejection(entry_1a=0.0, entry_1b=0.0)) == {
        "entry_1a": "Enter an amount above zero."
    }


def test_a_single_opener_plan_is_never_blamed_on_entry_1b() -> None:
    """With one opener the domain sees `entry_1b=None` and never checks it."""
    assert from_domain(_rejection(entry_1a=0.0, entry_1b=None)) == {
        "entry_1a": "Enter an amount above zero."
    }


def test_a_rejection_naming_no_field_is_reported_on_the_form_itself() -> None:
    assert from_domain(ValueError("something else")) == {"__form__": "something else"}

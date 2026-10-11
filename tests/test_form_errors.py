"""Unit tests for `web/form_errors.py` — no HTTP round trip.

The domain names the field it refused (`InvalidStakingConfig.field`); these pin
where each refusal lands on the form and how it is phrased there.
"""

import pytest

from app.domain.staking_simulator import StakingConfig, risk_entry
from app.web.form_errors import from_domain

RISK_MESSAGE = {"risk_percent": "Risk must be above 0% and size an entry of at least $0.01."}


def _rejection(**fields: object) -> ValueError:
    with pytest.raises(ValueError) as caught:
        StakingConfig(**fields)
    return caught.value


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"capital": 0.0}, {"capital": "Capital must be positive."}),
        ({"entry_1a": 0.0}, RISK_MESSAGE),
        ({"entry_1b": -3.0}, RISK_MESSAGE),
        (
            {"payout_ratio": 1.5},
            {"payout_percent": "Payout must be above 0% and no more than 100%."},
        ),
        ({"strategy": "triple"}, {"strategies": "Choose a valid strategy."}),
    ],
)
def test_a_domain_rejection_lands_on_the_form_field_it_names(
    fields: dict[str, object], expected: dict[str, str]
) -> None:
    assert from_domain(_rejection(**fields)) == expected


def test_a_risk_that_sizes_no_entry_lands_on_the_risk_field() -> None:
    """Nobody types an opener any more -- the risk sizes them, so the risk is
    the input to point at."""
    with pytest.raises(ValueError) as caught:
        risk_entry(1000.0, 0.0)
    assert from_domain(caught.value) == RISK_MESSAGE


def test_a_rejection_naming_no_field_is_reported_on_the_form_itself() -> None:
    assert from_domain(ValueError("something else")) == {"__form__": "something else"}

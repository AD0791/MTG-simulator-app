"""Domain tests — the arithmetic, called directly. No client, no fixtures.

The reference case is the published example from `staking_simulator_README.md`
and is the regression case for the whole project.
"""

import pytest

from app.domain.staking_simulator import StakingConfig, StakingTable

REFERENCE = {
    "capital": 1000.0,
    "entry_1a": 5.0,
    "entry_1b": 5.0,
    "payout_ratio": 0.92,
    "target_profit": 0.0,
}

# label, stake, cumulative_loss, balance
REFERENCE_LADDER = [
    ("1a", 5.0, 5.0, 995.0),
    ("1b", 5.0, 10.0, 990.0),
    ("2", 11.0, 21.0, 979.0),
    ("3", 23.0, 44.0, 956.0),
    ("4", 48.0, 92.0, 908.0),
    ("5", 100.0, 192.0, 808.0),
    ("6", 209.0, 401.0, 599.0),
    ("7", 436.0, 837.0, 163.0),
]


def test_reference_case_hits_the_wall_on_entry_eight() -> None:
    table = StakingTable.build(StakingConfig(**REFERENCE))

    assert table.wall_hit is True
    assert table.wall_required_stake == 910
    assert table.wall_balance_available == 163.0
    assert table.losses_survived == 8


def test_reference_case_ladder_matches_row_for_row() -> None:
    table = StakingTable.build(StakingConfig(**REFERENCE))

    assert len(table.rows) == 8
    actual = [(r.label, r.stake, r.cumulative_loss, r.balance) for r in table.rows]
    assert actual == REFERENCE_LADDER


def test_balance_if_win_recovers_the_streak() -> None:
    """A winning entry returns the stake plus payout on it, against the debt so far."""
    table = StakingTable.build(StakingConfig(**REFERENCE))

    first = table.rows[0]
    assert first.balance_if_win == pytest.approx(1000.0 + 5.0 * 0.92)

    # From entry 2 on, the stake is sized to recover everything lost so far, so a
    # win lands the balance back at or just above starting capital.
    for row in table.rows[2:]:
        assert row.balance_if_win >= 1000.0


def test_no_wall_when_capital_reaches_max_entries() -> None:
    config = StakingConfig(capital=100_000.0, entry_1a=5.0, entry_1b=5.0, max_entries=6)
    table = StakingTable.build(config)

    assert table.wall_hit is False
    assert table.wall_required_stake is None
    assert table.wall_balance_available is None
    assert table.losses_survived == 6
    assert len(table.rows) == 6


def test_higher_payout_moves_the_wall_but_does_not_remove_it() -> None:
    # 0.98 does not survive a further entry beyond the reference case's 0.92 — the
    # ladder's growth is coarse enough that not every payout increase crosses an
    # extra whole-dollar-rounded threshold. A lower payout does, so compare down.
    worse = StakingTable.build(StakingConfig(**{**REFERENCE, "payout_ratio": 0.70}))
    better = StakingTable.build(StakingConfig(**REFERENCE))

    assert better.wall_hit is True
    assert better.losses_survived > worse.losses_survived


@pytest.mark.parametrize("capital", [0.0, -1.0])
def test_non_positive_capital_is_rejected(capital: float) -> None:
    with pytest.raises(ValueError, match="capital must be positive"):
        StakingConfig(capital=capital)


@pytest.mark.parametrize("field", ["entry_1a", "entry_1b"])
@pytest.mark.parametrize("value", [0.0, -5.0])
def test_non_positive_entries_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValueError, match="must all be positive"):
        StakingConfig(**{field: value})


@pytest.mark.parametrize("payout_ratio", [0.0, -0.5, 1.01, 1.5])
def test_payout_ratio_outside_zero_to_one_is_rejected(payout_ratio: float) -> None:
    with pytest.raises(ValueError, match="payout_ratio must be between 0 and 1"):
        StakingConfig(payout_ratio=payout_ratio)


def test_payout_ratio_of_exactly_one_is_accepted() -> None:
    """The interval is (0, 1] — a 100% payout is the boundary, not an error."""
    assert StakingConfig(payout_ratio=1.0).payout_ratio == 1.0


def test_negative_target_profit_is_rejected() -> None:
    with pytest.raises(ValueError, match="target_profit cannot be negative"):
        StakingConfig(target_profit=-1.0)

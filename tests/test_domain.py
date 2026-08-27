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

# Same capital and openers, the "double" strategy: stake = 2 * cumulative_loss.
DOUBLE_LADDER = [
    ("1a", 5.0, 5.0, 995.0),
    ("1b", 5.0, 10.0, 990.0),
    ("2", 20.0, 30.0, 970.0),
    ("3", 60.0, 90.0, 910.0),
    ("4", 180.0, 270.0, 730.0),
    ("5", 540.0, 810.0, 190.0),
]

# A single opener (entry_1b=None): capital 1000, one $5 opener, 92% payout.
SINGLE_OPENER_LADDER = [
    ("1", 5.0, 5.0, 995.0),
    ("2", 6, 11.0, 989.0),
    ("3", 12, 23.0, 977.0),
    ("4", 25, 48.0, 952.0),
    ("5", 53, 101.0, 899.0),
    ("6", 110, 211.0, 789.0),
    ("7", 230, 441.0, 559.0),
    ("8", 480, 921.0, 79.0),
]

SINGLE_OPENER_DOUBLE_LADDER = [
    ("1", 5.0, 5.0, 995.0),
    ("2", 10.0, 15.0, 985.0),
    ("3", 30.0, 45.0, 955.0),
    ("4", 90.0, 135.0, 865.0),
    ("5", 270.0, 405.0, 595.0),
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


def test_adder_profit_is_the_default_strategy() -> None:
    assert StakingConfig().strategy == "adder_profit"


def test_unknown_strategy_is_rejected() -> None:
    with pytest.raises(ValueError, match="strategy must be one of"):
        StakingConfig(strategy="triple")


def test_adder_breakeven_matches_adder_profit_at_zero_target() -> None:
    """ceil((cum + 0) / p) is ceil(cum / p) — the same arithmetic, a different name."""
    breakeven = StakingTable.build(StakingConfig(**REFERENCE, strategy="adder_breakeven"))
    profit = StakingTable.build(StakingConfig(**REFERENCE, strategy="adder_profit"))

    assert [(r.label, r.stake) for r in breakeven.rows] == [(r.label, r.stake) for r in profit.rows]


def test_adder_breakeven_diverges_from_adder_profit_once_a_target_is_set() -> None:
    breakeven = StakingTable.build(
        StakingConfig(**{**REFERENCE, "target_profit": 10.0}, strategy="adder_breakeven")
    )
    profit = StakingTable.build(
        StakingConfig(**{**REFERENCE, "target_profit": 10.0}, strategy="adder_profit")
    )

    assert breakeven.rows[2].stake != profit.rows[2].stake


def test_double_strategy_ladder_matches_row_for_row() -> None:
    table = StakingTable.build(StakingConfig(**REFERENCE, strategy="double"))

    assert table.wall_hit is True
    assert table.wall_required_stake == 1620
    assert table.wall_balance_available == 190.0
    assert table.losses_survived == 6
    actual = [(r.label, r.stake, r.cumulative_loss, r.balance) for r in table.rows]
    assert actual == DOUBLE_LADDER


def test_double_survives_fewer_entries_than_adder_profit() -> None:
    """The teaching point: doubling recovers and profits at a 92% payout too — it
    just exhausts capital faster, reaching the wall sooner, not failing to recover."""
    double = StakingTable.build(StakingConfig(**REFERENCE, strategy="double"))
    adder = StakingTable.build(StakingConfig(**REFERENCE))

    assert double.losses_survived < adder.losses_survived
    # A win still clears the debt and profits — doubling isn't broken arithmetic.
    for row in double.rows[2:]:
        assert row.balance_if_win > 1000.0


# --- A single first entry (entry_1b=None) --------------------------------


def test_single_opener_is_accepted() -> None:
    config = StakingConfig(**{**REFERENCE, "entry_1b": None})
    assert config.entry_1b is None


def test_single_opener_ladder_is_labelled_from_one() -> None:
    table = StakingTable.build(StakingConfig(**{**REFERENCE, "entry_1b": None}))

    assert table.wall_hit is True
    assert table.wall_required_stake == 1002
    assert table.wall_balance_available == 79.0
    assert table.losses_survived == 8
    actual = [(r.label, r.stake, r.cumulative_loss, r.balance) for r in table.rows]
    assert actual == SINGLE_OPENER_LADDER
    assert [r.label for r in table.rows] == [str(n) for n in range(1, 9)]


def test_single_opener_double_ladder() -> None:
    table = StakingTable.build(StakingConfig(**{**REFERENCE, "entry_1b": None}, strategy="double"))

    assert table.wall_hit is True
    assert table.wall_required_stake == 810.0
    assert table.wall_balance_available == 595.0
    assert table.losses_survived == 5
    actual = [(r.label, r.stake, r.cumulative_loss, r.balance) for r in table.rows]
    assert actual == SINGLE_OPENER_DOUBLE_LADDER


def test_single_opener_places_more_entries_but_ends_with_less_cushion() -> None:
    """Halving the opener buys no extra depth: the adder still places 8 entries,
    just with less left when the wall arrives — $79 instead of $163."""
    two_openers = StakingTable.build(StakingConfig(**REFERENCE))
    one_opener = StakingTable.build(StakingConfig(**{**REFERENCE, "entry_1b": None}))

    assert one_opener.losses_survived == two_openers.losses_survived == 8
    assert one_opener.wall_balance_available < two_openers.wall_balance_available


def test_non_positive_entry_1b_still_rejected_with_unchanged_message() -> None:
    """The message is load-bearing — `form_errors.py` substring-matches it and
    must keep working whether entry_1b is a real value or None."""
    with pytest.raises(ValueError, match="entry_1a and entry_1b must all be positive"):
        StakingConfig(**{**REFERENCE, "entry_1b": -5.0})

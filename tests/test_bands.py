"""Unit tests for `services/bands.py` — no HTTP round trip.

Flagged in the roadmap as untested since before `opener_badge` existed; adding
real logic to the module is the moment to stop deferring it.
"""

from types import SimpleNamespace

import pytest

from app.domain.staking_simulator import (
    STRATEGIES,
    InvalidStakingConfig,
    StakingConfig,
    StakingTable,
)
from app.schemas import SimulationCreate
from app.services.bands import (
    REFERENCE_CONFIG,
    band_for,
    config_for,
    drawdown_band_for,
    funding,
    ladder,
    opener_badge,
    recovery_gain,
    worked_example,
)


def test_opener_badge_reports_what_both_openers_return() -> None:
    badge = opener_badge(capital=1000.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92)

    assert badge.profit == 9.2
    assert badge.balance == 1009.2
    assert badge.opener_count == 2


def test_opener_badge_is_identical_regardless_of_capital_or_strategy() -> None:
    """It depends only on the openers and the payout — not on capital, and
    the caller never passes a strategy at all, which is the point: neither
    strategy has acted before the streak starts."""
    small = opener_badge(capital=100.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92)
    large = opener_badge(capital=1_000_000.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92)

    assert small.profit == large.profit == 9.2


def test_opener_badge_sums_a_single_opener() -> None:
    badge = opener_badge(capital=1000.0, entry_1a=5.0, entry_1b=None, payout_ratio=0.92)

    assert badge.profit == 4.6
    assert badge.balance == 1004.6
    assert badge.opener_count == 1


# --- config_for: the one conversion from a request to a plan -----------------


def test_config_for_sizes_both_openers_from_the_risk() -> None:
    """The user's own example: 0.25% of $3534.68 is $8.8367, so $8.84 each."""
    config = config_for(SimulationCreate(capital=3534.68, risk_percent=0.25))

    assert (config.entry_1a, config.entry_1b) == (8.84, 8.84)


def test_config_for_sizes_one_opener_and_no_second() -> None:
    config = config_for(SimulationCreate(capital=3534.68, risk_percent=0.25, opener_count=1))

    assert (config.entry_1a, config.entry_1b) == (8.84, None)


def test_config_for_refuses_a_risk_that_sizes_no_entry() -> None:
    with pytest.raises(InvalidStakingConfig) as caught:
        config_for(SimulationCreate(capital=1000.0, risk_percent=0.0))
    assert caught.value.field == "risk_percent"


def test_the_reference_config_is_half_a_percent_of_a_thousand() -> None:
    assert (REFERENCE_CONFIG.entry_1a, REFERENCE_CONFIG.entry_1b) == (5.0, 5.0)


def test_band_for_thresholds() -> None:
    assert band_for(0.0) == "calm"
    assert band_for(0.09) == "calm"
    assert band_for(0.10) == "caution"
    assert band_for(0.24) == "caution"
    assert band_for(0.25) == "elevated"
    assert band_for(0.49) == "elevated"
    assert band_for(0.50) == "danger"
    assert band_for(1.0) == "danger"


def test_drawdown_band_for_is_uncoloured_below_the_fifty_percent_floor() -> None:
    """Not "the lowest band" — actually None. Colour below 50% would be
    crying wolf, per the roadmap's own framing."""
    assert drawdown_band_for(0.0) is None
    assert drawdown_band_for(0.49) is None


def test_drawdown_band_for_thresholds() -> None:
    assert drawdown_band_for(0.50) == "heavy"
    assert drawdown_band_for(0.64) == "heavy"
    assert drawdown_band_for(0.65) == "severe"
    assert drawdown_band_for(0.79) == "severe"
    assert drawdown_band_for(0.80) == "critical"
    assert drawdown_band_for(0.89) == "critical"
    assert drawdown_band_for(0.90) == "terminal"
    assert drawdown_band_for(1.0) == "terminal"


def test_recovery_gain_matches_the_roadmaps_worked_figures() -> None:
    # Down 25% -> need +33%. Down 50% -> need +100%. Down 54.1% -> need +118%.
    assert recovery_gain(0.25) == pytest.approx(1 / 3, abs=0.001)
    assert recovery_gain(0.50) == pytest.approx(1.0)
    assert recovery_gain(0.541) == pytest.approx(1.178, abs=0.001)


def test_recovery_gain_is_none_at_a_full_drawdown() -> None:
    """100% drawdown means the balance hit exactly zero — the gain needed is
    undefined, not merely a very large number."""
    assert recovery_gain(1.0) is None


def test_ladder_bands_drawdown_onto_the_balance_cell() -> None:
    entry = SimpleNamespace(
        label="7", stake=436.0, cumulative_loss=850.0, balance=150.0, balance_if_win=1000.0
    )

    rows = ladder([entry], capital=1000.0)

    assert rows[0].drawdown == pytest.approx(0.85)
    assert rows[0].drawdown_band == "critical"
    assert rows[0].recovery_gain == pytest.approx(850.0 / 150.0)


def test_ladder_leaves_drawdown_band_unset_below_the_floor() -> None:
    entry = SimpleNamespace(
        label="1a", stake=5.0, cumulative_loss=5.0, balance=995.0, balance_if_win=1004.6
    )

    rows = ladder([entry], capital=1000.0)

    assert rows[0].drawdown_band is None


# --- Short recovery: a win that ends below starting capital ------------------


def test_short_recovery_marks_a_derived_entry_whose_win_ends_below_capital() -> None:
    entry = SimpleNamespace(
        label="5", stake=160.0, cumulative_loss=310.0, balance=690.0, balance_if_win=997.2
    )

    [row] = ladder([entry], capital=1000.0)

    assert row.win_net == -2.8
    assert row.short_recovery is True


def test_short_recovery_is_never_judged_on_an_opener() -> None:
    """1b alone returns $4.60 against the $5 1a lost -- the opener badge's
    business, not the streak's."""
    entry = SimpleNamespace(
        label="1b", stake=5.0, cumulative_loss=10.0, balance=990.0, balance_if_win=999.6
    )

    [row] = ladder([entry], capital=1000.0)

    assert row.win_net == -0.4
    assert row.short_recovery is False


def test_short_recovery_marks_only_the_doubled_tail_of_the_reference_case() -> None:
    rows, _ = worked_example("double")

    assert [r.label for r in rows if r.short_recovery] == ["5", "6"]


@pytest.mark.parametrize("strategy", [s for s in STRATEGIES if s != "double"])
def test_short_recovery_never_appears_under_an_adder(strategy: str) -> None:
    """The ceiling makes `stake * payout >= cumulative loss` by construction."""
    rows, _ = worked_example(strategy)

    assert not any(r.short_recovery for r in rows)


# --- Funding: what the account must hold for a given number of losses -------


EIGHT_DOLLAR_DOUBLE = StakingConfig(capital=1000.0, entry_1a=8.0, entry_1b=None, strategy="double")


def test_funding_is_the_cumulative_stake_through_each_loss() -> None:
    """The $8 doubling plan: keep 8 to take one loss, 24 for two, … 504 for six."""
    covered = [row for row in funding(EIGHT_DOLLAR_DOUBLE) if not row.wall]

    assert [row.keep for row in covered] == [8, 24, 56, 120, 248, 504]
    assert [row.elsewhere for row in covered] == [992, 976, 944, 880, 752, 496]
    assert [row.losses for row in covered] == [1, 2, 3, 4, 5, 6]


def test_funding_stops_at_the_wall() -> None:
    """Six losses plus the $512 the wall demanded: $1,016, $16 over capital --
    the last row. Past the wall the account is already gone."""
    funded = funding(EIGHT_DOLLAR_DOUBLE)

    assert len(funded) == 7
    wall = funded[-1]
    assert [row.wall for row in funded] == [False] * 6 + [True]
    assert (wall.losses, wall.keep, wall.elsewhere) == (7, 1016, -16)
    assert wall.share == pytest.approx(1.016)


def test_funding_agrees_with_the_ladder_up_to_the_wall() -> None:
    """The same stakes, so the same totals, for every strategy -- and the wall
    falls exactly where the ladder's did."""
    for strategy in STRATEGIES:
        config = StakingConfig(strategy=strategy)
        table = StakingTable.build(config)
        funded = funding(config)

        assert [r.keep for r in funded[: table.losses_survived]] == [
            r.cumulative_loss for r in table.rows
        ]
        assert len(funded) == table.losses_survived + 1
        assert funded[-1].wall


def test_funding_has_no_wall_inside_a_ladder_that_never_hit_one() -> None:
    funded = funding(StakingConfig(capital=1000.0, entry_1a=5.0, entry_1b=5.0, max_entries=3))

    assert [row.losses for row in funded] == [1, 2, 3]
    assert not any(row.wall for row in funded)

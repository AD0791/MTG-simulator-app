"""Unit tests for `web/bands.py` — no HTTP round trip.

Flagged in the roadmap as untested since before `opener_badge` existed; adding
real logic to the module is the moment to stop deferring it.
"""

from types import SimpleNamespace

import pytest

from app.web.bands import (
    band_for,
    drawdown_band_for,
    ladder,
    opener_badge,
    recovery_gain,
    suggested_opener,
)


def test_opener_badge_with_no_target_reports_a_plain_profit() -> None:
    badge = opener_badge(
        capital=1000.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92, target_profit=0.0
    )

    assert badge.profit == 9.2
    assert badge.balance == 1009.2
    assert badge.target is None
    assert badge.meets_target is None


def test_opener_badge_reports_a_shortfall_below_target() -> None:
    badge = opener_badge(
        capital=1000.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92, target_profit=10.0
    )

    assert badge.profit == 9.2
    assert badge.target == 10.0
    assert badge.meets_target is False


def test_opener_badge_reports_clearing_a_target() -> None:
    badge = opener_badge(
        capital=1000.0, entry_1a=6.0, entry_1b=6.0, payout_ratio=0.92, target_profit=10.0
    )

    assert badge.profit == 11.04
    assert badge.meets_target is True


def test_opener_badge_treats_exactly_meeting_the_target_as_a_pass() -> None:
    badge = opener_badge(
        capital=1000.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92, target_profit=9.2
    )

    assert badge.meets_target is True


def test_opener_badge_is_identical_regardless_of_capital_or_strategy() -> None:
    """It depends only on the openers and the payout — not on capital, and
    the caller never passes a strategy at all, which is the point: neither
    strategy has acted before the streak starts."""
    small = opener_badge(
        capital=100.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92, target_profit=0.0
    )
    large = opener_badge(
        capital=1_000_000.0, entry_1a=5.0, entry_1b=5.0, payout_ratio=0.92, target_profit=0.0
    )

    assert small.profit == large.profit == 9.2


def test_suggested_opener_matches_the_roadmap_worked_example() -> None:
    # T=$10, p=0.92: ceil(10 / 1.84) = $6 each, returning $11.04 — clears $10.
    assert suggested_opener(10.0, 0.92) == 6


def test_suggested_opener_clears_the_target_it_was_derived_from() -> None:
    payout_ratio = 0.92
    target = 10.0
    opener = suggested_opener(target, payout_ratio)
    assert opener is not None

    badge = opener_badge(
        capital=1000.0,
        entry_1a=opener,
        entry_1b=opener,
        payout_ratio=payout_ratio,
        target_profit=target,
    )
    assert badge.meets_target is True


def test_suggested_opener_is_none_at_zero_or_negative_target() -> None:
    """A zero target derives a zero opener, which the domain rejects — the
    caller falls back to the reader's own values instead."""
    assert suggested_opener(0.0, 0.92) is None
    assert suggested_opener(-5.0, 0.92) is None


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

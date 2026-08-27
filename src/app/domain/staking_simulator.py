"""
staking_simulator.py

Order-sizing simulator for binary-option-style trading (Pocket Option OTC).

You specify the first entry or entries by hand: either one opener
(entry_1a, labelled "1") or two (entry_1a and entry_1b, labelled "1a" and
"1b") on candle 1 -- entry_1b=None means one opener. From candle 2 onward,
the stake is computed automatically by one of three named strategies --
adder_breakeven, adder_profit, or double -- continuing until the required
stake exceeds the remaining balance -- the martingale wall.

  adder_breakeven  stake = ceil(cumulative_loss / payout_ratio)
  adder_profit     stake = ceil((cumulative_loss + target_profit) / payout_ratio)
  double           stake = 2 * cumulative_loss

adder_profit is the default -- it is what every stored run before the
"double" method existed was computed with.

StakingTable.build(config) is the entry point: pass a StakingConfig, get
back a fully populated StakingTable. Everything is a dataclass DTO, so the
whole result serializes straight out of an API response.
"""

from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional
import json
import math


def _adder_breakeven(cumulative_loss: float, target_profit: float, payout_ratio: float) -> float:
    return math.ceil(cumulative_loss / payout_ratio)


def _adder_profit(cumulative_loss: float, target_profit: float, payout_ratio: float) -> float:
    return math.ceil((cumulative_loss + target_profit) / payout_ratio)


def _double(cumulative_loss: float, target_profit: float, payout_ratio: float) -> float:
    return 2 * cumulative_loss


# A strategy is a callable, selected by name -- not a class hierarchy. Three
# values don't fit a flag, and a fourth is plausible, so the name is what's
# stored and persisted.
STRATEGIES: Dict[str, Callable[[float, float, float], float]] = {
    "adder_breakeven": _adder_breakeven,
    "adder_profit": _adder_profit,
    "double": _double,
}


@dataclass
class StakingConfig:
    capital: float = 1000.0
    entry_1a: float = 5.0
    entry_1b: Optional[float] = 5.0
    payout_ratio: float = 0.92       # 0.92 = 92% payout
    target_profit: float = 0.0       # profit demanded on top of recovery (adder_profit only)
    max_entries: int = 50            # safety cap
    strategy: str = "adder_profit"   # one of STRATEGIES

    def __post_init__(self):
        if self.capital <= 0:
            raise ValueError("capital must be positive")
        if self.entry_1a <= 0 or (self.entry_1b is not None and self.entry_1b <= 0):
            raise ValueError("entry_1a and entry_1b must all be positive")
        if not (0 < self.payout_ratio <= 1):
            raise ValueError("payout_ratio must be between 0 and 1")
        if self.target_profit < 0:
            raise ValueError("target_profit cannot be negative")
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")


@dataclass
class EntryRow:
    label: str               # "1a", "1b", "2", "3", ...
    stake: float
    cumulative_loss: float
    balance: float             # balance remaining after this loss
    balance_if_win: float      # what balance would be if THIS entry had won


@dataclass
class StakingTable:
    config: StakingConfig
    rows: List[EntryRow] = field(default_factory=list)
    wall_hit: bool = False
    wall_required_stake: Optional[float] = None
    wall_balance_available: Optional[float] = None
    losses_survived: int = 0

    @classmethod
    def build(cls, config: StakingConfig) -> "StakingTable":
        table = cls(config=config)
        balance = config.capital
        cumulative_loss = 0.0

        manual_entries: List[tuple[str, float]] = (
            [("1a", config.entry_1a), ("1b", config.entry_1b)]
            if config.entry_1b is not None
            else [("1", config.entry_1a)]
        )

        entry_number = 0
        for label, stake in manual_entries:
            entry_number += 1
            if stake > balance:
                table._hit_wall(stake, balance, entry_number)
                return table
            balance, cumulative_loss = table._record(
                label, stake, balance, cumulative_loss, entry_number
            )

        stake_for = STRATEGIES[config.strategy]

        candle = 2
        while entry_number < config.max_entries:
            entry_number += 1
            stake = stake_for(cumulative_loss, config.target_profit, config.payout_ratio)

            if stake > balance:
                table._hit_wall(stake, balance, entry_number)
                return table

            balance, cumulative_loss = table._record(
                str(candle), stake, balance, cumulative_loss, entry_number
            )
            candle += 1

        return table

    def _record(self, label: str, stake: float, balance: float,
                cumulative_loss: float, entry_number: int) -> tuple[float, float]:
        loss_before = cumulative_loss
        balance -= stake
        cumulative_loss += stake
        win_balance = round(self.config.capital - loss_before + stake * self.config.payout_ratio, 2)

        self.rows.append(EntryRow(
            label=label,
            stake=round(stake, 2),
            cumulative_loss=round(cumulative_loss, 2),
            balance=round(balance, 2),
            balance_if_win=win_balance,
        ))
        self.losses_survived = entry_number
        return balance, cumulative_loss

    def _hit_wall(self, stake: float, balance: float, entry_number: int) -> None:
        self.wall_hit = True
        self.wall_required_stake = round(stake, 2)
        self.wall_balance_available = round(balance, 2)

    def to_json(self, indent: Optional[int] = 2) -> str:
        """JSON string of the full table -- config, rows, and wall info.
        Use indent=None for compact output (e.g. an HTTP response body)."""
        return json.dumps(asdict(self), indent=indent)

    def print_table(self) -> None:
        print(f"{'Entry':>8} | {'Stake':>10} | {'Cum. loss':>10} | {'Balance':>12} | {'If win':>12}")
        print("-" * 60)
        for r in self.rows:
            print(f"{r.label:>8} | {r.stake:>10.2f} | {r.cumulative_loss:>10.2f} | "
                  f"{r.balance:>12.2f} | {r.balance_if_win:>12.2f}")
        if self.wall_hit:
            print(f"{'WALL':>8} | {self.wall_required_stake:>10.2f} | {'--':>10} | "
                  f"only ${self.wall_balance_available} left")
            print(f"\nLosses survived before the wall: {self.losses_survived}")


if __name__ == "__main__":
    config = StakingConfig(capital=1000.0, entry_1a=5.0, entry_1b=5.0)
    table = StakingTable.build(config)
    table.print_table()

    print("\n=== As JSON ===\n")
    print(table.to_json())

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
  double           stake = 2 * previous stake

double is the textbook martingale: each candle doubles the one before it. On
candle 2 the "previous stake" is everything placed on candle 1 -- both openers
when there are two.

adder_profit is the default -- it is what every stored run before the
"double" method existed was computed with.

StakingTable.build(config) is the entry point: pass a StakingConfig, get
back a fully populated StakingTable. Everything is a dataclass DTO, so the
whole result serializes straight out of an API response.

required_balances(config) answers the funding question instead: the balance
the account must hold to absorb each number of straight losses, with no wall
-- for a trader who keeps most of the capital outside the account.
"""

from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, Iterator, List, Optional
import json
import math


def _adder_breakeven(cumulative_loss: float, last_stake: float,
                     target_profit: float, payout_ratio: float) -> float:
    return math.ceil(cumulative_loss / payout_ratio)


def _adder_profit(cumulative_loss: float, last_stake: float,
                  target_profit: float, payout_ratio: float) -> float:
    return math.ceil((cumulative_loss + target_profit) / payout_ratio)


def _double(cumulative_loss: float, last_stake: float,
            target_profit: float, payout_ratio: float) -> float:
    return 2 * last_stake


# A strategy is a callable, selected by name -- not a class hierarchy. Three
# values don't fit a flag, and a fourth is plausible, so the name is what's
# stored and persisted.
STRATEGIES: Dict[str, Callable[[float, float, float, float], float]] = {
    "adder_breakeven": _adder_breakeven,
    "adder_profit": _adder_profit,
    "double": _double,
}


class InvalidStakingConfig(ValueError):
    """A plan the simulator refuses to run.

    `field` names the StakingConfig field at fault, so a caller can point at
    the right input without reading the message text to find it.
    """

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name


def check_payout_ratio(payout_ratio: float) -> None:
    """The one payout rule: a ratio in (0, 1].

    A function of its own so that anything dividing by a payout without
    building a whole plan -- sizing the openers to a target -- refuses an
    impossible one by this rule rather than a second copy of it.
    """
    if not (0 < payout_ratio <= 1):
        raise InvalidStakingConfig("payout_ratio", "payout_ratio must be between 0 and 1")


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
        # One refusal per field, first failure wins. entry_1b is checked only
        # when it exists -- a single-opener plan never has it blamed.
        if self.capital <= 0:
            raise InvalidStakingConfig("capital", "capital must be positive")
        if self.entry_1a <= 0:
            raise InvalidStakingConfig("entry_1a", "entry_1a must be positive")
        if self.entry_1b is not None and self.entry_1b <= 0:
            raise InvalidStakingConfig("entry_1b", "entry_1b must be positive")
        check_payout_ratio(self.payout_ratio)
        if self.target_profit < 0:
            raise InvalidStakingConfig("target_profit", "target_profit cannot be negative")
        if self.strategy not in STRATEGIES:
            raise InvalidStakingConfig(
                "strategy", f"strategy must be one of {', '.join(STRATEGIES)}"
            )


def stakes(config: StakingConfig) -> Iterator[tuple[str, float]]:
    """Every stake the plan places, in order, as if every entry loses and the
    account never runs dry: the openers, then derived stakes until
    max_entries entries in all (the openers are always placed).

    No stake reads the balance -- each is sized from the streak alone -- so
    this is the ladder with the wall taken away. build() walks it and stops at
    the first stake the balance cannot cover.
    """
    openers: List[tuple[str, float]] = (
        [("1a", config.entry_1a), ("1b", config.entry_1b)]
        if config.entry_1b is not None
        else [("1", config.entry_1a)]
    )
    yield from openers

    stake_for = STRATEGIES[config.strategy]
    cumulative_loss = sum(stake for _, stake in openers)
    # The previous candle's stake: on candle 2 that is every opener together.
    last_stake = cumulative_loss
    for candle in range(2, config.max_entries - len(openers) + 2):
        stake = stake_for(cumulative_loss, last_stake, config.target_profit, config.payout_ratio)
        yield str(candle), stake
        cumulative_loss += stake
        last_stake = stake


def required_balances(config: StakingConfig) -> List[float]:
    """The balance the account must hold to absorb 1, 2, 3, ... straight
    losses: the running total of stakes(), past the wall and up to
    max_entries. Capital plays no part -- compare against it to find the wall."""
    required: List[float] = []
    total = 0.0
    for _, stake in stakes(config):
        total += stake
        required.append(round(total, 2))
    return required


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

        for entry_number, (label, stake) in enumerate(stakes(config), start=1):
            if stake > balance:
                table._hit_wall(stake, balance, entry_number)
                return table
            balance, cumulative_loss = table._record(
                label, stake, balance, cumulative_loss, entry_number
            )

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

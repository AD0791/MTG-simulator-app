# Staking Simulator — `staking_simulator.py`

A small simulation tool for order-sizing (staking) on binary-option-style
trades — built for Pocket Option OTC assets at a fixed payout ratio (e.g.
92%), but the payout, capital, and entry sizes are all configurable.

It answers one question: **if I follow this staking plan and keep losing,
how far can I go before my account can no longer cover the next required
stake?** That breaking point is referred to throughout as the **martingale
wall**.

---

## Background: why this exists

At less than 100% payout, no staking pattern (flat, Fibonacci, doubling, or
a debt-driven "recovery" formula) can *safely* guarantee recovering a
losing streak — because every win only pays back a fraction of what was
staked, so the amount needed to fully recover a streak grows faster than
the streak itself. The practical question isn't "which pattern recovers
losses" (several can, on paper) but "how many consecutive losses can my
capital actually absorb before the required stake exceeds what's left."

This script models one specific staking plan:

1. **Entry 1a** and **Entry 1b** — two manual entries placed on the first
   candle (e.g. two $5 orders).
2. **Second entry** — a third manual entry, placed on the next candle
   (e.g. $18). This is chosen by hand, not computed.
3. **From the third entry onward**, the stake is computed automatically
   from the accumulated debt:

   ```
   stake = ceil( (cumulative_loss + target_profit) / payout_ratio )
   ```

   rounded up to the next whole dollar. This is the smallest stake that,
   if it wins, recovers every dollar lost in the streak so far, plus
   `target_profit` on top.

The simulation always assumes the **worst case** — every entry loses —
and stops the instant the next required stake is larger than the money
left in the account. That stopping point is the wall.

---

## How to use it

### Basic usage

```python
from staking_simulator import StakingConfig, StakingTable

config = StakingConfig(
    capital=1000.0,
    entry_1a=5.0,
    entry_1b=5.0,
    second_entry=18.0,
    payout_ratio=0.92,     # 92% payout
    target_profit=0.0,     # 0 = aim for breakeven + rounding, not a fixed profit
)

table = StakingTable.build(config)

table.print_table()   # human-readable table in the terminal
print(table.to_json())  # same data as a JSON string
```

Running the file directly (`python3 staking_simulator.py`) does exactly
this with the example numbers above — handy for quickly testing a new set
of parameters from the terminal before wiring it into anything else.

### Changing the plan

Every field on `StakingConfig` has a default, so you only need to override
what you're testing:

```python
# Bigger starting capital, same staking pattern
StakingConfig(capital=2000.0, entry_1a=5.0, entry_1b=5.0, second_entry=18.0)

# A smaller second entry
StakingConfig(entry_1a=5.0, entry_1b=5.0, second_entry=12.0)

# Demand a fixed $10 profit on top of recovery, instead of just breakeven
StakingConfig(target_profit=10.0)

# A different payout (e.g. a different OTC asset)
StakingConfig(payout_ratio=0.85)
```

---

## What it produces

### `StakingTable`

The return value of `StakingTable.build(config)`. It holds:

| Field | Meaning |
|---|---|
| `config` | The `StakingConfig` that produced this table |
| `rows` | List of `EntryRow` — one per entry actually placed |
| `wall_hit` | `True` if the streak hit the wall before running out of entries to simulate |
| `wall_required_stake` | The stake that *would* have been needed on the entry that broke the bank |
| `wall_balance_available` | How much was actually left in the account at that point |
| `losses_survived` | How many entries were successfully placed before the wall |

### `EntryRow` (one per row of `rows`)

| Field | Meaning |
|---|---|
| `label` | `"1a"`, `"1b"`, `"2"`, `"3"`, ... — which entry this is |
| `stake` | The amount risked on this entry |
| `cumulative_loss` | Total lost so far, including this entry |
| `balance` | Account balance remaining after this entry loses |
| `balance_if_win` | What the balance *would* be if this specific entry had won instead of lost |

### Example output (`entry_1a=5, entry_1b=5, second_entry=18, capital=1000`)

Terminal table (`table.print_table()`):

```
   Entry |      Stake |  Cum. loss |      Balance |       If win
------------------------------------------------------------
      1a |       5.00 |       5.00 |       995.00 |      1004.60
      1b |       5.00 |      10.00 |       990.00 |       999.60
       2 |      18.00 |      28.00 |       972.00 |      1006.56
       3 |      31.00 |      59.00 |       941.00 |      1000.52
       4 |      65.00 |     124.00 |       876.00 |      1000.80
       5 |     135.00 |     259.00 |       741.00 |      1000.20
       6 |     282.00 |     541.00 |       459.00 |      1000.44
    WALL |     589.00 |         -- | only $459.0 left

Losses survived before the wall: 7
```

JSON (`table.to_json()`) — same information, structured for an API
response:

```json
{
  "config": {
    "capital": 1000.0,
    "entry_1a": 5.0,
    "entry_1b": 5.0,
    "second_entry": 18.0,
    "payout_ratio": 0.92,
    "target_profit": 0.0,
    "max_entries": 50
  },
  "rows": [
    {"label": "1a", "stake": 5.0, "cumulative_loss": 5.0, "balance": 995.0, "balance_if_win": 1004.6},
    {"label": "1b", "stake": 5.0, "cumulative_loss": 10.0, "balance": 990.0, "balance_if_win": 999.6},
    {"label": "2", "stake": 18.0, "cumulative_loss": 28.0, "balance": 972.0, "balance_if_win": 1006.56}
  ],
  "wall_hit": true,
  "wall_required_stake": 589,
  "wall_balance_available": 459.0,
  "losses_survived": 7
}
```

### How to read `wall_hit` and `losses_survived`

- `losses_survived` is the number you actually plan around: it's how many
  consecutive losing entries this exact staking plan can take before the
  account can't place the next one.
- If `wall_hit` is `False`, the streak ran all the way to `max_entries`
  (default 50) without breaking the account — in practice this only
  happens with a very large `capital` relative to the entry sizes.

---

## Design notes (for whoever picks this up next — including future you)

- **The simulation is deterministic, not random.** It always assumes the
  worst case (every entry loses in a row). It does not model win/loss
  probability, so it can't tell you *how likely* a 7-loss streak is for a
  given strategy — only what happens to the account *if* one occurs. Win
  rate is a separate question, dependent on the actual trading strategy
  (e.g. streak+CCI signals), not on the staking plan.
- **The recurrence can't be vectorized.** Each stake depends on the
  *rounded* result of the previous one (`math.ceil`), so the table has to
  be built one row at a time — pandas and Polars were both tested for
  this and came out slower than plain dataclasses for exactly this
  reason (see the code's git history / prior discussion for the
  benchmark numbers). They'd be useful if you later want to analyze
  *many* `StakingTable` results in bulk (e.g. a parameter sweep or a
  Monte Carlo across win rates), just not for building a single table.
- **`StakingConfig` validates itself** in `__post_init__` — a negative
  `target_profit`, non-positive `capital`/entries, or an out-of-range
  `payout_ratio` raises `ValueError` immediately, which is useful once
  this is fed by a web form or JSON body instead of hardcoded values.

## Planned next step: FastAPI

This module is the domain core of a FastAPI service. It stays
framework-agnostic and importable without FastAPI — the web layer depends
on it, never the other way around.

`StakingTable` and `StakingConfig` are plain dataclasses, so the transport
layer is a thin wrapper over `StakingTable.build()`: the request body maps
onto a `StakingConfig`, and the resulting `StakingTable` serializes
directly as the response.

`StakingConfig`'s validation in `__post_init__` is the seam that turns a
malformed request body into a `4xx` instead of a corrupt table — a bad
`payout_ratio` or a negative `target_profit` raises `ValueError` at
construction, before any simulation runs.

Routes are versioned (`/api/v1/...`).

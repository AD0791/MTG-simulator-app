# Martingale Wall Simulator

A web app that answers one question honestly:

> If I follow this staking plan and keep losing, how far can I go before my account can no longer
> cover the next required stake?

That breaking point is the **martingale wall**, and finding it is the entire purpose of this tool.

## What this is, and what it is not

On a binary-option-style trade paying less than 100%, a winning trade returns only a fraction of
what was staked. So recovering a losing streak requires staking *more* than the streak cost — and
the amount needed grows faster than the streak itself. No staking pattern escapes this. Not flat,
not Fibonacci, not doubling, not a debt-driven recovery formula.

The useful question is therefore not *"which pattern recovers losses"* — several do, on paper —
but *"how many consecutive losses can my capital actually absorb before the required stake exceeds
what's left."*

This simulator answers that, and only that. It is deterministic: it assumes **every entry loses**
and reports where the account breaks. It does not model win probability, it does not predict
markets, and it is not a strategy that beats a negative-expectancy game. It is an instrument for
seeing exactly how and where such a strategy fails.

## The staking plan being modelled

1. **Entry 1a** and **1b** — two entries placed by hand on the first candle.
2. **Second entry** — a third entry on the next candle, also chosen by hand.
3. **From the third entry on**, the stake is computed from accumulated debt:

   ```
   stake = ceil( (cumulative_loss + target_profit) / payout_ratio )
   ```

   the smallest whole-dollar stake that, if it won, would recover every dollar lost so far.

The simulation stops the instant the next required stake exceeds the remaining balance.

With $1000 of capital, $5 + $5 on the first candle, $18 on the second, and a 92% payout, the wall
arrives on the seventh entry: it needs **$589** and only **$459** remains.

## Pages

| Path | What it does |
|---|---|
| `/` | The theory — how the payout mechanic works, why recovery staking hits a wall, and a FAQ for reading the results table |
| `/simulator` | Three inputs — starting capital, payout %, second entry — with the remaining parameters under **Advanced** |
| `/results/{id}` | The full ladder, entry by entry, to the wall |
| `/history` | Past runs, revisitable and clearable |

A versioned JSON API is available alongside the pages at `/api/v1` — `POST /api/v1/simulations`
runs and stores a simulation, `GET`/`DELETE` read and soft-delete them.

## Running in development

Two supported paths. Both do everything; pick whichever you prefer.

### With uv

Requires [uv](https://docs.astral.sh/uv/). Python is managed for you.

```bash
uv sync                                  # create the venv from the lockfile
cp .env.example .env                     # local settings
uv run alembic upgrade head              # create the SQLite schema
uv run uvicorn app.main:app --reload     # http://127.0.0.1:8000
```

### With Docker

```bash
cp .env.example .env
docker compose up api                    # http://127.0.0.1:8000
```

The dev service bind-mounts the source, so edits reload without a rebuild. Rebuild only after a
dependency change:

```bash
docker compose build api
```

### Common commands

| Task | uv | Docker |
|---|---|---|
| Run tests | `uv run pytest` | `docker compose run --rm api pytest` |
| One test | `uv run pytest -k wall` | `docker compose run --rm api pytest -k wall` |
| Lint | `uv run ruff check .` | `docker compose run --rm api ruff check .` |
| Format | `uv run ruff format .` | `docker compose run --rm api ruff format .` |
| Typecheck | `uv run mypy src` | `docker compose run --rm api mypy src` |
| New migration | `uv run alembic revision --autogenerate -m "..."` | same, on the host |

Dependencies are always added on the host with `uv add`, never inside a container — a
container-local install dies with the container and never reaches the lockfile.

## Storage

SQLite, for the prototype. Rows are **soft-deleted**: clearing the history sets a `deleted_at`
timestamp rather than dropping data, so a cleared table can still be inspected.

Production moves to PostgreSQL or MySQL. The schema is written to be portable and the move is a
`DATABASE_URL` change plus `alembic upgrade head` — the same migrations build the schema on any of
the three engines. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the migration path.

## Layout

```
src/app/
  domain/      the simulator — pure Python, no dependencies, no framework
  models/      SQLAlchemy ORM
  schemas/     Pydantic request/response contracts
  services/    use cases
  api/v1/      JSON routers
  web/         HTML page routers
  templates/   Jinja2
  static/      hand-authored CSS
```

`domain/` is deliberately free of FastAPI, Pydantic, and SQLAlchemy. It runs under bare `python3`
with nothing installed, which keeps the simulation independently testable and reusable:

```bash
cd src && python3 -c "import app.domain.staking_simulator"
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design, data model, migration path
  (also as a PDF)
- [staking_simulator_README.md](staking_simulator_README.md) — the domain module in detail: the
  recurrence, the design decisions behind it, and the reference output

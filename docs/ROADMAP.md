# Roadmap

Work deliberately deferred past the prototype. Neither item is scheduled; both are recorded here
with the decisions they will force, so that whoever picks them up is not re-deriving the reasoning.

Nothing here should influence the prototype's scope. It is written down precisely so it does not
have to be built early.

---

## 1. A Typer CLI

**Intent:** a command-line front end to the simulator, for personal use — run a plan, see the
ladder, without opening a browser.

### Why this fits without rework

The layering already anticipates it. `domain/` depends on nothing and `services/` holds the use
cases, so a CLI is a **third adapter** alongside `web/` and `api/v1/` rather than a second
implementation:

```
web/  ─┐
api/  ─┼─→  services/  ──→  domain/
cli/  ─┘
```

The rule that makes it cheap: **the CLI calls `services/`, never re-implements a use case.** If a
CLI command needs logic that only exists inside a web route, that logic was in the wrong layer to
begin with — move it down into `services/` and let both callers use it.

This is also the moment the service layer earns its keep. The `fastapi-architect` skill says to
introduce an abstraction at the second real caller, not the first anticipated one. The CLI is that
second caller, and it arrives without needing the services rewritten.

### Shape

```
src/app/cli/
  __init__.py     typer.Typer() app
  simulate.py     run a plan, print the ladder
  history.py      list, show, clear
```

Wire the entry point in `pyproject.toml` so it installs as a real command:

```toml
[project.scripts]
mws = "app.cli:app"
```

Then `uv run mws simulate --capital 1000 --payout 92 --second-entry 18`.

Typer was at **0.27.1** on 2026-08-25 — resolve the actual version with `uv add typer` when this
is built; do not pin from this note.

### Decisions to make before building

- **Does the CLI persist runs?** It should, into the same database, so history and the dashboard
  below cover both surfaces. Stateless would be simpler but splits the record of what was run.
- **Where does the database live for CLI use?** The web app resolves `DATABASE_URL` from the
  environment. A CLI invoked from an arbitrary working directory needs an absolute path or an
  explicit `--db` flag, or it will quietly create a fresh empty SQLite file wherever it is run
  from. This is the most likely source of "my history disappeared".
- **Session handling.** The web layer gets a session per request from a dependency. The CLI needs
  the equivalent — one session per command invocation, committed at the end, closed after. Do not
  reach for a global session because the request lifecycle is absent.
- **Output format.** A rendered table for reading, plus a `--json` flag so results can be piped.
  Reuse the domain's existing serialisation rather than writing a second formatter.

---

## 2. A dashboard page

**Intent:** aggregate across every simulation ever run, rather than reading them one at a time.

### The soft-delete insight

Soft delete means cleared runs are still there. `deleted_at` is set; the rows remain. So a
dashboard can aggregate over the **complete** history, including runs the user cleared from the
history page — which is exactly what makes the aggregate worth looking at, since a personal tool
accumulates far more cleared runs than kept ones.

### The decision this forces

**Should cleared runs count in the dashboard?** This needs an explicit answer, not a default,
because it changes what "clear" means to the person clicking it.

- *Yes* — "clear" tidies the history list; the dashboard is the long-run record. Defensible for a
  personal tool, and it is where the interesting data lives.
- *No* — "clear" means gone from everything, and the dashboard reflects only live runs.

Whichever is chosen, **the page must say which it is doing.** A dashboard silently counting runs
the user believes they deleted is a trust problem, not a feature. If cleared runs are included,
show the split — *"142 runs (38 cleared)"* — so the number is never mysterious.

There is also a real deletion path to keep in mind: if a hard-delete or purge is ever added, the
dashboard's history is what it destroys. Decide that before adding one, not after.

### Amendment this will require

The `persistence` skill currently says the unfiltered select — the one that does **not** filter
`deleted_at IS NULL` — belongs only to a restore or audit view. The dashboard becomes a third
sanctioned caller. Amend the skill when this is built, and keep the list of sanctioned callers
short and explicit; the whole soft-delete discipline rests on unfiltered reads being rare and
deliberate.

### Aggregations worth having

The prototype answers "where is the wall for *this* plan". The dashboard should answer questions
one run cannot:

- Distribution of `losses_survived` across all runs — how deep the wall typically sits.
- `losses_survived` against starting capital, showing how weakly more capital buys more entries.
  This is the strongest visual argument the tool can make, because the curve is far flatter than
  intuition suggests.
- The same against payout ratio — a higher payout moves the wall but never removes it.
- Which parameter sets were tried most, and which survived longest.

### Notes for whoever builds it

- Aggregate in SQL, not in Python over fetched rows. It stays correct when the table grows and
  it survives the move to Postgres unchanged.
- The `ui-design` skill's escalation ramp is for a single ladder. A distribution chart needs its
  own treatment — extend the skill rather than reusing bands that mean something different here.
- Keep the honesty rule from `CLAUDE.md`. A dashboard makes it tempting to surface a "best"
  configuration. There isn't one: every configuration loses, and the dashboard shows how they
  differ in how long that takes.

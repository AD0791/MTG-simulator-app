# Martingale Wall Simulator — Architecture

**Document status:** design baseline · **Date:** 25 August 2026 · **Applies to:** prototype release

This document describes how the Martingale Wall Simulator is built and why. It is written for two
readers at once. Sections 1–3 and 8 are for anyone who needs to understand what the system does
and what state it is in. Sections 4–7 are for the engineers building and maintaining it. Technical
terms used anywhere are defined in the glossary at the end.

---

## 1. What the system does

The simulator answers a single question: **following a given staking plan, how many consecutive
losing trades can an account absorb before it can no longer place the next required trade?**

That breaking point is called the **wall**. The application exists to locate it precisely, and to
explain clearly why it is unavoidable.

The reasoning is arithmetic, not opinion. On a trade that pays back less than the amount staked, a
win returns only a fraction of what was risked. Recovering a run of losses therefore requires
staking more than the run cost — and the amount needed grows faster than the losing run itself.
Every recovery-staking pattern meets a wall. The only variables are where it sits and how quickly
it arrives.

**What the system deliberately does not do.** It does not predict markets, does not estimate the
probability of a losing run, and does not present the staking plan as profitable. It assumes the
worst case — every trade loses — and reports the consequence. Presenting it as anything else would
misrepresent the arithmetic it exists to demonstrate.

## 2. Who uses it, and how

A single visitor, using a browser, with no account and no login. Three steps:

1. **Read the theory** on the landing page — the payout mechanic, why recovery staking has a
   ceiling, and a FAQ explaining how to read the results.
2. **Run a simulation** from three inputs: starting capital, payout percentage, and the second
   entry size. Four further parameters sit under an *Advanced* panel at sensible defaults.
3. **Read the results** — every entry in the ladder, the stake it required, what remained
   afterwards, and the point at which the account could no longer continue.

Every run is stored, so results can be revisited and compared. Stored runs can be cleared, and
clearing is reversible — see section 6.

## 3. How the escalation behaves

The reason the wall arrives suddenly is that each entry consumes a larger share of what is left.
Using the reference case — $1,000 capital, $5 and $5 on the first candle, $18 on the second, 92%
payout — the share of the remaining balance each entry demands:

```
  1a   █░░░░░░░░░░░░░░░░░░░░░░░    0.5%
  1b   █░░░░░░░░░░░░░░░░░░░░░░░    0.5%
   2   █░░░░░░░░░░░░░░░░░░░░░░░    1.8%
   3   ██░░░░░░░░░░░░░░░░░░░░░░    3.2%
   4   ████░░░░░░░░░░░░░░░░░░░░    6.9%
   5   █████████░░░░░░░░░░░░░░░   15.4%
   6   ███████████████████████░   38.1%
WALL   ████████████████████████  128.3%  → exceeds balance
scale: 24 cells = 40% of the balance remaining before that entry
```

The first five entries look harmless — none risks more than 7% of what remains. The sixth demands
38%. The seventh demands more than the account holds, and the plan stops. Nothing warns the trader
in advance, which is precisely why the tool exists: **the danger is invisible until the entry
before last.**

---

## 4. System structure

The application is a single deployable unit. It serves web pages and a JSON interface from the
same process, with no separate frontend build.

It is organised in layers. Each layer may depend only on the layer beneath it, never the reverse.

<svg viewBox="0 0 660 340" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica Neue, Helvetica, Arial, sans-serif">
  <defs>
    <marker id="a1" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#5b5b5b"/>
    </marker>
  </defs>
  <rect x="25" y="15" width="270" height="56" rx="5" fill="#eef2f7" stroke="#1f4e8c" stroke-width="1.5"/>
  <text x="160" y="38" text-anchor="middle" font-size="13" font-weight="bold" fill="#1f4e8c">web/ — HTML pages</text>
  <text x="160" y="56" text-anchor="middle" font-size="10.5" fill="#5b5b5b">/ · /simulator · /results · /history</text>
  <rect x="365" y="15" width="270" height="56" rx="5" fill="#eef2f7" stroke="#1f4e8c" stroke-width="1.5"/>
  <text x="500" y="38" text-anchor="middle" font-size="13" font-weight="bold" fill="#1f4e8c">api/v1/ — JSON API</text>
  <text x="500" y="56" text-anchor="middle" font-size="10.5" fill="#5b5b5b">versioned contract</text>
  <rect x="155" y="115" width="350" height="56" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.5"/>
  <text x="330" y="138" text-anchor="middle" font-size="13" font-weight="bold" fill="#262626">services/ — use cases</text>
  <text x="330" y="156" text-anchor="middle" font-size="10.5" fill="#5b5b5b">run · persist · fetch · soft-delete</text>
  <rect x="25" y="215" width="270" height="56" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.5"/>
  <text x="160" y="238" text-anchor="middle" font-size="13" font-weight="bold" fill="#262626">domain/ — the simulator</text>
  <text x="160" y="256" text-anchor="middle" font-size="10.5" fill="#5b5b5b">pure Python · zero dependencies</text>
  <rect x="365" y="215" width="270" height="56" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.5"/>
  <text x="500" y="238" text-anchor="middle" font-size="13" font-weight="bold" fill="#262626">models/ — ORM</text>
  <text x="500" y="256" text-anchor="middle" font-size="10.5" fill="#5b5b5b">SQLAlchemy mappings</text>
  <rect x="405" y="295" width="190" height="34" rx="5" fill="#eef2f7" stroke="#5b5b5b" stroke-width="1.2" stroke-dasharray="4 3"/>
  <text x="500" y="317" text-anchor="middle" font-size="11.5" fill="#5b5b5b">SQLite (Postgres in prod)</text>
  <path d="M 200 71 L 250 113" stroke="#5b5b5b" stroke-width="1.4" fill="none" marker-end="url(#a1)"/>
  <path d="M 460 71 L 410 113" stroke="#5b5b5b" stroke-width="1.4" fill="none" marker-end="url(#a1)"/>
  <path d="M 250 173 L 200 213" stroke="#5b5b5b" stroke-width="1.4" fill="none" marker-end="url(#a1)"/>
  <path d="M 410 173 L 460 213" stroke="#5b5b5b" stroke-width="1.4" fill="none" marker-end="url(#a1)"/>
  <path d="M 500 271 L 500 293" stroke="#5b5b5b" stroke-width="1.4" fill="none" marker-end="url(#a1)"/>
</svg>

**The rule that matters most:** the domain layer — the simulation itself — depends on nothing. It
imports no web framework, no validation library, and no database library. It runs under a bare
Python interpreter with nothing installed.

This is not architectural decoration. It means the calculation can be tested without starting a
server, reused from a command line or a batch analysis, and left untouched when the web framework
is upgraded. The simulator is the asset; everything else is replaceable packaging around it.

**Two HTTP surfaces, versioned differently.** The JSON API is versioned (`/api/v1/…`) because
outside consumers depend on its shape and must not break when it changes. The web pages are not
versioned, because their only consumer is the browser being served and their addresses are things
people bookmark.

## 5. What happens when a simulation runs

<svg viewBox="0 0 660 320" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica Neue, Helvetica, Arial, sans-serif">
  <defs>
    <marker id="a2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#5b5b5b"/>
    </marker>
  </defs>
  <text x="165" y="14" text-anchor="middle" font-size="11" font-weight="bold" fill="#1f4e8c">SUBMIT</text>
  <text x="495" y="14" text-anchor="middle" font-size="11" font-weight="bold" fill="#1f4e8c">DISPLAY</text>
  <rect x="20" y="26" width="290" height="52" rx="5" fill="#eef2f7" stroke="#1f4e8c" stroke-width="1.4"/>
  <text x="34" y="46" font-size="11.5" font-weight="bold" fill="#262626">1 · POST /simulator</text>
  <text x="34" y="64" font-size="10.5" fill="#5b5b5b">three inputs + advanced panel</text>
  <rect x="20" y="98" width="290" height="52" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.4"/>
  <text x="34" y="118" font-size="11.5" font-weight="bold" fill="#262626">2 · validate</text>
  <text x="34" y="136" font-size="10.5" fill="#5b5b5b">schema, then domain self-validation</text>
  <rect x="20" y="170" width="290" height="52" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.4"/>
  <text x="34" y="190" font-size="11.5" font-weight="bold" fill="#262626">3 · build the ladder</text>
  <text x="34" y="208" font-size="10.5" fill="#5b5b5b">StakingTable.build() — no I/O</text>
  <rect x="20" y="242" width="290" height="52" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.4"/>
  <text x="34" y="262" font-size="11.5" font-weight="bold" fill="#262626">4 · persist + commit</text>
  <text x="34" y="280" font-size="10.5" fill="#5b5b5b">one simulation, many entries</text>
  <rect x="350" y="26" width="290" height="52" rx="5" fill="#eef2f7" stroke="#1f4e8c" stroke-width="1.4"/>
  <text x="364" y="46" font-size="11.5" font-weight="bold" fill="#262626">5 · 303 → /results/{id}</text>
  <text x="364" y="64" font-size="10.5" fill="#5b5b5b">redirect, so reload is safe</text>
  <rect x="350" y="98" width="290" height="52" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.4"/>
  <text x="364" y="118" font-size="11.5" font-weight="bold" fill="#262626">6 · fetch the run</text>
  <text x="364" y="136" font-size="10.5" fill="#5b5b5b">live rows only (not cleared)</text>
  <rect x="350" y="170" width="290" height="52" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.4"/>
  <text x="364" y="190" font-size="11.5" font-weight="bold" fill="#262626">7 · band each row</text>
  <text x="364" y="208" font-size="10.5" fill="#5b5b5b">stake ÷ balance before it</text>
  <rect x="350" y="242" width="290" height="52" rx="5" fill="#eef2f7" stroke="#1f4e8c" stroke-width="1.4"/>
  <text x="364" y="262" font-size="11.5" font-weight="bold" fill="#262626">8 · render the page</text>
  <text x="364" y="280" font-size="10.5" fill="#5b5b5b">ladder, summary, wall row</text>
  <path d="M 165 78 L 165 96" stroke="#5b5b5b" stroke-width="1.4" marker-end="url(#a2)"/>
  <path d="M 165 150 L 165 168" stroke="#5b5b5b" stroke-width="1.4" marker-end="url(#a2)"/>
  <path d="M 165 222 L 165 240" stroke="#5b5b5b" stroke-width="1.4" marker-end="url(#a2)"/>
  <path d="M 310 268 L 330 268 L 330 52 L 348 52" stroke="#1f4e8c" stroke-width="1.4" fill="none" marker-end="url(#a2)"/>
  <path d="M 495 78 L 495 96" stroke="#5b5b5b" stroke-width="1.4" marker-end="url(#a2)"/>
  <path d="M 495 150 L 495 168" stroke="#5b5b5b" stroke-width="1.4" marker-end="url(#a2)"/>
  <path d="M 495 222 L 495 240" stroke="#5b5b5b" stroke-width="1.4" marker-end="url(#a2)"/>
</svg>

Two details in that flow are deliberate.

**Validation happens twice, and that is correct.** The web schema rejects malformed input — a
missing field, text where a number belongs. The domain then applies its own rules: capital must be
positive, the payout must fall between 0 and 100%, the target profit cannot be negative. The
domain's checks are the authoritative ones because they protect the calculation from *every*
caller, not only from the web form. A single translation point converts a domain rejection into a
readable error response, so no individual route handles it.

**Submitting redirects rather than rendering.** The result page is reached by a fresh request, so
reloading it re-reads a stored run instead of re-submitting the form.

## 6. What is stored

<svg viewBox="0 0 660 300" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica Neue, Helvetica, Arial, sans-serif">
  <rect x="25" y="20" width="275" height="250" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.5"/>
  <rect x="25" y="20" width="275" height="28" rx="5" fill="#1f4e8c"/>
  <rect x="25" y="40" width="275" height="8" fill="#1f4e8c"/>
  <text x="162" y="39" text-anchor="middle" font-size="12.5" font-weight="bold" fill="#ffffff">simulations</text>
  <text x="40" y="68" font-size="10.5" font-family="Menlo, monospace" fill="#1f4e8c">id            PK</text>
  <text x="40" y="86" font-size="10.5" font-family="Menlo, monospace" fill="#262626">capital</text>
  <text x="40" y="104" font-size="10.5" font-family="Menlo, monospace" fill="#262626">payout_ratio</text>
  <text x="40" y="122" font-size="10.5" font-family="Menlo, monospace" fill="#262626">second_entry</text>
  <text x="40" y="140" font-size="10.5" font-family="Menlo, monospace" fill="#262626">entry_1a, entry_1b</text>
  <text x="40" y="158" font-size="10.5" font-family="Menlo, monospace" fill="#262626">target_profit</text>
  <text x="40" y="176" font-size="10.5" font-family="Menlo, monospace" fill="#262626">max_entries</text>
  <text x="40" y="194" font-size="10.5" font-family="Menlo, monospace" fill="#262626">wall_hit</text>
  <text x="40" y="212" font-size="10.5" font-family="Menlo, monospace" fill="#262626">wall_required_stake</text>
  <text x="40" y="230" font-size="10.5" font-family="Menlo, monospace" fill="#262626">losses_survived</text>
  <text x="40" y="248" font-size="10.5" font-family="Menlo, monospace" fill="#5b5b5b">created/updated/deleted_at</text>
  <rect x="385" y="20" width="250" height="196" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.5"/>
  <rect x="385" y="20" width="250" height="28" rx="5" fill="#1f4e8c"/>
  <rect x="385" y="40" width="250" height="8" fill="#1f4e8c"/>
  <text x="510" y="39" text-anchor="middle" font-size="12.5" font-weight="bold" fill="#ffffff">simulation_entries</text>
  <text x="400" y="68" font-size="10.5" font-family="Menlo, monospace" fill="#1f4e8c">id            PK</text>
  <text x="400" y="86" font-size="10.5" font-family="Menlo, monospace" fill="#1f4e8c">simulation_id FK</text>
  <text x="400" y="104" font-size="10.5" font-family="Menlo, monospace" fill="#262626">position</text>
  <text x="400" y="122" font-size="10.5" font-family="Menlo, monospace" fill="#262626">label</text>
  <text x="400" y="140" font-size="10.5" font-family="Menlo, monospace" fill="#262626">stake</text>
  <text x="400" y="158" font-size="10.5" font-family="Menlo, monospace" fill="#262626">cumulative_loss</text>
  <text x="400" y="176" font-size="10.5" font-family="Menlo, monospace" fill="#262626">balance</text>
  <text x="400" y="194" font-size="10.5" font-family="Menlo, monospace" fill="#262626">balance_if_win</text>
  <line x1="300" y1="120" x2="385" y2="120" stroke="#262626" stroke-width="1.4"/>
  <text x="312" y="112" font-size="11" font-family="Menlo, monospace" fill="#262626">1</text>
  <text x="362" y="112" font-size="11" font-family="Menlo, monospace" fill="#262626">N</text>
  <text x="342" y="240" text-anchor="middle" font-size="10.5" fill="#5b5b5b">one run</text>
  <text x="342" y="256" text-anchor="middle" font-size="10.5" fill="#5b5b5b">many entries</text>
</svg>

**Two tables rather than one.** The entry ladder could have been stored as a single structured
blob against each run. It is a separate table instead, because blob storage behaves differently
across SQLite, PostgreSQL, and MySQL — it would be the one part of the schema needing rework at
the production move, which is exactly what section 7 exists to avoid.

**Timestamps.** Every row records when it was created and last changed, in UTC with an explicit
time zone. The values are set by the application rather than the database, because the three
database engines each generate timestamps with different precision and different time-zone
handling. Setting them in one place makes all three agree.

**Clearing is reversible.** Deleting a run does not remove it. It records the time of deletion in a
`deleted_at` field, and every ordinary query ignores rows that carry one. The data remains for
inspection and can be restored by clearing that field. “Clear the table” marks every live run as
deleted; it never discards anything.

The correctness of this rests on a single rule: **every read path goes through one shared query
helper that applies the filter.** A query written by hand that omits it would silently show
deleted runs, and that is the one way this pattern fails.

## 7. Moving to production

The prototype runs on SQLite — a single file, no server, no setup. Production will run on
PostgreSQL or MySQL. The schema is written so that this is a configuration change.

<svg viewBox="0 0 660 250" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica Neue, Helvetica, Arial, sans-serif">
  <defs>
    <marker id="a3" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#1f4e8c"/>
    </marker>
  </defs>
  <rect x="165" y="18" width="330" height="60" rx="5" fill="#eef2f7" stroke="#1f4e8c" stroke-width="1.6"/>
  <text x="330" y="42" text-anchor="middle" font-size="13" font-weight="bold" fill="#1f4e8c">alembic/versions/</text>
  <text x="330" y="62" text-anchor="middle" font-size="10.5" fill="#5b5b5b">one set of migrations · engine-independent</text>
  <path d="M 250 78 L 165 132" stroke="#1f4e8c" stroke-width="1.5" fill="none" marker-end="url(#a3)"/>
  <path d="M 410 78 L 495 132" stroke="#1f4e8c" stroke-width="1.5" fill="none" marker-end="url(#a3)"/>
  <rect x="30" y="136" width="270" height="64" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.5"/>
  <text x="165" y="158" text-anchor="middle" font-size="12.5" font-weight="bold" fill="#262626">Development</text>
  <text x="165" y="176" text-anchor="middle" font-size="10.5" font-family="Menlo, monospace" fill="#5b5b5b">sqlite:///./app.db</text>
  <text x="165" y="192" text-anchor="middle" font-size="10" fill="#5b5b5b">one file · no server</text>
  <rect x="360" y="136" width="270" height="64" rx="5" fill="#ffffff" stroke="#262626" stroke-width="1.5"/>
  <text x="495" y="158" text-anchor="middle" font-size="12.5" font-weight="bold" fill="#262626">Production</text>
  <text x="495" y="176" text-anchor="middle" font-size="10.5" font-family="Menlo, monospace" fill="#5b5b5b">postgresql+psycopg://…</text>
  <text x="495" y="192" text-anchor="middle" font-size="10" fill="#5b5b5b">managed instance</text>
  <rect x="140" y="215" width="380" height="28" rx="14" fill="#eef2f7" stroke="#5b5b5b" stroke-width="1.2" stroke-dasharray="4 3"/>
  <text x="330" y="234" text-anchor="middle" font-size="11" fill="#262626">the only difference: one DATABASE_URL setting</text>
</svg>

The same migration files build the schema on either engine. Moving is three steps: point the
database setting at the new server, run the migrations, and copy the existing rows if they are
worth keeping.

What makes this work is discipline in the schema rather than anything clever at migration time —
no engine-specific column types, no structured blobs, explicit lengths on text columns, every
constraint named, and no reliance on the accidental row ordering SQLite happens to provide. Each
of those is a thing SQLite tolerates and PostgreSQL does not.

**Known limitation.** SQLite has weak support for altering existing columns, so a future migration
that changes a column type will need care. This is a limitation of the prototype database, not of
the migration tooling, and it disappears once production moves to PostgreSQL.

## 8. How we know it works

| Check | What it protects |
|---|---|
| Domain test suite | The arithmetic — both wall outcomes, every rejected input |
| Reference case | The published example still produces $589 needed, $459 left, 7 survived |
| Independence check | The simulator still runs with no libraries installed |
| Interface tests | Correct status codes, correct shapes, readable errors |
| Deletion test | A cleared run is retained in storage and absent from listings |
| Style and type checks | Consistent formatting, no type errors |
| Accessibility pass | Contrast, keyboard navigation, colour never the only signal |

Every check runs identically whether the developer works directly on their machine or inside a
container. That equivalence is deliberate: a defect that appears in one and not the other means
the two environments have diverged, and that divergence is then the defect to fix.

---

## Glossary

**Alembic** — the tool that records and applies changes to the database structure, so every
environment can be brought to the same shape reliably.

**Binary option** — a trade with two outcomes: a fixed payout if the prediction is right, the loss
of the stake if it is wrong.

**Candle** — one fixed interval of price movement, the unit of time an entry is placed against.

**Entry** — a single trade placed as part of the staking plan.

**Ladder** — the full sequence of entries a plan produces, from the first to the wall.

**Migration** — one recorded change to the database structure, applied in order with all others.

**ORM** — the layer that maps stored rows onto objects in the code, so the application is not
written in raw database language.

**Payout ratio** — the proportion of the stake returned as profit on a winning trade. At 92%, a
$100 winning stake returns $92 profit. Because this is below 100%, recovery staking has a ceiling.

**Recovery stake** — the amount that, if it won, would recover every loss in the run so far.

**Schema** — the structure of the stored data: which tables exist and what each column holds.

**Soft delete** — marking a record as deleted while keeping it stored, so the action is reversible
and the data remains available for inspection.

**SQLite / PostgreSQL / MySQL** — database engines. SQLite is a single file requiring no server,
suited to a prototype; the other two are server-based and suited to production.

**Stake** — the amount of money risked on one entry.

**Wall** — the point at which the next required stake exceeds the money remaining, so the plan
cannot continue. The subject of this application.

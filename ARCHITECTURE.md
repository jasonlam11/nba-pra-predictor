# Architecture

How the NBA PRA Predictor is put together, and why it is put together that way.

The "why" matters more than usual here: almost every unusual decision in this
codebase traces back to a single constraint, and the design looks arbitrary
without it.

---

## 1. The constraint everything else follows from

The app predicts a player's **P**oints + **R**ebounds + **A**ssists for their
next game. The obvious way to build that is to call the NBA's stats API when a
user asks for a player.

That does not work. The NBA:

- **rate-limits** `stats.nba.com` aggressively, and
- **blocks datacenter IP ranges** outright — AWS, GCP, Azure, Render, Vercel.

Measured from a laptop on a normal residential connection while building this
(2026-09-30):

| Host | Result |
|---|---|
| `github.com` | 200 in 0.43s |
| `site.api.espn.com` | 200 in 0.39s |
| `cdn.nba.com` | **403** |
| `www.nba.com` | **403** |
| `stats.nba.com` | **timeout — connection silently dropped after 25s** |

Every `nba.com` host refuses or black-holes the request while everything else
responds normally. This is not a network problem on our end; it is the NBA
declining to serve us.

So the original design was not slow. It was **dead** — and it could never have
been deployed to a free host even if it had worked locally, because those are
exactly the IPs the NBA blocks.

**The resolution: nothing is fetched at request time.** A job does all the work
offline, once a day, and writes a single file. The API only reads that file.
This makes the request path fast (~4ms), impossible to rate-limit, and free to
host anywhere.

Every design decision below is downstream of that.

---

## 2. System shape

```
          ┌──────────────────────── GitHub Actions (daily, 06:30 UTC) ────────────────────────┐
          │                                                                                   │
          │   sportsdataverse bulk parquet          ESPN public JSON                          │
          │   (every player-game, ~0.6 MB/season)   (schedule + injury report)                │
          │              │                                  │                                 │
          │              └───────────────┬──────────────────┘                                 │
          │                              ▼                                                    │
          │                   scripts/build_snapshot.py                                       │
          │                    • translate to nba_api column shape                            │
          │                    • map ESPN ids → nba_api ids                                   │
          │                    • compute opponent + absence histories                         │
          │                    • run the model for every player                               │
          │                    • validate, then atomically swap                               │
          │                              │                                                    │
          │                              ▼                                                    │
          │                      snapshot.db  (~9 MB SQLite)                                  │
          └──────────────────────────────┬────────────────────────────────────────────────────┘
                                         │ published as a GitHub Release asset
                                         ▼
                            ┌─────────────────────────┐
                            │  FastAPI  (backend/app) │   downloads at startup,
                            │  zero upstream calls    │   serves indexed reads
                            └────────────┬────────────┘
                                         ▲
                                         │ HTTP
                            ┌────────────┴────────────┐
                            │  Next.js frontend (src) │
                            └─────────────────────────┘
```

The dashed boundary matters: **everything that can be blocked or throttled lives
inside the daily job.** The serving path touches only a local file.

---

## 3. Data sources

All free, all keyless. There is no paid API anywhere in this project, and there
never was — `nba_api` is a free package; the problem was always access, not cost.

### sportsdataverse bulk box scores — the backbone

```
https://github.com/sportsdataverse/sportsdataverse-data/
  releases/download/espn_nba_player_boxscores/player_box_<YEAR>.parquet
```

Published as GitHub Release assets, so they download from any IP including
cloud. 25 seasons (2002–2026), ~0.6 MB per season, **16.6 MB for all of them**.
Refreshed daily around 05:00 UTC during the season.

A season file holds every player-game: minutes, points, rebounds, assists,
shooting splits, starter flag, home/away, opponent, team scores. One download
replaces the entire scrape the project used to do.

Note the season label is the year the season **ends**: `player_box_2026.parquet`
is the 2025-26 season.

### ESPN public JSON — schedule and injuries

- `site.api.espn.com/.../nba/scoreboard` — games, with `?dates=YYYYMMDD`
- `site.api.espn.com/.../nba/injuries` — league injury report

One counterintuitive detail, documented in `espn_live.py` because it will
otherwise cost someone an hour: **ESPN 403s a spoofed browser User-Agent** and
serves 200 to `requests`' own `python-requests/x.y` default. A browser UA
arriving without a browser TLS fingerprint reads as a bot. Do not "fix" this by
adding a Mozilla UA.

### nba_api — retained, off the serving path

`backend/scripts/fetch_data.py` is the original scraper. Nothing imports it on
any live code path. It stays as reference and because `check_parity.py` uses
`nba_api`'s bundled static player list for ID mapping — a local JSON file, not a
network call.

---

## 4. The daily job (`scripts/build_snapshot.py`)

Seven stages. The job may touch the network freely; only the request path may not.

**1 — Load bulk box scores.** `parquet_source.py` downloads and caches season
files. It probes years *downward* to find the newest published season, because a
new season's file does not exist until the season tips off — an October run must
not crash looking for a file upstream has not created yet.

**2 — Build the ID map.** See §5.

**3 — Fetch schedule and injuries** from ESPN, looking 8 days ahead so a
prediction still has a matchup across an off day or the All-Star break.

**4 — Compute team defense ratings** from the same box scores already in hand.

**5 — Build the player table** — jersey, position, headshot, team, taken from
each player's most recent game row.

**6 — Run the model** for every player with ≥10 games, storing the exact
`/players/{id}/stats` payload the API will return.

**7 — Validate, then atomically swap.** The job refuses to publish unless it
sees ≥400 players, ≥300 predictions, an ID match rate ≥95%, named spot-check
players present, and all predictions inside 0–100 PRA. It builds to
`snapshot.db.tmp` and `os.replace`s it into position, so a failed or partial run
never replaces a good snapshot.

### The translation layer (`espn_adapter.py`)

The single most important property of this codebase:

> `engineer_features` is **not modified** to accommodate the new data source.

The adapter maps bulk columns into nba_api's exact column shape — `GAME_DATE`,
`MATCHUP`, `WL`, `PTS`, `REB`, `AST`, `MIN`, shooting percentages — so the
features the model trains on and the features it serves on are identical *by
construction* rather than by inspection. Train/serve skew is designed out, not
tested for.

Three filters matter, and getting any of them wrong corrupts rolling windows
silently rather than raising:

1. **All-Star rosters** appear as fake teams `STARS` / `STRIPES` / `WORLD`. A
   30-tricode whitelist removes them. Deliberately *not* a `season_type`
   blacklist — `season_type == 5` is the play-in, which is real basketball.
2. **`did_not_play` rows** exist here (~6k/season) but `playergamelog` never
   returns them. Leaving them in inserts zero-minute games into every L5/L10
   window. The `active` column is *not* a safe substitute — rows exist with
   `active=False` and 23 minutes played.
3. **ESPN tricodes differ** for six teams: `GS→GSW, NO→NOP, NY→NYK, SA→SAS,
   UTAH→UTA, WSH→WAS`. `MATCHUP` strings are parsed downstream for the opponent,
   so these must be translated.

Row order is **newest-first**, matching nba_api, because `_recent_stats_from_log`
uses `.head(n)`. `engineer_features` re-sorts ascending internally, so both
conventions are satisfied.

---

## 5. Player identity

The bulk data uses **ESPN athlete ids**; the frontend keys off **nba_api player
ids**. The nba_api id stays canonical on purpose — pinned players in
localStorage, `/compare`, and roster links all use it, so changing the primary
key would force a client-side migration for no benefit.

`id_map.py` resolves in order:

1. `backend/data/id_overrides.json` — hand-maintained, always wins.
2. Normalized-name match (strip accents, punctuation, `Jr./Sr./II/III/IV`)
   against nba_api's **full ~5,100-name static list**.
3. Unresolved → **synthetic id `900_000_000 + espn_id`**, flagged as such.

Step 2's "full list" is load-bearing. Matching against the *active-only* list
reaches just 80%, because that list is bundled with the package and goes stale
between releases — dropping exactly the rookies a predictor most wants. Against
the full list: **98.8% of players with ≥10 games**. The handful that still miss
get synthetic ids so they remain usable instead of vanishing.

The job **fails** if the ≥10-game match rate drops below 95%, and writes
`backend/data/id_map.json` into the repo so ID churn shows up in diffs.

---

## 6. The model

Trained by `scripts/train_model.py`. Despite the file's history it is not
necessarily XGBoost — it compares Ridge, RandomForest and XGBoost and keeps
whichever wins on validation. Check `model_type` in the pickle.

**Current: XGBoost, 31 features, ~705 players / ~110k player-games.**
Test MAE **5.88** against a last-5-game-average baseline of **6.45**.

### Features

| Group | Columns |
|---|---|
| Context | `IS_HOME`, `DAYS_REST`, `IS_B2B` |
| Rolling form | `{PTS,REB,AST,PRA,MIN}` × `{L3, L5, L10, SEASON}` (20) |
| Consistency / momentum | `PRA_STD_L5`, `WIN_STREAK` |
| Opponent strength | `OPP_{PTS,REB,AST}_ALLOWED`, `OPP_PTS_ALLOWED_L10`, `OPP_PACE` |
| Usage opportunity | `TEAM_MIN_ABSENT` |

### What actually moves the needle

Ablation on an identical split with fixed hyperparameters, 16,600 test rows:

| Feature set | Test MAE | vs base |
|---|---|---|
| base rolling/context (25) | 6.059 | — |
| + opponent strength (30) | 6.028 | +0.031 (t=6.2) |
| + teammates out (26) | 5.912 | +0.147 (t=14.5) |
| + both (31) | 5.880 | +0.180 (t=15.8) |

**Opponent strength is statistically real and practically negligible** — 0.03
PRA on a stat averaging ~30, ranking 9th by importance. It is retained because
it costs nothing to compute, not because it earns its keep.

**Missing teammates is the signal that matters.** When a rotation player sits,
his minutes and usage redistribute. Across four seasons, players in the top
quintile of absent-teammate minutes beat their own 10-game form by **+2.2 PRA**
while the bottom quintile fell **1.5 short** — a 3.7 PRA spread.

`PRA_L10` still carries ~0.5 of total importance. The model is fundamentally a
smarter rolling average, which is why the naive baseline is hard to beat and why
further tuning is unlikely to help. Real gains need new *signal*, not new
hyperparameters.

### Leakage control

Every historical feature is shifted one game, so a row never sees its own result.
This is the easiest thing in the project to get wrong and the hardest to notice,
so it is verified rather than asserted: opponent ratings were checked against an
independent recomputation across **2,614 team-games with zero mismatches**, and
the absence calculation was checked against a straightforward per-game loop
(correlation **1.0000**, while running ~0.3s instead of minutes).

The train/val/test split is **chronological across the whole league**, not inside
each player's log. Per-player splitting lets the model train on games occurring
after ones it is tested on for a *different* player, which flatters the score.

### The one honest caveat

Training measures absence as **"did not play"** — only knowable after tip-off.
In production the job must substitute the **injury report**, restricted to
Out/Doubtful to stay conservative (`absence_from_injuries`).

That proxy is correlated but noisier: Questionable players often suit up, late
scratches never appear. **So the production gain is smaller than +0.18 PRA, and
it cannot be backtested** — ESPN serves only the current injury report, with no
history. Treat +0.18 as an upper bound.

The only way to learn the real number is to start logging the daily injury
report now and backtest in a few months against what accumulates.

### Prediction mechanics

The model predicts a **single PRA scalar**. The PTS/REB/AST shown in the UI are
that total split by the player's season ratios — they are derived, not
independently forecast. Splitting into three models is the largest remaining
modelling improvement available.

`make_prediction` builds the feature row for **tonight's** game: `IS_HOME` and
`DAYS_REST` come from the schedule, and opponent strength and absent minutes are
overridden with tonight's values rather than inherited from whoever the player
last faced.

---

## 7. The snapshot

A single SQLite file, ~9 MB.

| Table | Rows | Contents |
|---|---|---|
| `meta` | 8 | `built_at`, `schema_version`, `source_years`, `parquet_max_game_date`, … |
| `players` | 687 | identity, team, jersey, headshot, `id_source` |
| `game_logs` | 56,556 | per-player game history |
| `predictions` | 612 | **the full `/players/{id}/stats` JSON payload** |
| `games` | 17 | upcoming schedule |
| `injuries` | 66 | current report |
| `team_defense` | 30 | points/rebounds/assists allowed + ranks |

**Why SQLite rather than JSON or parquet:**

- `sqlite3` is **standard library** — no pyarrow in the serving image. pyarrow is
  a 40–90 MB wheel; this is what keeps the deploy at ~21 MB.
- A request needs **one player out of ~700** — an indexed seek, not a whole-file
  parse.
- Opened `mode=ro&immutable=1`, which suppresses `-wal`/`-shm` sidecar files, so
  the containing directory never needs to be writable. That is what makes it
  safe on a read-only or ephemeral filesystem.

**Published as a GitHub Release asset, not committed.** A ~9 MB binary committed
daily would add several GB of history per year.

### Connection handling — a trap worth knowing about

`store.py` opens **one connection per thread**, not one shared connection.

FastAPI runs sync endpoints in a threadpool. A single shared `sqlite3.Connection`
is *not* safe there even with `check_same_thread=False`: concurrent statements
corrupt its internal state and surface as `"file is not a database"` — on a
perfectly good file. This was found when a page load fired `/injuries` and
`/teams/defense-ratings` simultaneously; sequential `curl` requests had all
passed. Verified fixed at 120 requests / 40-way concurrency, zero errors.

---

## 8. The API (`backend/app/`)

209 lines, down from 486. Every endpoint is an indexed read.

| Endpoint | Returns |
|---|---|
| `GET /players/search?q=` | name search |
| `GET /players/{id}/stats` | prediction, recent games, reasons, absent teammates |
| `GET /games/today`, `/games/upcoming` | schedule |
| `GET /injuries` | current report |
| `GET /teams/defense-ratings` | per-team allowed + ranks |
| `GET /teams/{id}/players` | roster |
| `GET /health` | snapshot freshness, counts, staleness |

Module layout:

- `main.py` — routes only
- `store.py` — read-only SQLite accessor, snapshot resolution, staleness
- `features.py` — `engineer_features` + feature lists, **pandas only**
- `predict.py` — prediction and stat summaries, shared with the builder

`features.py` and `predict.py` are imported by *both* the API and the builder.
That shared import is what makes "the payload the job wrote is the payload the
API would have computed" structurally true.

The API **never loads the model.** Predictions are precomputed. This is why the
serving requirements are four packages.

---

## 9. Guarantees, and how they are enforced

Two scripts exist specifically to keep the design honest. Both run in CI on
every push.

### `check_offline.py` — the load-bearing one

Severs the socket layer (`socket.socket.connect`, `create_connection`,
`getaddrinfo` all raise), then exercises every endpoint. Any residual upstream
call fails loudly instead of silently succeeding on a networked laptop.

If this ever fails, the app can no longer be hosted for free. That is the whole
argument in one test.

### `check_parity.py` — two layers, reported separately

**Layer 1 — structural invariants** (always runs, needs only the parquet):

```
PTS == 2*(FGM-FG3M) + 3*FG3M + FTM     1.0000
REB == OREB + DREB                     1.0000
FGM <= FGA                             1.0000
distinct teams (All-Star removed)      30
teams per game == 2                    min=2 max=2
regular-season games per team ~82      min=82 max=83
home share of rows ~0.50               0.5019
GAME_DATE in nba_api format            0 bad
WL in {W,L}                            0 bad
```

**Layer 2 — direct diff against live `nba_api`** (best effort). This compares
our translated rows against what the NBA itself returns for the same player.

**It currently reports `INCONCLUSIVE`, not `PASSED`,** because `stats.nba.com`
does not respond (§1). A skipped check is not a passed check, and the script says
so deliberately — otherwise it would read as "cross-validated against the
official source" when no comparison happened. Pass `--require-live` to make
unreachability a hard failure.

What layer 2 would catch that layer 1 cannot: a *systematic* disagreement between
ESPN's box scores and the NBA's official record — a rebound credited differently,
a minutes rounding convention. Layer 1 proves internal consistency; layer 2 would
prove agreement with the source of truth. Practical risk is low (it is the same
underlying game data) but low risk is not verification.

To close it: run `python scripts/check_parity.py --require-live` from a network
the NBA does not block, or add an independent third source such as
Basketball-Reference for a subset of players.

### CI guard on serving weight

CI asserts that importing `app.main` pulls in **none** of pandas, numpy, sklearn,
scipy, xgboost, nba_api, pyarrow or joblib. That is what holds the deployed image
near 21 MB rather than ~400 MB.

---

## 10. Running it

### Local (the normal case)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements-data.txt    # serving deps + the job's extras
python scripts/build_snapshot.py        # builds data/snapshot.db, ~15s
uvicorn app.main:app --reload --port 8000
```

```bash
npm install && npm run dev              # http://localhost:3000
```

`requirements.txt` alone suffices to *serve* an existing snapshot;
`requirements-data.txt` adds what is needed to *build* one.

Local is a first-class mode, not a degraded one — the snapshot design means the
app behaves identically with or without a deployment, and without a cold start.

### Deployed (optional)

Backend on Render free tier via `render.yaml`, frontend on Vercel. Set
`CORS_ORIGINS` on the backend and `NEXT_PUBLIC_API_URL` on the frontend. Render's
blocked IP is irrelevant because the API makes no upstream calls; the only real
cost is a ~1 minute cold start after 15 minutes idle.

**Run the "Refresh data snapshot" workflow once manually before the first
deploy** — the backend downloads from a release that does not exist until then.

### Retraining

```bash
python scripts/train_model.py --seasons 4 --with-opponent --with-absence \
  --out models/pra_model_candidate.pkl
```

Promote by replacing `models/pra_model.pkl`, then rebuild the snapshot. Previous
models are kept (`pra_model_v1_ridge.pkl`, `pra_model_v2_xgb.pkl`) for comparison.

The builder only computes a feature history when the loaded model's
`feature_cols` actually asks for it, so an older pickle keeps working untouched.

### Automation

| Workflow | Trigger | Does |
|---|---|---|
| `refresh-data.yml` | daily 06:30 UTC + manual | rebuild snapshot, publish release asset |
| `train-model.yml` | monthly + manual | train a candidate, upload artifact (does **not** auto-publish) |
| `ci.yml` | every push / PR | build a real snapshot, run both check scripts, guard serving weight, `tsc` + `next build` |

Scheduled workflows only run from the **default branch**.

---

## 11. Known limitations

- **Freshness ceiling.** Bulk data publishes once daily, so last night's games
  appear the next morning. Fine for predicting tonight; the header shows
  "data · <date>" and flips to "stale data" past the threshold rather than
  implying live.
- **Live parity unverified** (§9).
- **Absence proxy unmeasured in production** (§6).
- **PTS/REB/AST are derived**, not independently predicted (§6).
- **Third-party upstream.** If sportsdataverse stops publishing, the app degrades
  to stale data rather than breaking. ESPN's gamelog endpoint is an independent
  fallback.
- **Python 3.9**, which is EOL. CI is pinned to match the local runtime so model
  pickles round-trip.
- **Offseason artifacts.** `_compute_reasons` measures rest from today rather
  than the next scheduled game, so it reads "152 days rest" in September.
  Correct in-season.
- **Git history still contains the removed virtualenv** (~68 MB clone). Only
  fixable by rewriting history.

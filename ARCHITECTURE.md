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
prediction still has a matchup across an off day or the All-Star break. Today's
injury report is also archived permanently (§6) — ESPN keeps no history, so a
report not saved when fetched is gone.

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

**Current: three XGBoost models — points, rebounds, assists — on 31 features,
~705 players / ~110k player-games.** PRA is their sum.

| target | test MAE | L5 baseline | gain |
|---|---|---|---|
| PTS | 4.49 | 4.90 | +0.41 |
| REB | 1.87 | 2.03 | +0.16 |
| AST | 1.34 | 1.38 | +0.05 |
| **PRA** (sum) | **5.88** | **6.45** | **+0.57** |

A dedicated PRA model was trained alongside purely to settle how the total
should be produced. Summing the three components scored 5.879 against 5.881 for
the direct model — indistinguishable — so the sum wins, because a headline PRA
that disagrees with the three numbers printed beside it would have to earn that
inconsistency, and it cannot.

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
further tuning is unlikely to help.

### Shot-location quality (opt-in, `--with-shots`)

Built and measured, **not shipped by default**. The idea is sound: `PTS_L5`
conflates how good a player's shots are (stable) with whether they went in
(noisy), and scoring shots by where they were taken separates the two. In
isolation the signal is strong — expected points beats actual recent points at
predicting the next game (MAE 4.32 vs 4.43), and players shooting far above
their shot quality regress ~2 points while those below bounce back ~1.9.

The model agrees it is informative: `SHOT_EXP_PTS_L10` becomes the **second most
important feature** in the points model (0.142, against `PTS_L5` at 0.039).

But against the actual shipped pipeline it is worth little:

| | PRA MAE |
|---|---|
| shipped (31 features) | 5.8790 |
| + shot quality (36 features) | 5.8641 |
| | **+0.0149 (t=2.70)** |

Points — the stat it targets — improves by only 0.007 (t=1.5, not significant).

**A measurement lesson worth recording.** A first ablation at *fixed*
hyperparameters showed +0.076 (t=10.4), five times the real figure. Tuning the
31-feature model closed most of that gap: the shot features were largely
compensating for a weaker baseline, not adding independent information.
Feature-set comparisons must be made against a pipeline tuned the same way the
production one is, or they flatter the new feature.

Not shipped because, unlike the opponent features, this is not free: it needs
~17 MB of extra downloads per build and a game-matching step (§ below) with a
0.6% miss rate, in exchange for a gain in the same "real but invisible" bucket
as opponent strength.

**Matching NBA shot data to ESPN box scores.** NBA game ids are not
chronological — game `0022500009` is Christmas Day — so they cannot be ordered
into dates, and the only sportsdataverse file carrying dates is refreshed far
less often than the shot files, which would silently stale the feature in
season. Games are instead matched on the pair of teams and each one's
field-goal points (ESPN points minus free throws), a key that is unique and
depends only on sources the daily job already refreshes: 99.4% of games matched,
100.00% of those dates agreeing with the official record.

### Datasets evaluated and rejected

- **Possessions** (`nba_stats_possessions`): true pace and per-player on-floor
  possessions. Added +0.014 on top of shot features (t=4.0) but was
  *significantly harmful on its own* (−0.017), and the file is refreshed far
  less often than the shot data, so it would go stale in season.
- **Lineups** (`nba_stats_game_lineups`): per-action five-man units. The natural
  feature — how much a player's usual lineup partners are on the floor —
  requires a pair self-join of 1.4 billion rows per season, and overlaps
  `TEAM_MIN_ABSENT`, which already captures availability at +0.147.

Real gains need new *signal*, and the box score may simply be close to
exhausted: three separate attempts (opponent strength, per-stat models, shot
quality) each landed between +0.01 and +0.03 PRA.

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

**This is now being measured.** The daily job archives the injury report to
`backend/data/injuries/YYYY-MM-DDTHH.json` (UTC), recording both the raw report
and `team_absent_minutes` — the exact feature value fed to the model, not a
reconstruction. Archiving started 2026-10-01.

The job runs **twice daily** (~06:30 and ~22:30 UTC) and the two captures differ
in kind: the evening one is taken shortly before tip-off, once questionable
players have been ruled in or out. That also means the evening rebuild serves
*better predictions*, since `TEAM_MIN_ABSENT` is refreshed with near-final
information rather than the small hours' guesswork.

After roughly 40–60 game days, retraining with the *logged predicted* absence in
place of the actual absence gives the feature's true production value, replacing
the +0.18 upper bound with a real number. `backend/data/injuries/README.md` has
the procedure.

One immutable file per capture rather than one growing file: git stores a new
blob for every version of a file it sees, so appending to a single JSONL would
re-store the whole history on every run (~1.4 GB/year at two runs a day) instead
of ~16 KB.

### Prediction mechanics

Each stat is predicted by its own model. PRA is the sum, so the headline figure
is always exactly the three component numbers added together.

**Honest note on what that bought.** Splitting into three models was expected to
be a significant accuracy win. Measured against the old approach — predict PRA,
then split by the player's season ratios — it was not:

| stat | ratio-split | dedicated model | gain |
|---|---|---|---|
| PTS | 4.500 | 4.493 | +0.008 (t=1, not significant) |
| REB | 1.885 | 1.869 | +0.017 (0.9%, t=4) |
| AST | 1.345 | 1.336 | +0.010 (0.7%, t=3) |

The ratio split was already close to optimal, because a player's scoring /
rebounding / assist mix is genuinely stable game to game, and the PRA model
already captured the overall level. The split is kept for three reasons that are
not accuracy:

1. **Per-stat error bars become possible.** Under the ratio split there was no
   independent error figure for points — only the PRA error, which says nothing
   about how far off an individual line might be. The UI now shows `± 4.5` on a
   points projection and flags "within margin of error" when the gap to the line
   is inside half of it.
2. **The product stops claiming something untrue.** The three numbers are now
   forecasts rather than a single number cut into shares.
3. **Stat-specific signal becomes exploitable.** `OPP_REB_ALLOWED` can only ever
   help a rebounds model; under the ratio split it had nowhere to act.

PRA accuracy is unchanged either way, so none of this costs anything.

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

**Layer 2 — agreement with the NBA's own record.**

This compares every player's season totals against the league's published
figures:

```
players compared                      506
games played agree                    95.8%
PTS totals identical (matched gp)     100.00%
REB totals identical (matched gp)     100.00%
AST totals identical (matched gp)     100.00%
```

Season totals are an exacting test despite being aggregates — one mis-parsed or
duplicated box-score row shifts a player's total and shows up immediately. Zero
players disagree.

This check previously called `stats.nba.com` directly and **could never
complete**, because the NBA blocks us (§1); it reported `INCONCLUSIVE` rather
than pretending to pass. The resolution is that the NBA's *data* is reachable
even though its *servers* are not: sportsdataverse republishes stats.nba.com
season totals as parquet on GitHub Releases
(`nba_stats_player_season_stats`). Same source of truth, no blocked host — and
full league coverage instead of the three-player spot check the live version
attempted.

**The 4.2% where games played disagree is expected, not a defect.** ESPN counts
the NBA Cup championship game as a regular-season game and the NBA does not. In
2025-26 that is NYK and SAS, who show 83 games to the league's 82, shifting the
season totals of everyone on those two rosters. This is also why the invariant
above allows 82–83 games per team. The gate therefore requires exact agreement
only among players whose games-played matches — where it demands 100%, with no
tolerance.

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

Two configurations are committed. **Vercel-only** (`vercel.json`) runs the
frontend and the FastAPI backend as two [Services](https://vercel.com/docs/services)
on one domain — cold starts in seconds, and no CORS because both halves share an
origin. **Vercel + Render** (`render.yaml`) splits them; Render's free tier
sleeps after 15 minutes and takes about a minute to wake.

The Vercel path needs one deliberate piece of glue. Vercel routes `/api/(.*)` to
the backend service but passes the **original** path through, so `/api/health`
arrives as `/api/health`. `backend/vercel_app.py` strips that prefix at the ASGI
boundary rather than prefixing every route, which keeps the routes identical on
Vercel, on Render and locally. Mounting the app under a parent FastAPI instance
would be the obvious alternative and is wrong here: Starlette does not propagate
lifespan events into mounted sub-applications, so the snapshot would never load.

`store._db()` also loads the snapshot on first use if it is not already loaded.
The lifespan handler normally does it, but not every serverless adapter runs
ASGI lifespan events, and the failure mode without this is an otherwise healthy
deployment reporting "no data" on every request.

Vercel's Python runtime supports 3.12 and newer only. The serving requirements
install cleanly there because they contain no numpy — the same split that keeps
the deployed bundle near 21 MB is what makes this possible at all.



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
| `refresh-data.yml` | 06:30 and 22:30 UTC + manual | rebuild snapshot, archive injury report, publish release asset |
| `train-model.yml` | monthly + manual | train a candidate, upload artifact (does **not** auto-publish) |
| `ci.yml` | every push / PR | build a real snapshot, run both check scripts, guard serving weight, `tsc` + `next build` |

Scheduled workflows only run from the **default branch**.

---

## 11. Known limitations

- **Freshness ceiling.** Bulk data publishes once daily, so last night's games
  appear the next morning. Fine for predicting tonight; the header shows
  "data · <date>" and flips to "stale data" past the threshold rather than
  implying live.
- **Absence proxy unmeasured in production** (§6) — now accumulating the data
  needed to measure it.
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

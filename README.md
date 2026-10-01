# NBA PRA Predictor

Predicts a player's **P**oints + **R**ebounds + **A**ssists for their next game,
using a model trained on four seasons of box scores. Next.js frontend, FastAPI
backend, and a scheduled job that rebuilds the data once a day.

For how the whole thing fits together and why, see **[ARCHITECTURE.md](ARCHITECTURE.md)**.

## Why it works the way it does

The obvious design — call the NBA's stats API when a user asks for a player — does
not survive contact with reality. `stats.nba.com` rate-limits aggressively and
**blocks datacenter IP ranges** (AWS, GCP, Azure, Render, Vercel), so an app that
scrapes on demand is slow locally and simply cannot be deployed on a free host.

So nothing is fetched at request time. A daily job does all the work offline and
writes one SQLite snapshot; the API only reads it. That makes the request path
fast, impossible to rate-limit, and free to host anywhere.

All data sources are free and need no API key:

| Source | Used for |
|---|---|
| [sportsdataverse bulk box scores](https://github.com/sportsdataverse/sportsdataverse-data) | Every player-game back to 2002, refreshed daily. ~0.6 MB per season. |
| ESPN public JSON feeds | Today's schedule, injury report. |

## Architecture

```
GitHub Actions (daily 06:30 UTC)
  └─ scripts/build_snapshot.py
       ├─ downloads bulk parquet          (free, no key, no IP block)
       ├─ maps ESPN ids -> nba_api ids
       ├─ runs the model for every player
       └─ writes snapshot.db  ──published as a GitHub Release asset──┐
                                                                     │
Render (free tier)                                                   │
  └─ FastAPI ── downloads snapshot at startup ◄──────────────────────┘
       └─ serves every endpoint from indexed SQLite reads, zero upstream calls

Vercel (free tier)
  └─ Next.js frontend ──► FastAPI
```

## Running locally

**Backend** (Python 3.9+):

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements-data.txt      # serving deps + the data job's extras
python scripts/build_snapshot.py          # builds data/snapshot.db, ~15s
uvicorn app.main:app --reload --port 8000
```

`requirements.txt` alone is enough to *serve* an existing snapshot;
`requirements-data.txt` adds what's needed to *build* one (pyarrow, xgboost, nba_api).

**Frontend:**

```bash
npm install
npm run dev
```

Then open http://localhost:3000. `.env.local` should contain:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Retraining

```bash
cd backend
python scripts/train_model.py --seasons 4 --out models/pra_model_candidate.pkl
```

Compares Ridge, RandomForest and XGBoost on a chronological validation split and
keeps the winner — so the saved artifact is not necessarily XGBoost. Check
`model_type` in the pickle. Promote a candidate by replacing
`models/pra_model.pkl`, then rebuild the snapshot.

Current model: **three XGBoost models** (points, rebounds, assists), 31 features,
~705 players / ~110k player-games. PRA is their sum.

| target | test MAE | L5 baseline |
|---|---|---|
| PTS | 4.49 | 4.90 |
| REB | 1.87 | 2.03 |
| AST | 1.34 | 1.38 |
| **PRA** (sum) | **5.88** | **6.45** |

Summing the three matches a dedicated PRA model (5.879 vs 5.881), so the split
costs nothing in total accuracy while keeping the headline consistent with its
own components.

Feature-set ablation, identical split and hyperparameters, 16,600 test rows:

| features | test MAE | vs base |
|---|---|---|
| base rolling/context (25) | 6.059 | — |
| + opponent strength (30) | 6.028 | +0.031 (t=6.2) |
| + teammates out (26) | 5.912 | +0.147 (t=14.5) |
| + both (31) | 5.880 | +0.180 (t=15.8) |

Opponent strength is statistically real but practically negligible. Missing
teammates is the signal that matters: players in the top quintile of absent
teammate minutes beat their own 10-game form by +2.2 PRA, the bottom quintile
by −1.5.

**Caveat on that number.** Training measures absence as "did not play", which is
only knowable after tip-off. In production the daily job substitutes the injury
report (Out/Doubtful only), which is noisier, so the real-world gain is smaller
than +0.18.

It could not be backtested, because ESPN serves only the current report. So the
job now archives one to `backend/data/injuries/` twice a day — morning and
shortly before tip-off — including the exact feature value given to the model.
After a few months that becomes measurable; see
`backend/data/injuries/README.md`.

The evening run is not just logging: it rebuilds the snapshot with near-final
injury information, so tonight's predictions use a better `TEAM_MIN_ABSENT` than
the small-hours run could produce.

## Verification scripts

```bash
python scripts/check_offline.py    # proves no endpoint makes a network call
python scripts/check_parity.py     # proves the bulk data matches nba_api
```

`check_offline.py` severs the socket layer and then exercises every endpoint. It
is the guarantee the whole design rests on — if it fails, the app can no longer
be hosted for free.

Both run in CI on every push and pull request (`.github/workflows/ci.yml`),
along with a check that `app.main` still imports none of the training stack.

## Layout

```
src/                        Next.js app router frontend
backend/
  app/
    main.py                 FastAPI routes — snapshot reads only
    store.py                read-only SQLite accessor
    features.py             feature engineering (shared by train + serve)
    predict.py              prediction + stat summaries (shared)
  scripts/
    build_snapshot.py       the daily job
    parquet_source.py       downloads/caches the bulk files
    espn_adapter.py         bulk box scores -> nba_api column shape
    espn_live.py            ESPN schedule + injuries
    id_map.py               ESPN athlete id -> nba_api player id
    train_model.py          training pipeline
    check_offline.py        no-network proof
    check_parity.py         data-source parity gate
    fetch_data.py           legacy nba_api scraper, no longer on any code path
```

## Deploying

`render.yaml` describes the backend service. Set `CORS_ORIGINS` to the deployed
frontend's origin and `NEXT_PUBLIC_API_URL` on Vercel to the Render URL. Both
free tiers suffice; the only cost is Render's ~1 minute cold start after 15
minutes of inactivity.

**Run the data workflow before the first deploy.** The backend downloads its
snapshot from the `data-snapshot` release, and that release does not exist until
the workflow has run once. Trigger it manually from the Actions tab
(*Refresh data snapshot* → *Run workflow*); otherwise the first deploy comes up
with `/health` reporting `"status": "degraded"` and no data to serve.

The snapshot is not committed to the repo — it is ~9 MB and would add several GB
of history per year — so a fresh clone has no `backend/data/snapshot.db` either.
Build one locally with `python scripts/build_snapshot.py`.

## Disclaimer

Informational and educational only. Predictions are statistical estimates, not
guarantees. Gamble responsibly.

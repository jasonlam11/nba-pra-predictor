# Injury report archive

One file per UTC day, written by `scripts/build_snapshot.py` on every run.

## Why this exists

The model's `TEAM_MIN_ABSENT` feature was trained on who **did not play**, which
is only knowable after tip-off. In production that has to be inferred from the
injury report instead, restricted to `Out` / `Doubtful`.

How much accuracy that substitution costs is **unknown and currently
unmeasurable** — ESPN serves only the *current* report and keeps no history, so
there is nothing to backtest against. The offline measurement (+0.18 PRA from
adding the feature) is therefore an upper bound, not a promise.

This archive is how that gets answered. Every day it records both the raw report
and the exact feature value fed to the model, so that after a few months of
accumulation the question becomes answerable from data you own.

## File format

`YYYY-MM-DD.json` (UTC):

```jsonc
{
  "date": "2026-10-01",
  "captured_at": "2026-10-01T06:30:12+00:00",
  "source_timestamp": "2026-10-01T06:28:41Z",   // ESPN's own timestamp
  "absent_statuses": ["doubtful", "out"],       // what counted as absent that day
  "n_entries": 66,
  "entries": [
    {
      "name": "Mouhamed Gueye",
      "team": "ATL",                            // NBA tricode, already translated
      "status": "Day-To-Day",
      "status_code": "INJURY_STATUS_DAYTODAY",  // ESPN's normalized enum
      "description": "Foot",
      "reported": "2026-07-19T00:14Z",
      "espn_id": 4712863,                       // null if not in our player table
      "expected_minutes": 10.5                  // their L10 minutes at capture time
    }
  ],
  "team_absent_minutes": { "1610612744": 60.8 } // keyed by nba_api team id
}
```

`team_absent_minutes` is the important field: it is the **actual model input**
for that day, not a reconstruction. Recomputing it later would mean rebuilding
rolling minute averages as of each historical date.

A day with no entries is never written — a failed fetch must not be
indistinguishable from "nobody was injured".

Note ESPN does not populate `athlete.id` in this feed, so `espn_id` is resolved
by name against the player table and will be `null` for players who have not
appeared in a box score yet.

## Backtesting, once enough days accumulate

Roughly 40–60 game days is enough for a first look.

1. For each archived day, take `team_absent_minutes` — the **predicted** absence.
2. From the bulk box scores for that date, compute `team_absence_history` — the
   **actual** absence (who really did not play).
3. Compare them. Correlation and bias answer "how good is the injury report as a
   proxy?" If the report systematically under-reports absence, the model is
   seeing a shifted feature in production versus training, which is worth
   correcting with a scaling factor.
4. Then the real question: retrain with the *logged predicted* values in place of
   the actual ones, and measure test MAE. That number is the feature's true
   production value — the one the +0.18 upper bound stands in for today.

Step 4 is the point of all this. Steps 1–3 are diagnostics.

# Injury report archive

One file per capture, written by `scripts/build_snapshot.py` on every run.
The daily job runs **twice**: ~06:30 UTC and ~22:30 UTC.

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

`YYYY-MM-DDTHH.json` — UTC date and hour of capture:

```jsonc
{
  "date": "2026-10-01",
  "captured_hour_utc": 6,                       // 6 = morning run, 22 = evening
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

A capture with no entries is never written — a failed fetch must not be
indistinguishable from "nobody was injured". Expect gaps.

## Why two captures a day

They are not duplicates. The 06:30 run is taken ~16 hours before tip-off; the
22:30 run lands shortly before the evening games, by which point most
questionable players have been ruled in or out.

That difference is itself a finding. The evening report is roughly what a bettor
actually has at decision time, so it is the honest input to evaluate the model
against. The morning/evening gap measures how much of the absence signal is
genuinely knowable in advance versus only resolved at the last minute — which is
the real reason the production gain is expected to fall short of the +0.18 PRA
upper bound.

Note ESPN does not populate `athlete.id` in this feed, so `espn_id` is resolved
by name against the player table and will be `null` for players who have not
appeared in a box score yet.

## Backtesting, once enough days accumulate

Roughly 40–60 game days is enough for a first look.

1. For each archived capture, take `team_absent_minutes` — the **predicted**
   absence. Prefer the evening (hour 22) capture per day: it is closest to tip-off
   and closest to what a user would actually be acting on.
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

A fifth check is now possible with paired captures: run step 3 separately for the
morning and evening files. If evening tracks actual absence much better than
morning does, the model should be fed the latest available report rather than a
fixed-time one — and the snapshot should be rebuilt as late as practical before
tip-off, which is already why the evening run exists.

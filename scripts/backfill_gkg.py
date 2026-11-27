"""Backfill historical GDELT GKG days into trust.db, time-budgeted.

One day at a time, OLDEST missing day first, commit per day, stop when the
time budget runs out. Safe to re-run: INSERT OR REPLACE everywhere, and days
already present in timeline_daily are skipped. GKG archive verified back to
at least 2025-11 (2026-11-26); GDELT 2.0 files start 2015-02.

Backfilled days carry media + business lenses only (HN/Bluesky/Reddit are
live-only sources) — the dashboard method note states this.

Run:
  python3 scripts/backfill_gkg.py --from 2026-08-28 --to 2026-11-25
  python3 scripts/backfill_gkg.py --from 2026-08-28 --budget-min 300
"""
import sys, os, datetime, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import store
from daily_update import run, DB

def days_between(a, b):
    d0, d1 = datetime.date.fromisoformat(a), datetime.date.fromisoformat(b)
    return [(d0 + datetime.timedelta(days=i)).isoformat()
            for i in range((d1 - d0).days + 1)]

def backfill(from_day, to_day=None, budget_min=300, force=False):
    to_day = to_day or (datetime.datetime.now(datetime.UTC).date() -
                        datetime.timedelta(days=1)).isoformat()
    t0 = time.time()
    if force:
        # Re-run EVERY day in range (e.g. after a term-list or scoring fix).
        # Oldest-first keeps each day's 7-day company window correct: the
        # preceding 6 days have already been refreshed when day d runs.
        todo = days_between(from_day, to_day)
        print(f"backfill FORCE: {from_day}..{to_day} | re-running all "
              f"{len(todo)} days")
    else:
        con = store.connect(DB)
        have = {r[0] for r in con.execute(
            "SELECT t.day FROM timeline_daily t JOIN series s ON s.day = t.day "
            "WHERE t.source='gdelt'")}   # require both: an interrupted day is redone
        con.close()
        todo = [d for d in days_between(from_day, to_day) if d not in have]
        print(f"backfill: {from_day}..{to_day} | {len(todo)} days to do "
              f"({len(days_between(from_day, to_day)) - len(todo)} already present)")
    done = 0
    for d in todo:
        if time.time() - t0 > budget_min * 60:
            print(f"budget exhausted after {done} days — re-run to continue")
            break
        print(f"== {d} ==")
        run(day=d, gkg_hours=24,
            gkg_end=(datetime.date.fromisoformat(d) +
                     datetime.timedelta(days=1)).isoformat() + "T00:00:00",
            only_gdelt=True)
        done += 1
    print(f"backfill pass complete: {done} days processed in "
          f"{(time.time() - t0) / 60:.0f} min")

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--from" not in args:
        sys.exit("usage: backfill_gkg.py --from YYYY-MM-DD [--to YYYY-MM-DD] "
                 "[--budget-min N] [--force]")
    kw = {"from_day": args[args.index("--from") + 1]}
    if "--to" in args:
        kw["to_day"] = args[args.index("--to") + 1]
    if "--budget-min" in args:
        kw["budget_min"] = int(args[args.index("--budget-min") + 1])
    if "--force" in args:
        kw["force"] = True
    backfill(**kw)

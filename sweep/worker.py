"""sweep.worker — the overnight roster crawl.

Pops pending sweep_events (FiveTool + Prospect Select), scrapes the full
event roster with the PROVEN fivetool_scrape.scrape_event (both hosts run
the same platform), then:
  1. writes/refreshes the event as a shared-catalog row (is_catalog=true,
     roster JSON + schedule_url) so it appears in every program's
     New-event dropdown with one-tap schedule Refresh, and
  2. fill-if-empty upserts every rosterable fact (name/grad/state/pos/
     commit) into public_players by identity hash — the pool grows with
     every event whether or not anyone subscribed.

Politeness: scrape_event already throttles per page; the worker adds a
pause between events, a per-run event cap, and the SWEEP_PAUSE=1
kill-switch from the design. Failures mark the row failed with the error
and never loop.

Usage: python -m sweep.worker [--max N]
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fivetool_scrape  # noqa: E402  (proven FT/PS event scraper)

from . import db  # noqa: E402

BETWEEN_EVENTS_SEC = 10


def norm_name(n):
    return re.sub(r"\s+", " ", (n or "").strip())


def ihash(name, state, grad):
    """Identity hash — EXACT formula from seed_public_players.py."""
    key = f"{norm_name(name).lower()}|{(state or '').upper()}|{grad or ''}"
    return hashlib.sha256(key.encode()).hexdigest()


def pool_records(data, source):
    recs, skipped = {}, 0
    for team in data.get("teams", []):
        for p in team.get("players", []):
            name = norm_name(p.get("name"))
            state = (p.get("state") or "").strip().upper()[:2]
            grad = str(p.get("grad") or "").strip()
            if not name or not grad or not state:
                skipped += 1          # unhashable-to-tenants = useless to tenants
                continue
            h = ihash(name, state, grad)
            rec = recs.get(h) or {
                "identity_hash": h, "name": name,
                "grad_year": int(grad) if grad.isdigit() else None,
                "state": state, "position": "", "commit": "", "sources": {},
            }
            if p.get("pos") and not rec["position"]:
                rec["position"] = str(p["pos"]).strip()
                rec["sources"]["position"] = source
            if p.get("commit") and not rec["commit"]:
                rec["commit"] = str(p["commit"]).strip()
                rec["sources"]["commit"] = source
            recs[h] = rec
    return list(recs.values()), skipped


def crawl_one(conn, row):
    url = row["url"]
    data = fivetool_scrape.scrape_event(url)
    name = data.get("event") or row.get("name") or url
    if name == "Event":                       # the known blank-title quirk
        name = row.get("name") or url
    roster_json = json.dumps(data, separators=(",", ":"))
    db.upsert_catalog_event(conn, name, roster_json, url)
    recs, skipped = pool_records(data, row["source"])
    n_pool = db.upsert_pool(conn, recs)
    stats = {"teams": len(data.get("teams", [])),
             "players": sum(len(t.get("players", [])) for t in data.get("teams", [])),
             "pool_upserts": n_pool, "unhashable": skipped}
    db.finish(conn, row["id"], True, stats=stats)
    print(f"done {row['source']}:{row['source_key']} — {name}: {stats}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=int(os.environ.get("SWEEP_MAX_EVENTS", 8)))
    args = ap.parse_args()
    conn = db.connect()
    n = 0
    while n < args.max:
        if os.environ.get("SWEEP_PAUSE") == "1":
            print("SWEEP_PAUSE=1 — stopping between events")
            break
        row = db.pop_pending(conn, ["fivetool", "ps"])
        if not row:
            print("queue empty")
            break
        print(f"crawling {row['source']}:{row['source_key']} ({row['url']})")
        try:
            crawl_one(conn, row)
        except Exception as e:
            conn.rollback()
            db.finish(conn, row["id"], False, error=str(e))
            print(f"FAILED {row['source']}:{row['source_key']}: {e}")
        n += 1
        time.sleep(BETWEEN_EVENTS_SEC)
    print(f"worker done — {n} event(s) processed")


if __name__ == "__main__":
    main()

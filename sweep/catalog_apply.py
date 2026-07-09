"""sweep.catalog_apply — push a roster JSON from the repo into the shared
catalog (and its kids into the pool) over SWEEP_DB_URL. This is the
"Claude runs it" lane for sources the sweep can't crawl yet (PG scrapes
from the extension, emailed PDFs turned to JSON): commit the file, dispatch
the Catalog apply workflow, done — no SQL editor, no copy-paste courier.

Usage: python -m sweep.catalog_apply --file data/catalog/x.json
         [--name "Event Name"] [--schedule-url URL] [--location "City, ST"]
"""
import argparse
import json

from . import db
from .worker import pool_records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--name", default="")
    ap.add_argument("--schedule-url", default="")
    ap.add_argument("--location", default="")
    args = ap.parse_args()

    data = json.load(open(args.file))
    name = args.name or data.get("event") or ""
    if not name or name == "Event":
        raise SystemExit("event name missing — pass --name")
    sched = args.schedule_url or data.get("url") or ""
    conn = db.connect()
    db.upsert_catalog_event(conn, name, json.dumps(data, separators=(",", ":")), sched, args.location)
    recs, skipped = pool_records(data, data.get("site") or "manual")
    n = db.upsert_pool(conn, recs)
    teams = len(data.get("teams", []))
    players = sum(len(t.get("players", [])) for t in data.get("teams", []))
    print(f"catalog: '{name}' upserted — {teams} teams, {players} players; "
          f"pool: {n} upserts ({skipped} unhashable)")


if __name__ == "__main__":
    main()

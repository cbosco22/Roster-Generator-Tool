#!/usr/bin/env python3
"""
sync_player_evals.py — project Event Day player evals into Recruiting
Sheet 2.0 (Chris 2026-07-06: "add a note on a single kid that then goes
into our system... if anything adjusts for a kid, append that he was seen
at that event").

Event Day's player card writes rating changes + notes to Supabase
player_evals immediately (durable, phone-first). This script flushes
unsynced rows into the sheet through the SAME proven path as post-event
writes: db_loader's locked fuzzy match, build_upsert_op (Seen append with
dedupe + tier only-if-changed), build_note_update_op (stamped, additive
notes), post_ops_chunked (op_id idempotency, per-op quarantine, never
blind-retry a real write). Rows are stamped synced_at ONLY for ops the
server reported applied cleanly; everything else stays unsynced and is
safe to re-flush.

DRY-RUN BY DEFAULT — pass --send for the real write. Run it manually
(post-event or evening), never on a timer during coach hours.

Same-flush collision handling (why evals are GROUPED per player before
building ops): build_upsert_op/build_note_update_op read the xlsx snapshot,
so two ops touching the same player's Seen or Notes in one batch would
each build from the same stale prior and the second would clobber the
first. One upsert op + at most one note op per player per flush instead:
tier = the LATEST rated eval (newest opinion wins), notes are merged
chronologically into one stamped block, Seen gets every new event of the
group appended once.

Usage:
  python3 sync_player_evals.py                # dry run (validation only)
  python3 sync_player_evals.py --send         # real write + synced_at stamps
  python3 sync_player_evals.py --xlsx data/recruiting.xlsx   # skip re-fetch
Sheet webapp creds: --url/--token, else SHEET_WRITE_URL/SHEET_WRITE_TOKEN
env vars, else .streamlit/secrets.toml (same values app.py uses).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests

import db_loader
import sheet_sync
import sheet_write

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://bcdoidnfbrsfeulyhwhi.supabase.co")


def _anon_key():
    key = os.environ.get("SUPABASE_ANON_KEY")
    if key:
        return key
    try:  # same baked-in public anon key push_event.py ships
        from push_event import SUPABASE_ANON_KEY as k
        return k
    except Exception:
        sys.exit("Set SUPABASE_ANON_KEY (public anon key).")


def _sheet_creds(args):
    url = args.url or os.environ.get("SHEET_WRITE_URL")
    token = args.token or os.environ.get("SHEET_WRITE_TOKEN")
    if url and token:
        return url, token
    try:  # fall back to the Streamlit secrets the app itself uses
        import tomllib
        with open(os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml"), "rb") as f:
            sec = tomllib.load(f)
        return (url or sec.get("sheet_write_url"), token or sec.get("sheet_write_token"))
    except Exception:
        return url, token


def _sb(method, path, key, **kw):
    r = requests.request(method, SUPABASE_URL.rstrip("/") + "/rest/v1" + path,
                         headers={"apikey": key, "Authorization": "Bearer " + key,
                                  "Content-Type": "application/json",
                                  "Prefer": "return=minimal"},
                         timeout=30, **kw)
    r.raise_for_status()
    return r


def fetch_unsynced(key):
    r = requests.get(SUPABASE_URL.rstrip("/") + "/rest/v1/player_evals",
                     params={"synced_at": "is.null", "order": "created_at.asc",
                             "select": "*"},
                     headers={"apikey": key, "Authorization": "Bearer " + key},
                     timeout=30)
    r.raise_for_status()
    return r.json()


def group_evals(evals):
    """Group by player identity (name|state|grad) preserving eval order."""
    groups = {}
    for e in evals:
        k = (e["player_name"].strip().lower(),
             (e.get("state") or "").strip().upper(),
             str(e.get("grad") or "").strip())
        groups.setdefault(k, []).append(e)
    return list(groups.values())


def _merge_note_text(group):
    """One stamped-block payload per player: 'Event — XX: note' per line."""
    lines = []
    for e in group:
        if not e.get("note"):
            continue
        tag = " — ".join(x for x in [e.get("event_name"), e.get("by_initials")] if x)
        lines.append(f"{tag}: {e['note']}" if tag else e["note"])
    return "\n".join(lines)


def _extend_seen(op, cols, extra_events):
    """Append the group's ADDITIONAL events to the op's Seen field, with the
    same already-most-recent dedupe build_upsert_op applies to the first."""
    seen_col = cols["seen"]
    if seen_col not in op["fields"]:
        return
    chain = [s.strip() for s in op["fields"][seen_col].split(",") if s.strip()]
    for ev in extra_events:
        if ev and (not chain or chain[-1] != ev):
            chain.append(ev)
    op["fields"][seen_col] = ", ".join(chain)


def build_ops(evals, db, cols):
    """Returns [(op, [eval_ids])...] — ids stamped synced only if their op applies."""
    out = []
    for group in group_evals(evals):
        first_ev = group[0]
        name_parts = first_ev["player_name"].strip().split()
        first, last = name_parts[0], " ".join(name_parts[1:])
        tiers = [e["new_tier"] for e in group if e.get("new_tier")]
        new_tier = tiers[-1] if tiers else None      # latest opinion wins
        events = []
        for e in group:
            if e.get("event_name") and e["event_name"] not in events:
                events.append(e["event_name"])
        note_text = _merge_note_text(group)
        ids = [e["id"] for e in group]

        existing = db_loader.lookup(db, first_ev["player_name"])
        if existing:
            op = sheet_write.build_upsert_op(
                db, cols, first=first, last=last,
                event_name=events[0] if events else "",
                new_tier=new_tier,
                state=first_ev.get("state") or None, hs=first_ev.get("hs") or None,
                team=first_ev.get("team") or None, pos=first_ev.get("pos") or None,
                class_year=str(first_ev.get("grad") or "") or None,
                by_initials=first_ev.get("by_initials") or None)
            _extend_seen(op, cols, events[1:])
            note_op = sheet_write.build_note_update_op(existing, cols, note_text) if note_text else None
            # ids ride ONE op of the group; flush() stamps them only when
            # every op for that player landed (upsert AND note)
            out.append((op, ids))
            if note_op:
                out.append((note_op, []))
        else:
            stamped = "\n".join(f"[{sheet_write.today_str()}] {ln}"
                                for ln in note_text.split("\n")) if note_text else None
            op = sheet_write.build_upsert_op(
                db, cols, first=first, last=last,
                event_name=events[0] if events else "",
                new_tier=new_tier,
                state=first_ev.get("state") or None, hs=first_ev.get("hs") or None,
                team=first_ev.get("team") or None, pos=first_ev.get("pos") or None,
                class_year=str(first_ev.get("grad") or "") or None,
                by_initials=first_ev.get("by_initials") or None,
                notes=stamped)
            _extend_seen(op, cols, events[1:])
            out.append((op, ids))
    return out


def flush(args):
    key = _anon_key()
    evals = fetch_unsynced(key)
    if not evals:
        print("No unsynced player evals. Nothing to do.")
        return 0
    print(f"{len(evals)} unsynced eval(s) across "
          f"{len(group_evals(evals))} player(s).")

    xlsx = args.xlsx
    if not xlsx:
        xlsx = os.path.join(os.path.dirname(__file__), "data", "recruiting.xlsx")
        print("Fetching fresh recruiting sheet…")
        sheet_sync.fetch_recruiting_xlsx(xlsx)
    cols = db_loader.find_columns(xlsx)
    db = db_loader.parse_xlsx(xlsx)

    pairs = build_ops(evals, db, cols)
    ops = [p[0] for p in pairs]
    for op, ids in pairs:
        kind = "append NEW row" if op["action"] == "append" else f"update row {op.get('row')}"
        print(f"  {op['player']}: {kind}, {len(op['fields'])} field(s)"
              + (f" -> stamps {len(ids)} eval(s)" if ids else " (paired op)"))

    url, token = _sheet_creds(args)
    if not (url and token):
        sys.exit("Missing sheet webapp creds — see --help.")

    print("\nDry-run validation…")
    check = sheet_write.post_ops_chunked(ops, url, token, dry_run=True)
    if not check["ok"]:
        print(json.dumps(check["quarantined"], indent=2))
        sys.exit("Dry run reported problems — fix before --send.")
    print(f"Dry run clean: {check['applied']}/{len(ops)} ops validate.")

    if not args.send:
        print("\nDRY RUN ONLY — rerun with --send to write the sheet.")
        return 0

    print("\nWriting to the sheet…")
    real = sheet_write.post_ops_chunked(ops, url, token, dry_run=False)
    bad_players = {q.get("player") for q in real.get("quarantined", [])}
    synced_ids = []
    for op, ids in pairs:
        # a group's evals are stamped only if EVERY op for that player
        # landed — one quarantined op (upsert OR note) leaves the whole
        # group unsynced for the next re-run (ops are op_id-idempotent,
        # so the already-applied half is skipped server-side)
        if ids and op["player"] not in bad_players:
            synced_ids.extend(ids)
    if synced_ids:
        now = datetime.now(timezone.utc).isoformat()
        _sb("PATCH", f"/player_evals?id=in.({','.join(map(str, synced_ids))})",
            key, json={"synced_at": now})
        print(f"Stamped synced_at on {len(synced_ids)} eval(s).")
    if real.get("quarantined"):
        print("\nQUARANTINED (left unsynced — safe to re-run, ops are "
              "idempotent by op_id):")
        print(json.dumps(real["quarantined"], indent=2))
        return 1
    print("All clean.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--send", action="store_true", help="real write (default: dry run)")
    ap.add_argument("--xlsx", help="use this xlsx instead of re-fetching")
    ap.add_argument("--url", help="Apps Script webapp URL")
    ap.add_argument("--token", help="Apps Script webapp token")
    sys.exit(flush(ap.parse_args()))

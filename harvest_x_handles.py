#!/usr/bin/env python3
"""
harvest_x_handles.py — overnight prep crawl (Chris 2026-07-06).

The three live-event PBR crawls (Boston / Mattingly / WWBA) finished before
the crawler learned to capture X/Twitter handles (26e7d5f, 7/5), so none of
the pbr_crawl.json files carry them. Event Day's new X links currently fall
back to an X name-search; real handles upgrade every one of them to a
deep link. This re-fetches ONLY the already-resolved profile paths from
those crawls and pulls the X handle off each page — no search step, reusing
pbr_crawler.fetch_profile() unchanged.

Read-only scrape → local files only. It does NOT touch Supabase, the
recruiting sheet, or any coach surface. Merging the harvested handles into
event rosters + pushing is a separate, deliberate step held for Chris's go
(it changes live event data during event week).

Design for an unattended overnight run:
  - Global checkpoint (data/x_harvest_checkpoint.jsonl): one line per
    profile_path processed. Resumable — rerun and it skips done paths.
  - Deduped by profile_path across all three events (a kid at two events
    is fetched once).
  - Polite: reuses the crawler's 2s throttle + honest UA. A hard block or
    a laptop sleep just pauses progress; the checkpoint keeps every page
    already fetched.
  - Emits data/x_handles.json: {identity_key: x_url} keyed name|ST|grad
    (the pool/roster merge key) plus a profile_path index, ready for a
    fast merge later.

Usage:
  python3 harvest_x_handles.py                 # all events, resumes
  python3 harvest_x_handles.py --throttle 2.5  # gentler pacing
  python3 harvest_x_handles.py --limit 200     # smoke test
"""
import argparse
import glob
import json
import os
import re
import sys
import time
import datetime as _dt

import pbr_crawler

HERE = os.path.dirname(os.path.abspath(__file__))
EVENTS_GLOB = os.path.join(HERE, "events", "*", "pbr_crawl.json")
CKPT = os.path.join(HERE, "data", "x_harvest_checkpoint.jsonl")
OUT = os.path.join(HERE, "data", "x_handles.json")


def _key(name, state, grad):
    """name|ST|grad — the identity key rosters/pool merge on."""
    nm = re.sub(r"\s+", " ", (name or "").strip())
    return f"{nm}|{(state or '').strip().upper()}|{str(grad or '').strip()}"


def load_targets():
    """Every (profile_path, name, state, grad) from the event crawls, deduped
    by profile_path. Smallest events first so a whole event completes early."""
    files = sorted(glob.glob(EVENTS_GLOB), key=lambda f: os.path.getsize(f))
    seen, targets = set(), []
    for f in files:
        try:
            d = json.load(open(f))
        except Exception as e:
            print(f"skip {f}: {e}", file=sys.stderr)
            continue
        for r in d.get("results", []):
            pp = r.get("profile_path")
            if not pp or pp in seen:
                continue
            seen.add(pp)
            q = r.get("query", {}) or {}
            targets.append({
                "profile_path": pp,
                "name": r.get("name") or q.get("name") or "",
                "state": q.get("state") or "",
                "grad": q.get("grad_year") or "",
            })
    return targets


def load_done():
    done = {}
    if os.path.exists(CKPT):
        with open(CKPT) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    done[rec["profile_path"]] = rec
                except Exception:
                    pass
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--throttle", type=float, default=pbr_crawler.THROTTLE_SEC)
    ap.add_argument("--limit", type=int, default=0, help="stop after N new fetches (smoke test)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(CKPT), exist_ok=True)
    targets = load_targets()
    done = load_done()
    todo = [t for t in targets if t["profile_path"] not in done]
    print(f"{len(targets)} unique profiles across events; "
          f"{len(done)} already harvested, {len(todo)} to go.", file=sys.stderr)

    session = pbr_crawler._session()
    ck = open(CKPT, "a")
    got = sum(1 for r in done.values() if r.get("twitter"))
    n = 0
    for t in todo:
        if args.limit and n >= args.limit:
            break
        pp = t["profile_path"]
        rec = {"profile_path": pp, "key": _key(t["name"], t["state"], t["grad"]),
               "at": _dt.datetime.now(_dt.timezone.utc).isoformat()}
        try:
            prof = pbr_crawler.fetch_profile(session, pp)
            rec["twitter"] = prof.get("twitter", "")
            rec["ok"] = True
        except Exception as e:
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {e}"
        ck.write(json.dumps(rec) + "\n")
        ck.flush()
        if rec.get("twitter"):
            got += 1
        n += 1
        if n % 50 == 0:
            print(f"[{n}/{len(todo)}] {got} handles found so far", file=sys.stderr)
        time.sleep(args.throttle)
    ck.close()

    # rebuild the merge map from the full checkpoint (done + this run)
    handles, by_path = {}, {}
    for rec in load_done().values():
        tw = rec.get("twitter")
        if tw:
            by_path[rec["profile_path"]] = tw
            if rec.get("key"):
                handles[rec["key"]] = tw
    json.dump({"handles": handles, "by_profile_path": by_path,
               "updated_at": _dt.datetime.now(_dt.timezone.utc).isoformat()},
              open(OUT, "w"), indent=1)
    print(f"DONE this run: +{n} fetched. Total {len(by_path)} X handles -> {OUT}",
          file=sys.stderr)
    print(json.dumps({"processed_this_run": n, "total_handles": len(by_path),
                      "unique_profiles": len(targets)}))


if __name__ == "__main__":
    main()

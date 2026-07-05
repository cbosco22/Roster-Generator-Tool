"""
academics.py — the persistent, multi-source academic store.

The problem Chris stated: "I really need academic info on all events."
No single source has everyone. FiveTool has ~60% (fast, direct URLs, only
FiveTool-sourced events). PBR's logged-in panel is universal (we resolve a
PBR profile for players at every event) but slower and account-mutating.
Twitter bios are rich but X can't be bulk-scraped.

The solution is not one source — it's a WATERFALL that writes into a
PERSISTENT cache keyed to the player, not the event. Once we learn a
player's GPA from ANY source at ANY event, it's attached to them forever
and appears automatically at every future event. Coverage only grows.

Cache file: data/academics.json
  { "<identity key>": {"acad": "GPA 3.8 · SAT 1280", "source": "fivetool",
                        "handle": "@Name", "updated": "2026-07-05"} }
identity key = normalized "first last|ST|grad" (state + grad guard against
the John-Smith collision, same principle as the PBR rank cross-check).
"""
import json
import os
import re
import datetime as _dt

_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "data", "academics.json")


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def identity_key(name, state=None, grad=None):
    """Stable per-player key. State + grad included so two 'John Smith's in
    different states/classes don't collide — same guard the PBR match uses."""
    st = (state or "").strip().upper()[:2]
    gy = re.sub(r"\D", "", str(grad or ""))[:4]
    return f"{_norm(name)}|{st}|{gy}"


def load():
    if os.path.exists(_CACHE):
        try:
            return json.load(open(_CACHE))
        except Exception:
            pass
    return {}


def save(cache):
    os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
    json.dump(cache, open(_CACHE, "w"), indent=1, sort_keys=True)


def put(cache, name, acad, *, state=None, grad=None, source="", handle=None):
    """Record academics for a player. Never overwrites a richer existing
    value with a poorer one: a string with more filled fields (GPA+SAT+ACT)
    wins over a bare GPA; a real value always beats blank."""
    if not acad and not handle:
        return cache
    k = identity_key(name, state, grad)
    cur = cache.get(k, {})
    better = (acad and len(acad) > len(cur.get("acad", "")))
    entry = dict(cur)
    if better:
        entry["acad"] = acad
        entry["source"] = source
    if handle and not entry.get("handle"):
        entry["handle"] = handle
    entry["updated"] = _dt.date.today().isoformat()
    cache[k] = entry
    return cache


def get(cache, name, state=None, grad=None):
    """Best known academic string for a player, or ''. Falls back to a
    name-only match when the state/grad-qualified key misses (rosters and
    sources don't always agree on state/grad)."""
    e = cache.get(identity_key(name, state, grad))
    if e:
        return e.get("acad", "")
    nm = _norm(name)
    for k, v in cache.items():
        if k.split("|", 1)[0] == nm and v.get("acad"):
            return v["acad"]
    return ""


def enrich_event_from_cache(teams, cache):
    """Fill each roster player's `acad` field from the cache (used at book
    build time, every event, regardless of platform). Returns count filled."""
    n = 0
    for t in teams:
        for p in t.get("players", []):
            if p.get("acad"):
                continue
            a = get(cache, p.get("name"), p.get("state"), p.get("grad"))
            if a:
                p["acad"] = a
                n += 1
    return n


def merge_harvest(cache, harvest_map, *, source, roster_index=None):
    """Fold a {name: 'GPA 3.8 · SAT 1280'} harvest (e.g. a FiveTool run)
    into the cache. roster_index optionally maps name -> (state, grad) so
    the identity key is fully qualified; without it, name-only keys are used
    (still fine — get() name-falls-back)."""
    for name, acad in (harvest_map or {}).items():
        st, gy = (roster_index or {}).get(_norm(name), (None, None))
        put(cache, name, acad, state=st, grad=gy, source=source)
    return cache

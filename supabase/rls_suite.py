#!/usr/bin/env python3
"""Adversarial RLS test suite — Recruiting AI platform (Phase 0).

Red-teams our own Postgres RLS through the public PostgREST API,
logged in as real users. GREEN here is the gate for tenant #2's data
(ONE-ROOF: "adversarial RLS test suite green before any real data").

Fixtures: supabase/rls_fixtures.sql (two TEST programs + users).
Run:  SUPABASE_ANON_KEY=... RLS_TEST_PW=... python3 supabase/rls_suite.py
"""
import json, os, sys, urllib.request, urllib.error

BASE = os.environ.get("SUPABASE_URL", "https://bcdoidnfbrsfeulyhwhi.supabase.co")
ANON = os.environ["SUPABASE_ANON_KEY"]     # public anon key
PW   = os.environ["RLS_TEST_PW"]           # password used when rls_fixtures.sql ran

# Fixture ids — printed by the final SELECT of rls_fixtures.sql.
# Current test tenants (created 2026-07-06):
NAVY_PROG    = os.environ.get("RLS_NAVY_PROG",    "619f16e0-a96c-4e6a-8529-3925762b73b0")
RIVAL_PROG   = os.environ.get("RLS_RIVAL_PROG",   "35b69ab9-2298-4a9c-81d6-5fb0b482326d")
NAVY_PLAYER  = os.environ.get("RLS_NAVY_PLAYER",  "feea5ea8-1e29-463e-ba16-1378be5fe4d7")
RIVAL_PLAYER = os.environ.get("RLS_RIVAL_PLAYER", "6703743b-d83d-48fc-9d97-bddd80ea9800")

def req(method, path, token=None, body=None, headers=None):
    h = {"apikey": ANON, "Authorization": f"Bearer {token or ANON}",
         "Content-Type": "application/json", "Prefer": "return=representation"}
    h.update(headers or {})
    r = urllib.request.Request(BASE + path, method=method,
                               data=json.dumps(body).encode() if body is not None else None,
                               headers=h)
    try:
        resp = urllib.request.urlopen(r)
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, raw.decode(errors="replace")

def login(email):
    code, d = req("POST", "/auth/v1/token?grant_type=password",
                  body={"email": email, "password": PW})
    assert code == 200 and d.get("access_token"), f"login failed for {email}: {code} {d}"
    return d["access_token"]

navy  = login("rls-test-navy@rlstest.gmail.com")
rival = login("rls-test-rival@rlstest.gmail.com")

results = []
def check(name, ok, detail=""):
    results.append((ok, name, detail))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  <- {detail}"))

# ---------- cross-tenant reads ----------
c, d = req("GET", f"/rest/v1/players?select=first_name,last_name&program_id=eq.{NAVY_PROG}", token=rival)
check("rival cannot read navy players (filtered query)", c == 200 and d == [], f"{c} {d}")

c, d = req("GET", "/rest/v1/players?select=last_name,program_id", token=rival)
leak = [r for r in (d or []) if r.get("program_id") != RIVAL_PROG] if c == 200 else ["err"]
check("rival full-table players scan returns only own rows", c == 200 and not leak, f"{c} {d}")

c, d = req("GET", f"/rest/v1/players?select=first_name&id=eq.{NAVY_PLAYER}", token=rival)
check("rival cannot read navy player by known UUID", c == 200 and d == [], f"{c} {d}")

c, d = req("GET", "/rest/v1/evaluations?select=note,program_id", token=rival)
leak = [r for r in (d or []) if r.get("program_id") != RIVAL_PROG] if c == 200 else ["err"]
check("rival cannot read navy evaluations", c == 200 and not leak, f"{c} {d}")

c, d = req("GET", "/rest/v1/programs?select=slug", token=rival)
slugs = {r["slug"] for r in (d or [])} if c == 200 else set()
check("rival sees only own program row", slugs == {"rls-test-rival"}, f"{c} {d}")

c, d = req("GET", "/rest/v1/members?select=display_name,program_id", token=rival)
leak = [r for r in (d or []) if r.get("program_id") != RIVAL_PROG] if c == 200 else ["err"]
check("rival cannot enumerate navy members (and no 42P17 recursion)", c == 200 and not leak, f"{c} {d}")

c, d = req("GET", "/rest/v1/access_audit?select=program_id,action", token=rival)
leak = [r for r in (d or []) if r.get("program_id") != RIVAL_PROG] if c == 200 else ["err"]
check("rival admin sees only own audit rows", c == 200 and not leak, f"{c} {d}")

# ---------- cross-tenant writes ----------
c, d = req("POST", "/rest/v1/players",
           body={"program_id": NAVY_PROG, "first_name": "Injected", "last_name": "ByRival"},
           token=rival)
check("rival cannot INSERT a player into navy's board", c in (401, 403), f"{c} {d}")

c, d = req("PATCH", f"/rest/v1/players?id=eq.{NAVY_PLAYER}",
           body={"first_name": "Vandalized"}, token=rival)
check("rival UPDATE of navy player affects 0 rows", c in (401, 403, 404) or (c in (200, 204) and not d), f"{c} {d}")

c, d = req("DELETE", f"/rest/v1/players?id=eq.{NAVY_PLAYER}", token=rival)
check("rival DELETE of navy player affects 0 rows", c in (401, 403, 404) or (c in (200, 204) and not d), f"{c} {d}")

c, d = req("POST", "/rest/v1/evaluations",
           body={"program_id": RIVAL_PROG, "player_id": NAVY_PLAYER, "note": "cross-ref probe"},
           token=rival)
check("rival cannot attach an eval to navy's player (cross-tenant FK)", c in (401, 403), f"{c} {d}")

c, d = req("POST", "/rest/v1/depth_chart",
           body={"program_id": RIVAL_PROG, "grad_year": 2027, "position": "RHP", "slot": 1,
                 "player_id": NAVY_PLAYER}, token=rival)
check("rival cannot slot navy's player into own depth chart", c in (401, 403), f"{c} {d}")

# verify navy player untouched
c, d = req("GET", f"/rest/v1/players?select=first_name&id=eq.{NAVY_PLAYER}", token=navy)
check("navy player intact after attacks", c == 200 and d and d[0]["first_name"] == "NavyOnly", f"{c} {d}")

# ---------- append-only evaluations ----------
c, d = req("GET", "/rest/v1/evaluations?select=id&limit=1", token=navy)
eval_id = d[0]["id"] if c == 200 and d else None
c, d = req("PATCH", f"/rest/v1/evaluations?id=eq.{eval_id}", body={"note": "history rewritten"}, token=navy)
check("navy cannot UPDATE its own eval (append-only)", c in (401, 403, 404) or (c in (200, 204) and not d), f"{c} {d}")
c, d = req("DELETE", f"/rest/v1/evaluations?id=eq.{eval_id}", token=navy)
check("navy cannot DELETE its own eval (append-only)", c in (401, 403, 404) or (c in (200, 204) and not d), f"{c} {d}")
c, d = req("POST", "/rest/v1/evaluations",
           body={"program_id": NAVY_PROG, "player_id": NAVY_PLAYER, "rating": "2", "note": "legit new eval"},
           token=navy)
check("navy CAN INSERT a new eval for its own player", c == 201, f"{c} {d}")

# ---------- own-board sanity (RLS must not break legit use) ----------
c, d = req("POST", "/rest/v1/players",
           body={"program_id": NAVY_PROG, "first_name": "Legit", "last_name": "Addition",
                 "grad_year": 2028, "state": "MD"}, token=navy)
check("navy CAN INSERT into own board", c == 201, f"{c} {d}")
if c == 201 and d:
    c2, d2 = req("DELETE", f"/rest/v1/players?id=eq.{d[0]['id']}", token=navy)
    check("navy CAN DELETE own player", c2 in (200, 204), f"{c2} {d2}")

# identity_hash generated column sanity
c, d = req("GET", f"/rest/v1/players?select=identity_hash&id=eq.{NAVY_PLAYER}", token=navy)
import hashlib
expect = hashlib.sha256("navyonly secretplayer|MD|2027".encode()).hexdigest()
check("identity_hash matches the documented formula", c == 200 and d and d[0]["identity_hash"] == expect, f"{c} {d}")

# ---------- shared pool ----------
c, d = req("GET", "/rest/v1/public_players?select=name&limit=1", token=ANON)
check("anon cannot read public_players", c == 200 and d == [], f"{c} {d}")
c, d = req("GET", "/rest/v1/public_players?select=name,measurables&limit=1", token=navy)
check("signed-in member CAN read public_players", c == 200 and d, f"{c} {d}")
c, d = req("POST", "/rest/v1/public_players",
           body={"identity_hash": "deadbeef", "name": "Poison Row"}, token=rival)
check("tenant cannot WRITE to public_players", c in (401, 403), f"{c} {d}")
c, d = req("GET", "/rest/v1/travel_programs?select=name&limit=1", token=navy)
check("signed-in member CAN read travel catalog", c == 200 and d, f"{c} {d}")
c, d = req("POST", "/rest/v1/travel_programs", body={"name": "Injected Program"}, token=rival)
check("tenant cannot WRITE to travel catalog", c in (401, 403), f"{c} {d}")

# ---------- feedback ----------
c, d = req("POST", "/rest/v1/feedback",
           body={"screen": "rls-suite", "message": "feedback insert works"}, token=ANON,
           headers={"Prefer": "return=minimal"})
check("anon CAN file feedback", c == 201, f"{c} {d}")
c, d = req("GET", "/rest/v1/feedback?select=message", token=rival)
check("tenant cannot read feedback stream", c == 200 and d == [], f"{c} {d}")

# ---------- legacy tables unaffected ----------
c, d = req("GET", "/rest/v1/events?select=id&limit=1", token=ANON)
check("legacy events table still readable by the live app (anon)", c == 200 and d, f"{c} {d}")

print()
fails = [r for r in results if not r[0]]
print(f"{len(results) - len(fails)}/{len(results)} passed")
sys.exit(1 if fails else 0)

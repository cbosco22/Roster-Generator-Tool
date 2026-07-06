#!/usr/bin/env python3
"""Build public_players seed SQL from Navy's caches (Phase 0, 2026-07-06).

Sources (all public/harvested facts only — NO tenant board data):
  - Supabase events.roster JSONs (3 events): name/grad/state/pos, meas
    chips (from the public PBR crawls), pg_rank, commit, pbr_url
  - data/pbr_rankings.pkl: PBR national + state ranks
  - data/academics.json: FiveTool GPA harvest, keyed "name|ST|grad"
  - travel_programs.json: shared catalog names (separate table)

identity_hash MUST match the players-table generated column:
  sha256(lower(trim(first)||' '||trim(last)) || '|' || upper(state) || '|' || grad)
Name normalization here: collapse whitespace; first token = first name,
remainder = last name -> equivalent to the SQL expression for "First Last".
"""
import json, pickle, hashlib, re, os, sys, urllib.request

# Run from anywhere. Emits seed_pool_NN.sql chunks + seed_travel.sql into
# supabase/ — run them in the Supabase SQL editor (postgres role;
# public_players is deliberately not writable through the API).
S = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(S)
ANON = os.environ["SUPABASE_ANON_KEY"]  # public anon key (read-only pulls)
BASE = "https://bcdoidnfbrsfeulyhwhi.supabase.co/rest/v1"
EVENTS = {
    "Boston Classic 2026": "8acd14f9-63f4-4328-a7ad-c995365854bc",
    "PG 16U WWBA 2026": "1a922c52-d544-4177-90e7-edbcecc9e909",
    "AABC Don Mattingly WS 2026": "6fcc0415-b18c-4fea-9190-bdc984475c07",
}

# PBR region names -> member state codes (mirror of _state_match)
STATE_CODES = {
 'alabama':'AL','alaska':'AK','arizona':'AZ','arkansas':'AR','california':'CA','colorado':'CO',
 'connecticut':'CT','delaware':'DE','florida':'FL','georgia':'GA','hawaii':'HI','idaho':'ID',
 'illinois':'IL','indiana':'IN','iowa':'IA','kansas':'KS','kentucky':'KY','louisiana':'LA',
 'maine':'ME','maryland':'MD','massachusetts':'MA','michigan':'MI','minnesota':'MN','mississippi':'MS',
 'missouri':'MO','montana':'MT','nebraska':'NE','nevada':'NV','new hampshire':'NH','new jersey':'NJ',
 'new mexico':'NM','new york':'NY','north carolina':'NC','north dakota':'ND','ohio':'OH','oklahoma':'OK',
 'oregon':'OR','pennsylvania':'PA','rhode island':'RI','south carolina':'SC','south dakota':'SD',
 'tennessee':'TN','texas':'TX','utah':'UT','vermont':'VT','virginia':'VA','washington':'WA',
 'west virginia':'WV','wisconsin':'WI','wyoming':'WY',
}
REGIONS = {
 'new england': {'MA','CT','RI','NH','VT','ME'},
 'dakotas': {'ND','SD'},
 'maryland': {'MD','DE','DC'},  # PBR Maryland region
 'mid-atlantic': {'MD','DE','DC'},
}

def norm_name(n):
    return re.sub(r"\s+", " ", (n or "").strip())

def ihash(name, state, grad):
    key = f"{norm_name(name).lower()}|{(state or '').upper()}|{grad or ''}"
    return hashlib.sha256(key.encode()).hexdigest(), key

def parse_meas(m):
    out = {}
    for chip in (m or "").split("·"):
        chip = chip.strip()
        if not chip: continue
        parts = chip.split(" ", 1)
        if len(parts) == 2: out[parts[0]] = parts[1]
        else: out[chip] = ""
    return out

def get(path):
    req = urllib.request.Request(BASE + path, headers={"apikey": ANON, "Authorization": "Bearer " + ANON})
    return urllib.request.urlopen(req).read()

pool = {}  # hash -> record
def upsert(name, state, grad, **fields):
    grad = str(grad or "").strip()
    if not re.fullmatch(r"20\d\d", grad): grad = ""
    state = (state or "").strip().upper()
    if not name or not state or not grad: return None  # unhashable-to-tenants; skip
    h, key = ihash(name, state, grad)
    rec = pool.setdefault(h, {"identity_hash": h, "name": norm_name(name),
                              "grad_year": int(grad), "state": state, "sources": {}})
    for k, v in fields.items():
        if k == "source_tag": continue
        if v in (None, "", {}, "NR"): continue
        if k == "measurables":
            rec.setdefault("measurables", {}).update(v)
        elif k not in rec or not rec.get(k):
            rec[k] = v
    tag = fields.get("source_tag")
    if tag:
        for f in fields:
            if f in ("source_tag",): continue
            if fields[f] not in (None, "", {}, "NR"):
                rec["sources"][f] = tag
    return rec

# ---- 1. event rosters ----
for ev_name, eid in EVENTS.items():
    raw = json.loads(get(f"/events?id=eq.{eid}&select=roster"))[0]["roster"]
    if not raw: continue
    rj = json.loads(raw)
    teams = rj if isinstance(rj, list) else rj.get("teams", [])
    n = 0
    for t in teams:
        for p in t.get("players", []):
            pg = p.get("pg_rank")
            pg = int(re.sub(r"[^\d]", "", str(pg))) if pg and str(pg) != "NR" and re.search(r"\d", str(pg)) else None
            upsert(p.get("name"), p.get("state"), p.get("grad"),
                   position=p.get("pos"), measurables=parse_meas(p.get("meas")),
                   pg_rank=pg, commit=p.get("commit"),
                   source_tag=f"roster:{ev_name}")
            n += 1
    print(f"{ev_name}: {n} roster players", file=sys.stderr)

# ---- 2. academics cache (keys are already name|ST|grad) ----
acads = json.load(open(f"{REPO}/data/academics.json"))
n = 0
for key, v in acads.items():
    try: nm, st, gr = key.rsplit("|", 2)
    except ValueError: continue
    if upsert(nm, st, gr, academics=v.get("acad"), source_tag=v.get("source", "academics_cache")): n += 1
print(f"academics merged: {n}", file=sys.stderr)

# ---- 3. PBR rankings (match by name+class against pool; region-aware) ----
rk = pickle.load(open(f"{REPO}/data/pbr_rankings.pkl", "rb"))
by_name_grad = {}
for h, rec in pool.items():
    by_name_grad.setdefault((rec["name"].lower(), str(rec["grad_year"])), []).append(rec)

def attach_rank(entry, field, code_field=None, code=None):
    matches = by_name_grad.get((norm_name(entry["name"]).lower(), str(entry.get("class") or "")), [])
    ok = []
    for rec in matches:
        st_entry = (entry.get("state") or "").strip().lower()
        if field == "pbr_rank_nat" or not st_entry or st_entry.startswith("- select"):
            ok.append(rec)
        else:
            codes = REGIONS.get(st_entry) or ({STATE_CODES[st_entry]} if st_entry in STATE_CODES else set())
            if not codes or rec["state"] in codes: ok.append(rec)
    for rec in ok:
        if field not in rec:
            rec[field] = entry["rank"]
            rec["sources"][field] = "pbr_rankings"
            if code_field and code: rec[code_field] = code
        if entry.get("commit") and not rec.get("commit"):
            rec["commit"] = entry["commit"]; rec["sources"]["commit"] = "pbr_rankings"
    return len(ok)

nat_hits = st_hits = 0
for e in rk.get("national", {}).values():
    nat_hits += attach_rank(e, "pbr_rank_nat")
for e in rk.get("state_rnks", {}).values():
    st = (e.get("state") or "").strip()
    st_hits += attach_rank(e, "pbr_rank_state", "pbr_rank_state_code", st)
print(f"rankings attached: nat {nat_hits}, state {st_hits} (of {len(rk.get('national',{}))} nat / {len(rk.get('state_rnks',{}))} state entries)", file=sys.stderr)

# ---- emit SQL chunks ----
def q(s):
    return "'" + str(s).replace("'", "''") + "'"

rows = []
for rec in pool.values():
    meas = json.dumps(rec.get("measurables") or {}, ensure_ascii=False) if rec.get("measurables") else None
    rows.append("(" + ",".join([
        q(rec["identity_hash"]), q(rec["name"]),
        str(rec["grad_year"]), q(rec["state"]),
        q(rec["position"]) if rec.get("position") else "null",
        q(meas) + "::jsonb" if meas else "null",
        str(rec["pbr_rank_nat"]) if rec.get("pbr_rank_nat") else "null",
        str(rec["pbr_rank_state"]) if rec.get("pbr_rank_state") else "null",
        q(rec["pbr_rank_state_code"]) if rec.get("pbr_rank_state_code") else "null",
        str(rec["pg_rank"]) if rec.get("pg_rank") else "null",
        q(rec["academics"]) if rec.get("academics") else "null",
        q(rec["commit"]) if rec.get("commit") else "null",
        q(json.dumps(rec["sources"], ensure_ascii=False)) + "::jsonb",
    ]) + ")")

HEAD = ("insert into public_players (identity_hash,name,grad_year,state,position,measurables,"
        "pbr_rank_nat,pbr_rank_state,pbr_rank_state_code,pg_rank,academics,commit,sources) values\n")
TAIL = "\non conflict (identity_hash) do nothing;"
CHUNK = 2500
files = []
for i in range(0, len(rows), CHUNK):
    fn = f"{S}/seed_pool_{i//CHUNK + 1:02d}.sql"
    with open(fn, "w") as f:
        f.write(f"-- public_players seed chunk {i//CHUNK + 1} ({len(rows[i:i+CHUNK])} rows)\n")
        f.write(HEAD + ",\n".join(rows[i:i+CHUNK]) + TAIL)
    files.append(fn)

# travel catalog
tp = json.load(open(f"{REPO}/travel_programs.json"))
with open(f"{S}/seed_travel.sql", "w") as f:
    f.write("insert into travel_programs (name) values\n")
    f.write(",\n".join(f"({q(name)})" for name in sorted(tp)) + "\non conflict (name) do nothing;")

stats = {
    "pool_rows": len(rows),
    "with_meas": sum(1 for r in pool.values() if r.get("measurables")),
    "with_acad": sum(1 for r in pool.values() if r.get("academics")),
    "with_nat_rank": sum(1 for r in pool.values() if r.get("pbr_rank_nat")),
    "with_state_rank": sum(1 for r in pool.values() if r.get("pbr_rank_state")),
    "with_pg_rank": sum(1 for r in pool.values() if r.get("pg_rank")),
    "with_commit": sum(1 for r in pool.values() if r.get("commit")),
    "travel_catalog": len(tp),
    "chunks": len(files),
}
print(json.dumps(stats, indent=2))

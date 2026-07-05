"""
push_event.py — push a schedule straight into the Navy Event Day app (Supabase).

WHY: replaces the copy/paste step. Call this right after you build the schedule CSV
in your Roster tool, and the event shows up (and updates) live for every coach.

HOW IT BEHAVES:
  - First push with a given name  -> CREATES the event.
  - Pushing again with the SAME name -> UPDATES that event's schedule in place.
    Because it's the same event row, coaches' tags and notes stay attached
    to their games (anything unchanged keeps its marks).

SETUP (once):
  1. Supabase -> Settings -> API Keys -> copy the `anon` `public` key.
  2. Either set env vars  SUPABASE_URL  and  SUPABASE_ANON_KEY,
     or paste them into the two constants below.

USAGE in your Roster tool, after building the CSV:
    from push_event import push_event
    csv_text = build_schedule_csv(...)          # your existing call
    result = push_event("PBR 16U Nat'l Champ 2026", csv_text)
    print(result)   # {'action': 'created' or 'updated', 'id': '...', 'name': '...'}

CLI test:
    python push_event.py "PBR 16U Nat'l Champ 2026" schedule.csv
"""
import json
import os
import sys
import csv
import io
import requests

# Your project URL is pre-filled. Paste your anon public key here, or set env vars.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://bcdoidnfbrsfeulyhwhi.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJjZG9pZG5mYnJzZmV1bHlod2hpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI3NzM2OTEsImV4cCI6MjA5ODM0OTY5MX0.aXLapvAxINhebAjiKY9wTYka9XxoJn827T5-CaiBPbc")  # <-- paste anon public key


def enrich_teams_with_crawl(teams, crawl_path):
    """Fold each player's PBR measurables into the roster teams list as a
    compact display string (p['meas'] = "FB 88 · EV 95.4 · 60 7.27"), so the
    Event Day app's tap-a-team roster view shows the same verified numbers
    as the roster book. Reuses gen_roster_pdf.meas_chip_items (short labels,
    order, 1-year freshness filter) for exact PDF parity. Mutates and
    returns teams; missing/loadable-less crawl file is a no-op."""
    import os
    import re as _re
    if not (crawl_path and os.path.exists(crawl_path)):
        return teams
    try:
        from gen_roster_pdf import meas_chip_items
        with open(crawl_path) as f:
            first = f.read(1)
            f.seek(0)
            if str(crawl_path).endswith('.jsonl') and first == '{':
                recs = [json.loads(l)['record'] for l in f
                        if l.strip() and json.loads(l).get('matched')]
            else:
                recs = json.load(f).get('results', [])
    except Exception as e:
        print(f'[MEAS] enrichment skipped ({e}) — roster pushes without measurables')
        return teams
    norm = lambda s: _re.sub(r'\s+', ' ', (s or '').strip().lower())
    idx = {}
    for r in recs:
        q = r.get('query', {})
        nm = norm(q.get('name'))
        if not nm:
            continue
        idx[(nm, norm(q.get('team')))] = r
        idx.setdefault(nm, r)
    n = 0
    for t in teams:
        for p in t.get('players', []):
            r = idx.get((norm(p.get('name')), norm(t.get('name')))) or idx.get(norm(p.get('name')))
            if not r:
                continue
            chips = meas_chip_items(r.get('measurables'), r.get('measurables_dated'))
            if chips:
                p['meas'] = ' · '.join(f'{lab} {val}' for val, lab in chips)
                n += 1
    print(f'[MEAS] {n} players enriched with measurables from {crawl_path}')
    return teams


def enrich_teams_with_ranks(teams, pkl_path=None):
    """Append rank chips to each player's `meas` display line so the Event
    Day app's tap-a-team roster view shows ranked guys, not just the PDF
    book (Chris 2026-07-05: "I need to know ranked guys" in-app). Same
    chip text as the book's Rank column — "#4 GA", "#120 Nat'l", "#57 PG"
    — folded into the existing meas string ("FB 88 · SPIN 2212 · #4 GA")
    so the app needs zero changes to render it. Same cross-validation
    semantics as gen_roster_pdf's _pbr_match: state rank must match the
    player's grad year AND state; national rank must match grad year
    (entries carry '- select state -' so the state check passes through).
    Mutates and returns teams; a missing pkl is a no-op."""
    import os
    import pickle
    from db_loader import strip_suffix
    from gen_schedule_csv import _STATE_ABV
    path = pkl_path or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    'data', 'pbr_rankings.pkl')
    if not os.path.exists(path):
        print('[RANK] pbr_rankings.pkl not found — roster pushes without ranks')
        return teams
    with open(path, 'rb') as f:
        d = pickle.load(f)
    nat, st = d.get('national', {}), d.get('state_rnks', {})

    def abbrev(s):
        s = (s or '').strip()
        if len(s) == 2:
            return s.upper()
        if s.lower() == 'new england':
            return 'NEng'
        return _STATE_ABV.get(s.lower(), s.upper())

    # mirrors gen_roster_pdf's region handling: a multi-state PBR region
    # entry ('New England', 'Dakotas', MD-site covering DE/DC) matches all
    # of its member states instead of rejecting real state ranks
    region_members = {
        'new england': {'CT', 'MA', 'ME', 'NH', 'RI', 'VT'},
        'dakotas': {'ND', 'SD'},
        'maryland': {'MD', 'DE', 'DC'},
    }

    def state_match(entry_state, player_state):
        if abbrev(entry_state) == abbrev(player_state):
            return True
        return abbrev(player_state) in region_members.get(
            (entry_state or '').strip().lower(), ())

    def valid(entry, grad, state):
        if not entry:
            return False
        if grad and str(entry.get('class', '')) != str(grad):
            return False
        if state and not state_match(entry.get('state', ''), state) and \
                entry.get('state', '') not in ('- select state -', ''):
            return False
        return True

    n = 0
    for t in teams:
        for p in t.get('players', []):
            key = strip_suffix((p.get('name') or '').strip().lower())
            if not key:
                continue
            grad = str(p.get('grad') or '')
            state = (p.get('state') or '').strip()
            chips = []
            e = st.get(key)
            if valid(e, grad, state):
                chips.append(f"#{e['rank']} {abbrev(e.get('state', ''))}")
            e = nat.get(key)
            if valid(e, grad, state):
                chips.append(f"#{e['rank']} Nat'l")
            pg = str(p.get('pg_rank') or '').strip()
            if pg.isdigit():
                chips.append(f"#{pg} PG")
            if chips:
                rank_str = ' · '.join(chips)
                p['meas'] = f"{p['meas']} · {rank_str}" if p.get('meas') else rank_str
                n += 1
    print(f'[RANK] {n} players carry rank chips in the roster line')
    return teams


def push_event(name, csv_text, roster_json=None, schedule_url=None, location=None,
               supabase_url=None, anon_key=None, timeout=30):
    """Create or update an event by name. Returns {'action','id','name'}.

    roster_json: optional JSON text of the event's full team rosters
    ({"teams":[{"name","players":[...]}]}). Stored on the event row so the
    Event Day app can cross-reference every roster against the LIVE
    recruiting board (kids added to the board mid-event light up on their
    team without a CSV rebuild). Omitted -> any existing roster is kept.

    location: optional 'City, ST' for the Event Day home page. Sent only when
    provided; if events.location doesn't exist yet (schema.sql ALTER not run),
    it's dropped and the push still succeeds — same pattern as roster."""
    url = (supabase_url or SUPABASE_URL).rstrip("/")
    key = anon_key or SUPABASE_ANON_KEY
    if not key:
        raise RuntimeError(
            "Missing Supabase anon key. Set SUPABASE_ANON_KEY env var "
            "or paste it into push_event.py."
        )
    if not name or not str(name).strip():
        raise ValueError("Event name is required.")

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    endpoint = f"{url}/rest/v1/events"

    # 1) Look for an existing event with this exact name.
    # NO embedded quotes: PostgREST's quoted-literal parsing broke on names
    # containing "/" (a real event name with dates, 2026-07-02) - the lookup
    # silently returned 0 rows, so pushes re-CREATED the event instead of
    # updating it. requests URL-encodes spaces/slashes fine unquoted.
    r = requests.get(
        endpoint,
        headers=headers,
        params={"name": "eq." + name, "select": "id"},
        timeout=timeout,
    )
    if not r.ok:
        raise RuntimeError(f"Lookup failed ({r.status_code}): {r.text}")
    existing = r.json()

    write_headers = {**headers, "Prefer": "return=representation"}

    # 2) Update in place if it exists, otherwise create it.
    # The roster column may not exist yet (its ALTER in supabase/schema.sql
    # hasn't been run) - never let that break the schedule push itself:
    # retry once without roster and report the miss instead of raising.
    roster_skipped = False

    def _write(body):
        if existing:
            return requests.patch(endpoint, headers=write_headers,
                                  params={"id": f"eq.{existing[0]['id']}"},
                                  json=body, timeout=timeout)
        return requests.post(endpoint, headers=write_headers,
                             json={"name": name, **body}, timeout=timeout)

    # csv_text=None -> leave the existing schedule untouched (one_link.py
    # pushes the roster before any schedule exists; Event Day's own Refresh
    # fills the schedule in later)
    body = {} if csv_text is None else {"csv": csv_text}
    if csv_text is None and not existing:
        body["csv"] = ""  # creating fresh: column wants a value
    if roster_json is not None:
        body["roster"] = roster_json
    if schedule_url:
        # saved link = the Event Day Refresh button becomes one-tap
        body["schedule_url"] = schedule_url
    if location:
        body["location"] = location
    r = _write(body)
    if not r.ok and location and "location" in r.text:
        body.pop("location", None)
        r = _write(body or {"csv": csv_text or ""})
    if not r.ok and roster_json is not None and "roster" in r.text:
        roster_skipped = True
        body.pop("roster", None)
        r = _write(body or {"csv": csv_text or ""})
    action = "updated" if existing else "created"

    if not r.ok:
        raise RuntimeError(f"Push failed ({r.status_code}): {r.text}")

    row = r.json()
    if isinstance(row, list):
        row = row[0] if row else {}
    out = {"action": action, "id": row.get("id"), "name": name}
    if roster_skipped:
        out["roster_skipped"] = ("events.roster column missing - run the "
                                 "ALTER line at the bottom of "
                                 "supabase/schema.sql in the Supabase SQL "
                                 "editor to enable live board cross-reference")
    return out


def fetch_event_csv(name, supabase_url=None, anon_key=None, timeout=30):
    """Return (event_id, csv_text) for the event with this exact name, or (None, None)."""
    url = (supabase_url or SUPABASE_URL).rstrip("/")
    key = anon_key or SUPABASE_ANON_KEY
    if not key:
        raise RuntimeError("Missing Supabase anon key. Set SUPABASE_ANON_KEY or paste it in.")
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    r = requests.get(
        f"{url}/rest/v1/events",
        headers=headers,
        params={"name": "eq." + name, "select": "id,csv"},
        timeout=timeout,
    )
    if not r.ok:
        raise RuntimeError(f"Lookup failed ({r.status_code}): {r.text}")
    rows = r.json()
    if not rows:
        return None, None
    return rows[0]["id"], rows[0]["csv"]


def _carry_forward_team_data(existing_csv):
    """Parse the live event CSV and return {team_name: {tier, stars, pbr, navy}}."""
    teams = {}
    if not existing_csv:
        return teams
    reader = csv.DictReader(io.StringIO(existing_csv))
    for row in reader:
        for side in ("1", "2"):
            tname = (row.get(f"Team{side}") or "").strip()
            if not tname or tname in teams:
                continue
            teams[tname] = {
                "tier": row.get(f"Team{side}Tier", "") or "",
                "stars": row.get(f"Team{side}★", "") or "",
                "pbr": row.get(f"Team{side}PBR", "") or "",
                "navy": row.get(f"Team{side} Navy Players", "") or "",
            }
    return teams


def _games_from_schedule_json(schedule_json):
    if isinstance(schedule_json, dict):
        return schedule_json.get("games", []) or []
    if isinstance(schedule_json, list):
        return schedule_json
    raise TypeError("schedule_json must be a dict with 'games' or a list of games.")


def push_schedule_update(name, schedule_json, supabase_url=None, anon_key=None, timeout=30):
    """
    Update an event using ONLY a new schedule (no roster). Carries each team's
    Navy data (tier, ★, PBR count, Navy Players string) forward from whatever
    is already live for that event, matched by exact team name, and rebuilds
    the schedule rows (game#/date/time/location/division/team1/team2) fresh.

    Use this for the "schedule update" tab -- when the link just shows a new
    time/field/game layout and you don't want to reload the roster.

    Returns {'action': 'updated', 'id': ..., 'name': ..., 'unmatched_teams': [...]}.
    'unmatched_teams' lists any team in the new schedule that wasn't found in
    the currently-live event -- those rows will have blank Navy data until a
    full tournament generation (with the roster) is run for them.
    """
    if not name or not str(name).strip():
        raise ValueError("Event name is required.")

    event_id, existing_csv = fetch_event_csv(name, supabase_url, anon_key, timeout)
    if event_id is None:
        raise RuntimeError(
            f'No live event named "{name}" found. Schedule-only updates need an '
            "existing event to carry Navy data forward from -- run a full "
            "tournament generation (push_event) first to create it."
        )

    team_data = _carry_forward_team_data(existing_csv)
    games = _games_from_schedule_json(schedule_json)

    unmatched = set()
    rows = []
    for g in games:
        t1 = (g.get("team1", "") or "").strip()
        t2 = (g.get("team2", "") or "").strip()
        d1 = team_data.get(t1)
        d2 = team_data.get(t2)
        if t1 and d1 is None:
            unmatched.add(t1)
        if t2 and d2 is None:
            unmatched.add(t2)
        d1 = d1 or {"tier": "", "stars": "", "pbr": "", "navy": ""}
        d2 = d2 or {"tier": "", "stars": "", "pbr": "", "navy": ""}

        def _to_int(s):
            try:
                return int(s)
            except (TypeError, ValueError):
                return 0

        total_stars = _to_int(d1["stars"]) + _to_int(d2["stars"])
        total_pbr = _to_int(d1["pbr"]) + _to_int(d2["pbr"])

        rows.append({
            "Game#": g.get("game", ""),
            "Date": g.get("date", ""),
            "Time": g.get("time", ""),
            "Location": g.get("location", ""),
            "Attend": "",
            "Notes": "",
            "Division": g.get("division", ""),
            "Team1": t1,
            "Team1Tier": d1["tier"],
            "Team1★": d1["stars"],
            "Team1PBR": d1["pbr"],
            "Team1 Navy Players": d1["navy"],
            "Team2": t2,
            "Team2Tier": d2["tier"],
            "Team2★": d2["stars"],
            "Team2PBR": d2["pbr"],
            "Team2 Navy Players": d2["navy"],
            "Total★": str(total_stars) if total_stars else "",
            "TotalPBR": str(total_pbr) if total_pbr else "",
        })

    cols = ['Game#','Date','Time','Location','Attend','Notes','Division',
            'Team1','Team1Tier','Team1★','Team1PBR','Team1 Navy Players',
            'Team2','Team2Tier','Team2★','Team2PBR','Team2 Navy Players',
            'Total★','TotalPBR']
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    new_csv = out.getvalue()

    url = (supabase_url or SUPABASE_URL).rstrip("/")
    key = anon_key or SUPABASE_ANON_KEY
    headers = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json", "Prefer": "return=representation",
    }
    r = requests.patch(
        f"{url}/rest/v1/events", headers=headers,
        params={"id": f"eq.{event_id}"}, json={"csv": new_csv}, timeout=timeout,
    )
    if not r.ok:
        raise RuntimeError(f"Push failed ({r.status_code}): {r.text}")

    return {"action": "updated", "id": event_id, "name": name, "unmatched_teams": sorted(unmatched)}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print('Usage: python push_event.py "Event Name" path/to/schedule.csv')
        sys.exit(1)
    event_name = sys.argv[1]
    with open(sys.argv[2], "r", encoding="utf-8") as f:
        text = f.read()
    print(push_event(event_name, text))


def push_pdf(name, pdf_bytes, filename, supabase_url=None, anon_key=None, timeout=120):
    """Attach the roster-book PDF to an event (event_files table) so coaches
    can download it straight from the Event Day app — 'easy first grab into
    GoodNotes' (Chris 2026-07-03). Upserts by event id; base64 in a side
    table so the events list stays light."""
    import base64
    url = (supabase_url or SUPABASE_URL).rstrip("/")
    key = anon_key or SUPABASE_ANON_KEY
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates"}
    r = requests.get(f"{url}/rest/v1/events", headers=headers,
                     params={"name": "eq." + name, "select": "id"}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise RuntimeError(f"push_pdf: no event named {name!r}")
    event_id = rows[0]["id"]
    body = {"event_id": event_id,
            "pdf": base64.b64encode(pdf_bytes).decode(),
            "pdf_name": filename}
    r = requests.post(f"{url}/rest/v1/event_files", headers=headers,
                      json=body, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"push_pdf failed ({r.status_code}): {r.text[:200]}")
    return {"event_id": event_id, "bytes": len(pdf_bytes)}

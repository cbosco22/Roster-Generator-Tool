"""
Builds and sends write operations to Recruiting Sheet 2.0 via the Apps
Script web app (see apps_script/Code.gs + apps_script/README.md for the
one-time deploy Chris does — this module is the Python side of that pair).

Upsert semantics (matches what Chris asked for 2026-06-30): a post-event
review either updates an EXISTING player's row or appends a NEW one.
Matching reuses db_loader's existing locked fuzzy-match logic — same rule
used everywhere else in this app, not a separate one invented here.

For an existing match:
  - Seen always gets the new event appended, comma-separated, never
    overwritten — unless that exact event is already the most recent
    entry, to guard against double-submits re-appending the same event.
  - tier (★) is overwritten only if a new rating was actually given this
    round and it differs from what is already there.
  - Every other tracked field (state, high school, summer team, pos,
    commit, class) is overwritten only if this round's data captured a
    value for it AND that value differs from what is already there.
    Anything not captured this round is left untouched.
For no match: a brand-new row is appended with whatever was captured,
including Date Added / By (only ever set on append — an update should
never rewrite when/who first added the player).

"ID" and "Pos Group" are spilling array formulas on the live sheet, not
real data. This module computes and writes ID/Name/Pos Group as plain
values on every write instead.

Column numbers are NEVER hardcoded here — every caller must pass a `cols`
dict resolved fresh from the live sheet via db_loader.find_columns().
This was a hardcoded dict until 2026-06-30, when Chris deleted two leading
columns on the live sheet and every hardcoded number silently pointed at
the wrong field (Apps Script reported success while most fields were
never actually visible anywhere in the row). Column position is not
stable enough to hardcode while the sheet is still being cleaned up -
resolve it fresh, every time, right before writing.

build_profile_update_op() / build_note_update_op() are narrower siblings of
build_upsert_op(), for the Board tab's profile-card edit: the caller
already has the exact row (from db_loader.all_players()), so there's no
fuzzy-lookup step, Seen is never touched (a Board edit isn't an event
sighting), and notes append instead of overwrite (see each docstring for
why).
"""
import requests
from datetime import date

# Mirrors the live sheet's E1 formula exactly:
# =iferror(IFS(M1="RHP","RHP",M1="LHP","LHP",M1="C","C",M1="CINF","INF",
#   M1="MINF","INF",M1="COF","OF",M1="CF","OF",M1="1B","INF",M1="2B","INF",
#   M1="3B","INF",M1="OF","OF",M1="INF","INF",M1="SS","INF"),"")
_POS_GROUP_MAP = {
    'RHP': 'RHP', 'LHP': 'LHP', 'C': 'C', 'CINF': 'INF', 'MINF': 'INF',
    'COF': 'OF', 'CF': 'OF', '1B': 'INF', '2B': 'INF', '3B': 'INF',
    'OF': 'OF', 'INF': 'INF', 'SS': 'INF',
}


def pos_group(pos):
    """Public on purpose - the Board tab (app.py) reuses this exact mapping
    to bucket players into the same 5 position groups (RHP/LHP/INF/OF/C)
    the live Big Board tab uses, instead of re-deriving its own copy."""
    return _POS_GROUP_MAP.get((pos or '').strip(), '')


def _id_label(first, last, tier, class_year, pos, state):
    """The compound 'ID' column label, e.g. "Noah Stead (0.1) - '25 MINF CA"."""
    label = f"{first} {last}".strip()
    if tier:
        label += f" ({tier})"
    yy = class_year[-2:] if class_year else ""
    tail = " ".join(x for x in [f"'{yy}" if yy else "", pos, state] if x)
    if tail:
        label += f" - {tail}"
    return label


def today_str():
    try:
        return date.today().strftime("%-m/%-d/%Y")
    except ValueError:                       # Windows fallback
        return date.today().strftime("%m/%d/%Y")


def build_upsert_op(current_db, cols, *, first, last, event_name, new_tier=None,
                     state=None, hs=None, team=None, pos=None, pos2=None,
                     bt=None, hometown=None, commit=None, class_year=None,
                     by_initials=None, date_added=None, notes=None,
                     academic=None, email=None, phone=None, comms=None):
    """Build one Apps Script op dict for a single player review (post-event
    rating, or a new/updated player from the Add Player tool). `cols` must
    come from db_loader.find_columns() on the SAME xlsx used to build
    `current_db` — never hardcode column numbers here, see module
    docstring for why. Looks the player up via db_loader's existing
    lookup() — does not duplicate or weaken that matching logic."""
    from db_loader import lookup
    existing = lookup(current_db, f"{first} {last}")
    simple_vals = {'hs': hs, 'team': team, 'commit': commit, 'pos2': pos2,
                   'bt': bt, 'hometown': hometown, 'academic': academic,
                   'email': email, 'phone': phone, 'comms': comms}

    if existing:
        fields = {}
        prior_seen = existing.get('seen', '') or ''
        seen_events = [s.strip() for s in prior_seen.split(',') if s.strip()]
        if not seen_events or seen_events[-1] != event_name:
            new_seen = ', '.join(seen_events + [event_name]) if seen_events else event_name
            fields[cols['seen']] = new_seen
        if new_tier and new_tier != existing.get('tier'):
            fields[cols['tier']] = new_tier
        relabel_inputs = {'tier': existing.get('tier'), 'class': existing.get('class'),
                          'pos': existing.get('pos'), 'state': existing.get('state')}
        for key, val in list(simple_vals.items()) + [('state', state), ('pos', pos),
                                                       ('class', class_year)]:
            if val and val != existing.get(key):
                fields[cols[key]] = val
                if key == 'pos':
                    fields[cols['pos_group']] = pos_group(val)
                if key in relabel_inputs:
                    relabel_inputs[key] = val
        if new_tier and new_tier != existing.get('tier'):
            relabel_inputs['tier'] = new_tier
        if any(k in fields for k in (cols['tier'], cols['class'], cols['pos'], cols['state'])):
            fields[cols['id']] = _id_label(existing['first'], existing['last'],
                                          relabel_inputs['tier'], relabel_inputs['class'],
                                          relabel_inputs['pos'], relabel_inputs['state'])
        if notes: fields[cols['notes']] = notes
        return {'action': 'update', 'row': existing['_row'], 'fields': fields,
                'player': existing['canonical_name']}

    fields = {
        cols['first']: first, cols['last']: last, cols['seen']: event_name,
        cols['name']: f"{first} {last}".strip(),
        cols['date_added']: date_added or today_str(),
    }
    if by_initials: fields[cols['by']] = by_initials
    if new_tier: fields[cols['tier']] = new_tier
    if class_year: fields[cols['class']] = class_year
    if pos: fields[cols['pos']] = pos
    if state: fields[cols['state']] = state
    if notes: fields[cols['notes']] = notes
    for key, val in simple_vals.items():
        if val: fields[cols[key]] = val
    fields[cols['id']] = _id_label(first, last, new_tier, class_year, pos, state)
    fields[cols['pos_group']] = pos_group(pos)
    return {'action': 'append', 'fields': fields, 'player': f"{first} {last}"}


_PROFILE_FIELDS = ('tier', 'commit', 'pos', 'pos2', 'bt', 'class', 'hometown',
                   'state', 'hs', 'team', 'academic', 'email', 'phone', 'comms')


def build_profile_update_op(existing, cols, **updates):
    """General field-update op for the Board tab's profile-card edit —
    unlike build_upsert_op(), this never touches Seen (Seen is an
    event-exposure log - "saw him at WWBA 2026" - not a general edit log,
    so a Board-side field edit shouldn't append a fake "event" to it).
    Accepts any of _PROFILE_FIELDS as kwargs (e.g. tier=..., team=...,
    hometown=...); only fields that are non-empty AND differ from the
    current value get written. `existing` comes straight from
    db_loader.parse_xlsx()'s db (the coach picked this exact player off a
    rendered row, not a fuzzy name lookup). Recomputes the ID label via
    _id_label() whenever tier/class/pos/state changes, same as every
    other write path. Returns None if nothing actually changed."""
    fields = {}
    relabel = {'tier': existing.get('tier'), 'class': existing.get('class'),
              'pos': existing.get('pos'), 'state': existing.get('state')}
    for key, val in updates.items():
        if key not in _PROFILE_FIELDS:
            raise ValueError(f"build_profile_update_op: unknown field {key!r}")
        val = val.strip() if isinstance(val, str) else val
        if not val or val == existing.get(key):
            continue
        fields[cols[key]] = val
        if key == 'pos':
            fields[cols['pos_group']] = pos_group(val)
        if key in relabel:
            relabel[key] = val
    if not fields:
        return None
    fields[cols['id']] = _id_label(existing['first'], existing['last'], relabel['tier'],
                                   relabel['class'], relabel['pos'], relabel['state'])
    return {'action': 'update', 'row': existing['_row'], 'fields': fields,
            'player': existing['canonical_name']}


def build_note_update_op(existing, cols, note_text):
    """Append a dated note to Notes — deliberately additive, unlike
    build_upsert_op()'s notes handling (which overwrites: appropriate
    there because a post-event note IS that round's complete summary).
    A Board-side "add a note" is a different action - a quick comment on
    top of whatever's already there - so it must never blow away prior
    notes. Requires `existing['notes']` (parse_xlsx() now parses it -
    added specifically so this diff/append is possible; it used to be
    write-only). Dedupe-guarded the same way Seen is, in case of a
    double-submit. Returns None if there's nothing new to write."""
    note_text = (note_text or '').strip()
    if not note_text:
        return None
    prior = (existing.get('notes') or '').strip()
    if prior.endswith(note_text):
        return None  # this exact note is already the most recent entry
    stamped = f"[{today_str()}] {note_text}"
    new_notes = f"{prior}\n{stamped}" if prior else stamped
    return {'action': 'update', 'row': existing['_row'],
            'fields': {cols['notes']: new_notes}, 'player': existing['canonical_name']}


def post_ops_chunked(ops, url, token, dry_run=True, chunk_size=10,
                     timeout=120, progress=None):
    """post_ops for big batches (post-event writes 100+ players at once).

    Why this exists (root-caused live 2026-07-02, Chris's 113-op post-event
    write): Code.gs re-scanned the whole ~4,700-row sheet per append and
    read-back-verified every field serially, so one big request blew past
    the client timeout while the script kept running server-side. Chunking
    keeps each request small enough to finish; and real writes are NEVER
    auto-retried on timeout - a timed-out real write may have SUCCEEDED
    server-side, so a blind retry could double-append players (dry runs
    stay retryable, they're read-only).

    progress: optional callable(done_ops, total_ops) for UI updates.
    Returns {'ok', 'results', 'error'?} aggregated across chunks; stops at
    the first failed chunk (results has everything up to and incl. it).
    """
    import time as _t
    all_results = []
    total = len(ops)
    for start in range(0, total, chunk_size):
        if start:
            _t.sleep(0.8)  # pacing: rapid-fire requests trip Apps Script's
                           # flaky response-echo redirect (404 seen live)
        chunk = ops[start:start + chunk_size]
        try:
            r = post_ops(chunk, url, token, dry_run=dry_run, timeout=timeout,
                         retries=2 if dry_run else 0)
        except Exception as e:
            return {'ok': False, 'results': all_results,
                    'error': f'{type(e).__name__}: {e}', 'failed_at': start,
                    'written_before_failure': 0 if dry_run else start}
        all_results.extend(r.get('results', []))
        if progress:
            progress(min(start + len(chunk), total), total)
        if not r.get('ok'):
            return {'ok': False, 'results': all_results,
                    'error': r.get('error'), 'failed_at': start,
                    'written_before_failure': 0 if dry_run else start}
    return {'ok': True, 'results': all_results}


def post_ops(ops, url, token, dry_run=True, timeout=45, retries=2):
    """Send a batch of ops to the deployed Apps Script web app. Defaults to
    dry_run=True — caller must explicitly opt into a real write.

    Apps Script web apps commonly have a slow "cold start" on the first
    request after a fresh deploy (or after sitting idle) - confirmed
    2026-06-30 when a dry-run call timed out at 30s right after a Code.gs
    redeploy, with nothing wrong in the code itself. Retries a bare
    Timeout/ConnectionError a couple times before giving up, since those
    are transient by nature - a real validation or write failure comes
    back as a normal (non-exception) response and is never retried here."""
    import time
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json={'token': token, 'dryRun': dry_run, 'ops': ops},
                                  timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
        except requests.exceptions.HTTPError as e:
            # Apps Script's response comes via a 302 to script.googleusercontent
            # .com/macros/echo?user_content_key=... and that echo URL 404s
            # intermittently under rapid successive requests (seen live
            # 2026-07-02, mid-validation). For read-only dry runs a retry is
            # always safe. For real writes it is NOT retried here: the 404
            # happens on the response fetch AFTER the script may have already
            # executed, so a blind retry could double-write - same policy as
            # timeouts.
            status = e.response.status_code if e.response is not None else 0
            if status in (401, 403):
                raise  # auth problems never fix themselves by retrying
            last_exc = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last_exc

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


def _pos_group(pos):
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
                     academic=None, email=None, phone=None):
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
                   'email': email, 'phone': phone}

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
                    fields[cols['pos_group']] = _pos_group(val)
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
    fields[cols['pos_group']] = _pos_group(pos)
    return {'action': 'append', 'fields': fields, 'player': f"{first} {last}"}


def post_ops(ops, url, token, dry_run=True, timeout=30):
    """Send a batch of ops to the deployed Apps Script web app. Defaults to
    dry_run=True — caller must explicitly opt into a real write."""
    resp = requests.post(url, json={'token': token, 'dryRun': dry_run, 'ops': ops},
                          timeout=timeout)
    resp.raise_for_status()
    return resp.json()

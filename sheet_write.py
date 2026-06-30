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
including a generated "Name" summary label matching the sheet's existing
convention (e.g. "Noah Stead (0.1) - '25 MINF CA").

"Pos Group" (e.g. RHP/INF/OF) is also a spilling array formula on the live
sheet, not real data — every write here computes and stores it as a plain
value instead, mirroring the sheet's own IFS() mapping exactly (copied from
the live formula 2026-06-30, not guessed), so new/updated rows are fully
self-consistent without depending on that formula at all.

Column map (1-indexed, matches Apps Script's getRange(row, col)) — keep in
sync with apps_script/Code.gs and db_loader.py's column comment.
"""
import requests

COL = {
    'name': 4, 'pos_group': 5, 'first': 8, 'last': 9, 'class': 10, 'tier': 11,
    'commit': 12, 'pos': 13, 'state': 17, 'hs': 18, 'team': 19, 'seen': 23,
}

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


def _name_label(first, last, tier, class_year, pos, state):
    label = f"{first} {last}".strip()
    if tier:
        label += f" ({tier})"
    yy = class_year[-2:] if class_year else ""
    tail = " ".join(x for x in [f"'{yy}" if yy else "", pos, state] if x)
    if tail:
        label += f" - {tail}"
    return label


def build_upsert_op(current_db, *, first, last, event_name, new_tier=None,
                     state=None, hs=None, team=None, pos=None, commit=None,
                     class_year=None):
    """Build one Apps Script op dict for a single post-event player review.
    Looks the player up via db_loader's existing lookup() — does not
    duplicate or weaken that matching logic."""
    from db_loader import lookup
    existing = lookup(current_db, f"{first} {last}")

    if existing:
        fields = {}
        prior_seen = existing.get('seen', '') or ''
        seen_events = [s.strip() for s in prior_seen.split(',') if s.strip()]
        if not seen_events or seen_events[-1] != event_name:
            new_seen = ', '.join(seen_events + [event_name]) if seen_events else event_name
            fields[COL['seen']] = new_seen
        if new_tier and new_tier != existing.get('tier'):
            fields[COL['tier']] = new_tier
        for key, val in (('state', state), ('hs', hs), ('team', team),
                          ('pos', pos), ('commit', commit), ('class', class_year)):
            if val and val != existing.get(key):
                fields[COL[key]] = val
                if key == 'pos':
                    fields[COL['pos_group']] = _pos_group(val)
        return {'action': 'update', 'row': existing['_row'], 'fields': fields,
                'player': existing['canonical_name']}

    fields = {COL['first']: first, COL['last']: last, COL['seen']: event_name}
    if new_tier: fields[COL['tier']] = new_tier
    if class_year: fields[COL['class']] = class_year
    if pos: fields[COL['pos']] = pos
    if commit: fields[COL['commit']] = commit
    if state: fields[COL['state']] = state
    if hs: fields[COL['hs']] = hs
    if team: fields[COL['team']] = team
    fields[COL['name']] = _name_label(first, last, new_tier, class_year, pos, state)
    fields[COL['pos_group']] = _pos_group(pos)
    return {'action': 'append', 'fields': fields, 'player': f"{first} {last}"}


def post_ops(ops, url, token, dry_run=True, timeout=30):
    """Send a batch of ops to the deployed Apps Script web app. Defaults to
    dry_run=True — caller must explicitly opt into a real write."""
    resp = requests.post(url, json={'token': token, 'dryRun': dry_run, 'ops': ops},
                          timeout=timeout)
    resp.raise_for_status()
    return resp.json()

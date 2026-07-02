"""Resolve a commit string ("LSU", "Texas A&M", "Navy") to a college logo
PNG on disk, for the roster PDF's COMMITTED block (Chris's sketch shows a
big school logo next to "COMMITTED" at the right edge of NOTES).

Source: ESPN's public team APIs — college BASEBALL first (437 teams, i.e.
every D1 baseball program: the actual commit universe, incl. baseball-only
schools like Dallas Baptist that the football list lacks), college football
second for anything else. Team lists are cached to
data/college_logos/teams.json and each downloaded logo to
data/college_logos/<league>_<id>.png, so PDF builds are offline-safe after
first use. No match -> None, caller falls back to text.
"""
import json
import os
import re

import requests

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    'data', 'college_logos')
_TEAMS_URLS = [
    ('bb', 'https://site.api.espn.com/apis/site/v2/sports/baseball/'
           'college-baseball/teams?limit=1000'),
    ('fb', 'https://site.api.espn.com/apis/site/v2/sports/football/'
           'college-football/teams?limit=1000'),
]
_teams_cache = None


def _norm(s):
    s = (s or '').lower().replace('&', 'and')
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _load_teams():
    global _teams_cache
    if _teams_cache is not None:
        return _teams_cache
    os.makedirs(_DIR, exist_ok=True)
    cache = os.path.join(_DIR, 'teams.json')
    if os.path.exists(cache):
        with open(cache) as f:
            _teams_cache = json.load(f)
        return _teams_cache
    teams = []
    seen_names = set()
    for league, url in _TEAMS_URLS:  # baseball first: it wins duplicates
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        for entry in r.json()['sports'][0]['leagues'][0]['teams']:
            t = entry['team']
            logos = t.get('logos') or []
            names = sorted({n for n in [
                t.get('displayName'), t.get('shortDisplayName'),
                t.get('name'), t.get('nickname'), t.get('location'),
                t.get('abbreviation')] if n})
            if not logos or not names:
                continue
            key = _norm(names[0])
            if key in seen_names:
                continue
            seen_names.add(key)
            teams.append({
                'id': f"{league}_{t['id']}",
                'names': names,
                'logo': logos[0]['href'],
            })
    with open(cache, 'w') as f:
        json.dump(teams, f)
    _teams_cache = teams
    return teams


def _match(commit_text):
    """Best team for a free-text commit string. Exact normalized name/abbrev
    match first; then whole-word containment. Deliberately conservative --
    a wrong school logo on a recruiting PDF is worse than no logo."""
    q = _norm(commit_text)
    if not q:
        return None
    teams = _load_teams()
    for t in teams:
        if any(_norm(n) == q for n in t['names']):
            return t
    q_words = set(q.split())
    best = None
    for t in teams:
        for n in t['names']:
            nw = set(_norm(n).split())
            if nw and (nw <= q_words or q_words <= nw):
                cand = (len(nw), t)
                if best is None or cand[0] > best[0]:
                    best = cand
    return best[1] if best else None


def logo_path(commit_text):
    """Local PNG path for the school in commit_text, or None."""
    try:
        t = _match(commit_text)
        if not t:
            return None
        path = os.path.join(_DIR, f"{t['id']}.png")
        if not os.path.exists(path):
            r = requests.get(t['logo'], timeout=20)
            r.raise_for_status()
            with open(path, 'wb') as f:
                f.write(r.content)
        return path
    except Exception:
        return None  # logos are a nice-to-have; never break a PDF build

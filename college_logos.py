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
    seen_schools = set()
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
            # Dedup by SCHOOL IDENTITY (displayName), not the alphabetically
            # first name — the old key collided on shared mascots ("Bulldogs",
            # "Tigers"), silently dropping Georgia, Oklahoma State, etc. from
            # the bank entirely. displayName ("Georgia Bulldogs") is unique
            # per school and identical across the baseball/football lists, so
            # baseball still wins the cross-league dupe.
            key = _norm(t.get('displayName') or names[0])
            if key in seen_schools:
                continue
            seen_schools.add(key)
            teams.append({
                'id': f"{league}_{t['id']}",
                'names': names,
                'logo': logos[0]['href'],
            })
    with open(cache, 'w') as f:
        json.dump(teams, f)
    _teams_cache = teams
    return teams


# Grammatical filler only. A commit's leftover words (after a team name is
# matched) may ONLY be these for a team-name-is-subset match to count, so
# "University of Florida" -> Florida works, but "Massachusetts Maritime
# Academy" does NOT collapse to Massachusetts (maritime/academy aren't
# filler). Deliberately excludes college/state/academy/community, which are
# distinctive (Boston College vs Boston University; Florida vs Florida State).
_FILLER = {'university', 'of', 'the', 'at', 'a', 'and'}


def _match(commit_text):
    """Best team for a free-text commit string, scored to avoid wrong logos
    (a wrong school logo is worse than none):
      4 exact normalized name/abbrev
      3 significant words equal
      2 commit words fully inside the team name (e.g. "Miami" -> Miami Hurricanes)
      1 team name is the commit's distinctive core (leftover is filler only,
        e.g. "University of Florida" -> Florida) — the guarded direction
    A school not in the bank (JUCO/D2/D3) that shares one word with a D1
    school (Mass Maritime vs Massachusetts) now scores nothing -> None."""
    # drop parentheticals first: "Louisiana State University (LSU)" would
    # otherwise inject a stray "lsu" token that blocks the filler match.
    q = _norm(re.sub(r'\([^)]*\)', ' ', commit_text or ''))
    if not q:
        return None
    q_words = set(q.split())
    teams = _load_teams()
    best = None  # (score, name_word_count, team)
    for t in teams:
        for n in t['names']:
            nq = _norm(n)
            nw = set(nq.split())
            if not nw:
                continue
            if nq == q:
                score = 4
            elif nw == q_words:
                score = 3
            elif q_words <= nw:
                score = 2
            elif nw <= q_words and (q_words - nw) <= _FILLER:
                score = 1
            else:
                continue
            cand = (score, len(nw), t)
            if best is None or cand[:2] > best[:2]:
                best = cand
    return best[2] if best else None


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

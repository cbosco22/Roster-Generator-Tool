"""
pbr_crawler.py
--------------
Broad shallow scrape of Prep Baseball Report player profile pages for
Tier 1/Tier 2 enrichment (measurables: 60 time, exit velo, arm velo, bat
speed, etc.) that don't live in pbr_rankings.pkl (which only has
rank/name/class/state/commit).

Two-step per player, same pattern as _pbr_match() in gen_roster_pdf.py
(cross-validate on grad year + state to avoid the "John Smith problem"):

  1. resolve_profile()  -- POST the site's own search form, pick the best
     matching row from the results table.
  2. fetch_profile()    -- GET the profile page, parse the bio + the
     "dynamic-stat-box" measurable carousel.

No login required for either step -- verified by hand against a live
profile (Dylan Seward, CA '27): the search form, results table and stat
carousel are all in the plain server-rendered HTML. Only the numeric
national/state RANK and videos are gated behind a PBR+ subscription --
irrelevant here since pbr_rankings.pkl already has rank.

Usage:
    python3 pbr_crawler.py --input players.json --out crawler_output.json
    python3 pbr_crawler.py --test   # smoke test against 3 known players

players.json shape: [{"name": "...", "grad_year": "2027", "state": "CA", "school": "..."}]
"""

import argparse
import json
import re
import sys
import time
import datetime as _dt

import requests
from bs4 import BeautifulSoup

BASE = "https://www.prepbaseballreport.com"
SEARCH_URL = f"{BASE}/profile-search-results"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
THROTTLE_SEC = 2.0

# player_state select values, scraped from the live search form on prepbaseballreport.com
STATE_CODES = {
    "AL": 31, "AK": 32, "AZ": 33, "AR": 20, "CA": 34, "CO": 13, "CT": 28, "DE": 35,
    "FL": 16, "GA": 36, "HI": 37, "ID": 38, "IL": 2, "IN": 3, "IA": 14, "KS": 11,
    "KY": 8, "LA": 22, "ME": 25, "MD": 23, "MA": 21, "MI": 6, "MN": 15, "MS": 39,
    "MO": 4, "MT": 40, "NE": 41, "NV": 42, "NH": 27, "NJ": 30, "NM": 43, "NY": 17,
    "NC": 44, "ND": 45, "OH": 5, "OK": 46, "OR": 47, "PA": 7, "PR": 54, "RI": 29,
    "SC": 48, "SD": 49, "TN": 18, "TX": 50, "UT": 51, "VT": 26, "VA": 12, "WA": 52,
    "DC": 81, "WV": 10, "WI": 9, "WY": 53,
}


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def search_pbr(session, name, grad_year=None, state=None, school=None):
    """
    POST the site's own "Find a Player" form. Returns a list of candidate
    rows: {"name", "state", "school", "class", "position", "commit", "profile_path"}.
    """
    # player_position must always be present in the POST (even as "#") or the
    # site's search silently returns zero results -- found by diffing a real
    # browser submission against this script's request 2026-07-01.
    data = {"player_name": name, "player_state": "#", "player_class": "#",
            "player_school": "", "player_position": "#"}
    if state and state.upper() in STATE_CODES:
        data["player_state"] = str(STATE_CODES[state.upper()])
    if grad_year:
        data["player_class"] = str(grad_year)
    if school:
        data["player_school"] = school

    r = session.post(SEARCH_URL, data=data, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    rows = []
    for a in soup.select('a[href^="/profiles/"]'):
        href = a.get("href", "")
        tr = a.find_parent("tr")
        cells = [td.get_text(strip=True) for td in tr.find_all("td")] if tr else []
        # NAME, STATE, SCHOOL, CLASS, POSITION, COMMITMENT (order confirmed live 2026-07-01)
        row = {
            "name": a.get_text(strip=True),
            "state": cells[1] if len(cells) > 1 else "",
            "school": cells[2] if len(cells) > 2 else "",
            "class": cells[3] if len(cells) > 3 else "",
            "position": cells[4] if len(cells) > 4 else "",
            "commit": cells[5] if len(cells) > 5 else "",
            "profile_path": href,
        }
        rows.append(row)
    return rows


def resolve_profile(session, name, grad_year=None, state=None, school=None):
    """
    Cross-validates candidates the same way _pbr_match() does in
    gen_roster_pdf.py: grad year + state must agree with what we already
    know about the player, to avoid the "John Smith problem".
    Returns (profile_path, reason) -- profile_path is None on failure.
    """
    candidates = search_pbr(session, name, grad_year=grad_year, state=state, school=school)
    if not candidates:
        return None, "no_results"

    target = _norm(name)
    exact = [c for c in candidates if _norm(c["name"]) == target]
    pool = exact or candidates

    def _valid(c):
        yr_ok = (not grad_year) or (str(c["class"]) == str(grad_year))
        st_ok = (not state) or (c["state"].upper() == state.upper())
        return yr_ok and st_ok

    valid = [c for c in pool if _valid(c)]
    if len(valid) == 1:
        return valid[0]["profile_path"], "matched"
    if len(valid) > 1:
        return valid[0]["profile_path"], "ambiguous_took_first"
    if len(pool) == 1 and not (grad_year or state):
        return pool[0]["profile_path"], "matched_no_context"
    return None, "no_confident_match"


def fetch_profile(session, profile_path):
    """
    GET a resolved profile page. Returns a dict of bio + measurable fields.
    Field set varies by player (a pitcher won't have INF VELO, etc.) --
    this crawler captures whatever cards the page actually has rather
    than assuming a fixed schema.
    """
    url = BASE + profile_path if profile_path.startswith("/") else profile_path
    r = session.get(url, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    out = {"profile_path": profile_path, "scraped_at": _dt.datetime.now(_dt.timezone.utc).isoformat()}

    header = soup.select_one("h1") or soup.select_one(".player-name")
    out["name"] = header.get_text(" ", strip=True) if header else ""

    # bio fragments ("5' 11\" - 171.7LBS", "S/R - 17yr 9mo", "Travel Team: ...")
    # live as loose text next to the verified-height icon -- isolate that one
    # small block instead of the whole page (whose text otherwise runs
    # together and breaks these regexes).
    lbs_node = soup.find(string=re.compile("LBS"))
    bio_text = lbs_node.parent.get_text(" ", strip=True) if lbs_node else ""
    m = re.search(r"(\d)'\s*(\d{1,2})\"?\s*\S?\s*([\d.]+)\s*LBS", bio_text, re.I)
    if m:
        out["height"] = f"{m.group(1)}-{m.group(2)}"
        out["weight"] = m.group(3)
    m = re.search(r"Travel Team:\s*(.+)$", bio_text)
    if m:
        out["travel_team"] = m.group(1).strip()

    commit_el = soup.select_one(".commitment, [class*=commit]")
    if commit_el:
        out["commitment"] = re.sub(r"^Commitment\s*", "", commit_el.get_text(" ", strip=True))

    # measurable stat cards: <div class="dynamic-stat-box stat"><strong>91</strong><span>INF<br>VELO</span></div>
    measurables = {}
    for box in soup.select(".dynamic-stat-box.stat"):
        val_el = box.find("strong")
        lbl_el = box.find("span")
        if not val_el or not lbl_el:
            continue
        label = lbl_el.get_text(" ", strip=True)
        label = re.sub(r"\s+", " ", label).strip().upper()
        measurables[label] = val_el.get_text(strip=True)
    out["measurables"] = measurables

    return out


def crawl(players, throttle=THROTTLE_SEC, log=print):
    """
    players: list of {"name", "grad_year", "state", "school"}.
    Returns (results, unmatched) -- results have profile_path as the join
    key back to the recruiting sheet / players.parquet.
    """
    session = _session()
    results, unmatched = [], []
    for i, p in enumerate(players):
        name = p.get("name", "").strip()
        if not name:
            continue
        try:
            profile_path, reason = resolve_profile(
                session, name, grad_year=p.get("grad_year"), state=p.get("state"), school=p.get("school")
            )
        except requests.RequestException as e:
            log(f"[{i+1}/{len(players)}] {name}: search failed ({e})")
            unmatched.append({**p, "reason": "search_error"})
            continue
        time.sleep(throttle)

        if not profile_path:
            log(f"[{i+1}/{len(players)}] {name}: {reason}")
            unmatched.append({**p, "reason": reason})
            continue

        try:
            profile = fetch_profile(session, profile_path)
        except requests.RequestException as e:
            log(f"[{i+1}/{len(players)}] {name}: profile fetch failed ({e})")
            unmatched.append({**p, "reason": "fetch_error", "profile_path": profile_path})
            continue
        time.sleep(throttle)

        profile["query"] = p
        profile["match_reason"] = reason
        results.append(profile)
        log(f"[{i+1}/{len(players)}] {name}: {reason} -> {profile_path} "
            f"({len(profile['measurables'])} measurables)")

    return results, unmatched


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="JSON file: [{name, grad_year, state, school}]")
    ap.add_argument("--out", default="pbr_crawler_output.json")
    ap.add_argument("--test", action="store_true", help="Smoke test against 3 known players")
    args = ap.parse_args()

    if args.test:
        players = [
            {"name": "Dylan Seward", "grad_year": "2027", "state": "CA"},
            {"name": "Connor Salerno", "grad_year": "2027"},
            {"name": "Grant Westphal", "grad_year": "2027", "state": "TX"},
        ]
    elif args.input:
        with open(args.input) as f:
            players = json.load(f)
    else:
        ap.error("Provide --input players.json or --test")
        sys.exit(1)

    results, unmatched = crawl(players)
    with open(args.out, "w") as f:
        json.dump({"scraped_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    "results": results, "unmatched": unmatched}, f, indent=2)
    print(f"\n{len(results)} matched, {len(unmatched)} unmatched -> {args.out}")

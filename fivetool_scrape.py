"""
fivetool_scrape.py — scrape a whole FiveTool event (teams + rosters) with
plain HTTP. No Chrome, no extension, no login.

Verified live 2026-07-02 against the AABC Don Mattingly World Series event:
FiveTool event pages and team roster pages are fully public, server-rendered
HTML (148 team links + complete rosters straight from `requests`). Only the
per-player profile extras (GPA/contact) are login-gated — rosters are not.
This replaces the Chrome-extension step for FiveTool events and produces the
exact same JSON shape the extension did, so everything downstream
(run_event.py, push_event.py, navy-event-day ingest) works unchanged.

Player rows also carry the player's fivetool.org profile URL — that UUID is
the key the future login-gated enrichment pass will need, captured now so
that pass never has to re-scrape rosters.

USAGE:
    python3 fivetool_scrape.py <event url> [--out event.json]
    # any event page URL works: .../events/<slug>, .../events/<slug>/teams, etc.
"""
import argparse
import datetime as _dt
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36"}
THROTTLE_SEC = 0.4
WORKERS = 4  # light parallelism, same spirit as api/refresh.py's PG scraper


def _get(session, url):
    r = session.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text


def _event_teams_url(url):
    """Normalize any event page URL to its /teams page."""
    m = re.match(r"(https?://events\.fivetool\.org/events/[^/?#]+)", url.strip())
    if not m:
        raise ValueError(f"Not a FiveTool event URL: {url}")
    return m.group(1) + "/teams", m.group(1)


def _clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def scrape_team(session, team_url, team_name=""):
    """One team roster page -> {'name','url','players':[...]} (extension-shape).
    team_name comes from the event page's team-link text (the roster page
    itself has no clean h1 - only a suffixed <title>)."""
    soup = BeautifulSoup(_get(session, team_url), "html.parser")
    if not team_name:
        title = soup.select_one("title")
        team_name = _clean((title.get_text() if title else "").split("Team Profile")[0])
    players = []
    for tr in soup.select("tbody tr"):
        cells = {}
        for td in tr.find_all("td"):
            label = _clean(td.get("data-title", ""))
            if not label:
                continue
            cells[label] = _clean(td.get_text(" "))
        if not cells.get("Name"):
            continue
        prof = tr.select_one('a.player_profile_link[href*="fivetool.org/players/"]')
        city = cells.get("City", "")
        state = cells.get("State", "")
        players.append({
            "_raw": cells,
            "jersey": cells.get("#", ""),
            "name": cells.get("Name", ""),
            "grad": cells.get("Grad Year - HS", ""),
            "hs": cells.get("High School", ""),
            "state": state,
            "city": city,
            "hometown": f"{city}, {state}" if city and state else (city or state),
            "pos": cells.get("Primary Pos", ""),
            "pos2": cells.get("Sec. Pos", ""),
            "commit": cells.get("College Committed To", ""),
            "bt": cells.get("H/T", ""),
            "ht": cells.get("HEIGHT", ""),
            "wt": cells.get("Weight", ""),
            "profile_url": prof["href"] if prof else "",
        })
    return {"name": team_name, "url": team_url, "players": players}


def scrape_event(event_url, log=print):
    session = requests.Session()
    teams_url, base_url = _event_teams_url(event_url)
    html = _get(session, teams_url)
    soup = BeautifulSoup(html, "html.parser")

    # Event name lives in <title> as
    # "AABC Don Mattingly World Series 07/07/2026 - 07/12/2026 - Baseball
    # Tournaments | Five Tool Baseball" (no h1 on the page) - keep name+dates,
    # drop the site suffix. run_event.py already parses that date range out.
    title = soup.select_one("title")
    event_name = _clean((title.get_text() if title else "")
                        .split(" - Baseball Tournaments")[0])

    team_links = []
    seen = set()
    for a in soup.select('a[href*="/team/details/"]'):
        href = urljoin(teams_url, a["href"])
        name = _clean(a.get_text(" "))
        if href not in seen and name:
            seen.add(href)
            team_links.append((href, name))
    log(f"{event_name or event_url}: {len(team_links)} teams")

    teams = []
    def _one(url, name):
        time.sleep(THROTTLE_SEC)
        return scrape_team(session, url, team_name=name)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_one, u, n): u for u, n in team_links}
        for i, fut in enumerate(as_completed(futures)):
            t = fut.result()
            teams.append(t)
            log(f"[{i+1}/{len(team_links)}] {t['name']} — {len(t['players'])} players")
    teams.sort(key=lambda t: t["name"].lower())

    return {
        "event": event_name or "Event",
        "url": base_url,
        "site": "fivetool",
        "scrapedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "dates": None,
        "source": None,
        "schedule_team_divs": {},
        "teams": teams,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="FiveTool event URL (any page of the event)")
    ap.add_argument("--out", default="fivetool_event.json")
    args = ap.parse_args()
    data = scrape_event(args.url)
    with open(args.out, "w") as f:
        json.dump(data, f, indent=1)
    n = sum(len(t["players"]) for t in data["teams"])
    print(f"\n{data['event']}: {len(data['teams'])} teams, {n} players -> {args.out}")

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


# FiveTool built the platform; Prospect Select and PBR run the same code on
# their own hosts (verified live 2026-07-02: identical /schedule_ajax,
# window.EVENT_ID, team-detail pages). PBR (prepbaseballreport) is
# Cloudflare-walled to plain requests, so it needs the browser path.
_PLATFORM_HOSTS = {
    "events.fivetool.org": "/events/",
    "play.ps-baseball.com": "/public/events/",
    "tournaments.prepbaseballreport.com": "/public/events/",
}


def _platform_host(url):
    from urllib.parse import urlparse
    return urlparse(url).netloc.lower()


def _event_teams_url(url):
    """Normalize any FiveTool-platform event URL to its /teams page.
    Returns (teams_url, base_url, host)."""
    host = _platform_host(url)
    prefix = _PLATFORM_HOSTS.get(host)
    if not prefix:
        raise ValueError(f"Not a FiveTool-platform event URL: {url}")
    m = re.match(rf"(https?://{re.escape(host)}{re.escape(prefix)}[^/?#]+)", url.strip())
    if not m:
        raise ValueError(f"Not a recognizable event URL for {host}: {url}")
    return m.group(1) + "/teams", m.group(1), host


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
    teams_url, base_url, host = _event_teams_url(event_url)
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




def scrape_schedule(event_url, log=print, venue_addresses=True):
    """Scrape the event's full schedule server-side -> {'games': [...],
    'venues': [{'venue','address','games'}], 'hub': {'name','address'}}.

    How (found by watching the page's own network traffic, 2026-07-02):
    the /schedule/all page is a Vue shell; games come from
    POST /schedule_ajax with the CSRF token from the page's meta tag and
    the event id from `window.EVENT_ID = "NNNN"` in the page source.
    Venue street addresses come from POST /venue_by_field per field id.
    games match the Chrome-extension schedule shape exactly, so
    gen_schedule_csv.build_schedule_csv() consumes them unchanged.
    """
    session = requests.Session()
    _, base_url, host = _event_teams_url(event_url)
    page = _get(session, base_url + "/schedule/all")
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', page)
    event_id = re.search(r'window\.EVENT_ID\s*=\s*"(\d+)"', page)
    if not csrf or not event_id:
        raise RuntimeError("schedule page missing csrf/event id - layout changed?")
    hh = {**HEADERS, "X-CSRF-TOKEN": csrf.group(1),
          "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"}
    r = session.post(f"https://{host}/schedule_ajax", headers=hh,
                     json={"event_id": event_id.group(1), "event_price_id": "0",
                           "event_registration_item_id": 0, "schedule_id": 0,
                           "data_type": "schedules"}, timeout=40)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not data.get("schedules"):
        return {"games": [], "venues": [], "hub": None}

    games, field_ids, venue_game_counts = [], {}, {}
    for day in data["schedules"].values():
        date = day.get("date", "")
        raw_teams = day.get("teams") or []
        # PHP serialization quirk: a day's games arrive as a LIST when keys
        # are contiguous and as a DICT otherwise (seen live on day 2+)
        if isinstance(raw_teams, dict):
            raw_teams = list(raw_teams.values())
        for g in raw_teams:
            if not isinstance(g, dict):
                continue
            loc = _clean(g.get("location", ""))
            games.append({
                "game": str(g.get("game_number", "")),
                "date": date,
                "time": _clean(g.get("time", "")),
                "location": loc,
                "division": _clean(g.get("division", "")),
                "team1": _clean(g.get("team_name_1", "")),
                "team2": _clean(g.get("team_name_2", "")),
                "score": "",
            })
            if g.get("field_id"):
                field_ids.setdefault(loc, g["field_id"])
            venue_game_counts[loc] = venue_game_counts.get(loc, 0) + 1
    log(f"schedule: {len(games)} games across {len(data['schedules'])} days, "
        f"{len(field_ids)} fields")

    venues, seen_names = [], set()
    if venue_addresses:
        for loc, fid in field_ids.items():
            time.sleep(0.3)
            try:
                vr = session.post(f"https://{host}/venue_by_field",
                                  headers=hh, json={"field_id": fid,
                                                    "event_id": event_id.group(1)},
                                  timeout=20)
                soup = BeautifulSoup(vr.json().get("html", ""), "html.parser")
                name_el = soup.select_one("h2")
                vname = _clean(name_el.get_text()) if name_el else loc
                txt = _clean(soup.get_text(" ", strip=True))
                m = re.search(r"(\d+[^|]*?\b[A-Z]{2}\s+\d{5})", txt)
                addr = _clean(m.group(1)) if m else ""
                if vname in seen_names:
                    for v in venues:
                        if v["venue"] == vname:
                            v["games"] += venue_game_counts.get(loc, 0)
                else:
                    seen_names.add(vname)
                    venues.append({"venue": vname, "address": addr,
                                   "games": venue_game_counts.get(loc, 0)})
            except Exception:
                if loc not in seen_names:
                    seen_names.add(loc)
                    venues.append({"venue": loc, "address": "",
                                   "games": venue_game_counts.get(loc, 0)})
    # hub = the venue hosting the most games (the event's home complex)
    hub = max(venues, key=lambda v: v.get("games", 0)) if venues else None
    return {"games": games, "venues": venues,
            "hub": {"name": hub["venue"], "address": hub["address"]} if hub else None}


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

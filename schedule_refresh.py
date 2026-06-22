"""
schedule_refresh.py
-------------------
Perfect Game schedule  ->  Feed builder for the Navy recruiting sheet.

A coach pastes ANY one day's PG "TournamentSchedule" URL, e.g.
    https://www.perfectgame.org/Events/TournamentSchedule.aspx?event=141563&Date=06/23/2026
and this:
  1. reads the event id from the URL,
  2. discovers every day of that event from the date strip,
  3. pulls each day server-side (no Chrome extension needed),
  4. parses it into a clean feed: Game# | Date | Time | Location (+ GameID, Team1, Team2),
  5. lets the coach download feed.csv and paste columns A-D into the sheet's `Feed` tab.

Game number is unique across the whole event (Tue 1-186, Wed 187-..., etc.),
so Game# alone is the join key the sheet's XLOOKUP formulas use.

Integration (see notes at bottom):
  - add `beautifulsoup4` to requirements.txt
  - drop this file in the repo
  - add a tab that calls schedule_refresh.render()
"""

import re
import io
import json
import datetime as _dt
from urllib.parse import urlparse, parse_qs

import requests
import pandas as pd
import streamlit as st

try:
    from bs4 import BeautifulSoup
    _HAVE_BS4 = True
except ImportError:  # graceful fallback; bs4 strongly recommended
    _HAVE_BS4 = False

# --------------------------------------------------------------------------- #
# constants / patterns
# --------------------------------------------------------------------------- #
PG_SCHEDULE = "https://www.perfectgame.org/Events/TournamentSchedule.aspx"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_GID_RE  = re.compile(r"GameID:\s*(\d+)", re.I)
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*[AP]M)", re.I)
_TEAM_SEL = 'a[href*="Tournaments/Teams/Default.aspx?team="]'

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# Date discovery — three independent, encoding-proof sources:
# (A) the visible day strip "Tue Jun 23 183 Games" (primary; plain text)
_DAYLABEL_RE = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"(\d{1,2})\s+\d+\s+Games?", re.I)
# (B) explicit Date= params, tolerant of &amp;(-> ;), %2F, padding, param order
_DATEPARAM_RE = re.compile(
    r"(?<![A-Za-z])Date=\s*(\d{1,2})(?:/|%2[Ff])(\d{1,2})(?:/|%2[Ff])(\d{4})", re.I)
# (C) event range header "Jun 23-30" / "Jun 28-Jul 2" (fallback enumeration)
_RANGE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\s*"
    r"(?:-|\u2013|\u2014|to)\s*"
    r"(?:(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?(\d{1,2})\b",
    re.I)

FEED_COLUMNS = ["Game#", "Date", "Time", "Location", "GameID", "Team1", "Team2"]


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _event_id(url: str) -> str:
    ev = parse_qs(urlparse(url).query).get("event", [None])[0]
    if not ev:
        raise ValueError("That URL has no `event=` id. Paste a TournamentSchedule link.")
    return ev


def _fetch(url: str) -> str:
    r = requests.get(url, headers=_HEADERS, timeout=25)
    r.raise_for_status()
    return r.text


def _day_url(event_id: str, date_str: str) -> str:
    return f"{PG_SCHEDULE}?event={event_id}&Date={date_str}"


def _get_html(url: str, cache: dict) -> str:
    if url not in cache:
        cache[url] = _fetch(url)
    return cache[url]


def _url_date(url: str):
    """The Date= already in the pasted URL, normalized to 'M/D/YYYY' (or None)."""
    q = parse_qs(urlparse(url).query)
    raw = (q.get("Date") or q.get("date") or [None])[0]
    if not raw:
        return None
    m = re.match(r"(\d{1,2})\D(\d{1,2})\D(\d{4})", raw)
    return f"{int(m.group(1))}/{int(m.group(2))}/{int(m.group(3))}" if m else None


def _date_key(s: str) -> _dt.date:
    mo, da, yr = (int(x) for x in s.split("/"))
    return _dt.date(yr, mo, da)


def _fmt_date(date_str: str) -> str:
    """6/23/2026 -> 'Tuesday, 6/23' (matches the sheet's Date column)."""
    d = _date_key(date_str)
    return f"{d.strftime('%A')}, {d.month}/{d.day}"


def _discover_dates(html: str, url: str) -> list:
    """All event dates as 'M/D/YYYY', deduped & sorted. Pulls from three
    encoding-proof sources — the visible day strip, explicit Date= params, and
    (only if those look thin) the event's range header — plus the URL's own date."""
    seen, yr = set(), None

    # (B) explicit Date= params carry their own year
    for m in _DATEPARAM_RE.finditer(html):
        try:
            seen.add(_dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))))
            yr = yr or int(m.group(3))
        except ValueError:
            pass

    # the date already in the pasted URL (and a year hint)
    ud = _url_date(url)
    if ud:
        d = _date_key(ud)
        seen.add(d)
        yr = yr or d.year
    yr = yr or _dt.date.today().year

    # (A) visible day strip "Tue Jun 23 183 Games"
    for m in _DAYLABEL_RE.finditer(html):
        try:
            seen.add(_dt.date(yr, _MONTHS[m.group(1).lower()[:3]], int(m.group(2))))
        except (ValueError, KeyError):
            pass

    # (C) range header "Jun 23-30" — only lean on it if we still look thin
    if len(seen) <= 1:
        rm = _RANGE_RE.search(html)
        if rm:
            try:
                m1 = _MONTHS[rm.group(1).lower()[:3]]
                m2 = _MONTHS[rm.group(3).lower()[:3]] if rm.group(3) else m1
                start = _dt.date(yr, m1, int(rm.group(2)))
                end = _dt.date(yr if m2 >= m1 else yr + 1, m2, int(rm.group(4)))
                cur = start
                while cur <= end:
                    seen.add(cur)
                    cur += _dt.timedelta(days=1)
            except (ValueError, KeyError):
                pass

    return [f"{d.month}/{d.day}/{d.year}" for d in sorted(seen)]


def _page_text(html: str) -> str:
    if _HAVE_BS4:
        return BeautifulSoup(html, "html.parser").get_text("\n")
    # crude fallback if bs4 is unavailable
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", "\n", t)
    return t


def _block_teams(block_html: str) -> tuple:
    """Team names scoped to a single game's HTML block (handles a missing
    'Home'/'Bye' placeholder that has no team link)."""
    if not _HAVE_BS4:
        return "", ""
    names = [a.get_text(strip=True)
             for a in BeautifulSoup(block_html, "html.parser").select(_TEAM_SEL)]
    return (names[0] if names else ""), (names[1] if len(names) > 1 else "")


def _location_from(lines_after_gid: list) -> str:
    """Rebuild 'Field 1 @ East Cobb Complex' from the lines that follow the
    GameID line. The ballpark is a maps <a>, so get_text() may split it onto
    its own line; handle the common renderings."""
    a = [ln for ln in lines_after_gid if ln]
    if not a:
        return ""
    first = a[0]
    # "X @ Y" already on one line
    if "@" in first and not first.rstrip().endswith("@"):
        right = first.split("@", 1)[1].strip()
        if right:
            return re.sub(r"\s*@\s*", " @ ", first).strip()
    # "X @" then ballpark on next line
    if first.rstrip().endswith("@"):
        prefix = first.rstrip()[:-1].strip()
        ballpark = a[1] if len(a) > 1 else ""
        return f"{prefix} @ {ballpark}".strip()
    # "X" / "@" / "Y" across three lines
    if len(a) >= 3 and a[1].strip() == "@":
        return f"{a[0].strip()} @ {a[2].strip()}".strip()
    # fallback
    return " ".join(a[:2]).strip()


def _parse_day(html: str, date_str: str) -> list:
    """Parse one day's schedule page. We split the RAW html on the 'Gm#'
    marker so each block holds exactly one game; team links are then scoped
    to that block. Core fields come from the block's text."""
    label = _fmt_date(date_str)
    blocks = re.split(r"Gm#\s*", html)[1:]      # drop the page preamble
    rows = []
    for blk in blocks:
        btext = _page_text(blk)
        gnum_m = re.match(r"\s*(\d+)", btext)
        time_m = _TIME_RE.search(btext[:80])
        if not (gnum_m and time_m):
            continue
        gid_m = _GID_RE.search(btext)

        lines = [ln.strip() for ln in btext.splitlines()]
        loc = ""
        if gid_m:
            for j, ln in enumerate(lines):
                if "GameID:" in ln:
                    loc = _location_from(lines[j + 1:])
                    break

        t1, t2 = _block_teams(blk)
        rows.append({
            "Game#": int(gnum_m.group(1)),
            "Date": label,
            "Time": re.sub(r"\s+", " ", time_m.group(1)).upper(),
            "Location": loc,
            "GameID": gid_m.group(1) if gid_m else "",
            "Team1": t1,
            "Team2": t2,
        })
    return rows


def _probe_range(event_id: str, seed_str: str, cache: dict) -> list:
    """Last-resort discovery: walk outward from the seed date, keeping days that
    return at least one game. Bounded so it always terminates."""
    seed = _date_key(seed_str)
    found = []
    for direction, limit in ((1, 21), (-1, 14)):       # forward incl. seed, then back
        d = seed if direction == 1 else seed - _dt.timedelta(days=1)
        for _ in range(limit):
            ds = f"{d.month}/{d.day}/{d.year}"
            if _parse_day(_get_html(_day_url(event_id, ds), cache), ds):
                found.append(d)
                d += _dt.timedelta(days=direction)
            else:
                break
    return [f"{d.month}/{d.day}/{d.year}" for d in sorted(set(found))]


def build_feed(url: str, progress=None) -> pd.DataFrame:
    """Fetch every day of the event in `url` and return the feed DataFrame."""
    event_id = _event_id(url)
    cache = {}

    seed_str = _url_date(url)
    seed_url = _day_url(event_id, seed_str) if seed_str else url
    seed_html = _get_html(seed_url, cache)

    dates = _discover_dates(seed_html, url)
    if len(dates) <= 1 and seed_str:                    # discovery came up thin
        probed = _probe_range(event_id, seed_str, cache)
        if len(probed) > len(dates):
            dates = probed
    if not dates and seed_str:
        dates = [seed_str]

    all_rows = []
    for n, ds in enumerate(dates):
        if progress is not None:
            progress(n / max(len(dates), 1), f"Reading {_fmt_date(ds)} ...")
        all_rows.extend(_parse_day(_get_html(_day_url(event_id, ds), cache), ds))
    if progress is not None:
        progress(1.0, "Done")

    df = pd.DataFrame(all_rows, columns=FEED_COLUMNS)
    if not df.empty:
        df = (df.drop_duplicates(subset=["Game#"])
                .sort_values("Game#")
                .reset_index(drop=True))
    return df


SCRAPE_COLUMNS = ["Game#", "Date", "Time", "Location", "Division", "Team1", "Team2"]


def _norm_scrape_date(s: str) -> str:
    """Extension dates look like 'THURSDAY - JUNE 05, 2025' -> 'Thursday, 6/5'.
    Falls back to other common forms, then to the raw string."""
    s = (s or "").strip()
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", s)   # 'JUNE 05, 2025'
    if m:
        mon = _MONTHS.get(m.group(1).lower()[:3])
        if mon:
            try:
                return _fmt_date(f"{mon}/{int(m.group(2))}/{int(m.group(3))}")
            except ValueError:
                pass
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)        # '6/5/2025'
    if m:
        yr = int(m.group(3))
        yr += 2000 if yr < 100 else 0
        try:
            return _fmt_date(f"{int(m.group(1))}/{int(m.group(2))}/{yr}")
        except ValueError:
            pass
    return s


def feed_from_scrape(text: str) -> pd.DataFrame:
    """Reshape the extension's scraped schedule JSON (FiveTool / PBR / Prospect
    Select) into the same Feed. Accepts the full {…, games:[…]} object or a bare
    games list."""
    data = json.loads(text)
    games = data.get("games", []) if isinstance(data, dict) else data
    if not isinstance(games, list):
        raise ValueError("JSON has no 'games' list.")

    rows = []
    for g in games:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("game", "")).strip().lstrip("#").strip()
        if not gid:
            continue
        rows.append({
            "Game#": gid,
            "Date": _norm_scrape_date(str(g.get("date", ""))),
            "Time": re.sub(r"\s+", " ", str(g.get("time", ""))).strip().upper(),
            "Location": str(g.get("location", "")).strip(),
            "Division": str(g.get("division", "")).strip(),
            "Team1": str(g.get("team1", "")).strip(),
            "Team2": str(g.get("team2", "")).strip(),
        })

    df = pd.DataFrame(rows, columns=SCRAPE_COLUMNS)
    # keep scraped (chronological) order; if game numbers are all integers, sort them
    if not df.empty and df["Game#"].str.fullmatch(r"\d+").all():
        df = (df.assign(_n=df["Game#"].astype(int))
                .sort_values("_n").drop(columns="_n").reset_index(drop=True))
    return df
def _show_feed(df, *, empty_msg: str, collision_check: bool = False):
    """Render results identically for both sources: summary, copy box, download."""
    if df is None or df.empty:
        st.error(empty_msg)
        return

    days = list(dict.fromkeys(df["Date"].tolist()))
    numeric = df["Game#"].astype(str).str.fullmatch(r"\d+").all()
    head = f"{len(df)} games across {len(days)} day(s)"
    if numeric:
        nums = df["Game#"].astype(int)
        head += f"  ·  Game # {nums.min()}–{nums.max()}"
    st.success(head)
    st.caption("Days covered: " + "  ·  ".join(d for d in days if d))

    if collision_check:
        ser = df["Game#"].astype(str)
        dups = ser[ser.duplicated(keep=False)]
        if not dups.empty:
            ex = ", ".join(sorted(set(dups))[:6])
            st.warning(
                f"Some game numbers repeat across the event ({ex} …). On this "
                "platform the game number may not be unique event-wide, so the sheet "
                "may need a Date+Game# key. Tell me and I'll wire that variant.")

    st.dataframe(df, use_container_width=True, hide_index=True)

    core = df[["Game#", "Date", "Time", "Location"]]
    st.markdown("**Copy into the Feed tab**")
    st.caption("Tap the copy icon (top-right of the box), then paste into cell "
               "**A1** of the `Feed` tab — it overwrites the four columns and the "
               "main schedule updates itself.")
    st.code(core.to_csv(index=False, sep="\t"), language=None)
    st.download_button("⬇️  Or download feed.csv",
                       data=df.to_csv(index=False).encode("utf-8"),
                       file_name="feed.csv", mime="text/csv",
                       use_container_width=True)
    st.info("First time wiring up the sheet? See **First-time setup** at the top.")


def render():
    st.subheader("Schedule Refresh")
    st.caption(
        "Build the **Feed** for the schedule sheet. For Perfect Game, paste any "
        "one day's link and it pulls the whole event. For FiveTool / PBR / Prospect "
        "Select, scrape with the extension and paste the JSON. Either way you get the "
        "same Game# / Date / Time / Location feed — copy columns A–D into the **Feed** tab."
    )

    if not _HAVE_BS4:
        st.warning("`beautifulsoup4` isn't installed — add it to requirements.txt "
                   "for reliable parsing.")

    with st.expander("First-time setup — connect this to the schedule sheet"):
        st.markdown(
            "**1.** In the schedule sheet, add a tab named **`Feed`** with row-1 "
            "headers: `Game#`  `Date`  `Time`  `Location`.\n\n"
            "**2.** Every refresh, paste columns **A–D** (below) into that `Feed` tab, "
            "overwriting what's there.\n\n"
            "**3.** *One time only* — on the main schedule tab, drop these into row 2 "
            "and fill down. They pull Date / Time / Location live off the game number:"
        )
        st.code(
            '=IFERROR(XLOOKUP($A2, Feed!$A:$A, Feed!$B:$B), "")    →  Date  (column B)\n'
            '=IFERROR(XLOOKUP($A2, Feed!$A:$A, Feed!$C:$C), "")    →  Time  (column C)\n'
            '=IFERROR(XLOOKUP($A2, Feed!$A:$A, Feed!$D:$D), "")    →  Location (column D)',
            language="text",
        )
        st.caption("A row that goes blank later = PG moved or cancelled that game — a built-in flag.")

    src = st.radio(
        "Source",
        ["Perfect Game (paste URL)",
         "FiveTool / PBR / Prospect Select (paste scraped JSON)"],
    )

    if src.startswith("Perfect Game"):
        url = st.text_input(
            "Perfect Game schedule URL",
            placeholder="https://www.perfectgame.org/Events/TournamentSchedule.aspx?event=141563&Date=06/23/2026",
        )
        if st.button("Build schedule feed", type="primary", disabled=not url):
            bar = st.progress(0.0, text="Starting ...")
            try:
                df = build_feed(url.strip(), progress=lambda p, t: bar.progress(p, text=t))
            except Exception as e:  # noqa: BLE001
                bar.empty()
                st.error(f"Could not build the feed: {e}")
                return
            bar.empty()
            _show_feed(df, empty_msg="No games parsed — the page layout may have "
                       "changed. Send Claude this URL and we'll adjust the parser.")
    else:
        st.caption("In the extension's **Schedule** tab, scrape the event, hit "
                   "**Copy to Clipboard**, then paste here.")
        raw = st.text_area("Scraped schedule JSON", height=160,
                           placeholder='{ "event": "...", "games": [ ... ] }')
        if st.button("Build schedule feed", type="primary", disabled=not raw.strip()):
            try:
                df = feed_from_scrape(raw.strip())
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't read that JSON: {e}")
                return
            _show_feed(df, empty_msg="No games found in that JSON.",
                       collision_check=True)


# Allows: `streamlit run schedule_refresh.py` for a quick standalone test.
if __name__ == "__main__":
    render()

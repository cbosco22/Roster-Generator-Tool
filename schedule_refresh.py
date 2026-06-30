"""
schedule_refresh.py
-------------------
Unified schedule feed builder. One flow for all sites:

  1. Paste any tournament URL
  2. If Perfect Game  -> scrapes automatically (server-side, no friction)
  3. If anything else -> shows "Print to PDF" instructions + opens the URL
                         User saves PDF, uploads it here
                         Claude Vision extracts every game
  4. Output is the same Feed CSV either way:
     Game# | Date | Time | Location  ->  paste into Feed tab, sheet updates

Supports: Perfect Game, FiveTool, PBR, Prospect Select, any other site.
"""

import re
import io
import json
import base64
import datetime as _dt
from urllib.parse import urlparse, parse_qs, unquote

import requests
import pandas as pd
import streamlit as st

try:
    from push_event import push_schedule_update as _push_update
    _HAVE_PUSH = True
except ImportError:
    _HAVE_PUSH = False

try:
    from bs4 import BeautifulSoup
    _HAVE_BS4 = True
except ImportError:
    _HAVE_BS4 = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
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

_DAYLABEL_RE = re.compile(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"(\d{1,2})\s+\d+\s+Games?", re.I)
_DATEPARAM_RE = re.compile(
    r"(?<![A-Za-z])Date=\s*(\d{1,2})(?:/|%2[Ff])(\d{1,2})(?:/|%2[Ff])(\d{4})", re.I)
_RANGE_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\s*"
    r"(?:-|\u2013|\u2014|to)\s*"
    r"(?:(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+)?(\d{1,2})\b",
    re.I)

FEED_COLUMNS   = ["Game#", "Date", "Time", "Location", "GameID", "Team1", "Team2"]
SCRAPE_COLUMNS = ["Game#", "Date", "Time", "Location", "Division", "Team1", "Team2"]

# ---------------------------------------------------------------------------
# Site detection
# ---------------------------------------------------------------------------
def _detect_site(url):
    host = urlparse(url.lower()).netloc
    if "perfectgame" in host:
        return "pg"
    if "fivetool" in host:
        return "fivetool"
    if "prepbaseballreport" in host or ("pbr" in host and "baseball" in host):
        return "pbr"
    if "prospectselect" in host or "pros-select" in host:
        return "ps"
    return "other"


def _site_label(site):
    return {"pg": "Perfect Game", "fivetool": "FiveTool",
            "pbr": "PBR", "ps": "Prospect Select"}.get(site, "this site")


# ---------------------------------------------------------------------------
# Perfect Game scraper (unchanged from original)
# ---------------------------------------------------------------------------
def _event_id(url):
    ev = parse_qs(urlparse(url).query).get("event", [None])[0]
    if not ev:
        raise ValueError("That URL has no `event=` id. Paste a TournamentSchedule link.")
    return ev

def _fetch(url):
    r = requests.get(url, headers=_HEADERS, timeout=25)
    r.raise_for_status()
    return r.text

def _day_url(event_id, date_str):
    return f"{PG_SCHEDULE}?event={event_id}&Date={date_str}"

def _get_html(url, cache):
    if url not in cache:
        cache[url] = _fetch(url)
    return cache[url]

def _url_date(url):
    q = parse_qs(urlparse(url).query)
    raw = (q.get("Date") or q.get("date") or [None])[0]
    if not raw:
        return None
    m = re.match(r"(\d{1,2})\D(\d{1,2})\D(\d{4})", raw)
    return f"{int(m.group(1))}/{int(m.group(2))}/{int(m.group(3))}" if m else None

def _date_key(s):
    mo, da, yr = (int(x) for x in s.split("/"))
    return _dt.date(yr, mo, da)

def _fmt_date(date_str):
    d = _date_key(date_str)
    return f"{d.strftime('%A')}, {d.month}/{d.day}"

def _discover_dates(html, url):
    seen, yr = set(), None
    for m in _DATEPARAM_RE.finditer(html):
        try:
            seen.add(_dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2))))
            yr = yr or int(m.group(3))
        except ValueError:
            pass
    ud = _url_date(url)
    if ud:
        d = _date_key(ud)
        seen.add(d)
        yr = yr or d.year
    yr = yr or _dt.date.today().year
    for m in _DAYLABEL_RE.finditer(html):
        try:
            seen.add(_dt.date(yr, _MONTHS[m.group(1).lower()[:3]], int(m.group(2))))
        except (ValueError, KeyError):
            pass
    if len(seen) <= 1:
        rm = _RANGE_RE.search(html)
        if rm:
            try:
                m1 = _MONTHS[rm.group(1).lower()[:3]]
                m2 = _MONTHS[rm.group(3).lower()[:3]] if rm.group(3) else m1
                start = _dt.date(yr, m1, int(rm.group(2)))
                end   = _dt.date(yr if m2 >= m1 else yr + 1, m2, int(rm.group(4)))
                cur = start
                while cur <= end:
                    seen.add(cur)
                    cur += _dt.timedelta(days=1)
            except (ValueError, KeyError):
                pass
    return [f"{d.month}/{d.day}/{d.year}" for d in sorted(seen)]

def _page_text(html):
    if _HAVE_BS4:
        return BeautifulSoup(html, "html.parser").get_text("\n")
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", "\n", t)
    return t

def _block_teams(block_html):
    if not _HAVE_BS4:
        return "", ""
    names = [a.get_text(strip=True)
             for a in BeautifulSoup(block_html, "html.parser").select(_TEAM_SEL)]
    return (names[0] if names else ""), (names[1] if len(names) > 1 else "")

def _location_from(lines_after_gid):
    a = [ln for ln in lines_after_gid if ln]
    if not a:
        return ""
    first = a[0]
    if "@" in first and not first.rstrip().endswith("@"):
        right = first.split("@", 1)[1].strip()
        if right:
            return re.sub(r"\s*@\s*", " @ ", first).strip()
    if first.rstrip().endswith("@"):
        prefix   = first.rstrip()[:-1].strip()
        ballpark = a[1] if len(a) > 1 else ""
        return f"{prefix} @ {ballpark}".strip()
    if len(a) >= 3 and a[1].strip() == "@":
        return f"{a[0].strip()} @ {a[2].strip()}".strip()
    return " ".join(a[:2]).strip()

def _parse_day(html, date_str):
    label  = _fmt_date(date_str)
    blocks = re.split(r"Gm#\s*", html)[1:]
    rows   = []
    for blk in blocks:
        btext  = _page_text(blk)
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
            "Game#":    int(gnum_m.group(1)),
            "Date":     label,
            "Time":     re.sub(r"\s+", " ", time_m.group(1)).upper(),
            "Location": loc,
            "GameID":   gid_m.group(1) if gid_m else "",
            "Team1":    t1,
            "Team2":    t2,
        })
    return rows

def _probe_range(event_id, seed_str, cache):
    seed  = _date_key(seed_str)
    found = []
    for direction, limit in ((1, 21), (-1, 14)):
        d = seed if direction == 1 else seed - _dt.timedelta(days=1)
        for _ in range(limit):
            ds = f"{d.month}/{d.day}/{d.year}"
            if _parse_day(_get_html(_day_url(event_id, ds), cache), ds):
                found.append(d)
                d += _dt.timedelta(days=direction)
            else:
                break
    return [f"{d.month}/{d.day}/{d.year}" for d in sorted(set(found))]

def build_feed(url, progress=None):
    event_id  = _event_id(url)
    cache     = {}
    seed_str  = _url_date(url)
    seed_url  = _day_url(event_id, seed_str) if seed_str else url
    seed_html = _get_html(seed_url, cache)
    dates = _discover_dates(seed_html, url)
    if len(dates) <= 1 and seed_str:
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


# ---------------------------------------------------------------------------
# PDF -> Claude Vision extractor  (LINE-BASED, robust to truncation)
# ---------------------------------------------------------------------------
# We ask the model for one game per line in a fixed pipe-delimited format
# instead of JSON. A cut-off response just loses the final partial line
# rather than corrupting the whole parse — far more reliable for big events.

_VISION_PROMPT = """\
You are reading a printed tournament schedule PDF for a high school baseball event.
List EVERY game. Output ONE game per line, nothing else — no preamble, no JSON,
no markdown, no header row.

Each line MUST be exactly these 7 fields separated by a pipe (|) character:

game_num|date|time|location|division|team1|team2

Field rules:
- game_num: the game number exactly as shown (e.g. 16, 142). Strip any leading #.
- date: day and date exactly as printed (e.g. Thursday, June 25). Repeat the
  current date on every game line under that day's header.
- time: e.g. 8:00 AM
- location: field or venue (e.g. LakePoint 10)
- division: age division if shown (e.g. 16U), else leave empty
- team1: first/home team EXACTLY as printed
- team2: second/away team EXACTLY as printed
- If a team slot is blank or shows TBD, write TBD.
- Never put a pipe character inside a field.
- Include ALL games: pool play, bracket play, seeding, placement, everything.

Output only the game lines.
"""


def _pdf_to_images_b64(pdf_bytes):
    """Render each PDF page to base64 JPEG. Returns [] if no renderer available."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf_bytes)
        out = []
        for i in range(len(doc)):
            bmp = doc[i].render(scale=2.0)
            buf = io.BytesIO()
            bmp.to_pil().save(buf, format="JPEG", quality=90)
            out.append(base64.b64encode(buf.getvalue()).decode())
        return out
    except Exception:
        pass
    try:
        from pdf2image import convert_from_bytes
        out = []
        for img in convert_from_bytes(pdf_bytes, dpi=144):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            out.append(base64.b64encode(buf.getvalue()).decode())
        return out
    except Exception:
        pass
    return []


def _pdf_text_fallback(pdf_bytes):
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as e:
        return f"[text extraction failed: {e}]"


def _call_vision_lines(client, content):
    """Single API call. Returns list of parsed game dicts.
    Parses line-by-line; a truncated final line is simply skipped."""
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": content}],
    )
    raw = resp.content[0].text
    games = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) < 7:
            # truncated / malformed line — skip it, don't crash
            continue
        gnum, date, time, loc, div, t1, t2 = [p.strip() for p in parts[:7]]
        if not gnum or gnum.lower() in ("game_num", "game#", "game"):
            continue  # header row or empty
        games.append({
            "game_num": gnum, "date": date, "time": time,
            "location": loc, "division": div, "team1": t1, "team2": t2,
        })
    return games


def _vision_extract(pdf_bytes, api_key):
    """Send PDF pages to Claude Vision, return {'games': [...]}.
    Chunks large PDFs (>5 pages) into batches so no single call overflows."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    images = _pdf_to_images_b64(pdf_bytes)

    def _make_content(imgs_b64, text_fallback=""):
        content = []
        if imgs_b64:
            for i, b64 in enumerate(imgs_b64):
                if len(imgs_b64) > 1:
                    content.append({"type": "text", "text": f"Page {i+1}:"})
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                })
        else:
            content.append({"type": "text",
                             "text": f"Schedule PDF text:\n\n{text_fallback}"})
        content.append({"type": "text", "text": _VISION_PROMPT})
        return content

    CHUNK_SIZE = 5
    all_games = []

    if len(images) <= CHUNK_SIZE:
        text_fallback = "" if images else _pdf_text_fallback(pdf_bytes)
        all_games = _call_vision_lines(client, _make_content(images, text_fallback))
    else:
        for i in range(0, len(images), CHUNK_SIZE):
            chunk = images[i:i + CHUNK_SIZE]
            all_games.extend(_call_vision_lines(client, _make_content(chunk)))

    # De-dupe on game number (chunk overlap safety) keeping first occurrence
    seen, deduped = set(), []
    for g in all_games:
        key = g["game_num"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(g)

    return {"event": "Tournament", "games": deduped}


def _norm_vision_date(s):
    """'Thursday, June 26' or 'June 26, 2026' -> 'Thursday, 6/26'."""
    s = (s or "").strip()
    if re.match(r"\w+,\s+\d{1,2}/\d{1,2}", s):
        return s
    m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s*(\d{4})?", s)
    if m:
        mon = _MONTHS.get(m.group(1).lower()[:3])
        if mon:
            yr = int(m.group(3)) if m.group(3) else _dt.date.today().year
            try:
                return _fmt_date(f"{mon}/{int(m.group(2))}/{yr}")
            except ValueError:
                pass
    return s


def _feed_from_vision(data):
    """Turn vision games into the standard Feed DataFrame."""
    rows = []
    for g in data.get("games", []):
        gnum = str(g.get("game_num", "")).strip().lstrip("#").strip()
        if not gnum:
            continue
        rows.append({
            "Game#":    gnum,
            "Date":     _norm_vision_date(str(g.get("date", ""))),
            "Time":     str(g.get("time", "")).strip().upper(),
            "Location": str(g.get("location", "")).strip(),
            "Division": str(g.get("division", "")).strip(),
            "Team1":    str(g.get("team1", "")).strip(),
            "Team2":    str(g.get("team2", "")).strip(),
        })
    cols = ["Game#", "Date", "Time", "Location", "Division", "Team1", "Team2"]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty and df["Game#"].str.fullmatch(r"\d+").all():
        df = (df.assign(_n=df["Game#"].astype(int))
                .sort_values("_n").drop(columns="_n")
                .reset_index(drop=True))
    return df


# ---------------------------------------------------------------------------
# Event Day push helper
# ---------------------------------------------------------------------------
def _push_section(df, event_name):
    """Show a push-to-Event-Day button beneath a schedule feed."""
    if not _HAVE_PUSH:
        return
    if not event_name or not event_name.strip():
        st.caption("💡 Enter the event name above to push this schedule "
                   "live to the Event Day app.")
        return

    if st.button("📲 Push to Event Day", type="primary",
                 use_container_width=True, key="sr_push_btn"):
        games = []
        for _, row in df.iterrows():
            games.append({
                "game":     str(row.get("Game#", "")),
                "date":     str(row.get("Date", "")),
                "time":     str(row.get("Time", "")),
                "location": str(row.get("Location", "")),
                "division": str(row.get("Division", "")) if "Division" in df.columns else "",
                "team1":    str(row.get("Team1", "")),
                "team2":    str(row.get("Team2", "")),
            })
        try:
            result = _push_update(event_name.strip(), {"games": games})
            unmatched = result.get("unmatched_teams", [])
            st.success(
                f"✅ Schedule updated live — **{result['name']}** "
                f"({len(games)} games pushed)."
            )
            if unmatched:
                st.warning(
                    f"⚠️ {len(unmatched)} team(s) not found in the existing event "
                    f"(blank Navy data until next full build): "
                    + ", ".join(unmatched[:8])
                    + (" …" if len(unmatched) > 8 else "")
                )
        except Exception as e:
            st.error(f"Push failed: {e}")


# ---------------------------------------------------------------------------
# Shared output renderer
# ---------------------------------------------------------------------------
def _show_feed(df, source_label="", collision_check=False):
    if df is None or df.empty:
        st.error("No games found. Make sure the PDF has the full schedule printed.")
        return

    days    = list(dict.fromkeys(df["Date"].tolist()))
    numeric = df["Game#"].astype(str).str.fullmatch(r"\d+").all()
    head    = f"{len(df)} games across {len(days)} day(s)"
    if numeric:
        nums = df["Game#"].astype(int)
        head += f"  |  Game #{nums.min()}-{nums.max()}"
    st.success(head)
    if source_label:
        st.caption(f"Source: {source_label}")
    st.caption("Days: " + "  |  ".join(d for d in days if d))

    if collision_check:
        ser  = df["Game#"].astype(str)
        dups = ser[ser.duplicated(keep=False)]
        if not dups.empty:
            ex = ", ".join(sorted(set(dups))[:6])
            st.warning(
                f"Some game numbers repeat ({ex} ...). The sheet may need a "
                "Date+Game# key. Let me know and I'll wire that variant.")

    st.dataframe(df, use_container_width=True, hide_index=True)

    core = df[["Game#", "Date", "Time", "Location"]]
    st.markdown("**Copy into the Feed tab**")
    st.caption(
        "Tap the copy icon (top-right), then paste into cell **A1** of the "
        "`Feed` tab — overwrites the four columns and the schedule updates.")
    st.code(core.to_csv(index=False, sep="\t"), language=None)
    st.download_button("Download feed.csv",
                       data=df.to_csv(index=False).encode("utf-8"),
                       file_name="feed.csv", mime="text/csv",
                       use_container_width=True)


# ---------------------------------------------------------------------------
# API key helper
# ---------------------------------------------------------------------------
def _get_api_key():
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        import os
        return os.environ.get("ANTHROPIC_API_KEY")


# ---------------------------------------------------------------------------
# Main render — called by app.py as schedule_refresh.render()
# ---------------------------------------------------------------------------
def render():
    st.subheader("Schedule Refresh")
    st.caption(
        "Paste any tournament link. Perfect Game pulls automatically. "
        "For FiveTool, PBR, and Prospect Select you'll save a quick print PDF "
        "and upload it here."
    )

    if not _HAVE_BS4:
        st.warning("`beautifulsoup4` not installed — add it to requirements.txt.")

    # Step 1: URL input — always visible
    url  = st.text_input(
        "Tournament schedule URL",
        placeholder="Paste any schedule link — PG, FiveTool, PBR, Prospect Select ...",
        key="sr_url",
    )
    site = _detect_site(url.strip()) if url.strip() else None

    sr_event_name = st.text_input(
        "Event Day app name",
        placeholder="e.g. PBR 16U Nat'l Champ 2026 — must match the name used in Tournament Builder",
        key="sr_event_name",
        help="The schedule will push live to the Event Day app under this name. "
             "Use the same name as the full tournament build to update in place.",
    )

    # ── Perfect Game: one button, done ─────────────────────────────────────
    if site == "pg":
        if st.button("Build schedule feed", type="primary",
                     use_container_width=True, key="sr_pg_btn"):
            try:
                bar = st.progress(0.0, text="Working...")
                df  = build_feed(url.strip(),
                                 progress=lambda p, t: bar.progress(p, text=t))
                bar.empty()
            except Exception as e:
                st.error(f"Could not build the feed: {e}")
                st.stop()
            _show_feed(df, source_label="Perfect Game (direct)")
            _push_section(df, sr_event_name)

    # ── FiveTool / PBR / Prospect Select / other: print-to-PDF flow ────────
    elif site is not None:
        label = _site_label(site)
        st.info(
            f"**{label}** blocks direct scraping — but the print PDF works great.\n\n"
            "**5 taps on iPhone:**\n"
            "1. Tap **Open schedule page** below\n"
            "2. Share button → **Print**\n"
            "3. Pinch-zoom out on the preview to get the PDF view\n"
            "4. Share button again → **Save to Files**\n"
            "5. Come back here and upload it below"
        )
        st.link_button(f"Open {label} schedule page",
                       url.strip(), use_container_width=True)

        st.divider()

        pdf_file = st.file_uploader(
            "Upload the saved schedule PDF",
            type=["pdf"],
            key="sr_pdf",
        )

        if pdf_file:
            if st.button("Extract schedule", type="primary",
                         use_container_width=True, key="sr_pdf_btn"):
                api_key = _get_api_key()
                if not api_key:
                    st.error("Anthropic API key missing — set `ANTHROPIC_API_KEY` "
                             "in Streamlit secrets.")
                    st.stop()
                with st.spinner(f"Reading {label} schedule..."):
                    try:
                        data = _vision_extract(pdf_file.read(), api_key)
                        df   = _feed_from_vision(data)
                    except Exception as e:
                        st.error(f"Extraction failed: {e}")
                        st.stop()
                _show_feed(df,
                           source_label=f"{label} (PDF)",
                           collision_check=(site == "fivetool"))
                _push_section(df, sr_event_name)

    # ── No URL yet: show the simple routing table ───────────────────────────
    else:
        st.markdown(
            "| Site | How |\n"
            "|---|---|\n"
            "| Perfect Game | Paste URL → pulls automatically |\n"
            "| FiveTool | Paste URL → print to PDF → upload |\n"
            "| PBR | Paste URL → print to PDF → upload |\n"
            "| Prospect Select | Paste URL → print to PDF → upload |"
        )

    # ── First-time setup (collapsed) ────────────────────────────────────────
    with st.expander("First-time setup — connect to the schedule sheet"):
        st.markdown(
            "**1.** In the schedule sheet, add a tab named **`Feed`** with row-1 "
            "headers: `Game#`  `Date`  `Time`  `Location`.\n\n"
            "**2.** Every refresh, paste columns **A-D** (above) into that `Feed` tab, "
            "overwriting what's there.\n\n"
            "**3.** One time only — on the main schedule tab, drop these into row 2 "
            "and fill down:"
        )
        st.code(
            '=IFERROR(XLOOKUP($A2, Feed!$A:$A, Feed!$B:$B), "")    ->  Date\n'
            '=IFERROR(XLOOKUP($A2, Feed!$A:$A, Feed!$C:$C), "")    ->  Time\n'
            '=IFERROR(XLOOKUP($A2, Feed!$A:$A, Feed!$D:$D), "")    ->  Location',
            language="text",
        )
        st.caption("A row that goes blank = game was moved or cancelled.")


if __name__ == "__main__":
    render()

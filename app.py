"""
Navy Baseball Recruiting Tools

Streamlit app for coaches in the field:
  * Generate rosters and schedules for teams and events
  * Generate post event summaries allowing for fast player entry
  * Get back a Navy-formatted PDF + on-screen summary of DB/PBR hits

Admin tab lets Chris swap in a new recruiting xlsx or rebuild PBR rankings.

Run locally:    streamlit run app.py
Deploy:         push to GitHub, connect at share.streamlit.io
"""
import os
import io
import json
import time
import tempfile
import pickle
from datetime import datetime
from pathlib import Path

import html
import requests
import pandas as pd
import streamlit as st

# Ensure local imports work no matter where streamlit is launched from
APP_DIR = Path(__file__).parent.resolve()
import sys
sys.path.insert(0, str(APP_DIR))

# Persistent data lives in data/ next to the app.
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
XLSX_PATH = DATA_DIR / "recruiting.xlsx"
PKL_PATH  = DATA_DIR / "pbr_rankings.pkl"

# Now import the locked scripts. gen_roster_pdf looks for the pkl in
# <script_dir>/data/pbr_rankings.pkl by default, so nothing to mirror.
from db_loader import parse_xlsx, find_columns
import gen_roster_pdf
from photo_to_roster import extract_roster_from_image, extract_roster_from_images, extract_roster_from_files, to_pdf_payload
from post_event_extractor import extract_post_event_page
from post_event_flow import (
    NEW_PLAYER_COLUMNS, UPDATE_COLUMNS,
    split_pools, prefill_new_player_rows, build_updates_rows,
    rows_to_csv, today_str,
)
import run_event
import schedule_refresh
import sheet_write
import twitter_extract
from org_tier import lookup_org_tier
try:
    from push_event import push_event as _push_event
    _HAVE_PUSH = True
except ImportError:
    _HAVE_PUSH = False


# ---------------------- helpers ----------------------

def _get_api_key():
    """API key precedence: Streamlit secrets > env var > none."""
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY")


def _get_secret(key):
    """st.secrets raises StreamlitSecretNotFoundError on ANY access -
    including .get() - when no secrets.toml exists at all, not just when
    the specific key is missing. Same bug class as _get_api_key() already
    guards against; this is the same fix for the sheet-write secrets."""
    try:
        return st.secrets.get(key)
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner="Syncing recruiting sheet…")
def _sync_recruiting_sheet():
    """Treat Recruiting Sheet 2.0 as the source of truth: re-pull it into
    data/recruiting.xlsx via Drive's public export endpoint (the sheet is
    link-shared — see sheet_sync.py for why no auth is needed, and why
    that's intentional). Cached for 10 min per running container, so this
    also re-syncs automatically on every fresh container boot/deploy — no
    more manual xlsx upload or git-commit needed for routine board updates.
    Falls back to whatever xlsx is already on disk if the fetch fails for
    any reason (network blip, sheet sharing changed, etc.) — the Admin
    tab's manual upload still works as an override either way."""
    try:
        import sheet_sync
        sheet_sync.fetch_recruiting_xlsx(str(XLSX_PATH))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _load_raw_sheet_text_from_xlsx(xlsx_path: Path) -> str:
    """
    The locked build_pdf signature takes raw sheet text.
    db_loader.parse_xlsx returns the parsed dict directly, but
    gen_roster_pdf.init_db calls build_db_from_raw(raw_sheet_text)
    which goes through parse_sheet_content. To use the xlsx instead,
    we monkey-patch the module's _DB after parse_xlsx.
    """
    db = parse_xlsx(str(xlsx_path))
    # Install into gen_roster_pdf's namespace as if init_db ran.
    class _XlsxDB:
        def __init__(self, d): self._db = d
        def lookup(self, name):
            from db_loader import lookup as _lookup
            return _lookup(self._db, name)
    gen_roster_pdf._DB = _XlsxDB(db)
    return ""  # signal to build_pdf that init_db can be a no-op


def _summarize_hits(extracted: dict) -> dict:
    """
    Build a quick text-summary structure for the dugout view:
    DB matches (with tier) and PBR-ranked players (state/national rank).
    """
    from db_loader import lookup as db_lookup
    import pickle as _pickle
    db = gen_roster_pdf._DB._db if hasattr(gen_roster_pdf, "_DB") and gen_roster_pdf._DB else {}

    pbr_nat, pbr_state = {}, {}
    if PKL_PATH.exists():
        with open(PKL_PATH, "rb") as f:
            d = _pickle.load(f)
        pbr_nat = d.get("national", {})
        pbr_state = d.get("state_rnks", {})

    from db_loader import strip_suffix

    hits = {"db_matches": [], "pbr_hits": [], "total_players": 0}
    for p in extracted.get("players", []):
        hits["total_players"] += 1
        name = p.get("name", "").strip()
        if not name:
            continue

        # DB lookup
        if db:
            entry = db_lookup(db, name)
            if entry:
                tier = entry.get("tier", "")
                tier_label = {"0.1": "Commit", "1": "Tier 1",
                              "2": "Tier 2", "3": "Tier 3",
                              "4": "Tier 4"}.get(tier, f"Tier {tier}")
                hits["db_matches"].append({
                    "jersey": p.get("jersey", ""),
                    "name": entry.get("canonical_name", name),
                    "tier": tier,
                    "tier_label": tier_label,
                    "class": entry.get("class", ""),
                    "pos": entry.get("pos", ""),
                    "commit": entry.get("commit", ""),
                })

        # PBR lookup (state takes precedence visually)
        key = strip_suffix(name.lower())
        st_e = pbr_state.get(key)
        nat_e = pbr_nat.get(key)
        # Validate against grad/state when we have them
        grad = p.get("grad", "")
        state = (p.get("state", "") or "").upper()

        def _valid(entry):
            if not entry:
                return False
            if grad and str(entry.get("class", "")) != grad:
                return False
            es = (entry.get("state", "") or "").strip()
            if state and es and es.lower() not in ("- select state -", ""):
                # crude 2-letter compare
                from_full = {"alabama":"AL","arkansas":"AR","arizona":"AZ","california":"CA",
                             "colorado":"CO","connecticut":"CT","delaware":"DE","florida":"FL",
                             "georgia":"GA","hawaii":"HI","idaho":"ID","illinois":"IL",
                             "indiana":"IN","iowa":"IA","kansas":"KS","kentucky":"KY",
                             "louisiana":"LA","maine":"ME","maryland":"MD","massachusetts":"MA",
                             "michigan":"MI","minnesota":"MN","mississippi":"MS","missouri":"MO",
                             "montana":"MT","nebraska":"NE","nevada":"NV","new hampshire":"NH",
                             "new jersey":"NJ","new mexico":"NM","new york":"NY",
                             "north carolina":"NC","north dakota":"ND","ohio":"OH",
                             "oklahoma":"OK","oregon":"OR","pennsylvania":"PA",
                             "rhode island":"RI","south carolina":"SC","south dakota":"SD",
                             "tennessee":"TN","texas":"TX","utah":"UT","vermont":"VT",
                             "virginia":"VA","washington":"WA","west virginia":"WV",
                             "wisconsin":"WI","wyoming":"WY"}
                e_abv = from_full.get(es.lower(), es.upper()[:2])
                if e_abv != state:
                    return False
            return True

        st_ok  = _valid(st_e)
        nat_ok = _valid(nat_e)
        if st_ok or nat_ok:
            rec = {"jersey": p.get("jersey", ""),
                   "name": name,
                   "class": grad,
                   "pos": p.get("pos", "")}
            if st_ok:
                rec["state_rank"] = f"#{st_e['rank']} {(st_e.get('state','') or '')[:2].upper() or state}"
            if nat_ok:
                rec["nat_rank"] = f"#{nat_e['rank']} Nat'l"
            hits["pbr_hits"].append(rec)

    return hits


def _generate_pdf(extracted: dict, event_name: str, division: str) -> bytes:
    """Run the locked build_pdf pipeline. Returns PDF bytes."""
    payload = to_pdf_payload(extracted, event_name, division or None)
    with tempfile.TemporaryDirectory() as td:
        in_json = Path(td) / "roster.json"
        out_pdf = Path(td) / "out.pdf"
        in_json.write_text(json.dumps(payload))
        # Build with raw_sheet_text="" — our xlsx DB is already installed.
        gen_roster_pdf.build_pdf(str(in_json), str(out_pdf), raw_sheet_text="", skip_cover=True)
        return out_pdf.read_bytes()


def _pdf_open_link(pdf_bytes: bytes, filename: str,
                   label: str = "📂 Open in a browser tab (mobile-safe)") -> None:
    """Render a link that opens the PDF in a real browser tab.

    On an iPhone/iPad home-screen shortcut the app runs full-screen with no
    browser toolbar, so the normal download can open the PDF with no way back —
    you get stuck and have to close the app. This link uses target=_blank so the
    PDF opens in Safari (which has a Done/back button) instead of trapping the
    app. Best for normally-sized rosters; very large event books may be slow.
    """
    import base64 as _b64
    href = "data:application/pdf;base64," + _b64.b64encode(pdf_bytes).decode("ascii")
    st.markdown(
        f'<a href="{href}" target="_blank" rel="noopener" download="{filename}" '
        f'style="display:inline-block;margin-top:0.4em;padding:0.45em 0.9em;'
        f'border:1px solid #1A3A6B;border-radius:0.4em;color:#1A3A6B;'
        f'text-decoration:none;font-weight:600;">{label}</a>',
        unsafe_allow_html=True,
    )


# ---------------------- UI ----------------------

st.set_page_config(
    page_title="Navy Baseball — Recruiting Tools",
    page_icon="⚓",
    layout="centered",
)

_sheet_sync_result = _sync_recruiting_sheet()

# Global design system — professional sports-org look (Inter, refined
# buttons/tabs/metrics/tables), not just the header brand lockup. Added
# 2026-06-30 per direct feedback that the default Streamlit look read as
# "JV" — goal is something an NFL/MLB front office tool would look like.
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&display=swap');

    html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }

    /* Fraunces on headers/brand moments only, Inter everywhere else that's
       functional (buttons, labels, data) — the serif is what reads as
       premium/editorial, but a whole app set in a display serif would hurt
       readability on data-dense screens. Added 2026-06-30 per feedback that
       Inter alone still read as generic, not "worth $20k/year." */
    h1, h2, h3, .brand-serif {
      font-family: 'Fraunces', Georgia, serif !important;
      font-weight: 600 !important;
      letter-spacing: -0.01em;
      color: #14233B;
    }

    /* Buttons — depth and weight instead of the flat default box */
    .stButton > button, .stDownloadButton > button {
      border-radius: 10px !important;
      font-weight: 600 !important;
      transition: all 0.15s ease !important;
      border: 1px solid #E4E1D8 !important;
      box-shadow: 0 1px 2px rgba(20,35,59,0.06) !important;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
      transform: translateY(-1px);
      box-shadow: 0 4px 10px rgba(20,35,59,0.12) !important;
    }
    /* color was never set explicitly here - relied on inheritance for
       white text, which silently broke wherever that assumption didn't
       hold (found 2026-07-02: buttons rendered inside a popover, a
       portaled/detached part of the DOM tree, rendered black text on the
       navy background - unreadable). Force it instead of assuming it. */
    .stButton > button[kind="primary"],
    [data-testid^="stBaseButton-primary"] {
      background: #14233B !important;
      color: #FFFFFF !important;
      border: none !important;
      box-shadow: 0 2px 8px rgba(20,35,59,0.25) !important;
    }
    .stButton > button[kind="primary"]:hover,
    [data-testid^="stBaseButton-primary"]:hover {
      background: #1F3357 !important;
      color: #FFFFFF !important;
      box-shadow: 0 6px 16px rgba(20,35,59,0.35) !important;
    }

    /* Tabs — cleaner bar, gold active indicator matching the brand */
    .stTabs [data-baseweb="tab-list"] {
      gap: 4px;
      border-bottom: 2px solid #E4E1D8;
    }
    .stTabs [data-baseweb="tab"] {
      font-weight: 600 !important;
      font-size: 14px !important;
      color: #6B7682 !important;
      padding: 10px 6px !important;
    }
    .stTabs [aria-selected="true"] { color: #14233B !important; }
    .stTabs [data-baseweb="tab-highlight"] {
      background-color: #C8A24B !important;
      height: 3px !important;
      border-radius: 3px 3px 0 0;
    }

    /* Metrics — card treatment instead of bare numbers */
    [data-testid="stMetric"] {
      background: #F7F6F2;
      border-radius: 12px;
      padding: 14px 16px;
      border: 1px solid #E4E1D8;
    }
    [data-testid="stMetricLabel"] { font-weight: 600 !important; color: #6B7682 !important; }
    [data-testid="stMetricValue"] { font-weight: 800 !important; color: #14233B !important; }

    /* Tables / dataframes — rounded, bordered, less "spreadsheet" */
    [data-testid="stDataFrame"], [data-testid="stTable"] {
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid #E4E1D8;
    }

    /* Status boxes (success/info/warning/error) — softer corners */
    [data-testid="stAlert"] { border-radius: 10px !important; }

    /* File uploader — Chris reported the caption text bleeding into the
       Browse button on his phone 2026-06-30. Force real stacking with a
       guaranteed gap and full text wrapping instead of relying on default
       flex behavior, which can render differently across mobile Safari
       versions than it does here. */
    [data-testid="stFileUploaderDropzone"] {
      flex-direction: column !important;
      align-items: flex-start !important;
      row-gap: 12px !important;
      padding: 16px !important;
    }
    [data-testid="stFileUploaderDropzone"] > div {
      white-space: normal !important;
      overflow: visible !important;
      text-overflow: unset !important;
      width: 100% !important;
    }
    [data-testid="stFileUploaderDropzone"] small {
      white-space: normal !important;
      overflow-wrap: break-word !important;
    }
    [data-testid="stFileUploaderDropzone"] section > button,
    [data-testid="stFileUploaderDropzone"] span > button {
      margin-top: 4px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Brand lockup — mirrors the Event Day app (navy header, gold eyebrow).
st.markdown(
    """
    <div style="background:#14233B;border:1px solid #1F3357;border-radius:14px;
                padding:18px 20px;margin-bottom:14px;">
      <div style="color:#C8A24B;letter-spacing:.18em;font-size:11px;font-weight:700;
                  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">
        NAVY BASEBALL · RECRUITING
      </div>
      <div style="color:#FFFFFF;font-size:28px;font-weight:600;line-height:1.15;margin-top:4px;
                  font-family:'Fraunces',Georgia,serif;letter-spacing:-0.01em;">
        ⚓ Recruiting Tools
      </div>
      <div style="color:#A9B4C6;font-size:13px;margin-top:5px;
                  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;">
        PDF rosters · CSV schedules · post-event summaries
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_field, tab_add, tab_board, tab_post, tab_tourney, tab_sched, tab_admin = st.tabs(
    ["🎯 Field Tool", "➕ Add Player", "📋 Board", "📥 Post-Event", "🏟️ Tournament Builder",
     "🔄 Schedule Refresh", "⚙️  Admin"])


# ---- Field Tool ----
with tab_field:
    # Status: is data loaded?
    db_ready = XLSX_PATH.exists()
    pbr_ready = PKL_PATH.exists()
    api_key = _get_api_key()

    if not db_ready or not pbr_ready or not api_key:
        with st.container(border=True):
            st.warning("Setup needed:")
            if not db_ready:
                st.write("• Recruiting xlsx not loaded — go to **Admin** tab")
            if not pbr_ready:
                st.write("• PBR rankings not loaded — go to **Admin** tab")
            if not api_key:
                st.write("• Anthropic API key missing — set `ANTHROPIC_API_KEY` "
                         "in Streamlit secrets or env")

    st.write("**1. Photo(s) or PDF of the roster**")
    img_files = st.file_uploader(
        "Take or upload photo(s) or a PDF",
        type=["jpg", "jpeg", "png", "heic", "webp", "pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        help="For long rosters, shoot 2-3 close-up sections (~15-20 players each) "
             "so the text is big and sharp — or upload a single-team PDF. "
             "Everything uploaded is merged into one team.",
    )

    col1, col2 = st.columns(2)
    with col1:
        event_name = st.text_input(
            "Event name",
            placeholder="e.g. PG WWBA 17U Championship",
            help="Goes on the cover page and running header.",
        )
    with col2:
        division = st.selectbox(
            "Age division",
            ["16U", "17U", "18U", "15U", "14U", "Other / leave blank"],
            index=1,
        )
        if division == "Other / leave blank":
            division = ""

    go = st.button("🚀 Generate PDF",
                   type="primary", use_container_width=True,
                   disabled=not (img_files and event_name and api_key
                                 and db_ready and pbr_ready))

    if go:
        # Load the DB fresh in case admin updated it this session
        try:
            _load_raw_sheet_text_from_xlsx(XLSX_PATH)
        except Exception as e:
            st.error(f"Could not read recruiting xlsx: {e}")
            st.stop()

        with st.status("Working…", expanded=True) as status:
            try:
                # Step 1: vision extract — each source processed at full resolution
                n_src = len(img_files)
                label = ("📸 Reading roster…" if n_src == 1
                         else f"📸 Reading {n_src} files…")
                status.update(label=label)
                sources = []
                for f in img_files:
                    mt = f.type or ""
                    if mt == "image/jpg":
                        mt = "image/jpeg"
                    if not mt:
                        mt = ("application/pdf"
                              if f.name.lower().endswith(".pdf") else "image/jpeg")
                    sources.append((f.read(), mt))

                extracted = extract_roster_from_files(sources, api_key=api_key)

                n = len(extracted.get("players", []))
                team = extracted.get("team_name", "")
                src = "1 file" if n_src == 1 else f"{n_src} files"
                st.write(f"✓ Extracted **{n}** players from **{team or 'team'}** ({src})")

                if n == 0:
                    status.update(label="No players found", state="error")
                    st.error("Couldn't read any players. "
                             "Try sharper/closer shots — get the text big in frame.")
                    st.stop()

                # Step 2: summary of hits
                status.update(label="🔎 Cross-referencing DB and PBR rankings…")
                hits = _summarize_hits(extracted)

                # Step 3: PDF
                status.update(label="📄 Building Navy PDF…")
                pdf_bytes = _generate_pdf(extracted, event_name, division)

                status.update(label="Done", state="complete")
            except Exception as e:
                status.update(label="Error", state="error")
                st.exception(e)
                st.stop()

        # Stash for rendering below
        st.session_state["last_extracted"] = extracted
        st.session_state["last_hits"] = hits
        st.session_state["last_pdf"] = pdf_bytes
        st.session_state["last_team"] = team
        st.session_state["last_event"] = event_name
        st.session_state["last_division"] = division

    # Render last result (if any)
    if "last_pdf" in st.session_state:
        st.divider()
        team = st.session_state["last_team"] or "Roster"
        st.subheader(f"📋 {team}")

        hits = st.session_state["last_hits"]
        n_total = hits["total_players"]
        n_db = len(hits["db_matches"])
        n_pbr = len(hits["pbr_hits"])

        m1, m2, m3 = st.columns(3)
        m1.metric("Players", n_total)
        m2.metric("On our board", n_db)
        m3.metric("PBR ranked", n_pbr)

        if hits["db_matches"]:
            st.markdown("**🎯 On Navy's recruiting board**")
            for h in sorted(hits["db_matches"], key=lambda x: x["tier"]):
                jersey = f"#{h['jersey']} " if h["jersey"] else ""
                commit = f" — committed: {h['commit']}" if h["commit"] else ""
                st.write(f"• {jersey}**{h['name']}** ({h['class']}, {h['pos']}) "
                         f"— **{h['tier_label']}**{commit}")

        if hits["pbr_hits"]:
            st.markdown("**📈 PBR ranked players**")
            for h in hits["pbr_hits"]:
                jersey = f"#{h['jersey']} " if h["jersey"] else ""
                ranks = " · ".join(filter(None,
                                          [h.get("state_rank"), h.get("nat_rank")]))
                st.write(f"• {jersey}**{h['name']}** ({h['class']}, {h['pos']}) "
                         f"— {ranks}")

        if n_db == 0 and n_pbr == 0:
            st.info("No DB or PBR hits on this roster. PDF still generated for reference.")

        st.divider()
        fname = (st.session_state["last_event"] or "roster").replace(" ", "_") + \
                "_" + (team.replace(" ", "_") or "team") + ".pdf"
        st.download_button(
            "⬇️  Download Navy PDF",
            data=st.session_state["last_pdf"],
            file_name=fname,
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )
        _pdf_open_link(st.session_state["last_pdf"], fname)
        st.caption("On phone and the download opens full-screen with no way back? "
                   "Use the link above — or open this app from Safari instead of a "
                   "home-screen shortcut.")


# ---- Tournament Builder ----
with tab_tourney:
    st.subheader("Tournament Builder")
    st.caption("Upload a whole event — rosters, plus an optional schedule and "
               "age-groups PDF — and get the full roster book (cover, divisions, "
               "running header) and the schedule CSV.")

    tb_db_ready = XLSX_PATH.exists()
    if not tb_db_ready:
        st.warning("Recruiting xlsx not loaded — load it on the **Admin** tab first.")
    if not PKL_PATH.exists():
        st.info("No PBR rankings loaded — the build still works, but PBR columns "
                "and counts will be blank. Load them on the Admin tab.")

    st.write("**1. Rosters JSON** (upload one, or several to combine — PG splits by age group)")
    tb_roster = st.file_uploader("Scraped rosters for the whole event", type=["json"],
                                 accept_multiple_files=True,
                                 label_visibility="collapsed", key="tb_roster")

    def _guess_div_label(fname):
        n = fname.upper()
        for tok, lbl in (("18U", "18U"), ("17U", "17/18U"), ("16U", "15/16U"),
                         ("15U", "15U"), ("14U", "14U")):
            if tok in n:
                return lbl
        return ""

    st.write("**2. Schedule JSON** (optional — one or several; PDF only if omitted)")
    tb_sched = st.file_uploader("Scraped schedule(s)", type=["json"],
                                accept_multiple_files=True,
                                label_visibility="collapsed", key="tb_sched")
    tb_sched_labels = {}
    if tb_sched:
        st.caption("For a multi-age-group event, label each schedule so the CSV's "
                   "Division column is right (auto-filled from the filename). Leave "
                   "blank to use the single-division label below.")
        for f in tb_sched:
            tb_sched_labels[f.name] = st.text_input(
                f"Age group — {f.name}",
                value=_guess_div_label(f.name),
                key=f"tb_schedlabel_{f.name}")

    st.write("**3. Age-group PDFs** (optional — one PDF per age group)")
    tb_divpdfs = st.file_uploader(
        "One PDF per age group (PG 'Participating Teams' export, or a Ctrl-P "
        "print of a single age group). Each PDF is the authoritative team list "
        "for its division.",
        type=["pdf"], accept_multiple_files=True,
        label_visibility="collapsed", key="tb_divpdfs")

    tb_div_labels = {}
    if tb_divpdfs:
        st.caption("Confirm the division label for each PDF (auto-filled from the "
                   "filename). Leave a single PDF's label blank to fall back to "
                   "automatic multi-division detection.")
        for f in tb_divpdfs:
            tb_div_labels[f.name] = st.text_input(
                f"Division label — {f.name}",
                value=_guess_div_label(f.name),
                key=f"tb_divlabel_{f.name}")

    c1, c2 = st.columns(2)
    with c1:
        tb_event = st.text_input("Event name (optional)",
                                 placeholder="e.g. National Program Invitational (NPI)",
                                 key="tb_event",
                                 help="Used to push the schedule to the Event Day app. "
                                      "Use the same name every time to update in place.")
    with c2:
        tb_division = st.text_input("Division label (single-division events)",
                                    value="17U/18U", key="tb_division",
                                    help="Ignored when an age-groups PDF is provided.")

    tb_go = st.button("🏟️ Build tournament", type="primary",
                      use_container_width=True,
                      disabled=not (tb_roster and tb_db_ready))

    if tb_go:
        import tempfile
        with st.status("Building…", expanded=True) as tstatus:
            try:
                tdir = tempfile.mkdtemp()
                roster_paths = []
                for i, f in enumerate(tb_roster):
                    rp = os.path.join(tdir, f"rosters_{i}.json")
                    Path(rp).write_bytes(f.read())
                    roster_paths.append(rp)
                sched_paths = []
                for i, f in enumerate(tb_sched or []):
                    sp = os.path.join(tdir, f"schedule_{i}.json")
                    Path(sp).write_bytes(f.read())
                    sched_paths.append(sp)
                # Labeled schedules -> schedule_specs so the CSV Division column
                # is correct per age group. If no labels were entered, fall back
                # to the merged single-division behavior.
                schedule_specs = None
                if tb_sched:
                    labeled_s = [(tb_sched_labels.get(f.name, "").strip(), sp)
                                 for f, sp in zip(tb_sched, sched_paths)]
                    if any(lbl for lbl, _ in labeled_s):
                        fallback = tb_division or "17U/18U"
                        schedule_specs = [(lbl or fallback, p) for lbl, p in labeled_s]
                # Age-group PDFs: labeled files -> division_pdfs (per-group team
                # lists). A single unlabeled PDF -> div_pdf (reset detection).
                division_pdfs = None
                divpdf_path = None
                if tb_divpdfs:
                    saved = []
                    for i, f in enumerate(tb_divpdfs):
                        p = os.path.join(tdir, f"agegroup_{i}.pdf")
                        Path(p).write_bytes(f.read())
                        saved.append((tb_div_labels.get(f.name, "").strip(), p))
                    labeled = [(lbl, p) for lbl, p in saved if lbl]
                    if labeled:
                        division_pdfs = labeled
                    elif len(saved) == 1:
                        divpdf_path = saved[0][1]

                tstatus.update(label="📄 Generating roster book + schedule "
                                     "(a full event can take a minute)…")
                pdf_path, csv_path = run_event.run_event(
                    xlsx=str(XLSX_PATH), roster=roster_paths,
                    schedule=(sched_paths or None), schedule_specs=schedule_specs,
                    event=(tb_event or None), division=(tb_division or "17U/18U"),
                    outdir=tdir, div_pdf=divpdf_path, division_pdfs=division_pdfs,
                )
                st.session_state["tb_pdf"] = Path(pdf_path).read_bytes()
                st.session_state["tb_pdfname"] = os.path.basename(pdf_path)
                st.session_state["tb_csv"] = (Path(csv_path).read_text()
                                              if csv_path else None)
                st.session_state["tb_csvname"] = (os.path.basename(csv_path)
                                                  if csv_path else None)
                tstatus.update(label="Done", state="complete")
                # Auto-push schedule to Event Day app
                if _HAVE_PUSH and (tb_event or "").strip() and st.session_state.get("tb_csv"):
                    try:
                        _r = _push_event(
                            (tb_event or "").strip(),
                            st.session_state["tb_csv"],
                        )
                        st.session_state["tb_push_status"] = (
                            "✅ Pushed to Event Day",
                            f"**{_r['name']}** — {_r['action']} live for all coaches.",
                        )
                    except Exception as _pe:
                        st.session_state["tb_push_status"] = (
                            "⚠️ Event Day push failed",
                            str(_pe),
                        )
            except Exception as e:
                tstatus.update(label="Error", state="error")
                st.exception(e)
                st.stop()

    if "tb_pdf" in st.session_state:
        import csv as _csv
        st.divider()
        st.download_button("⬇️  Roster book (PDF)", data=st.session_state["tb_pdf"],
                           file_name=st.session_state["tb_pdfname"],
                           mime="application/pdf", use_container_width=True,
                           type="primary")
        _pdf_open_link(st.session_state["tb_pdf"], st.session_state["tb_pdfname"])
        if st.session_state.get("tb_csv"):
            csv_text = st.session_state["tb_csv"]
            reader = list(_csv.reader(io.StringIO(csv_text)))
            header, data = reader[0], reader[1:]
            st.markdown(f"**📅 Schedule** — {len(data)} games")
            st.dataframe(pd.DataFrame(data, columns=header),
                         use_container_width=True, hide_index=True)
            st.caption("Tap the copy icon to grab the whole schedule, or download the CSV.")
            tsv = "\n".join("\t".join(r) for r in reader)
            st.code(tsv, language=None)
            st.download_button("⬇️  Schedule (CSV)", data=csv_text,
                               file_name=st.session_state["tb_csvname"],
                               mime="text/csv", use_container_width=True)
            if st.session_state.get("tb_push_status"):
                icon, msg = st.session_state["tb_push_status"]
                if icon.startswith("✅"):
                    st.success(f"{icon} — {msg}")
                else:
                    st.warning(f"{icon} — {msg}")
            elif _HAVE_PUSH and not (st.session_state.get("tb_event") or "").strip():
                st.caption("💡 Add an event name above to auto-push this schedule "
                           "to the Event Day app.")


# ---- Schedule Refresh ----
with tab_sched:
    schedule_refresh.render()


# ---- Post-Event ----
with tab_post:
    st.subheader("Post-event ratings")

    # Rollout notice — self-expires 5 days after it was added (2026-06-30),
    # no manual cleanup needed. Chris asked for this so coaches stop doing
    # the old copy/paste workflow now that direct writes work.
    if datetime.now() <= datetime(2026, 7, 5, 23, 59, 59):
        st.info("**New:** you no longer need to copy/paste ratings into the spreadsheet "
                "yourself. Fill this out below and click **Write to Recruiting Sheet "
                "2.0** at the bottom — it goes straight in. (A copy/paste table is still "
                "available at the very bottom of this page as a manual backup.)")

    st.caption("Drop your annotated GoodNotes pages (exported as JPGs). I read the "
               "hand-written New★, split existing-board players from new players, and "
               "write straight to Recruiting Sheet 2.0.")

    pe_api_key = _get_api_key()
    if not pe_api_key:
        st.warning("Anthropic API key missing — set `ANTHROPIC_API_KEY` in Streamlit "
                   "secrets (the Admin tab shows status).")

    st.write("**1. Annotated pages (JPG)**")
    pe_imgs = st.file_uploader(
        "Export each GoodNotes page as a JPG and drop them here",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key="post_event_imgs",
        help="JPG, not PDF — PDF export garbles the handwriting.",
    )

    colA, colB = st.columns(2)
    with colA:
        pe_by = st.selectbox("By (initials)", ["CB", "AP", "TR", "AM", "CR"],
                             index=0, key="pe_by")
    with colB:
        pe_event = st.text_input("Event (optional — fills 'Seen')",
                                 placeholder="e.g. NPI 2026", key="pe_event")

    pe_go = st.button("📥 Extract & split", type="primary",
                      use_container_width=True,
                      disabled=not (pe_imgs and pe_api_key))

    if pe_go:
        with st.status("Reading pages…", expanded=True) as pstatus:
            try:
                pages = []
                for i, f in enumerate(pe_imgs):
                    mt = f.type or "image/jpeg"
                    if mt == "image/jpg":
                        mt = "image/jpeg"
                    pstatus.update(label=f"📄 Reading page {i+1}/{len(pe_imgs)}…")
                    page = extract_post_event_page(f.read(), media_type=mt,
                                                   api_key=pe_api_key)
                    pages.append(page)
                    st.write(f"✓ {page.get('team_name') or 'page'} — "
                             f"{len(page.get('players', []))} rows read")
                pe_db = parse_xlsx(str(XLSX_PATH)) if XLSX_PATH.exists() else None
                result = split_pools(pages, db=pe_db)
                pstatus.update(label="Done", state="complete")
            except Exception as e:
                pstatus.update(label="Error", state="error")
                st.exception(e)
                st.stop()

        new_rows = prefill_new_player_rows(
            result["new_players"], date_added=today_str(), by_initials=pe_by)
        if pe_event:
            for r in new_rows:
                r["Seen"] = pe_event
        st.session_state["pe_new_rows"] = new_rows
        st.session_state["pe_upd_rows"] = build_updates_rows(result["updates"])
        st.session_state["pe_upd_raw"] = result["updates"]
        st.session_state["pe_stats"] = result["stats"]
        st.session_state["pe_write_preview"] = None

    if "pe_stats" in st.session_state:
        s = st.session_state["pe_stats"]
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("New players", s["new_players"])
        c2.metric("Rating updates", s["updates"])
        c3.metric("Skipped (no New★)", s["skipped"])

        # Flag non-standard / ambiguous ratings (e.g. a "2/3" written by hand)
        _ok = {"0.1", "1", "2", "3", "4"}
        flags = []
        for r in st.session_state["pe_new_rows"]:
            v = str(r.get("★", "")).strip()
            if v and v not in _ok:
                flags.append(f"{r['First']} {r['Last']} — New★ '{v}'")
        for r in st.session_state["pe_upd_rows"]:
            v = str(r.get("New ★", "")).strip()
            if v and v not in _ok:
                flags.append(f"{r['Name']} — New★ '{v}'")
        if flags:
            st.warning("Review these ratings (non-standard / ambiguous) before you "
                       "paste:\n\n" + "\n".join(f"• {x}" for x in flags))

        # --- Updates ---
        st.markdown("**📈 Rating updates** — existing board players")
        if st.session_state["pe_upd_rows"]:
            st.dataframe(pd.DataFrame(st.session_state["pe_upd_rows"]),
                         use_container_width=True, hide_index=True)
        else:
            st.caption("No rating updates on these pages.")

        # --- New players (editable before write) ---
        st.markdown("**🆕 New players** — review/edit before writing")
        edited_rows = []
        if st.session_state["pe_new_rows"]:
            df = pd.DataFrame(st.session_state["pe_new_rows"],
                              columns=NEW_PLAYER_COLUMNS)
            edited = st.data_editor(
                df, use_container_width=True, hide_index=True,
                num_rows="dynamic", key="pe_editor",
                column_config={
                    "By": st.column_config.SelectboxColumn(
                        "By", options=["CB", "AP", "TR", "AM", "CR"], width="small"),
                },
            )
            edited_rows = edited.fillna("").to_dict("records")
        else:
            st.caption("No new players on these pages.")

        # --- Write straight to Recruiting Sheet 2.0 ---
        st.divider()
        sw_url = _get_secret("sheet_write_url")
        sw_token = _get_secret("sheet_write_token")
        if not (sw_url and sw_token):
            st.info("Sheet write-back not configured — set `sheet_write_url` / "
                    "`sheet_write_token` in Streamlit secrets (see "
                    "`apps_script/README.md`) to enable the button below instead of "
                    "the copy/paste tables above.")
        elif not pe_event:
            st.info("Fill in the **Event** field above first — it is what gets "
                    "appended to each player's Seen history.")
        else:
            upd_raw = st.session_state.get("pe_upd_raw", [])
            if st.button("📤 Write to Recruiting Sheet 2.0", type="primary",
                        use_container_width=True,
                        disabled=not (upd_raw or edited_rows)):
                with st.status("Writing to Recruiting Sheet 2.0…", expanded=True) as wstatus:
                    try:
                        st.write("Loading current sheet…")
                        db_for_write = parse_xlsx(str(XLSX_PATH))
                        cols = find_columns(str(XLSX_PATH))

                        st.write("Matching players…")
                        ops = []
                        for r in upd_raw:
                            ops.append(sheet_write.build_upsert_op(
                                db_for_write, cols, first=r.get("first", ""), last=r.get("last", ""),
                                event_name=pe_event, new_tier=(r.get("new_star") or "").strip(),
                                state=r.get("state", ""), hs=r.get("school", ""),
                                team=r.get("_team_name", ""), pos=r.get("pos", ""),
                                commit=r.get("commit", ""),
                                notes=r.get("notes_handwritten", "")))
                        for r in edited_rows:
                            ops.append(sheet_write.build_upsert_op(
                                db_for_write, cols, first=r.get("First", ""), last=r.get("Last", ""),
                                event_name=(r.get("Seen") or pe_event),
                                new_tier=str(r.get("★", "") or "").strip(),
                                state=r.get("State", ""), hs=r.get("High School", ""),
                                team=r.get("Summer Team", ""), pos=r.get("Pos", ""),
                                commit=r.get("Commit", ""), class_year=r.get("Class", ""),
                                by_initials=r.get("By", ""), date_added=r.get("Date Added", ""),
                                notes=r.get("Notes", "")))

                        st.write("Validating…")
                        check = sheet_write.post_ops(ops, sw_url, sw_token, dry_run=True)
                        if not check.get("ok"):
                            wstatus.update(label="Failed", state="error")
                            st.error(f"Validation failed, nothing written: {check.get('error')}")
                            st.stop()

                        st.write(f"Writing {len(ops)} player(s)…")
                        real = sheet_write.post_ops(ops, sw_url, sw_token, dry_run=False)
                        if real.get("ok"):
                            n_new = sum(1 for r in real["results"] if r["action"] == "append")
                            n_upd = sum(1 for r in real["results"] if r["action"] == "update")
                            wstatus.update(label="Done", state="complete")
                            st.success(f"✓ Written to Recruiting Sheet 2.0 — "
                                      f"{n_new} new player(s), {n_upd} update(s), "
                                      f"every field verified by reading it back.")
                        else:
                            wstatus.update(label="Failed", state="error")
                            bad = [(op, r) for op, r in zip(ops, real.get("results", []))
                                  if not r.get("ok")]
                            if bad:
                                st.error("Some fields did not verify after writing — "
                                        "nothing here is guaranteed applied correctly:")
                                for op, r in bad:
                                    st.write(f"- {op.get('player')} (row {r.get('row')}): "
                                            f"{r.get('error')}")
                            else:
                                st.error(f"Write failed: {real.get('error')}")
                        with st.expander("🔍 What was sent (debug)"):
                            st.write("Resolved columns for this write:")
                            st.json(cols)
                            st.write("Built from the table above:")
                            st.json(ops)
                            st.write("Apps Script verified after writing (read back, not just setValue success):")
                            st.json(real)
                    except requests.exceptions.RequestException as e:
                        wstatus.update(label="Failed", state="error")
                        st.error(f"Couldn't reach the Recruiting Sheet 2.0 write endpoint "
                                f"after retrying — this is a network/timeout issue, not a "
                                f"data problem. **Nothing was written** (this failed during "
                                f"validation, before any real write is attempted). This is "
                                f"most common right after a Code.gs redeploy — wait a few "
                                f"seconds and click the write button again.\n\n`{e}`")
                    except Exception as e:
                        wstatus.update(label="Failed", state="error")
                        st.exception(e)

        # --- Manual fallback: copy/paste tables, same shape as the old
        # workflow. Chris asked to keep this available at the bottom in
        # case the direct write has a bad day - it uses the same
        # edited_rows / pe_upd_rows already built above, not a separate
        # path, so it can never drift out of sync with what "Write to
        # Recruiting Sheet 2.0" would send. ---
        st.divider()
        with st.expander("🛟 Manual fallback — copy/paste into the sheet yourself"):
            st.caption("Only needed if the write button above has a bad day. Each "
                       "block is a tab-separated table — click the copy icon in the "
                       "top-right of the box, then paste directly into the sheet.")
            st.markdown("**New players**")
            if edited_rows:
                new_tsv = rows_to_csv(edited_rows, NEW_PLAYER_COLUMNS,
                                      delimiter="\t").decode("utf-8")
                st.code(new_tsv, language=None)
                st.download_button("⬇️ New players (CSV)",
                                   data=rows_to_csv(edited_rows, NEW_PLAYER_COLUMNS),
                                   file_name="new_players.csv", mime="text/csv",
                                   key="pe_fallback_new_dl")
            else:
                st.caption("No new players on these pages.")
            st.markdown("**Rating updates**")
            if st.session_state["pe_upd_rows"]:
                upd_tsv = rows_to_csv(st.session_state["pe_upd_rows"], UPDATE_COLUMNS,
                                      delimiter="\t").decode("utf-8")
                st.code(upd_tsv, language=None)
                st.download_button("⬇️ Rating updates (CSV)",
                                   data=rows_to_csv(st.session_state["pe_upd_rows"], UPDATE_COLUMNS),
                                   file_name="rating_updates.csv", mime="text/csv",
                                   key="pe_fallback_upd_dl")
            else:
                st.caption("No rating updates on these pages.")


# ---- Add Player ----
@st.cache_data(ttl=60, show_spinner=False)
def _load_db_and_cols(mtime_key):
    """Cached so the live duplicate-check below doesn't re-parse the xlsx on
    every keystroke. Keyed on the file's mtime so it naturally refreshes
    after a sync/write without a manual cache-clear."""
    return parse_xlsx(str(XLSX_PATH)), find_columns(str(XLSX_PATH))


# Option lists below are copied field-for-field from the live AppSheet "High
# School Players Form" 2026-06-30 (Chris wanted this tab to look and behave
# like that form specifically) - do not add/remove options without checking
# the real form again, this is not a guess.
_AP_BY_OPTIONS = ["CB", "AP", "TR", "AM", "CR"]
_AP_TIER_OPTIONS = ["1", "2", "3", "4", "5", "0.1", "XX"]
_AP_POS_OPTIONS = ["RHP", "LHP", "MINF", "CINF", "C", "UTL", "OF",
                   "COF", "INF", "1B", "2B", "3B", "SS", "CF",
                   "Power Bat", "Burner OF"]
_AP_BT_OPTIONS = ["R/R", "R/L", "L/L", "L/R", "S/R", "S/L"]


def _ap_class_years():
    """Rolling 5-year window matching the live AppSheet form (was 2025-2029
    on 2026-06-30, i.e. current_year-1 through current_year+3) - computed
    so it doesn't go stale like a hardcoded list would."""
    y = datetime.now().year
    return [str(y - 1 + i) for i in range(5)]


def _ap_org_tier_flag(team):
    if not team:
        return
    match = lookup_org_tier(team)
    if match:
        st.caption(f"✓ \"{team}\" recognized as a Tier {match} travel program.")
    else:
        st.caption(f"⚠️ \"{team}\" isn't in the tracked travel programs list — "
                  "will still be saved exactly as written.")


with tab_add:
    st.subheader("Add a player")
    st.caption("Straight into Recruiting Sheet 2.0 — from screenshots, or by hand.")

    ap_api_key = _get_api_key()
    ap_sw_url = _get_secret("sheet_write_url")
    ap_sw_token = _get_secret("sheet_write_token")

    ap_mode = st.radio("How are you adding players?",
                       ["📸 From screenshots", "✍️ Manual entry"],
                       horizontal=True, key="ap_mode")

    # ============================= SCREENSHOTS =============================
    # Batch: several screenshots in one pass -> one reviewable table -> one
    # write, same shape as the Post-Event tab's New Players table. Chris
    # explicitly did not want single-player-at-a-time here.
    if ap_mode == "📸 From screenshots":
        if not ap_api_key:
            st.warning("Anthropic API key missing — set `ANTHROPIC_API_KEY` in Streamlit secrets.")
        ap_imgs = st.file_uploader(
            "Twitter/X profile, FiveTool/PBR profile, or roster-list screenshots",
            type=["jpg", "jpeg", "png", "webp", "heic"],
            accept_multiple_files=True, key="ap_imgs")
        colA, colB = st.columns(2)
        with colA:
            ap_batch_by = st.selectbox("By (initials)", _AP_BY_OPTIONS, key="ap_batch_by")
        with colB:
            ap_batch_source = st.text_input("Source (fills Seen)",
                                            placeholder="e.g. Twitter scouting",
                                            key="ap_batch_source")

        if st.button("🔍 Extract all", type="primary", use_container_width=True,
                    disabled=not (ap_imgs and ap_api_key)):
            rows = []
            from sheet_write import today_str as _today_str
            today = _today_str()
            with st.status(f"Reading {len(ap_imgs)} screenshot(s)…", expanded=True) as ap_xstatus:
                for i, img in enumerate(ap_imgs):
                    st.write(f"📄 {i+1}/{len(ap_imgs)} — {img.name}")
                    mt = img.type or "image/jpeg"
                    if mt == "image/jpg": mt = "image/jpeg"
                    try:
                        ex = twitter_extract.extract_twitter_player(
                            img.read(), media_type=mt, api_key=ap_api_key)
                        rows.append({
                            "First": ex.get("first", ""), "Last": ex.get("last", ""),
                            "Class": ex.get("class", ""), "★": "", "Commit": ex.get("commit", ""),
                            "Pos": ex.get("pos", ""), "POS2": ex.get("pos2", ""),
                            "B/T": ex.get("bt", ""), "Hometown": ex.get("hometown", ""),
                            "State": ex.get("state", ""), "High School": ex.get("hs", ""),
                            "Summer Team": ex.get("team", ""), "Academic": ex.get("academic", ""),
                            "Email": ex.get("email", ""), "Phone": ex.get("phone", ""),
                            "Seen": ap_batch_source, "Comms": "", "Notes": ex.get("notes", ""),
                            "By": ap_batch_by, "Date Added": today,
                        })
                    except Exception as e:
                        st.error(f"Failed on {img.name}: {e}")
                ap_xstatus.update(label="Done", state="complete")
            st.session_state["ap_batch_rows"] = rows

        ap_batch_rows = st.session_state.get("ap_batch_rows", [])
        if ap_batch_rows:
            st.divider()
            st.markdown("**Review before adding**")

            # Duplicate check, shown BEFORE the write - manual entry already
            # warns about an existing match (line ~1240 below); the batch
            # path never did, so a screenshot of a kid already on the board
            # would silently become an "update" with no heads-up. Found by
            # Chris 2026-07-02: added a second player who was already in the
            # system, got no notice, just a generic "Done." This uses the
            # same cached db + lookup() as manual entry, not a new check.
            if XLSX_PATH.exists():
                from db_loader import lookup as _ap_batch_lookup
                ap_batch_db, _ = _load_db_and_cols(XLSX_PATH.stat().st_mtime)
                ap_batch_dups = []
                for r in ap_batch_rows:
                    if not (r.get("First") and r.get("Last")):
                        continue
                    match = _ap_batch_lookup(ap_batch_db, f"{r['First']} {r['Last']}")
                    if match:
                        ap_batch_dups.append((r["First"], r["Last"], match))
                if ap_batch_dups:
                    dup_lines = "\n".join(
                        f"- **{first} {last}** matches an existing player, "
                        f"**{m['canonical_name']}** (Tier {m.get('tier') or '?'}, "
                        f"{m.get('hs') or 'no school listed'}) — this will **update** "
                        f"that player, not add a duplicate."
                        for first, last, m in ap_batch_dups)
                    st.warning("⚠️ Already on the board:\n\n" + dup_lines)

            ap_batch_df = st.data_editor(
                pd.DataFrame(ap_batch_rows), use_container_width=True, hide_index=True,
                num_rows="dynamic", key="ap_batch_editor",
                column_config={
                    "By": st.column_config.SelectboxColumn("By", options=_AP_BY_OPTIONS, width="small"),
                    "★": st.column_config.SelectboxColumn("★", options=[""] + _AP_TIER_OPTIONS, width="small"),
                    "Pos": st.column_config.SelectboxColumn("Pos", options=[""] + _AP_POS_OPTIONS, width="small"),
                    "POS2": st.column_config.SelectboxColumn("POS2", options=[""] + _AP_POS_OPTIONS, width="small"),
                    "B/T": st.column_config.SelectboxColumn("B/T", options=[""] + _AP_BT_OPTIONS, width="small"),
                    "Class": st.column_config.SelectboxColumn("Class", options=[""] + _ap_class_years(), width="small"),
                },
            )
            ap_batch_edited = ap_batch_df.fillna("").to_dict("records")

            if not (ap_sw_url and ap_sw_token):
                st.info("Sheet write-back not configured — set `sheet_write_url` / "
                        "`sheet_write_token` in Streamlit secrets (see `apps_script/README.md`).")
            elif st.button("➕ Add all to Recruiting Sheet 2.0", type="primary",
                          use_container_width=True):
                with st.status("Writing to Recruiting Sheet 2.0…", expanded=True) as bstatus:
                    try:
                        st.write("Loading current sheet…")
                        bdb = parse_xlsx(str(XLSX_PATH))
                        bcols = find_columns(str(XLSX_PATH))

                        st.write(f"Matching {len(ap_batch_edited)} player(s)…")
                        bops = []
                        for r in ap_batch_edited:
                            if not (r.get("First") and r.get("Last")):
                                continue
                            bops.append(sheet_write.build_upsert_op(
                                bdb, bcols, first=r["First"], last=r["Last"],
                                event_name=r.get("Seen") or "Added via app",
                                new_tier=r.get("★") or None, state=r.get("State", ""),
                                hs=r.get("High School", ""), team=r.get("Summer Team", ""),
                                pos=r.get("Pos", ""), pos2=r.get("POS2", ""),
                                bt=r.get("B/T", ""), hometown=r.get("Hometown", ""),
                                commit=r.get("Commit", ""), class_year=r.get("Class", ""),
                                by_initials=r.get("By", ""), date_added=r.get("Date Added", ""),
                                academic=r.get("Academic", ""), email=r.get("Email", ""),
                                phone=r.get("Phone", ""), comms=r.get("Comms", ""),
                                notes=r.get("Notes", "")))

                        st.write("Validating…")
                        bcheck = sheet_write.post_ops(bops, ap_sw_url, ap_sw_token, dry_run=True)
                        if not bcheck.get("ok"):
                            bstatus.update(label="Failed", state="error")
                            st.error(f"Validation failed, nothing written: {bcheck.get('error')}")
                            st.stop()

                        st.write(f"Writing {len(bops)} player(s)…")
                        breal = sheet_write.post_ops(bops, ap_sw_url, ap_sw_token, dry_run=False)
                        if breal.get("ok"):
                            new_names = [op.get('player') for op, r in zip(bops, breal["results"])
                                        if r["action"] == "append"]
                            upd_names = [op.get('player') for op, r in zip(bops, breal["results"])
                                        if r["action"] == "update"]
                            bstatus.update(label="Done", state="complete")
                            st.success(f"✓ Written to Recruiting Sheet 2.0 — "
                                      f"{len(new_names)} new player(s), {len(upd_names)} update(s), "
                                      "every field verified by reading it back.")
                            # Named, not just counted - a coach re-adding someone already
                            # on the board needs to see WHO got updated, not just a number
                            # buried in one sentence (Chris 2026-07-02: got no notice a
                            # screenshot matched an existing player).
                            if upd_names:
                                st.info("🔄 Updated existing profile(s) instead of adding "
                                       "duplicates: " + ", ".join(upd_names))
                            st.session_state["ap_batch_rows"] = []
                            _load_db_and_cols.clear()
                        else:
                            bstatus.update(label="Failed", state="error")
                            bad = [(op, r) for op, r in zip(bops, breal.get("results", []))
                                  if not r.get("ok")]
                            for op, r in bad:
                                st.error(f"{op.get('player')}: {r.get('error')}")
                        with st.expander("🔍 What was sent (debug)"):
                            st.json(bops)
                            st.json(breal)
                    except requests.exceptions.RequestException as e:
                        bstatus.update(label="Failed", state="error")
                        st.error(f"Couldn't reach the Recruiting Sheet 2.0 write endpoint "
                                f"after retrying — this is a network/timeout issue, not a "
                                f"data problem. **Nothing was written** (this failed during "
                                f"validation, before any real write is attempted). This is "
                                f"most common right after a Code.gs redeploy — wait a few "
                                f"seconds and click the write button again.\n\n`{e}`")
                    except Exception as e:
                        bstatus.update(label="Failed", state="error")
                        st.exception(e)

    # ============================== MANUAL ==================================
    # Field order, control types (pill buttons vs dropdown vs text), and
    # option lists all copied from the live AppSheet form on purpose.
    else:
        c1, c2 = st.columns(2)
        with c1:
            ap_date_added = st.date_input("Date Added", value=datetime.now(), key="ap_date_added")
        with c2:
            ap_by = st.pills("By", _AP_BY_OPTIONS, key="ap_by")

        ap_first = st.text_input("First Name", key="ap_first")
        ap_last = st.text_input("Last Name", key="ap_last")
        ap_class = st.pills("Class", _ap_class_years(), key="ap_class")
        ap_tier = st.pills("★", _AP_TIER_OPTIONS, key="ap_tier")
        ap_commit = st.text_input("Commit", placeholder="leave blank if uncommitted", key="ap_commit")
        ap_pos = st.pills("Pos", _AP_POS_OPTIONS, key="ap_pos")
        ap_pos2 = st.selectbox("POS2", [""] + _AP_POS_OPTIONS, key="ap_pos2")
        ap_bt = st.pills("B/T", _AP_BT_OPTIONS, key="ap_bt")
        ap_hometown = st.text_input("Hometown", key="ap_hometown")
        ap_state = st.text_input("State", key="ap_state")
        ap_hs = st.text_input("High School", key="ap_hs")
        ap_team = st.text_input("Summer Team", key="ap_team")
        _ap_org_tier_flag(ap_team)
        ap_academic = st.text_input("Academic", placeholder="GPA / SAT / ACT", key="ap_academic")
        ap_email = st.text_input("Email", key="ap_email")
        ap_phone = st.text_input("Phone Number", key="ap_phone")
        ap_seen = st.text_input("Seen", placeholder="e.g. Twitter scouting, NPI 2026", key="ap_seen")
        ap_comms = st.text_input("Comms", key="ap_comms")
        ap_notes = st.text_area("Notes", key="ap_notes", height=80)

        ap_dup = None
        if ap_first and ap_last and XLSX_PATH.exists():
            from db_loader import lookup as _ap_lookup
            ap_db, ap_cols = _load_db_and_cols(XLSX_PATH.stat().st_mtime)
            ap_dup = _ap_lookup(ap_db, f"{ap_first} {ap_last}")
            if ap_dup:
                st.warning(f"⚠️ **{ap_dup['canonical_name']}** is already in the database "
                          f"(Tier {ap_dup.get('tier') or '?'}, "
                          f"{ap_dup.get('hs') or 'no school listed'}) — submitting will "
                          "**update** this existing player instead of creating a duplicate.")

        ap_label = "🔄 Update existing player" if ap_dup else "➕ Add to Recruiting Sheet 2.0"
        if not (ap_sw_url and ap_sw_token):
            st.info("Sheet write-back not configured — set `sheet_write_url` / "
                    "`sheet_write_token` in Streamlit secrets (see `apps_script/README.md`).")
        elif st.button(ap_label, type="primary", use_container_width=True,
                      disabled=not (ap_first and ap_last)):
            with st.status("Writing to Recruiting Sheet 2.0…", expanded=True) as ap_wstatus:
                try:
                    st.write("Loading current sheet…")
                    ap_db_write = parse_xlsx(str(XLSX_PATH))
                    ap_cols_write = find_columns(str(XLSX_PATH))

                    st.write("Building record…")
                    ap_op = sheet_write.build_upsert_op(
                        ap_db_write, ap_cols_write, first=ap_first, last=ap_last,
                        event_name=ap_seen or "Added via app", new_tier=ap_tier,
                        state=ap_state, hs=ap_hs, team=ap_team, pos=ap_pos, pos2=ap_pos2,
                        bt=ap_bt, hometown=ap_hometown, commit=ap_commit,
                        class_year=ap_class, by_initials=ap_by,
                        date_added=ap_date_added.strftime("%-m/%-d/%Y"),
                        academic=ap_academic, email=ap_email, phone=ap_phone,
                        comms=ap_comms, notes=ap_notes)

                    st.write("Validating…")
                    ap_check = sheet_write.post_ops([ap_op], ap_sw_url, ap_sw_token, dry_run=True)
                    if not ap_check.get("ok"):
                        ap_wstatus.update(label="Failed", state="error")
                        st.error(f"Validation failed, nothing written: {ap_check.get('error')}")
                        st.stop()

                    st.write("Writing…")
                    ap_real = sheet_write.post_ops([ap_op], ap_sw_url, ap_sw_token, dry_run=False)
                    if ap_real.get("ok"):
                        ap_wstatus.update(label="Done", state="complete")
                        verb = "Updated" if ap_op["action"] == "update" else "Added"
                        st.success(f"✓ {verb} {ap_op['player']} in Recruiting Sheet 2.0, "
                                  "every field verified by reading it back.")
                        _load_db_and_cols.clear()
                    else:
                        ap_wstatus.update(label="Failed", state="error")
                        r = ap_real.get("results", [{}])[0]
                        st.error(f"Some fields did not verify: {r.get('error', ap_real.get('error'))}")
                    with st.expander("🔍 What was sent (debug)"):
                        st.json(ap_op)
                        st.json(ap_real)
                except requests.exceptions.RequestException as e:
                    ap_wstatus.update(label="Failed", state="error")
                    st.error(f"Couldn't reach the Recruiting Sheet 2.0 write endpoint "
                            f"after retrying — this is a network/timeout issue, not a "
                            f"data problem. **Nothing was written** (this failed during "
                            f"validation, before any real write is attempted). This is "
                            f"most common right after a Code.gs redeploy — wait a few "
                            f"seconds and click the write button again.\n\n`{e}`")
                except Exception as e:
                    ap_wstatus.update(label="Failed", state="error")
                    st.exception(e)


# ---- Board ----
# Browse the recruiting board one class + position group at a time, styled
# to match a mock Chris built directly in Sheets, plus a per-player profile
# card (click a row -> st.dialog modal, edit any field) - the thing that
# used to require opening High School Players directly (or AppSheet).
# Reuses db_loader.all_players() (same parsed data Field Tool/Add Player
# already load, just deduped to one row per player), sheet_write.pos_group()
# (the same RHP/LHP/INF/OF/C bucketing the sheet itself uses), and
# sheet_write.build_profile_update_op()/build_note_update_op() - no new
# data path, no new write path.
_BOARD_POS_GROUPS = ['ALL', 'RHP', 'LHP', 'INF', 'OF', 'C']
# Matches the live Big Board tab's own default (its FILTER formula's
# threshold is "★ < 3") - a user-facing filter now instead of a hardcoded
# tuple, since Chris wants the option to widen it.
_BOARD_TIER_FILTER_OPTIONS = ['0.1', '1', '2', '3', '4', 'XX']
_BOARD_TIER_FILTER_DEFAULT = ['0.1', '1', '2']
_BOARD_TIER_FILTER_LABELS = {'0.1': '0.1 · Committed', '1': '1 · Offer',
                             '2': '2 · High Follow', '3': '3 · Follow',
                             '4': '4 · Need to see', 'XX': 'XX · Off list'}
# Rating bubble colors - matches gen_roster_pdf.TIER_DOT_COLOR exactly
# (can't import directly, those are reportlab Color objects; this is CSS -
# duplicated on purpose, keep in sync if that palette ever changes). Per
# Chris: "show as the bubbles colored like on my pdfs." (dot_bg, dot_fg,
# dot_label) per tier.
_BOARD_TIER_BADGE = {
    '0.1': ('#1A3A6B', '#FFFFFF', 'C'),
    '1':   ('#2E7D32', '#FFFFFF', '1'),
    '2':   ('#F9A825', '#333300', '2'),
    '3':   ('#7E57C2', '#FFFFFF', '3'),
    '4':   ('#90CAF9', '#1A3A6B', '4'),
}


def _bd_write(ops, sw_url, sw_token, player_label):
    """Dry-run-then-write, same pattern as every other write path in this
    app (Add Player, Post-Event). Shared by the profile dialog's Save."""
    if not ops:
        st.info("Nothing changed.")
        return
    with st.status("Writing to Recruiting Sheet 2.0…", expanded=True) as wstatus:
        try:
            st.write("Validating…")
            check = sheet_write.post_ops(ops, sw_url, sw_token, dry_run=True)
            if not check.get("ok"):
                wstatus.update(label="Failed", state="error")
                st.error(f"Validation failed, nothing written: {check.get('error')}")
                st.stop()

            st.write("Writing…")
            real = sheet_write.post_ops(ops, sw_url, sw_token, dry_run=False)
            if real.get("ok"):
                wstatus.update(label="Done", state="complete")
                st.success(f"✓ Updated {player_label} in Recruiting Sheet 2.0, "
                          "every field verified by reading it back.")
                _load_db_and_cols.clear()
            else:
                wstatus.update(label="Failed", state="error")
                bad = [(op, r) for op, r in zip(ops, real.get("results", [])) if not r.get("ok")]
                for op, r in bad:
                    st.error(f"{op.get('player')}: {r.get('error')}")
            with st.expander("🔍 What was sent (debug)"):
                st.json(ops)
                st.json(real)
        except requests.exceptions.RequestException as e:
            wstatus.update(label="Failed", state="error")
            st.error(f"Couldn't reach the Recruiting Sheet 2.0 write endpoint "
                    f"after retrying — this is a network/timeout issue, not a "
                    f"data problem. **Nothing was written** (this failed during "
                    f"validation, before any real write is attempted). This is "
                    f"most common right after a Code.gs redeploy — wait a few "
                    f"seconds and click the write button again.\n\n`{e}`")
        except Exception as e:
            wstatus.update(label="Failed", state="error")
            st.exception(e)


@st.dialog("Player profile")
def _bd_profile_dialog(p, cols, sw_url, sw_token):
    """The 'little card' - opened by clicking a player's row button. Shows
    and edits every field parse_xlsx() loads, not just tier/notes, per
    Chris's explicit ask ("really all of them if we can")."""
    st.markdown(f"### {p['canonical_name']}")
    st.caption(f"{p.get('hs') or 'no school listed'} · {p.get('team') or 'no summer team listed'}")
    if p.get('notes'):
        st.caption("**Notes so far:**  \n" + p['notes'].replace('\n', '  \n'))

    c1, c2, c3 = st.columns(3)
    with c1:
        tier_default = p['tier'] if p['tier'] in _AP_TIER_OPTIONS else None
        f_tier = st.pills("★", _AP_TIER_OPTIONS, default=tier_default, key=f"bdp_tier_{p['_row']}")
        f_class = st.pills("Class", _ap_class_years(),
                           default=p['class'] if p['class'] in _ap_class_years() else None,
                           key=f"bdp_class_{p['_row']}")
    with c2:
        f_pos = st.pills("Pos", _AP_POS_OPTIONS, default=p['pos'] if p['pos'] in _AP_POS_OPTIONS else None,
                         key=f"bdp_pos_{p['_row']}")
        f_pos2 = st.selectbox("POS2", [""] + _AP_POS_OPTIONS,
                              index=([""] + _AP_POS_OPTIONS).index(p['pos2']) if p.get('pos2') in _AP_POS_OPTIONS else 0,
                              key=f"bdp_pos2_{p['_row']}")
    with c3:
        f_bt = st.pills("B/T", _AP_BT_OPTIONS, default=p['bt'] if p['bt'] in _AP_BT_OPTIONS else None,
                        key=f"bdp_bt_{p['_row']}")

    f_commit = st.text_input("Commit", value=p.get('commit') or '', key=f"bdp_commit_{p['_row']}")
    f_hometown = st.text_input("Hometown", value=p.get('hometown') or '', key=f"bdp_hometown_{p['_row']}")
    f_state = st.text_input("State", value=p.get('state') or '', key=f"bdp_state_{p['_row']}")
    f_hs = st.text_input("High School", value=p.get('hs') or '', key=f"bdp_hs_{p['_row']}")
    f_team = st.text_input("Summer Team", value=p.get('team') or '', key=f"bdp_team_{p['_row']}")
    f_academic = st.text_input("Academic", value=p.get('academic') or '', key=f"bdp_academic_{p['_row']}")
    f_email = st.text_input("Email", value=p.get('email') or '', key=f"bdp_email_{p['_row']}")
    f_phone = st.text_input("Phone", value=p.get('phone') or '', key=f"bdp_phone_{p['_row']}")
    f_comms = st.text_input("Comms", value=p.get('comms') or '', key=f"bdp_comms_{p['_row']}")
    f_note = st.text_area("Add a note (appended, doesn't overwrite prior notes)",
                          key=f"bdp_note_{p['_row']}")

    if not (sw_url and sw_token):
        st.info("Sheet write-back not configured — set `sheet_write_url` / "
                "`sheet_write_token` in Streamlit secrets (see `apps_script/README.md`).")
    elif st.button("💾 Save", type="primary", use_container_width=True, key=f"bdp_save_{p['_row']}"):
        ops = []
        # 'class' is a Python keyword, so it has to go through **{} rather
        # than a normal kwarg like the rest of these.
        profile_op = sheet_write.build_profile_update_op(
            p, cols, **{
                'tier': f_tier, 'commit': f_commit, 'pos': f_pos, 'pos2': f_pos2,
                'bt': f_bt, 'class': f_class, 'hometown': f_hometown, 'state': f_state,
                'hs': f_hs, 'team': f_team, 'academic': f_academic, 'email': f_email,
                'phone': f_phone, 'comms': f_comms,
            })
        if profile_op:
            ops.append(profile_op)
        note_op = sheet_write.build_note_update_op(p, cols, f_note)
        if note_op:
            ops.append(note_op)
        _bd_write(ops, sw_url, sw_token, p['canonical_name'])


with tab_board:
    st.subheader("Recruiting board")
    st.caption("Same board as the sheet — click a player to view or edit their profile.")

    if not XLSX_PATH.exists():
        st.warning("Recruiting xlsx not loaded — go to **Admin** tab")
    else:
        from db_loader import all_players as _all_players

        bd_db, bd_cols = _load_db_and_cols(XLSX_PATH.stat().st_mtime)
        bd_players = _all_players(bd_db)
        bd_sw_url = _get_secret("sheet_write_url")
        bd_sw_token = _get_secret("sheet_write_token")

        bd_classes = sorted({p['class'] for p in bd_players if p['class']}, reverse=True)

        f1, f2 = st.columns(2)
        with f1:
            bd_class = st.selectbox("Class", bd_classes, key="bd_class")
        with f2:
            bd_pos = st.selectbox("Position", _BOARD_POS_GROUPS, key="bd_pos")
        bd_tiers = st.multiselect("Show ratings", _BOARD_TIER_FILTER_OPTIONS,
                                  default=_BOARD_TIER_FILTER_DEFAULT,
                                  format_func=lambda t: _BOARD_TIER_FILTER_LABELS[t],
                                  key="bd_tiers")

        bd_filtered = [p for p in bd_players
                       if p['class'] == bd_class
                       and (bd_pos == 'ALL' or sheet_write.pos_group(p['pos']) == bd_pos)
                       and p['tier'] in bd_tiers]
        bd_filtered.sort(key=lambda p: ((float(p['tier']) if p['tier'] != 'XX' else 99),
                                        p['last'], p['first']))

        bd_show_bt = bd_pos != 'RHP' and bd_pos != 'LHP'  # pitchers: Pos already implies throwing hand
        bd_show_pos = bd_pos == 'ALL'  # position is implied by the filter otherwise

        if not bd_filtered:
            st.caption(f"No {bd_pos} in the {bd_class} class at the selected rating(s) right now.")
        else:
            # st.dataframe's row selection only responds to its own checkbox
            # column - confirmed live 2026-07-02 by clicking directly on a
            # NAME cell and seeing nothing happen. Chris doesn't want that
            # checkbox visible at all, and wants the whole row clickable, so
            # dataframe is out. Back to a real st.button per row (reliable
            # click-anywhere, no checkbox, no icon-font dependency) inside
            # st.container(horizontal=True) (doesn't stack on a phone
            # viewport the way st.columns() does). Fixed pixel widths on
            # every column, including TEAM - "stretch" on a non-last column
            # pushed it onto its own line in an earlier attempt. Wrapped in
            # a scoped, horizontally-scrollable container so a wide
            # combination (ALL positions + B/T + state + team) scrolls
            # instead of squeezing.
            #
            # Rating is its own real colored bubble now (matching
            # gen_roster_pdf.TIER_DOT_COLOR exactly, per Chris - "show as
            # the bubbles colored like on my pdfs"), not text fused into the
            # button - a plain st.button label can't render a colored
            # circle. That splits the click target down to just the name
            # button (which centers its label natively, unlike the bubble
            # which sits left in its own narrow column) - matches Chris's
            # literal ask ("i want to be able to click the name"), the
            # bubble was never required to be part of the click target.
            # Column order after Name, per Chris: POS, ST, TEAM, B/T.
            # Header row was rendering at ~9.6px tall - `overflow-x: auto` on
            # the SAME element that also holds the row's content collapsed
            # it, because Streamlit's own layout wrapper resolves height
            # against the overflow box rather than the (short, button-less)
            # header content - confirmed live via computed style, not
            # guessed. Fix: overflow-x scrolling now lives on ONE outer
            # wrapper around the whole header+rows stack (so header and
            # rows scroll horizontally together, in sync, instead of each
            # row being its own independent scroller), and every row/header
            # gets an explicit min-height instead of trusting content to
            # size it. Header is also its own keyed container now, sticky
            # to the top of the page on vertical scroll ("freeze label row
            # as we scroll").
            st.markdown("""
                <style>
                .st-key-nb_board_rows {
                    overflow-x: auto !important;
                    gap: 0.2rem !important;
                }
                .st-key-nb_board_rows [data-testid="stHorizontalBlock"] {
                    flex-wrap: nowrap !important;
                    align-items: center !important;
                    min-height: 38px !important;
                }
                .st-key-nb_board_rows [data-testid="stVerticalBlock"] {
                    justify-content: center !important;
                    gap: 0 !important;
                }
                /* Streamlit gives every element wrapper a bottom margin;
                   inside the board it skews vertical centering, so zero it. */
                .st-key-nb_board_rows [data-testid="stMarkdown"],
                .st-key-nb_board_rows [data-testid="stMarkdownContainer"],
                .st-key-nb_board_rows .stElementContainer {
                    margin: 0 !important;
                }
                /* Never let a name wrap to a second line inside its button. */
                .st-key-nb_board_rows .stButton button p {
                    white-space: nowrap !important;
                    font-size: 14px !important;
                }
                .st-key-nb_board_header {
                    position: sticky !important;
                    top: 0 !important;
                    z-index: 5 !important;
                    background: #FFFFFF !important;
                }
                </style>
                """, unsafe_allow_html=True)

            # Desktop-first sizing (2026-07-02: "you're forcing it to look
            # good on mobile and it's just not looking good at all on
            # desktop"). Name column is sized to the longest visible name so
            # no button label ever wraps to a second line; everything else
            # got real breathing room. Narrow phones still get the
            # horizontal-scroll wrapper below rather than squeezed columns.
            bd_name_w = max(170, 24 + round(max(
                len(p['canonical_name']) for p in bd_filtered) * 8.2))
            bd_widths = [40, bd_name_w]  # bubble, name
            if bd_show_pos:
                bd_widths.append(56)
            bd_widths += [46, 210]  # ST, TEAM
            if bd_show_bt:
                bd_widths.append(56)

            with st.container(key="nb_board_rows"):
                # One continuous dark bar (2026-07-02: "I don't like how
                # those are bubbles. I'd like it to be one straight name
                # across") - a single flex div whose cells reuse bd_widths,
                # so the labels line up over the row columns below. The flex
                # gap must match the gap="small" the row containers use;
                # verified live with preview_inspect rather than assumed.
                headers = ["★", "NAME"]
                if bd_show_pos:
                    headers.append("POS")
                headers += ["ST", "TEAM"]
                if bd_show_bt:
                    headers.append("B/T")
                hdr_cells = ''.join(
                    f'<span style="flex:0 0 {w}px;'
                    f'text-align:{"left" if lbl == "TEAM" else "center"};">'
                    f'{lbl}</span>'
                    for lbl, w in zip(headers, bd_widths))
                with st.container(key="nb_board_header"):
                    st.markdown(f'<div style="display:flex;gap:1rem;min-width:max-content;'
                               f'background:#14233B;color:#FFFFFF;font-size:12px;'
                               f'font-weight:700;padding:7px 0;border-radius:6px;'
                               f'white-space:nowrap;">{hdr_cells}</div>',
                               unsafe_allow_html=True)

                # Every text cell gets an explicit line-height equal to the
                # name button's rendered height, so POS/ST/TEAM sit dead
                # center against the name no matter what Streamlit's element
                # wrappers do with margins (2026-07-02: "they're bottom
                # aligned if you look at it visually to the names").
                _BD_ROW_H = 38
                for p in bd_filtered:
                    dot_bg, dot_fg, dot_label = _BOARD_TIER_BADGE.get(p['tier'], ('#CCCCCC', '#000', '?'))
                    with st.container(horizontal=True, gap="small"):
                        with st.container(width=bd_widths[0]):
                            st.markdown(f'<div style="width:28px;height:28px;border-radius:50%;'
                                       f'background:{dot_bg};color:{dot_fg};text-align:center;'
                                       f'line-height:28px;font-weight:700;font-size:12px;'
                                       f'margin:{(_BD_ROW_H - 28) // 2}px auto;">'
                                       f'{dot_label}</div>', unsafe_allow_html=True)
                        with st.container(width=bd_widths[1]):
                            if st.button(p['canonical_name'], key=f"bd_open_{p['_row']}",
                                        width="stretch"):
                                _bd_profile_dialog(p, bd_cols, bd_sw_url, bd_sw_token)
                        wi = 2
                        if bd_show_pos:
                            with st.container(width=bd_widths[wi]):
                                st.markdown(f'<div style="text-align:center;font-size:13px;'
                                           f'line-height:{_BD_ROW_H}px;'
                                           f'white-space:nowrap;">{html.escape(p["pos"] or "—")}'
                                           f'</div>', unsafe_allow_html=True)
                            wi += 1
                        with st.container(width=bd_widths[wi]):
                            st.markdown(f'<div style="text-align:center;font-size:13px;'
                                       f'line-height:{_BD_ROW_H}px;'
                                       f'white-space:nowrap;">{html.escape(p["state"] or "—")}'
                                       f'</div>', unsafe_allow_html=True)
                        wi += 1
                        with st.container(width=bd_widths[wi]):
                            st.markdown(f'<div style="text-align:left;font-size:12px;color:#555;'
                                       f'line-height:{_BD_ROW_H}px;'
                                       f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                                       f'{html.escape(p["team"] or "")}</div>', unsafe_allow_html=True)
                        wi += 1
                        if bd_show_bt:
                            with st.container(width=bd_widths[wi]):
                                st.markdown(f'<div style="text-align:center;font-size:13px;'
                                           f'line-height:{_BD_ROW_H}px;'
                                           f'white-space:nowrap;">{html.escape(p["bt"] or "—")}'
                                           f'</div>', unsafe_allow_html=True)


# ---- Admin ----
with tab_admin:
    st.subheader("Data status")

    if XLSX_PATH.exists():
        mt = datetime.fromtimestamp(XLSX_PATH.stat().st_mtime)
        try:
            db = parse_xlsx(str(XLSX_PATH))
            n_players = len(set(e["canonical_name"] for e in db.values()))
        except Exception as e:
            n_players = f"error: {e}"
        st.success(f"✓ Recruiting xlsx loaded ({n_players} players) — "
                   f"updated {mt:%Y-%m-%d %H:%M}")
    else:
        st.error("✗ No recruiting xlsx loaded")

    if PKL_PATH.exists():
        mt = datetime.fromtimestamp(PKL_PATH.stat().st_mtime)
        with open(PKL_PATH, "rb") as f:
            d = pickle.load(f)
        st.success(f"✓ PBR rankings loaded "
                   f"({len(d.get('national',{}))} national + "
                   f"{len(d.get('state_rnks',{}))} state) — "
                   f"updated {mt:%Y-%m-%d %H:%M}")
    else:
        st.error("✗ No PBR rankings loaded")

    api_key = _get_api_key()
    if api_key:
        st.success("✓ Anthropic API key configured")
    else:
        st.error("✗ Anthropic API key missing — set in Streamlit secrets "
                 "(`ANTHROPIC_API_KEY`)")

    st.divider()
    st.subheader("Recruiting Sheet 2.0 sync")
    if _sheet_sync_result.get("ok"):
        st.success("✓ Synced from Recruiting Sheet 2.0 (re-checks every 10 min, "
                   "and on every fresh deploy/reboot — no manual upload needed).")
    else:
        st.error(f"✗ Sheet sync failed: {_sheet_sync_result.get('reason')} — "
                "falling back to whatever xlsx is already on disk. (Check the "
                "sheet is still shared as \"anyone with the link can view.\")")
    if st.button("🔄 Sync now"):
        _sync_recruiting_sheet.clear()
        st.rerun()

    st.divider()
    st.subheader("Update recruiting xlsx (manual override)")
    st.caption("Only needed if Sheet 2.0 sync above isn't configured, or you "
              "need to load a one-off xlsx that isn't in the live sheet yet.")
    new_xlsx = st.file_uploader("Upload Navy_Recruiting_Sheet.xlsx",
                                type=["xlsx"], key="admin_xlsx")
    if new_xlsx and st.button("Save xlsx", type="primary"):
        try:
            XLSX_PATH.write_bytes(new_xlsx.read())
            db = parse_xlsx(str(XLSX_PATH))
            n = len(set(e["canonical_name"] for e in db.values()))
            st.success(f"Saved. {n} players loaded.")
            st.info("⚠️  On Streamlit Cloud this update only sticks for the "
                    "current container, and the next sheet sync (10 min, or "
                    "next deploy) will overwrite it with Sheet 2.0's data again.")
        except Exception as e:
            st.exception(e)

    st.divider()
    st.subheader("Rebuild PBR rankings")
    st.write("Drop in all the PBR ranking JSON files (1 national + state files). "
             "Files with `National` in the name are treated as national.")
    new_pbrs = st.file_uploader("PBR JSONs",
                                type=["json"], accept_multiple_files=True,
                                key="admin_pbr")
    if new_pbrs and st.button("Rebuild pkl", type="primary"):
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for f in new_pbrs:
                p = Path(td) / f.name
                p.write_bytes(f.read())
                paths.append(str(p))
            from build_rankings import build_from_files
            build_from_files(paths, str(PKL_PATH))
            with open(PKL_PATH, "rb") as f:
                d = pickle.load(f)
            st.success(f"Rebuilt. {len(d.get('national',{}))} national + "
                       f"{len(d.get('state_rnks',{}))} state rankings.")
            st.info("⚠️  Same caveat: on Streamlit Cloud, commit the new pkl "
                    "to `data/pbr_rankings.pkl` in your repo for a permanent "
                    "update. Use the download button below.")
            with open(PKL_PATH, "rb") as f:
                st.download_button("⬇️  Download pbr_rankings.pkl",
                                   data=f.read(),
                                   file_name="pbr_rankings.pkl",
                                   mime="application/octet-stream")

    st.divider()
    st.caption("Field Tool v1 · runs on Streamlit · vision via Claude Sonnet 4.6")

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
from db_loader import parse_xlsx
import gen_roster_pdf
from photo_to_roster import extract_roster_from_image, extract_roster_from_images, to_pdf_payload
from post_event_extractor import extract_post_event_page
from post_event_flow import (
    NEW_PLAYER_COLUMNS, UPDATE_COLUMNS,
    split_pools, prefill_new_player_rows, build_updates_rows,
    rows_to_csv, today_str,
)
import run_event


# ---------------------- helpers ----------------------

def _get_api_key():
    """API key precedence: Streamlit secrets > env var > none."""
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        return os.environ.get("ANTHROPIC_API_KEY")


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


# ---------------------- UI ----------------------

st.set_page_config(
    page_title="Navy Field Tool",
    page_icon="⚓",
    layout="centered",
)

st.markdown(
    "<h2 style='margin-bottom:0'>⚓ Navy Recruiting Tools</h2>"
    "<p style='color:#666;margin-top:0.2em'>Navy Baseball Recruiting Tools

Streamlit app for coaches in the field:
  * Generate pdf rosters, csv schedules, and post event summaries</p>",
    unsafe_allow_html=True,
)

tab_field, tab_import, tab_tourney, tab_post, tab_admin = st.tabs(
    ["🎯 Field Tool", "🧩 Importer", "🏟️ Tournament Builder", "📥 Post-Event", "⚙️  Admin"])


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

    st.write("**1. Photo(s) of the roster**")
    img_files = st.file_uploader(
        "Take or upload photo(s)",
        type=["jpg", "jpeg", "png", "heic", "webp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        help="For long rosters, shoot 2-3 close-up sections (~15-20 players each) "
             "so the text is big and sharp. They'll be merged into one team.",
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
                # Step 1: vision extract — each photo processed at full resolution
                n_photos = len(img_files)
                label = ("📸 Reading roster from photo…" if n_photos == 1
                         else f"📸 Reading {n_photos} sections…")
                status.update(label=label)
                images = []
                for f in img_files:
                    mt = "image/jpeg" if f.type in (None, "") else f.type
                    if mt == "image/jpg":
                        mt = "image/jpeg"
                    images.append((f.read(), mt))

                if len(images) == 1:
                    extracted = extract_roster_from_image(
                        images[0][0], media_type=images[0][1], api_key=api_key,
                    )
                else:
                    extracted = extract_roster_from_images(images, api_key=api_key)

                n = len(extracted.get("players", []))
                team = extracted.get("team_name", "")
                src = "photo" if n_photos == 1 else f"{n_photos} sections"
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


# ---- Importer ----
with tab_import:
    st.subheader("PDF Importer")
    st.caption("Drop an event PDF — a showcase roster or a tournament export — and "
               "turn it into the roster JSON the Tournament Builder uses.")

    imp_api_key = _get_api_key()
    if not imp_api_key:
        st.warning("Anthropic API key missing — set `ANTHROPIC_API_KEY` in Streamlit secrets.")

    imp_pdf = st.file_uploader("Event PDF", type=["pdf"], key="imp_pdf")
    imp_name = st.text_input("Event / list name",
                             placeholder="e.g. 2026 PA State Games Session 1",
                             key="imp_name")
    imp_mode = st.radio(
        "How is this PDF organized?",
        ["Split into teams (multiple squads in the file)",
         "One big list (single showcase roster)"],
        key="imp_mode",
    )
    imp_instr = st.text_area(
        "Anything I should know? (optional)",
        placeholder="e.g. 'split by the Team/Color column', or "
                    "'ignore the Travel Team column — that's their club, not the squad'",
        key="imp_instr", height=80,
    )

    imp_go = st.button("🧩 Generate JSON", type="primary",
                       use_container_width=True,
                       disabled=not (imp_pdf and imp_api_key))

    if imp_go:
        import pdf_to_roster
        mode = "split" if imp_mode.startswith("Split") else "one_list"
        with st.status("Reading the PDF…", expanded=True) as istatus:
            try:
                result = pdf_to_roster.extract_roster_from_pdf(
                    imp_pdf.read(), mode=mode,
                    list_name=(imp_name or "Event"),
                    instructions=imp_instr, api_key=imp_api_key,
                )
                istatus.update(label="Done", state="complete")
            except Exception as e:
                istatus.update(label="Error", state="error")
                st.exception(e)
                st.stop()
        st.session_state["imp_result"] = result

    if "imp_result" in st.session_state:
        res = st.session_state["imp_result"]
        nteams = len(res["teams"])
        nplayers = sum(len(t["players"]) for t in res["teams"])
        st.divider()
        c1, c2 = st.columns(2)
        c1.metric("Teams", nteams)
        c2.metric("Players", nplayers)
        with st.expander("Team breakdown", expanded=(nteams > 1)):
            for t in res["teams"]:
                st.write(f"- **{t['name']}** — {len(t['players'])} players")

        js = json.dumps(res, indent=2)
        st.download_button("⬇️  roster JSON",
                           data=js,
                           file_name=(imp_name or "rosters").replace(" ", "_") + ".json",
                           mime="application/json",
                           use_container_width=True, type="primary")
        st.caption("Split look wrong? Adjust the note above and Generate again. When "
                   "it's right, download and load it in the Tournament Builder tab.")
        st.code(js, language="json")


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
                                 key="tb_event")
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
            except Exception as e:
                tstatus.update(label="Error", state="error")
                st.exception(e)
                st.stop()

    if "tb_pdf" in st.session_state:
        import csv as _csv
        import pandas as pd
        st.divider()
        st.download_button("⬇️  Roster book (PDF)", data=st.session_state["tb_pdf"],
                           file_name=st.session_state["tb_pdfname"],
                           mime="application/pdf", use_container_width=True,
                           type="primary")
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


# ---- Post-Event ----
with tab_post:
    st.subheader("Post-event ratings")
    st.caption("Drop your annotated GoodNotes pages (exported as JPGs). I read the "
               "hand-written New★, split existing-board players from new players, and "
               "give you two paste-ready files.")

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
                result = split_pools(pages)
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
        st.session_state["pe_stats"] = result["stats"]

    if "pe_stats" in st.session_state:
        import pandas as pd
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
            st.caption("Tap the copy icon (top-right of the box), then paste into the "
                       "next empty row of your sheet — columns split automatically.")
            upd_copy = rows_to_csv(st.session_state["pe_upd_rows"], UPDATE_COLUMNS,
                                   delimiter="\t", header=False).decode()
            st.code(upd_copy, language=None)
            upd_tsv = rows_to_csv(st.session_state["pe_upd_rows"], UPDATE_COLUMNS,
                                  delimiter="\t")
            st.download_button("⬇️  Or download (TSV, with headers)",
                               data=upd_tsv, file_name="rating_updates.tsv",
                               mime="text/tab-separated-values",
                               use_container_width=True)
        else:
            st.caption("No rating updates on these pages.")

        # --- New players (editable before download) ---
        st.markdown("**🆕 New players** — review/edit, then copy or download")
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
            st.caption("Tap the copy icon (top-right of the box), then paste into the "
                       "next empty row of your sheet — columns split automatically. "
                       "Reflects any edits you made above.")
            new_copy = rows_to_csv(edited_rows, NEW_PLAYER_COLUMNS,
                                   delimiter="\t", header=False).decode()
            st.code(new_copy, language=None)
            new_csv = rows_to_csv(edited_rows, NEW_PLAYER_COLUMNS)
            st.download_button("⬇️  Or download (CSV, with headers)",
                               data=new_csv, file_name="new_players.csv",
                               mime="text/csv", use_container_width=True)
        else:
            st.caption("No new players on these pages.")


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
    st.subheader("Update recruiting xlsx")
    new_xlsx = st.file_uploader("Upload Navy_Recruiting_Sheet.xlsx",
                                type=["xlsx"], key="admin_xlsx")
    if new_xlsx and st.button("Save xlsx", type="primary"):
        try:
            XLSX_PATH.write_bytes(new_xlsx.read())
            db = parse_xlsx(str(XLSX_PATH))
            n = len(set(e["canonical_name"] for e in db.values()))
            st.success(f"Saved. {n} players loaded.")
            st.info("⚠️  On Streamlit Cloud this update only sticks for the "
                    "current container. For a permanent update, also commit "
                    "the new xlsx to the GitHub repo's `data/` folder.")
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

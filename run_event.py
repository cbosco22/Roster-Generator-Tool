#!/usr/bin/env python3
"""
run_event.py — Navy Baseball event orchestrator (PORTABLE, one entry point)

Give it the file paths for an event and it produces:
  1. <Event>.pdf            — roster book with cover (Navy dots + PBR counts) and
                              a two-level PDF outline (division -> teams) for
                              GoodNotes / Acrobat.
  2. <Event>_Schedule.csv   — schedule with per-team Navy counts + Total, and a
                              "Name (Tier) 'YY POS STATE" cell per team.

Everything that used to live in an AI's head is baked in here:
  - DB is read straight from the xlsx via openpyxl (NEVER a Drive text dump).
  - PBR pkl is built automatically from the ranking JSONs if it's missing.
  - PG often scrapes the event name as "Event"; we patch it from the --event
    flag, else from the roster filename.
  - Every team is stamped with the event division (single-division events) so
    the cover groups correctly and never shows "Unknown".

REQUIREMENTS (pip): reportlab, pypdf, openpyxl
SIBLING SCRIPTS (must be in the same folder as this file):
  gen_roster_pdf.py, gen_schedule_csv.py, db_loader.py, fetch_db.py,
  org_tier.py, travel_programs.json, build_rankings.py

------------------------------------------------------------------------------
USAGE

  python run_event.py \
      --xlsx        Navy_Recruiting_Sheet.xlsx \
      --roster      17U_Beast_of_the_East_Roster.json \
      --schedule    schedule_..._.json            (optional; PDF-only if omitted)
      --pbr         nat.json state1.json ...       (optional; reused if pkl exists)
      --event       "2026 17U PG Beast of the East Invitational"  (optional)
      --division    "17U/18U"                      (optional, default 17U/18U)
      --outdir      ./out                          (optional, default ./out)

Or call run_event(...) directly from Python — see the bottom of this file.
------------------------------------------------------------------------------
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, '/home/claude')  # harmless if absent elsewhere


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _clean_event_name(raw):
    """Strip site-name tails the scrapers append (PBR/Five Tool/Prospect Select)."""
    raw = re.sub(
        r'\s*-\s*(Prep Baseball Tournaments|Baseball Tournaments|'
        r'Five Tool Baseball.*|Prospect Select.*)',
        '', raw or '').strip()
    return raw


def _event_name_from_filename(roster_path):
    """Derive a readable event name from a roster filename like
    '17U_Beast_of_the_East_Roster.json' -> '17U Beast of the East'."""
    base = os.path.splitext(os.path.basename(roster_path))[0]
    base = re.sub(r'(?i)[_\s]*roster$', '', base)
    return base.replace('_', ' ').strip()


def _safe_stub(event_name):
    """Filesystem-safe stub for output filenames."""
    stub = re.sub(r'[^\w\s-]', '', event_name).strip()
    return re.sub(r'\s+', '_', stub) or 'Event'


def _ensure_pbr_pkl(pbr_files):
    """Make sure pbr_rankings.pkl exists next to the scripts. Build it if we
    were handed ranking JSONs and no pkl is present yet."""
    pkl = os.path.join(HERE, 'pbr_rankings.pkl')
    if os.path.exists(pkl):
        return pkl
    # deployed layout keeps the pkl in data/
    data_pkl = os.path.join(HERE, 'data', 'pbr_rankings.pkl')
    if os.path.exists(data_pkl):
        return data_pkl
    # also accept a pkl already sitting in /home/claude
    alt = '/home/claude/pbr_rankings.pkl'
    if os.path.exists(alt):
        return alt
    if pbr_files:
        from build_rankings import build_from_files
        build_from_files(list(pbr_files), out_path=pkl)
        return pkl
    print('[run_event] No PBR pkl and no ranking JSONs supplied — '
          'PBR Rank column and cover PBR counts will be blank.')
    return None


# ----------------------------------------------------------------------------
# Core
# ----------------------------------------------------------------------------
def run_event(xlsx, roster, schedule=None, pbr=None,
              event=None, division='17U/18U', outdir='out', div_pdf=None):
    """Run the full event workup. Returns (pdf_path, csv_path|None).
    
    div_pdf: path to an age-groups PDF (screenshot of event Teams tab).
             When provided, divisions are parsed from the PDF and stamped via
             alphabetical-reset detection instead of using the single --division
             label. Works for multi-division events (PS, PBR, Five Tool).
    """
    pbr = pbr or []
    os.makedirs(outdir, exist_ok=True)

    # 1) PBR pkl (build if needed) — must exist before importing the generator's
    #    load step runs, but the generator loads lazily inside build_pdf so order
    #    only needs the pkl present on disk before build_pdf is called.
    _ensure_pbr_pkl(pbr)

    # 2) Load roster JSON and patch the event name + divisions
    with open(roster) as f:
        roster_data = json.load(f)

    # Some roster JSONs are a plain list of teams instead of a dict
    if isinstance(roster_data, list):
        roster_data = {'teams': roster_data}

    # Normalize the team-name key. Some scrapes emit 'team' / 'team_name' /
    # 'teamName' instead of 'name'; the rest of the pipeline (here and in
    # gen_roster_pdf) relies on t['name'], so fold those in once and drop any
    # entry that has no usable name at all. (No division guessing happens here.)
    _teams = roster_data.get('teams', [])
    _clean_teams = []
    for t in _teams:
        if not isinstance(t, dict):
            continue
        if not t.get('name'):
            t['name'] = (t.get('team') or t.get('team_name')
                         or t.get('teamName') or '').strip()
        if t.get('name'):
            _clean_teams.append(t)
    roster_data['teams'] = _clean_teams

    # Normalize player field keys too. The usual scrape gives each player
    # 'name'/'jersey'/'grad'/'hs'; some variants (e.g. PA State Games) split the
    # name and use '#'/'class'/'school' instead. Fold those onto the keys the
    # generator reads so names/numbers/classes/schools aren't silently blank.
    # Pure key remapping — no data is inferred or guessed.
    for t in roster_data['teams']:
        for p in t.get('players', []):
            if not isinstance(p, dict):
                continue
            if not p.get('name'):
                fn = str(p.get('first', '') or '').strip()
                ln = str(p.get('last', '') or '').strip()
                full = (p.get('name') or f'{fn} {ln}').strip()
                if full:
                    p['name'] = full
            if not p.get('jersey') and p.get('#') is not None:
                p['jersey'] = p.get('#')
            if not p.get('grad') and p.get('class'):
                p['grad'] = p.get('class')
            if not p.get('hs') and p.get('school'):
                p['hs'] = p.get('school')

    raw_event = _clean_event_name(roster_data.get('event', ''))
    if event:
        event_name = event.strip()
    elif raw_event and raw_event.lower() != 'event':
        event_name = raw_event
    else:
        # PG scraped it as "Event" (or blank) — recover from the filename
        event_name = _event_name_from_filename(roster)
    roster_data['event'] = event_name

    # Stamp every team with the division so the cover groups correctly.
    # When a div_pdf is provided (multi-division event), skip this — build_pdf
    # will parse the PDF and use alphabetical-reset detection instead.
    if not div_pdf:
        sched_divs = dict(roster_data.get('schedule_team_divs', {}))
        for t in roster_data.get('teams', []):
            sched_divs.setdefault(t['name'], t.get('division') or division)
        if schedule:
            with open(schedule) as f:
                schedule_data = json.load(f)
            for g in schedule_data.get('games', []):
                for key in ('team1', 'team2'):
                    nm = g.get(key)
                    if nm:
                        sched_divs.setdefault(nm, division)
        else:
            schedule_data = None
        roster_data['schedule_team_divs'] = sched_divs
    else:
        # Multi-division: load schedule but don't stamp divisions
        if schedule:
            with open(schedule) as f:
                schedule_data = json.load(f)
        else:
            schedule_data = None

    # Write the patched roster to a temp file the generator can read
    patched_roster = os.path.join(outdir, '_patched_roster.json')
    with open(patched_roster, 'w') as f:
        json.dump(roster_data, f)

    stub = _safe_stub(event_name)
    pdf_path = os.path.join(outdir, f'{stub}.pdf')
    csv_path = os.path.join(outdir, f'{stub}_Schedule.csv') if schedule else None

    # 3) Load the DB straight from the xlsx, then build the PDF
    import gen_roster_pdf as grp
    grp.init_db_from_xlsx(xlsx)              # <- the correct, only DB source
    grp.build_pdf(patched_roster, pdf_path,
                  divisions_pdf=div_pdf)     # build_pdf keeps the loaded DB

    # 4) Schedule CSV (if a schedule was provided)
    if schedule:
        from db_loader import parse_xlsx, lookup
        from gen_schedule_csv import build_schedule_csv
        db = parse_xlsx(xlsx)
        csv_text = build_schedule_csv(roster_data, schedule_data, db, lookup,
                                      division=division)
        with open(csv_path, 'w') as f:
            f.write(csv_text)

    # tidy temp
    try:
        os.remove(patched_roster)
    except OSError:
        pass

    print(f'[run_event] PDF -> {pdf_path}')
    if csv_path:
        print(f'[run_event] CSV -> {csv_path}')
    return pdf_path, csv_path


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description='Navy Baseball event workup')
    ap.add_argument('--xlsx', required=True, help='Navy Recruiting Sheet .xlsx')
    ap.add_argument('--roster', required=True, help='roster JSON')
    ap.add_argument('--schedule', help='schedule JSON (optional; PDF-only if omitted)')
    ap.add_argument('--pbr', nargs='*', default=[], help='PBR ranking JSON files (optional)')
    ap.add_argument('--event', help='override event name (optional)')
    ap.add_argument('--division', default='17U/18U', help='event division label')
    ap.add_argument('--div-pdf', dest='div_pdf',
                    help='age-groups PDF (Teams tab screenshot) for multi-division events')
    ap.add_argument('--outdir', default='out', help='output directory')
    args = ap.parse_args()
    run_event(args.xlsx, args.roster, schedule=args.schedule, pbr=args.pbr,
              event=args.event, division=args.division, outdir=args.outdir,
              div_pdf=args.div_pdf)


if __name__ == '__main__':
    main()

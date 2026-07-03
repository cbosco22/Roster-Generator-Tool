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


def _as_list(x):
    """Coerce a single path or a list/tuple of paths into a clean list."""
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [p for p in x if p]
    return [x]


def _load_roster_dict(path):
    """Load one roster JSON, normalizing the plain-list form to {'teams': [...]}."""
    with open(path) as f:
        d = json.load(f)
    if isinstance(d, list):
        d = {'teams': d}
    return d


def _merge_rosters(paths):
    """Combine one or more roster JSONs into a single {'teams': [...]} dict.

    PG splits a single event across age-group exports (a 16U file and a 17U
    file); this folds them into one roster in upload order so the divisions and
    duplicate-team tiebreak resolve correctly. The first usable event string and
    any pre-set schedule_team_divs are carried over.
    """
    merged = {'teams': []}
    event_name = ''
    sched_divs = {}
    for p in paths:
        d = _load_roster_dict(p)
        merged['teams'].extend(d.get('teams', []))
        if not event_name:
            ev = (d.get('event') or '').strip()
            if ev and ev.lower() != 'event':
                event_name = ev
        sd = d.get('schedule_team_divs') or {}
        if isinstance(sd, dict):
            sched_divs.update(sd)
    if event_name:
        merged['event'] = event_name
    if sched_divs:
        merged['schedule_team_divs'] = sched_divs
    return merged


def _merge_schedules(paths):
    """Combine one or more schedule JSONs into a single {'games': [...]} dict.
    Returns None when no schedule was supplied. Non-games top-level keys are
    taken from the first file."""
    if not paths:
        return None
    merged = None
    for p in paths:
        with open(p) as f:
            d = json.load(f)
        if isinstance(d, list):
            d = {'games': d}
        if merged is None:
            merged = dict(d)
            merged['games'] = list(d.get('games', []))
        else:
            merged['games'].extend(d.get('games', []))
    return merged


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
              event=None, division='17U/18U', outdir='out',
              div_pdf=None, division_pdfs=None, schedule_specs=None,
              crawl=False, log=print):
    """Run the full event workup. Returns (pdf_path, csv_path|None).

    crawl: False = no PBR measurables. True = run pbr_crawler over every
           rostered player (public data, ~3-4s/player, checkpointed in
           outdir/pbr_checkpoint.jsonl so re-runs resume). A string = path
           to an existing pbr_crawl.json / checkpoint .jsonl to reuse.

    roster: a roster JSON path, OR a list of paths to combine (PG often splits
            one event into per-age-group exports — pass them all and they're
            merged in order).
    schedule: a schedule JSON path, OR a list of paths to combine. PDF-only if
            omitted.

    schedule_specs: list of (division_label, schedule_path) tuples — one schedule
            per age group. When provided, the schedule CSV is built per age group
            so each game's Division column is correct, then the rows are stitched
            into one CSV with continuous Game# numbering. Takes priority over
            `schedule` for CSV generation.

    div_pdf: path to a single age-groups PDF (screenshot of event Teams tab).
             Divisions are parsed from the PDF and stamped via alphabetical-reset
             detection. Works for PS / PBR / Five Tool multi-division pages.

    division_pdfs: list of (label, pdf_path) tuples — one PDF per age group
             (e.g. a PG 'Participating Teams' export or a Ctrl-P print of one
             age group). Each PDF is the authoritative team list for its
             division; teams are matched by name. This is the robust, no-guessing
             path and takes priority over div_pdf when provided.
    """
    pbr = pbr or []
    os.makedirs(outdir, exist_ok=True)

    # 1) PBR pkl (build if needed) — must exist before importing the generator's
    #    load step runs, but the generator loads lazily inside build_pdf so order
    #    only needs the pkl present on disk before build_pdf is called.
    _ensure_pbr_pkl(pbr)

    # 2) Load + merge roster JSON(s) and patch the event name + divisions
    roster_paths = _as_list(roster)
    roster_data = _merge_rosters(roster_paths)

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
        event_name = _event_name_from_filename(roster_paths[0]) if roster_paths else 'Event'
    roster_data['event'] = event_name

    # Merge schedule JSON(s) once (PG may split these per age group too).
    # schedule_specs (labeled, one per age group) takes priority and is also kept
    # grouped so the CSV can stamp the right Division per game.
    if schedule_specs:
        schedule_groups = [(lbl, _merge_schedules([p])) for lbl, p in schedule_specs]
        schedule_data = _merge_schedules([p for _, p in schedule_specs])
    else:
        schedule_paths = _as_list(schedule)
        schedule_data = _merge_schedules(schedule_paths)
        schedule_groups = [(division, schedule_data)] if schedule_data is not None else []
    has_schedule = schedule_data is not None

    # Stamp every team with the division so the cover groups correctly.
    # When divisions come from PDF(s) — either a single reset-detected PDF
    # (div_pdf) or one PDF per age group (division_pdfs) — skip this; build_pdf
    # assigns divisions from the PDF(s) instead.
    _pdf_divisions = bool(div_pdf or division_pdfs)
    if not _pdf_divisions:
        sched_divs = dict(roster_data.get('schedule_team_divs', {}))
        for t in roster_data.get('teams', []):
            sched_divs.setdefault(t['name'], t.get('division') or division)
        # Use each schedule's own label so teams seen only in the schedule land
        # in the correct age group.
        for lbl, sd in schedule_groups:
            for g in (sd or {}).get('games', []):
                for key in ('team1', 'team2'):
                    nm = g.get(key)
                    if nm:
                        sched_divs.setdefault(nm, lbl)
        roster_data['schedule_team_divs'] = sched_divs

    # Write the patched roster to a temp file the generator can read
    patched_roster = os.path.join(outdir, '_patched_roster.json')
    with open(patched_roster, 'w') as f:
        json.dump(roster_data, f)

    stub = _safe_stub(event_name)
    pdf_path = os.path.join(outdir, f'{stub}.pdf')
    csv_path = os.path.join(outdir, f'{stub}_Schedule.csv') if has_schedule else None

    # 2.5) PBR measurables (public crawl) — same crawl one_link.py runs, so
    #      an extension-scraped event (PG / PBR tournaments) gets the same
    #      measurable chips as a one-link FiveTool/PS event.
    crawl_out = None
    if isinstance(crawl, str) and crawl:
        crawl_out = crawl
    elif crawl:
        import pbr_crawler
        seen, players = set(), []
        for t in roster_data['teams']:
            for p in t.get('players', []):
                nm = (p.get('name') or '').strip()
                key = (nm.lower(), str(p.get('grad')), str(p.get('state')),
                       (p.get('hs') or '').lower())
                if nm and key not in seen:
                    seen.add(key)
                    players.append({'name': nm, 'grad_year': p.get('grad'),
                                    'state': p.get('state'), 'school': p.get('hs'),
                                    'team': t['name']})
        ckpt = os.path.join(outdir, 'pbr_checkpoint.jsonl')
        log(f'[run_event] PBR crawl: {len(players)} unique players '
            f'(resumable — checkpoint {ckpt})')
        done_n = [0]
        def _clog(msg):
            done_n[0] += 1
            if done_n[0] % 100 == 0:
                log(f'      {msg}')
        results, unmatched = pbr_crawler.crawl(players, checkpoint=ckpt, log=_clog)
        crawl_out = os.path.join(outdir, 'pbr_crawl.json')
        import datetime as _dt
        with open(crawl_out, 'w') as f:
            json.dump({'scraped_at': _dt.datetime.now(_dt.timezone.utc).isoformat(),
                       'results': results, 'unmatched': unmatched}, f)
        log(f'[run_event] crawl done: {len(results)} matched, '
            f'{len(unmatched)} without a PBR profile')

    # 3) Load the DB straight from the xlsx, then build the PDF
    import gen_roster_pdf as grp
    grp.init_db_from_xlsx(xlsx)              # <- the correct, only DB source
    grp.build_pdf(patched_roster, pdf_path,
                  divisions_pdf=div_pdf,
                  division_pdfs=division_pdfs,
                  crawl=crawl_out)   # build_pdf keeps the loaded DB

    # 4) Schedule CSV (if any schedule was provided). When schedules are labeled
    #    per age group, build each separately so its Division column is correct,
    #    then stitch the rows under one header with continuous Game# numbering.
    if has_schedule:
        import csv as _csv
        import io as _io
        from db_loader import parse_xlsx, lookup
        from gen_schedule_csv import build_schedule_csv
        db = parse_xlsx(xlsx)

        if schedule_specs:
            header = None
            data_rows = []
            for lbl, sd in schedule_groups:
                if sd is None:
                    continue
                txt = build_schedule_csv(roster_data, sd, db, lookup, division=lbl)
                rows = list(_csv.reader(_io.StringIO(txt)))
                if not rows:
                    continue
                if header is None:
                    header = rows[0]
                data_rows.extend(rows[1:])
            # Continuous Game# in column 0 (only if that's what the column is).
            if header and header[0].strip().lower() in ('game#', 'game #', 'game'):
                for i, r in enumerate(data_rows, 1):
                    if r:
                        r[0] = str(i)
            buf = _io.StringIO()
            w = _csv.writer(buf, lineterminator='\n')
            if header:
                w.writerow(header)
            w.writerows(data_rows)
            csv_text = buf.getvalue()
        else:
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
    ap.add_argument('--roster', required=True, nargs='+',
                    help='roster JSON(s) — pass several to combine (PG splits by age group)')
    ap.add_argument('--schedule', nargs='*', default=None,
                    help='schedule JSON(s). Use "LABEL=path.json" per age group so the '
                         'CSV Division column is correct (e.g. --schedule "15/16U=s16.json" '
                         '"17/18U=s17.json"). Bare paths are merged under --division.')
    ap.add_argument('--pbr', nargs='*', default=[], help='PBR ranking JSON files (optional)')
    ap.add_argument('--event', help='override event name (optional)')
    ap.add_argument('--division', default='17U/18U', help='event division label')
    ap.add_argument('--div-pdf', dest='div_pdf', action='append', default=[],
                    help='Age-groups PDF. Repeatable. Use "LABEL=path.pdf" for one '
                         'PDF per age group (e.g. --div-pdf "15/16U=16u.pdf" '
                         '--div-pdf "17/18U=17u.pdf"). A bare path (no "=") uses the '
                         'single-PDF alphabetical-reset detection (PS/PBR/Five Tool).')
    ap.add_argument('--outdir', default='out', help='output directory')
    args = ap.parse_args()

    labeled = [v for v in args.div_pdf if '=' in v]
    bare    = [v for v in args.div_pdf if '=' not in v]
    division_pdfs = [tuple(v.split('=', 1)) for v in labeled] or None
    single_div_pdf = bare[0] if (bare and not division_pdfs) else None

    sched_args = args.schedule or []
    sched_labeled = [v for v in sched_args if '=' in v]
    sched_bare    = [v for v in sched_args if '=' not in v]
    schedule_specs = [tuple(v.split('=', 1)) for v in sched_labeled] or None
    schedule_arg = sched_bare or None

    run_event(args.xlsx, args.roster, schedule=schedule_arg, pbr=args.pbr,
              event=args.event, division=args.division, outdir=args.outdir,
              div_pdf=single_div_pdf, division_pdfs=division_pdfs,
              schedule_specs=schedule_specs)


if __name__ == '__main__':
    main()

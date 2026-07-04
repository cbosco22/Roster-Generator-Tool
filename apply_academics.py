"""
apply_academics.py — merge harvested academic info into an event and rebuild.

The login-gated academics (GPA / SAT / ACT) can only be HARVESTED with a live
signed-in PBR/PG session (see memory pbr-crawler-progress). This script is the
second half: once a harvest has produced a {name: "GPA 3.8 · SAT 1280 · ACT 29"}
map, it writes each string onto the matching roster player's `acad` field
(what gen_roster_pdf renders as academic chips) and rebuilds + re-pushes the
book and the enriched roster JSON.

    python3 apply_academics.py <event_dir> <academics.json> "<Event Name>"

academics.json shape: { "First Last": "GPA 3.8 · SAT 1280", ... }
Names are matched with the same normalization the crawl/enrich use, plus the
locked strip_suffix + nickname pass from db_loader for robustness.
"""
import json
import os
import re
import sys


def _norm(s):
    return re.sub(r'\s+', ' ', (s or '').strip().lower())


def apply_academics(event_dir, acad_map, event_name, rebuild=True, push=True):
    roster_path = os.path.join(event_dir, 'roster.json')
    data = json.load(open(roster_path))
    idx = {_norm(k): v for k, v in acad_map.items()}
    n = 0
    for t in data['teams']:
        for p in t.get('players', []):
            v = idx.get(_norm(p.get('name')))
            if v:
                p['acad'] = v
                n += 1
    with open(roster_path, 'w') as f:
        json.dump(data, f, indent=1)
    print(f'[ACAD] wrote academics onto {n} players in {roster_path}')

    if not rebuild:
        return n

    import gen_roster_pdf as grp
    from push_event import push_event, push_pdf, enrich_teams_with_crawl
    from sheet_sync import fetch_recruiting_xlsx
    xlsx = os.path.join(os.path.dirname(__file__), 'data', 'recruiting.xlsx')
    try:
        fetch_recruiting_xlsx(xlsx)
    except Exception as e:
        print(f'[ACAD] sheet sync skipped ({e}) — using xlsx on disk')
    grp.init_db_from_xlsx(xlsx)
    slug = os.path.basename(event_dir.rstrip('/'))
    pdf_path = os.path.join(event_dir, f'{slug}_roster_book.pdf')
    crawl = os.path.join(event_dir, 'pbr_crawl.json')
    grp.build_pdf(roster_path, pdf_path, preset='navy',
                  crawl=crawl if os.path.exists(crawl) else None)

    # prepend the venue map page if the schedule has one
    sched_path = os.path.join(event_dir, 'schedule.json')
    if os.path.exists(sched_path):
        try:
            import pypdf
            from reportlab.pdfgen import canvas as rc
            from venue_map import drive_minutes, venue_map_for
            from venue_page import draw_venue_page
            sched = json.load(open(sched_path))
            if sched.get('venues') and sched.get('hub'):
                venues = drive_minutes(sched['hub'], sched['venues'])
                img = venue_map_for(sched['hub'], venues)
                vp = os.path.join(event_dir, '_venues.pdf')
                c = rc.Canvas(vp)
                draw_venue_page(c, event_name, sched['hub'], venues, map_img=img)
                c.showPage(); c.save()
                w = pypdf.PdfWriter()
                for pg in pypdf.PdfReader(vp).pages:
                    w.add_page(pg)
                for pg in pypdf.PdfReader(pdf_path).pages:
                    w.add_page(pg)
                with open(pdf_path, 'wb') as f:
                    w.write(f)
                os.remove(vp)
        except Exception as e:
            print(f'[ACAD] venue page skipped ({e})')

    print(f'[ACAD] rebuilt {pdf_path} ({os.path.getsize(pdf_path)//1024} KB)')

    if push:
        with open(pdf_path, 'rb') as f:
            push_pdf(event_name, f.read(), os.path.basename(pdf_path))
        enrich_teams_with_crawl(data['teams'], crawl)
        push_event(event_name, None, roster_json=json.dumps({'teams': data['teams']}))
        print('[ACAD] book + roster re-pushed to Event Day')
    return n


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    ev, acad_json, name = sys.argv[1], sys.argv[2], sys.argv[3]
    apply_academics(ev, json.load(open(acad_json)), name)

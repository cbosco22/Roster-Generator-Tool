"""
one_link.py — the whole event from ONE link.

Chris's end goal ("I provide the link, everything else just happens"):
    python3 one_link.py <fivetool event url>

does, in order:
  1. sync the recruiting sheet (fresh Cur★ for the PDF's yellow cells)
  2. scrape the event server-side — teams, rosters, event name w/ dates
     (fivetool_scrape.py; no Chrome, no extension, verified 2026-07-02)
  3. crawl PBR public data for every rostered player (pbr_crawler.py,
     checkpointed per event — re-runs skip everyone already crawled, so
     a second run only picks up roster additions)
  4. build the full roster-book PDF (navy preset: measurables w/ 1-year
     freshness filter, acad/rank, commit logos, Cur★)
  5. push the roster JSON to the Event Day app (live-board cross-ref);
     the schedule joins it via Event Day's own one-tap refresh once the
     tournament posts games — venue map page hooks in at that point too,
     since venues come from the schedule.

NOT here (yet, by design): the login-gated academics/contacts pass —
that must drive Chris's signed-in Chrome, so it stays a prompted,
attended step ("include paywalled data" toggle in the future wizard).

Everything is resumable: killed mid-crawl -> rerun the same command.
"""
import argparse
import json
import os
import re
import sys


def _slug(name):
    s = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    return s[:60] or 'event'


def run(url, outdir=None, event_name=None, crawl=True, push=True,
        checkpoint=None, log=print):
    from fivetool_scrape import scrape_event
    import pbr_crawler
    import gen_roster_pdf as grp
    from sheet_sync import fetch_recruiting_xlsx

    here = os.path.dirname(os.path.abspath(__file__))
    xlsx = os.path.join(here, 'data', 'recruiting.xlsx')

    log('[1/5] Syncing recruiting sheet…')
    try:
        fetch_recruiting_xlsx(xlsx)
    except Exception as e:
        log(f'      sheet sync failed ({e}) — using the xlsx already on disk')

    log('[2/5] Scraping event (teams + rosters)…')
    data = scrape_event(url, log=lambda m: None)
    if event_name:
        data['event'] = event_name
    name = data['event']
    outdir = outdir or os.path.join(here, 'events', _slug(name))
    os.makedirs(outdir, exist_ok=True)
    roster_json = os.path.join(outdir, 'roster.json')
    with open(roster_json, 'w') as f:
        json.dump(data, f, indent=1)
    n_players = sum(len(t['players']) for t in data['teams'])
    log(f'      {name}: {len(data["teams"])} teams, {n_players} players')

    crawl_out = os.path.join(outdir, 'pbr_crawl.json')
    if crawl:
        log('[3/5] Crawling PBR public data (resumable — safe to re-run)…')
        seen, players = set(), []
        for t in data['teams']:
            for p in t['players']:
                key = (p['name'].lower(), str(p.get('grad')), str(p.get('state')),
                       (p.get('hs') or '').lower())
                if p['name'] and key not in seen:
                    seen.add(key)
                    players.append({'name': p['name'], 'grad_year': p.get('grad'),
                                    'state': p.get('state'), 'school': p.get('hs'),
                                    'team': t['name']})
        ckpt = checkpoint or os.path.join(outdir, 'pbr_checkpoint.jsonl')
        done_n = [0]
        def _log(msg):
            done_n[0] += 1
            if done_n[0] % 100 == 0:
                log(f'      {msg}')
        results, unmatched = pbr_crawler.crawl(players, checkpoint=ckpt, log=_log)
        with open(crawl_out, 'w') as f:
            import datetime as _dt
            json.dump({'scraped_at': _dt.datetime.now(_dt.timezone.utc).isoformat(),
                       'results': results, 'unmatched': unmatched}, f)
        log(f'      {len(results)} matched, {len(unmatched)} without a PBR profile')
    else:
        log('[3/5] Skipping PBR crawl (--no-crawl)')

    log('[4/5] Building the roster book PDF…')
    grp.init_db_from_xlsx(xlsx)
    pdf_path = os.path.join(outdir, f'{_slug(name)}_roster_book.pdf')
    grp.build_pdf(roster_json, pdf_path,
                  crawl=crawl_out if (crawl and os.path.exists(crawl_out)) else None)
    log(f'      {pdf_path}')

    if push:
        log('[5/5] Pushing roster to Event Day (live board cross-ref)…')
        try:
            from push_event import push_event
            r = push_event(name, None, roster_json=json.dumps(
                {'teams': data['teams']}))
            msg = f'      {r["action"]} — schedule joins via Refresh in the app'
            if r.get('roster_skipped'):
                msg += f' (⚠ {r["roster_skipped"]})'
            log(msg)
        except Exception as e:
            log(f'      push failed (event still fully usable locally): {e}')
    else:
        log('[5/5] Skipping Event Day push (--no-push)')

    log('DONE.')
    return {'outdir': outdir, 'pdf': pdf_path, 'roster_json': roster_json}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Whole event from one link')
    ap.add_argument('url', help='FiveTool event URL (any page of the event)')
    ap.add_argument('--name', help='Override the event name')
    ap.add_argument('--outdir')
    ap.add_argument('--checkpoint', help='Reuse an existing PBR crawl checkpoint')
    ap.add_argument('--no-crawl', action='store_true')
    ap.add_argument('--no-push', action='store_true')
    args = ap.parse_args()
    run(args.url, outdir=args.outdir, event_name=args.name,
        crawl=not args.no_crawl, push=not args.no_push,
        checkpoint=args.checkpoint)

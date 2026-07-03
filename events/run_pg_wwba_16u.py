"""Driver: PG 16U WWBA National Championship prep from extension-scraped JSONs.

Same flow as one_link.py steps 1/3/4/5, but PG has no server-side scraper yet —
roster + schedule come from the Chrome-extension JSONs in ~/Downloads.
PG rosters carry no `state` field; derived here from hometown ("City, ST").
"""
import json, os, re, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

EVENT = "2026 PG 16U WWBA National Championship"
OUTDIR = os.path.join(HERE, 'pg-16u-wwba-national-championship-2026')
ROSTER_SRC = os.path.expanduser('~/Downloads/PG WWBA 16U rost.json')
SCHED_SRC = os.path.expanduser('~/Downloads/schedule_2026_PG_16U_WWBA_National_Championship_2026-06-30.json')

_ST = re.compile(r',\s*([A-Z]{2})\s*$')

def hometown_state(p):
    m = _ST.search(p.get('hometown') or '')
    return m.group(1) if m else None

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    data = json.load(open(ROSTER_SRC))
    data['event'] = EVENT
    for t in data['teams']:
        for p in t['players']:
            if not p.get('state'):
                st = hometown_state(p)
                if st:
                    p['state'] = st
    roster_json = os.path.join(OUTDIR, 'roster.json')
    with open(roster_json, 'w') as f:
        json.dump(data, f, indent=1)

    sched = json.load(open(SCHED_SRC))
    with open(os.path.join(OUTDIR, 'schedule.json'), 'w') as f:
        json.dump(sched, f, indent=1)

    from sheet_sync import fetch_recruiting_xlsx
    xlsx = os.path.join(REPO, 'data', 'recruiting.xlsx')
    try:
        fetch_recruiting_xlsx(xlsx)
        print('sheet synced')
    except Exception as e:
        print(f'sheet sync failed ({e}) — using xlsx on disk')

    import pbr_crawler
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
    print(f'{len(players)} unique players to crawl', flush=True)
    ckpt = os.path.join(OUTDIR, 'pbr_checkpoint.jsonl')
    n = [0]
    def _log(msg):
        n[0] += 1
        if n[0] % 100 == 0:
            print(f'{dt.datetime.now():%H:%M} {msg}', flush=True)
    results, unmatched = pbr_crawler.crawl(players, checkpoint=ckpt, log=_log)
    with open(os.path.join(OUTDIR, 'pbr_crawl.json'), 'w') as f:
        json.dump({'scraped_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                   'results': results, 'unmatched': unmatched}, f)
    print(f'CRAWL DONE: {len(results)} matched, {len(unmatched)} unmatched', flush=True)

if __name__ == '__main__':
    main()

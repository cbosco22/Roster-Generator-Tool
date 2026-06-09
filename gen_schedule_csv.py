"""
gen_schedule_csv.py — Navy Baseball schedule CSV builder

Builds the schedule CSV from a roster JSON + schedule JSON + recruiting DB.

Columns:
  Game#, Date, Time, Location, Attend, Notes, Division,
  Team1, Team1Tier, Team1★, Team1PBR, Team1 Navy Players,
  Team2, Team2Tier, Team2★, Team2PBR, Team2 Navy Players,
  Total★, TotalPBR

Star columns are SIMPLE COUNTS:
  Team1★ = number of Navy DB players on team 1 in this game
  Team1PBR = number of PBR-ranked players on team 1
  Total★ = Team1★ + Team2★ (simple sum)
  TotalPBR = Team1PBR + Team2PBR

Navy Players format:
  "Name (Tier) 'YY POS STATE" joined by "; "
  e.g. "Bobby Bastek (2) '27 SS GA; Win Hoots (1) '27 OF GA"
  Tier shown as C/1/2/4 (raw tier 0.1 -> C). Other tiers (3, XX) shown as-is.
"""
import csv
import io
import os
import re

_STATE_ABV = {
    'alabama':'AL','alaska':'AK','arizona':'AZ','arkansas':'AR','california':'CA',
    'colorado':'CO','connecticut':'CT','delaware':'DE','florida':'FL','georgia':'GA',
    'hawaii':'HI','idaho':'ID','illinois':'IL','indiana':'IN','iowa':'IA',
    'kansas':'KS','kentucky':'KY','louisiana':'LA','maine':'ME','maryland':'MD',
    'massachusetts':'MA','michigan':'MI','minnesota':'MN','mississippi':'MS',
    'missouri':'MO','montana':'MT','nebraska':'NE','nevada':'NV',
    'new hampshire':'NH','new jersey':'NJ','new mexico':'NM','new york':'NY',
    'north carolina':'NC','north dakota':'ND','ohio':'OH','oklahoma':'OK',
    'oregon':'OR','pennsylvania':'PA','rhode island':'RI','south carolina':'SC',
    'south dakota':'SD','tennessee':'TN','texas':'TX','utah':'UT','vermont':'VT',
    'virginia':'VA','washington':'WA','west virginia':'WV','wisconsin':'WI','wyoming':'WY',
    'washington dc':'DC','district of columbia':'DC',
}

# Only these tiers count on the schedule. XX, 3, and anything else are ignored.
_COUNTED_TIERS = {'0.1', '1', '2', '4'}

# Tier display: only 0.1 is remapped to C; the rest shown verbatim
_TIER_LABEL = {'0.1': 'C'}

COLS = ['Game#','Date','Time','Location','Attend','Notes','Division',
        'Team1','Team1Tier','Team1★','Team1PBR','Team1 Navy Players',
        'Team2','Team2Tier','Team2★','Team2PBR','Team2 Navy Players',
        'Total★','TotalPBR']


def _state_abbrev(player):
    raw = (player.get('state') or player.get('home_state') or '').strip()
    if not raw:
        ht = (player.get('hometown') or '').strip()
        if ',' in ht:
            raw = ht.split(',')[-1].strip()
    if not raw:
        return ''
    if len(raw) == 2:
        return raw.upper()
    return _STATE_ABV.get(raw.lower(), raw[:2].upper())


def _tier_label(tier):
    return _TIER_LABEL.get(str(tier), str(tier))


def _load_pbr():
    """Load PBR rankings pkl from script dir or /home/claude/."""
    import pickle
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for candidate in [
        os.path.join(script_dir, 'data', 'pbr_rankings.pkl'),
        os.path.join(script_dir, 'pbr_rankings.pkl'),
        '/home/claude/pbr_rankings.pkl',
    ]:
        if os.path.exists(candidate):
            with open(candidate, 'rb') as f:
                data = pickle.load(f)
            return data.get('national', {}), data.get('state_rnks', {})
    return {}, {}


def _pbr_count_for_team(players, pbr_nat, pbr_st):
    """Count how many players on a team have a PBR ranking (state or national)."""
    count = 0
    for p in players:
        name = p.get('name', '').strip().lower()
        if not name:
            continue
        if name in pbr_nat or name in pbr_st:
            count += 1
    return count


def build_schedule_csv(roster_json, schedule_json, db, lookup_fn, division='17U/18U'):
    """
    roster_json  : parsed roster dict (has 'teams')
    schedule_json: parsed schedule dict (has 'games')
    db           : parsed recruiting DB dict (from parse_xlsx)
    lookup_fn    : function(db, name) -> entry or None
    division     : division label to stamp on every row (single-div events)
    Returns the CSV text as a string.
    """
    # Load PBR rankings and org tier lookup
    pbr_nat, pbr_st = _load_pbr()
    try:
        from org_tier import lookup_org_tier
    except ImportError:
        lookup_org_tier = lambda x: ''

    # team name -> list of player dicts
    team_players = {t['name']: t['players'] for t in roster_json['teams']}

    def navy_list_and_count(team_name):
        players = team_players.get(team_name, [])
        entries = []
        for p in players:
            e = lookup_fn(db, p['name'])
            if not e:
                continue
            tier = str(e.get('tier', ''))
            if tier not in _COUNTED_TIERS:
                continue  # ignore XX, 3, etc. on the schedule
            tier_lbl = _tier_label(tier)
            yr = str(p.get('grad', ''))
            yr2 = yr[-2:] if len(yr) == 4 else yr
            pos = (p.get('pos', '') or '').strip()
            st = _state_abbrev(p)
            parts = p['name'].strip().split()
            first = parts[0] if parts else ''
            last = ' '.join(parts[1:]) if len(parts) > 1 else ''
            seg = f"{first} {last} ({tier_lbl}) '{yr2} {pos} {st}".strip()
            entries.append(seg)
        return '; '.join(entries), len(entries)

    rows = []
    for g in schedule_json['games']:
        t1, t2 = g['team1'], g['team2']
        np1, c1 = navy_list_and_count(t1)
        np2, c2 = navy_list_and_count(t2)
        total = c1 + c2

        # Org tier per team
        tier1 = lookup_org_tier(t1) or ''
        tier2 = lookup_org_tier(t2) or ''
        if tier1:
            tier1 = f'Tier {tier1}'
        if tier2:
            tier2 = f'Tier {tier2}'

        # PBR count per team
        pbr1 = _pbr_count_for_team(team_players.get(t1, []), pbr_nat, pbr_st)
        pbr2 = _pbr_count_for_team(team_players.get(t2, []), pbr_nat, pbr_st)
        total_pbr = pbr1 + pbr2

        rows.append({
            'Game#': g.get('game', ''),
            'Date': g.get('date', ''),
            'Time': g.get('time', ''),
            'Location': g.get('location', ''),
            'Attend': '',
            'Notes': '',
            'Division': g.get('division') or division,
            'Team1': t1,
            'Team1Tier': tier1,
            'Team1★': str(c1) if c1 else '',
            'Team1PBR': str(pbr1) if pbr1 else '',
            'Team1 Navy Players': np1,
            'Team2': t2,
            'Team2Tier': tier2,
            'Team2★': str(c2) if c2 else '',
            'Team2PBR': str(pbr2) if pbr2 else '',
            'Team2 Navy Players': np2,
            'Total★': str(total) if total else '',
            'TotalPBR': str(total_pbr) if total_pbr else '',
        })

    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=COLS)
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()

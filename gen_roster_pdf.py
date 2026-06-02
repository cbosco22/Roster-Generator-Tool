#!/usr/bin/env python3
"""Navy Baseball Recruiting — GoodNotes Roster PDF Generator (v5, with cover page)
LOCKED FORMAT — do not change without explicit instruction.

Key features:
- Multi-page cover: event title, dates, teams by age division, Navy★ dots (C/1/2/4)
- Org tier label (from travel_programs.json) shown on cover + each roster page
- Division assigned from schedule_team_divs dict > team data > name inference
- Teams sorted alphabetically within each age group on cover AND roster pages
- Age group label shown above each team name on roster pages
- Cover expands to as many pages as needed, legend always on last page
- Event name + dates auto-parsed from raw event string
- Roster rows: alternating gray/white, Cur★ cell yellow for DB players
- Cols: # | First | Last | Pos | Ht | Wt | Class | School | Cur★ | New★ | Commit | NOTES
- Notes fixed 2.50", Commit 0.80", School gets remaining width
- Commit: DB value takes priority, roster packet commit is fallback
- Running header: NAVY BASEBALL RECRUITING left | event center | Page N right
"""

import json
from collections import defaultdict
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas as rl_canvas

import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from fetch_db import build_db_from_raw
from db_loader import strip_suffix

HEADER_BG  = colors.HexColor('#1A1A1A')
WHITE      = colors.white
ROW_ALT    = colors.HexColor('#F2F2F2')
DB_YELLOW  = colors.HexColor('#FFF176')
TEXT_DARK  = colors.HexColor('#111111')
TEXT_MED   = colors.HexColor('#555555')
LINE_DARK  = colors.HexColor('#888888')
LINE_LITE  = colors.HexColor('#CCCCCC')

DOT_COMMIT = colors.HexColor('#1A3A6B')
DOT_T1     = colors.HexColor('#2E7D32')
DOT_T2     = colors.HexColor('#F9A825')
DOT_T4     = colors.HexColor('#90CAF9')

TIER_DOT_COLOR = {
    '0.1': (DOT_COMMIT, colors.white, 'C'),
    '1':   (DOT_T1,     colors.white, '1'),
    '2':   (DOT_T2,     colors.HexColor('#333300'), '2'),
    '4':   (DOT_T4,     colors.HexColor('#1A3A6B'), '4'),
}

SHEET_ID = '1ecpbBbWaVaSlmz4qmHUWJw9Esj6P0x5R4y81QQYhMzE'
_DB = None

def init_db(raw_sheet_text):
    """No-op when raw_sheet_text is empty/blank, so callers can pre-install
    their own DB object (e.g. xlsx-backed) before build_pdf runs."""
    global _DB
    if not (raw_sheet_text and raw_sheet_text.strip()):
        return
    _DB = build_db_from_raw(raw_sheet_text)

def db_lookup(name):
    return _DB.lookup(name) if _DB else None

def split_name(full):
    parts = full.strip().split()
    if not parts: return '',''
    if len(parts)==1: return '',parts[0]
    return parts[0], ' '.join(parts[1:])

def ht_fmt(h):
    if not h or str(h)=='0': return ''
    h = str(h).replace('"','').replace('\u201d','').replace('\u2019',"'")
    parts = h.replace("'",'-').replace('\u2018','-').split('-')
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts)==2: return f"{parts[0]}-{parts[1]}"
    return h.strip()

def jersey_key(p):
    try: return int(str(p.get('jersey','999')))
    except: return 999


def draw_cover_page(c, event_name, event_dates, division_chunks, W, H, page_num, total_pages, is_last):
    """Draw one cover page. division_chunks is the subset of divisions for this page."""
    L = 0.40 * inch
    R = W - 0.40 * inch
    FOOTER_Y = 0.85 * inch

    c.setFillColor(colors.HexColor('#1A1A1A'))
    c.rect(0, H - 0.07*inch, W, 0.07*inch, fill=1, stroke=0)

    c.setFont('Helvetica', 7.5)
    c.setFillColor(TEXT_MED)
    c.drawString(L, H - 0.27*inch, 'NAVY BASEBALL RECRUITING')
    c.setStrokeColor(LINE_LITE)
    c.setLineWidth(0.5)
    c.line(L, H - 0.34*inch, R, H - 0.34*inch)

    y = H - 0.95*inch

    if page_num == 1:
        c.setFont('Helvetica-Bold', 28)
        c.setFillColor(TEXT_DARK)
        c.drawCentredString(W/2, y, event_name.upper())
        y -= 0.32*inch
        if event_dates:
            c.setFont('Helvetica', 13)
            c.setFillColor(TEXT_MED)
            c.drawCentredString(W/2, y, event_dates)
            y -= 0.28*inch
        c.setStrokeColor(LINE_LITE)
        c.setLineWidth(0.5)
        c.line(L, y, R, y)
        y -= 0.28*inch
    else:
        c.setFont('Helvetica-Bold', 11)
        c.setFillColor(TEXT_DARK)
        c.drawCentredString(W/2, y, f'{event_name.upper()} — TEAMS (CONTINUED)')
        y -= 0.22*inch
        c.setStrokeColor(LINE_LITE)
        c.line(L, y, R, y)
        y -= 0.22*inch

    ROW_H   = 0.26 * inch
    DOT_R   = 0.085 * inch
    DOT_GAP = 0.22 * inch

    for division, teams in division_chunks:
        if y - 0.40*inch < FOOTER_Y:
            break

        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(TEXT_MED)
        c.drawString(L, y, division.upper())
        y -= 0.04*inch
        c.setStrokeColor(LINE_LITE)
        c.line(L, y, R, y)
        y -= 0.04*inch

        c.setFont('Helvetica-Bold', 7)
        c.setFillColor(colors.HexColor('#AAAAAA'))
        c.drawString(L + 0.08*inch, y + 0.04*inch, 'TEAM')
        c.drawRightString(R, y + 0.04*inch, 'NAVY TARGETS')
        y -= 0.20*inch

        for row_i, (team_name, dots) in enumerate(teams):
            if y - ROW_H < FOOTER_Y:
                break
            bg = colors.HexColor('#F9F9F9') if row_i % 2 == 0 else WHITE
            c.setFillColor(bg)
            c.rect(L, y - 0.04*inch, R - L, ROW_H, fill=1, stroke=0)
            c.setFont('Helvetica-Bold', 10)
            c.setFillColor(TEXT_DARK)
            name_display = team_name if len(team_name) <= 45 else team_name[:43] + '...'
            c.drawString(L + 0.08*inch, y + 0.07*inch, name_display)
            # Org tier label
            from org_tier import lookup_org_tier
            _org_t = lookup_org_tier(team_name)
            if _org_t:
                _name_w = c.stringWidth(name_display, 'Helvetica-Bold', 10)
                _label_x = L + 0.08*inch + _name_w + 0.10*inch
                c.setFont('Helvetica', 7.5)
                c.setFillColor(colors.HexColor('#AAAAAA'))
                c.drawString(_label_x, y + 0.07*inch, f'— Tier {_org_t}')
            if dots:
                dot_x = R
                for tier in reversed(dots):
                    cfg = TIER_DOT_COLOR.get(tier)
                    if not cfg: continue
                    dot_color, text_color, label = cfg
                    dot_x -= DOT_R
                    cx, cy = dot_x, y + 0.08*inch
                    c.setFillColor(dot_color)
                    c.circle(cx, cy, DOT_R, fill=1, stroke=0)
                    c.setStrokeColor(colors.HexColor('#00000022'))
                    c.setLineWidth(0.3)
                    c.circle(cx, cy, DOT_R, fill=0, stroke=1)
                    c.setFont('Helvetica-Bold', 7)
                    c.setFillColor(text_color)
                    c.drawCentredString(cx, cy - 0.026*inch, label)
                    dot_x -= DOT_GAP - DOT_R
            else:
                c.setFont('Helvetica', 9)
                c.setFillColor(colors.HexColor('#DDDDDD'))
                c.drawRightString(R, y + 0.07*inch, '—')
            y -= ROW_H
        y -= 0.16*inch

    if is_last:
        ly = 0.55*inch
        c.setStrokeColor(LINE_LITE)
        c.line(L, ly + 0.14*inch, R, ly + 0.14*inch)
        legend_items = [
            ('0.1', 'Committed'),
            ('1',   'Tier 1 — offer'),
            ('2',   'Tier 2 — follow'),
            ('4',   'Tier 4 — recruiting board'),
        ]
        lx = L
        DOT_R = 0.085 * inch
        for tier, label in legend_items:
            cfg = TIER_DOT_COLOR.get(tier)
            if not cfg: continue
            dot_color, text_color, lbl = cfg
            c.setFillColor(dot_color)
            c.circle(lx + DOT_R, ly, DOT_R, fill=1, stroke=0)
            c.setFont('Helvetica-Bold', 7)
            c.setFillColor(text_color)
            c.drawCentredString(lx + DOT_R, ly - 0.026*inch, lbl)
            c.setFont('Helvetica', 8)
            c.setFillColor(TEXT_MED)
            c.drawString(lx + DOT_R*2 + 0.05*inch, ly - 0.022*inch, label)
            lx += 1.55*inch

    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#AAAAAA'))
    c.drawCentredString(W/2, 0.20*inch, str(page_num))


def draw_cover(c, event_name, event_dates, teams_by_division, W, H):
    """Draw cover — auto-expands to multiple pages if needed."""
    FOOTER_Y = 0.85 * inch
    ROW_H = 0.26 * inch
    DIV_HEADER_H = 0.46 * inch

    all_divs = sorted(teams_by_division.items())

    def available_height(page_num):
        if page_num == 1:
            return H - 0.95*inch - 1.60*inch - FOOTER_Y
        return H - 0.95*inch - 0.70*inch - FOOTER_Y

    pages = []
    current_page_divs = []
    avail = available_height(1)
    used = 0

    for div, teams in all_divs:
        needed = DIV_HEADER_H + len(teams) * ROW_H + 0.16*inch
        if used + needed > avail and current_page_divs:
            pages.append(current_page_divs)
            current_page_divs = []
            used = 0
            avail = available_height(len(pages) + 1)
        current_page_divs.append((div, teams))
        used += needed

    if current_page_divs:
        pages.append(current_page_divs)

    total_pages = len(pages)
    for i, page_divs in enumerate(pages):
        if i > 0:
            c.showPage()
        draw_cover_page(c, event_name, event_dates, page_divs, W, H,
                        page_num=i+1, total_pages=total_pages, is_last=(i==total_pages-1))


def _infer_division(team_name):
    import re
    n = team_name.upper()
    for pat, div in [
        (r'\b18U\b', '18U'),
        (r'\b17U\b|17/18U', '17/18U'),
        (r'\b16U\b|15/16U', '15/16U'),
        (r'\b15U\b', '15U'),
        (r'\b14U\b', '14U'),
    ]:
        if re.search(pat, n): return div
    m = re.search(r'20(2[5-9]|3[0-2])', n)
    if m:
        yr = int(m.group())
        if yr <= 2026: return '17/18U'
        if yr <= 2028: return '15/16U'
        return '15U'
    return 'Unknown'


def build_cover_data(teams, db_lookup_fn, schedule_team_divs=None):
    by_div = defaultdict(list)
    for team in teams:
        div = None
        if schedule_team_divs:
            div = schedule_team_divs.get(team['name'])
        if not div:
            div = (team.get('division') or team.get('age_group') or
                   _infer_division(team['name']))
        dots = []
        for p in team.get('players', []):
            entry = db_lookup_fn(p.get('name',''))
            if entry and entry.get('tier') in TIER_DOT_COLOR:
                dots.append(entry['tier'])
        order = {'0.1':0,'1':1,'2':2,'4':3}
        dots.sort(key=lambda t: order.get(t, 99))
        by_div[div].append((team['name'], dots))
    for div in by_div:
        by_div[div].sort(key=lambda x: x[0].lower())
    return by_div


def build_pdf(json_path, out_path, raw_sheet_text="", proof_only=False):
    init_db(raw_sheet_text)

    with open(json_path) as f:
        data = json.load(f)

    import re as _re
    from datetime import datetime as _dt
    raw_event = data.get('event','')
    raw_event = _re.sub(
        r'\s*-\s*(Prep Baseball Tournaments|Baseball Tournaments|Five Tool Baseball.*|Prospect Select.*)',
        '', raw_event).strip()
    _dm = _re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s*-\s*(\d{1,2}/\d{1,2}/\d{4})', raw_event)
    if _dm:
        _d1 = _dt.strptime(_dm.group(1), '%m/%d/%Y')
        _d2 = _dt.strptime(_dm.group(2), '%m/%d/%Y')
        event_name  = raw_event[:_dm.start()].strip().rstrip('-').strip()
        if _d1.month == _d2.month:
            event_dates = f"{_d1.strftime('%B %-d')}-{_d2.day}, {_d1.year}"
        else:
            event_dates = f"{_d1.strftime('%B %-d')} - {_d2.strftime('%B %-d, %Y')}"
    else:
        event_name  = raw_event
        event_dates = data.get('dates', '')

    all_teams = data.get('teams', [])
    if proof_only:
        all_teams = all_teams[:3]

    L_MARGIN = 0.30 * inch
    R_MARGIN = 0.30 * inch
    Wp, Hp = letter

    _sched_divs = data.get('schedule_team_divs', {})
    cover_divs = build_cover_data(all_teams, db_lookup, schedule_team_divs=_sched_divs)

    # Load PBR rankings — look next to the script first, then legacy /home/claude
    import pickle as _pickle, os as _os
    _pbr_nat = {}; _pbr_st = {}
    _script_dir = _os.path.dirname(_os.path.abspath(__file__))
    _pkl_candidates = [
        _os.path.join(_script_dir, 'data', 'pbr_rankings.pkl'),
        _os.path.join(_script_dir, 'pbr_rankings.pkl'),
        '/home/claude/pbr_rankings.pkl',
    ]
    _pkl = next((p for p in _pkl_candidates if _os.path.exists(p)), None)
    if _pkl:
        with open(_pkl,'rb') as _f:
            _pbr = _pickle.load(_f)
        _pbr_nat = _pbr.get('national', {})
        _pbr_st  = _pbr.get('state_rnks', {})
        print(f'[PBR] Loaded {len(_pbr_nat)} national + {len(_pbr_st)} state rankings')
    else:
        print('[PBR] WARNING: pbr_rankings.pkl not found — PBR Rank column will be blank')

    # Full state name → abbreviation map
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
        'virginia':'VA','washington':'WA','west virginia':'WV','wisconsin':'WI',
        'wyoming':'WY',
    }

    def _abbrev(state_raw):
        s = (state_raw or '').strip()
        if len(s) == 2: return s.upper()
        return _STATE_ABV.get(s.lower(), s.upper())

    def _pbr_match(name, grad_year=None, state=None):
        """
        Look up PBR ranking with cross-validation on grad year + state.
        Prevents false matches for common names (John Smith problem).
        Falls back to name-only if no grad_year/state available.
        Returns (state_entry, nat_entry) tuple, either can be None.
        """
        key = strip_suffix(name.strip().lower())
        st_entry  = _pbr_st.get(key)
        nat_entry = _pbr_nat.get(key)

        # If we have context to cross-check, apply the guard
        if grad_year or state:
            def _valid(entry):
                if not entry: return False
                yr_ok    = (not grad_year) or (str(entry.get('class','')) == str(grad_year))
                state_ok = (not state)     or (_abbrev(entry.get('state','')) == _abbrev(state)) \
                           or entry.get('state','') in ('- select state -', '')
                return yr_ok and state_ok

            if st_entry  and not _valid(st_entry):
                print(f"[PBR] Rejected state rank for '{name}': "
                      f"class={st_entry.get('class')} state={st_entry.get('state')} "
                      f"(player: class={grad_year} state={state})")
                st_entry = None
            if nat_entry and not _valid(nat_entry):
                print(f"[PBR] Rejected nat'l rank for '{name}': "
                      f"class={nat_entry.get('class')} "
                      f"(player: class={grad_year})")
                nat_entry = None

        return st_entry, nat_entry

    def pbr_rank_str(name, pg_rank='', grad_year=None, state=None):
        st_entry, nat_entry = _pbr_match(name, grad_year, state)
        lines = []
        if st_entry:
            lines.append(f"#{st_entry['rank']} {_abbrev(st_entry.get('state',''))}")
        if nat_entry:
            lines.append(f"#{nat_entry['rank']} Nat'l")
        # PG rank — only show if numeric
        if pg_rank and str(pg_rank).strip().isdigit():
            lines.append(f"#{str(pg_rank).strip()} PG")
        return '\n'.join(lines)

    import os, tempfile
    tmp        = out_path + '.tmp.pdf'
    cover_file = out_path + '.cover.pdf'

    doc = SimpleDocTemplate(
        tmp, pagesize=letter,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=0.50*inch, bottomMargin=0.30*inch,
    )
    W = doc.width
    NOTES_W = 2.50 * inch

    sTeam   = ParagraphStyle('TM', fontName='Helvetica-Bold', fontSize=20,
                              textColor=TEXT_DARK, alignment=TA_CENTER, spaceBefore=4, spaceAfter=16)
    sDivLabel = ParagraphStyle('DL', fontName='Helvetica-Bold', fontSize=9,
                               textColor=TEXT_MED, alignment=TA_CENTER, spaceBefore=8, spaceAfter=2)
    sHdr    = ParagraphStyle('HD', fontName='Helvetica-Bold', fontSize=6.5,
                              textColor=WHITE, alignment=TA_CENTER, leading=8)
    sNum    = ParagraphStyle('NM', fontName='Helvetica-Bold', fontSize=7.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=9)
    sName   = ParagraphStyle('NA', fontName='Helvetica-Bold', fontSize=8.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=10)
    sCell   = ParagraphStyle('CE', fontName='Helvetica', fontSize=6.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=8)
    sSchl   = ParagraphStyle('SC', fontName='Helvetica', fontSize=6.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=8)
    sStarHL = ParagraphStyle('SH', fontName='Helvetica-Bold', fontSize=7,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=9)
    sNL     = ParagraphStyle('NL', fontName='Helvetica', fontSize=5.5,
                              textColor=colors.HexColor('#BBBBBB'), alignment=TA_LEFT, leading=7)

    BASE_CW  = [0.25, 0.68, 0.85, 0.30, 0.30, 0.25, 0.30]
    STAR_CW  = [0.33, 0.33]
    COMMIT_W = 0.70 * inch
    PBR_W    = 0.48 * inch
    school_w = W - NOTES_W - sum(c*inch for c in BASE_CW) - sum(c*inch for c in STAR_CW) - COMMIT_W - PBR_W
    CW       = [c*inch for c in BASE_CW] + [school_w] + [c*inch for c in STAR_CW] + [PBR_W] + [COMMIT_W] + [NOTES_W]
    HEADERS  = ['#','First','Last','Pos','Ht','Wt','Class','School','Cur *','New *','PBR Rank','Commit','NOTES']
    ROW_H    = 0.46*inch
    HDR_H    = 0.26*inch

    def hdr_row():
        return [Paragraph(h, sHdr) for h in HEADERS]

    def data_row(p):
        first, last = split_name(p.get('name',''))
        j   = str(p.get('jersey','')); j = '' if j in ('0','') else j
        pos = p.get('pos','')
        ht  = ht_fmt(p.get('ht',''))
        wt  = str(p.get('wt','')) if str(p.get('wt','0'))!='0' else ''
        yr  = str(p.get('grad','')) if str(p.get('grad','')) not in ('0','') else ''
        sch = (p.get('hs','') or '').strip()
        state = (p.get('state','') or p.get('home_state','') or '').strip()
        db  = db_lookup(p.get('name',''))
        cur = db['tier'] if db else ''
        # Commit priority: PG roster packet → DB → PBR rankings
        pg_commit  = (p.get('commit') or '').strip()
        db_commit  = (db.get('commit') or '').strip() if db else ''
        pbr_commit = ''
        if not pg_commit and not db_commit:
            _st_e, _nat_e = _pbr_match(p.get('name',''), grad_year=yr or None, state=state or None)
            pbr_commit = ((_st_e or _nat_e) or {}).get('commit', '') or ''
        commit_val = pg_commit or db_commit or pbr_commit
        # PBR rank string — cross-validated with grad year + state
        pbr_str = pbr_rank_str(p.get('name',''), p.get('pg_rank',''), grad_year=yr or None, state=state or None)
        sPBR = ParagraphStyle('PBR', fontName='Helvetica', fontSize=6,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=7)
        jlabel = f'#{j} ' if j else ''
        return [
            Paragraph(j, sNum), Paragraph(first, sName), Paragraph(last, sName),
            Paragraph(pos, sCell), Paragraph(ht, sCell), Paragraph(wt, sCell),
            Paragraph(yr, sCell), Paragraph(sch, sSchl),
            Paragraph(cur, sStarHL if db else sCell),
            Paragraph('', sCell),
            Paragraph(pbr_str, sPBR),
            Paragraph(commit_val, sCell),
            Paragraph(f'{jlabel}{first} {last}', sNL),
        ]

    def team_sort_key(t):
        div = _sched_divs.get(t['name']) or t.get('division') or t.get('age_group') or _infer_division(t['name'])
        return (div, t['name'].lower())

    teams = sorted(all_teams, key=team_sort_key)

    story = []
    for ti, team in enumerate(teams):
        players = sorted(team['players'], key=jersey_key)
        div = _sched_divs.get(team['name']) or team.get('division') or team.get('age_group') or _infer_division(team['name'])
        if div and div != 'Unknown':
            story.append(Paragraph(div, sDivLabel))
        story.append(Paragraph(team['name'], sTeam))
        from org_tier import lookup_org_tier
        org_t = lookup_org_tier(team['name'])
        if org_t:
            story.append(Paragraph(f'Tier {org_t}', sDivLabel))
        rows = [hdr_row()]
        rh   = [HDR_H]
        for p in players:
            rows.append(data_row(p))
            rh.append(ROW_H)
        tbl = Table(rows, colWidths=CW, rowHeights=rh)
        ts = [
            ('BACKGROUND',(0,0),(-1,0),HEADER_BG), ('ALIGN',(0,0),(-1,0),'CENTER'),
            ('VALIGN',(0,0),(-1,0),'MIDDLE'), ('TOPPADDING',(0,0),(-1,0),4),
            ('BOTTOMPADDING',(0,0),(-1,0),4), ('ALIGN',(0,1),(-1,-1),'CENTER'),
            ('VALIGN',(0,1),(-1,-1),'MIDDLE'), ('TOPPADDING',(0,1),(-1,-1),0),
            ('BOTTOMPADDING',(0,1),(-1,-1),0), ('LEFTPADDING',(0,0),(-1,-1),3),
            ('RIGHTPADDING',(0,0),(-1,-1),3), ('ALIGN',(12,1),(12,-1),'LEFT'),
            ('VALIGN',(12,1),(12,-1),'TOP'), ('TOPPADDING',(12,1),(12,-1),3),
            ('LEFTPADDING',(12,1),(12,-1),4), ('BOX',(0,0),(-1,-1),0.7,LINE_DARK),
            ('LINEBELOW',(0,0),(-1,-1),0.4,LINE_LITE),
            ('LINEAFTER',(0,0),(0,-1),0.4,LINE_LITE), ('LINEAFTER',(1,0),(1,-1),0.4,LINE_LITE),
            ('LINEAFTER',(2,0),(2,-1),0.7,LINE_DARK), ('LINEAFTER',(3,0),(3,-1),0.4,LINE_LITE),
            ('LINEAFTER',(4,0),(4,-1),0.4,LINE_LITE), ('LINEAFTER',(5,0),(5,-1),0.4,LINE_LITE),
            ('LINEAFTER',(6,0),(6,-1),0.4,LINE_LITE), ('LINEAFTER',(7,0),(7,-1),0.4,LINE_LITE),
            ('LINEAFTER',(8,0),(8,-1),0.4,LINE_LITE), ('LINEAFTER',(9,0),(9,-1),0.4,LINE_LITE),
            ('LINEAFTER',(10,0),(10,-1),0.4,LINE_LITE), ('LINEAFTER',(11,0),(11,-1),0.7,LINE_DARK),
        ]
        for i, p in enumerate(players):
            ri = i + 1
            is_db = db_lookup(p.get('name','')) is not None
            ts.append(('BACKGROUND',(0,ri),(-1,ri), ROW_ALT if i%2==0 else WHITE))
            if is_db:
                ts.append(('BACKGROUND',(8,ri),(8,ri), DB_YELLOW))
        tbl.setStyle(TableStyle(ts))
        story.append(tbl)
        if ti < len(teams)-1:
            story.append(PageBreak())

    def on_page(c, doc):
        c.saveState()
        c.setFont('Helvetica', 7.5)
        c.setFillColor(TEXT_MED)
        c.drawString(L_MARGIN, Hp-0.30*inch, 'NAVY BASEBALL RECRUITING')
        c.drawCentredString(Wp/2, Hp-0.30*inch, event_name)
        c.drawRightString(Wp-R_MARGIN, Hp-0.30*inch, f'Page {doc.page + 1}')
        c.setStrokeColor(LINE_LITE)
        c.setLineWidth(0.5)
        c.line(L_MARGIN, Hp-0.36*inch, Wp-R_MARGIN, Hp-0.36*inch)
        c.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)

    from reportlab.pdfgen.canvas import Canvas as RLCanvas
    cv = RLCanvas(cover_file, pagesize=letter)
    draw_cover(cv, event_name, event_dates, cover_divs, Wp, Hp)
    cv.showPage()
    cv.save()

    try:
        import pypdf
        writer = pypdf.PdfWriter()
        for src in [cover_file, tmp]:
            for page in pypdf.PdfReader(src).pages:
                writer.add_page(page)
        with open(out_path, 'wb') as f:
            writer.write(f)
    except ImportError:
        import shutil
        shutil.copy(tmp, out_path)
        print("WARNING: pypdf not found — cover page omitted")

    for f in [tmp, cover_file]:
        try: os.remove(f)
        except: pass

    print(f'Done -> {out_path}')

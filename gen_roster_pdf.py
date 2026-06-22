#!/usr/bin/env python3
"""Navy Baseball Recruiting — GoodNotes Roster PDF Generator (v5, with cover page)
LOCKED FORMAT — do not change without explicit instruction.

Key features:
- Multi-page cover: event title, dates, teams by age division, Navy★ dots (C/1/2/3/4)
- Org tier label (from travel_programs.json) shown on cover + each roster page
- Division assigned from schedule_team_divs dict > team data > name inference
- Teams sorted alphabetically within each age group on cover AND roster pages
- Age group label shown above each team name on roster pages
- Cover expands to as many pages as needed, legend always on last page
- Event name + dates auto-parsed from raw event string
- Roster rows: alternating gray/white, Cur★ cell yellow for DB players
- Cols: # | First | Last | Pos | Ht | Wt | Class | School | St | Cur★ | New★ | PBR Rank | Commit | Acad | NOTES
- Notes fixed 2.50", Commit 0.80", School gets remaining width
- Commit: DB value takes priority, roster packet commit is fallback
- Running header: NAVY BASEBALL RECRUITING left | event center | Page N right
"""

import json
from collections import defaultdict
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas as rl_canvas

import sys as _sys
_sys.path.insert(0, '/home/claude')
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
DOT_T3     = colors.HexColor('#7E57C2')
DOT_T4     = colors.HexColor('#90CAF9')

TIER_DOT_COLOR = {
    '0.1': (DOT_COMMIT, colors.white, 'C'),
    '1':   (DOT_T1,     colors.white, '1'),
    '2':   (DOT_T2,     colors.HexColor('#333300'), '2'),
    '3':   (DOT_T3,     colors.white, '3'),
    '4':   (DOT_T4,     colors.HexColor('#1A3A6B'), '4'),
}

SHEET_ID = '1ecpbBbWaVaSlmz4qmHUWJw9Esj6P0x5R4y81QQYhMzE'
_DB = None

def init_db(raw_sheet_text):
    global _DB
    _DB = build_db_from_raw(raw_sheet_text)

def init_db_from_xlsx(xlsx_path, sheet_name='High School Players'):
    """LOCKED DB source — parse the High School Players tab via openpyxl.
    Sets the module-level _DB so db_lookup() resolves against the xlsx."""
    global _DB
    import db_loader
    _db = db_loader.parse_xlsx(xlsx_path, sheet_name=sheet_name)
    class _XlsxDB:
        def __init__(self, d): self._d = d
        def lookup(self, name): return db_loader.lookup(self._d, name)
        def all_names(self):
            return sorted({e['canonical_name'] for e in self._d.values()})
    _DB = _XlsxDB(_db)
    return _DB

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

    overflow = []
    for di, (division, teams) in enumerate(division_chunks):
        if y - 0.40*inch < FOOTER_Y:
            overflow.extend(division_chunks[di:])
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

        _stopped = None
        for row_i, row in enumerate(teams):
            if y - ROW_H < FOOTER_Y:
                _stopped = row_i
                break
            team_name = row[0]
            dots = row[1]
            ranked_n = row[2] if len(row) > 2 else 0
            bg = colors.HexColor('#F9F9F9') if row_i % 2 == 0 else WHITE
            c.setFillColor(bg)
            c.rect(L, y - 0.04*inch, R - L, ROW_H, fill=1, stroke=0)
            c.setFont('Helvetica-Bold', 10)
            c.setFillColor(TEXT_DARK)
            name_display = team_name if len(team_name) <= 45 else team_name[:43] + '...'
            c.drawString(L + 0.08*inch, y + 0.07*inch, name_display)
            # Inline gray labels after the name: "— Tier N   N Ranked"
            from org_tier import lookup_org_tier
            _org_t = lookup_org_tier(team_name)
            _gray = colors.HexColor('#AAAAAA')
            _cursor_x = L + 0.08*inch + c.stringWidth(name_display, 'Helvetica-Bold', 10) + 0.10*inch
            c.setFont('Helvetica', 7.5)
            c.setFillColor(_gray)
            if _org_t:
                _seg = f'— Tier {_org_t}'
                c.drawString(_cursor_x, y + 0.07*inch, _seg)
                _cursor_x += c.stringWidth(_seg, 'Helvetica', 7.5) + 0.10*inch
            if ranked_n:
                c.drawString(_cursor_x, y + 0.07*inch, f'{ranked_n} Ranked')
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
        if _stopped is not None:
            overflow.append((division, teams[_stopped:]))
            overflow.extend(division_chunks[di+1:])
            break
        y -= 0.16*inch

    if not overflow:
        ly = 0.55*inch
        c.setStrokeColor(LINE_LITE)
        c.line(L, ly + 0.14*inch, R, ly + 0.14*inch)
        legend_items = [
            ('0.1', 'Committed'),
            ('1',   'Offer'),
            ('2',   'High Follow'),
            ('3',   'Follow'),
            ('4',   'Rec'),
        ]
        from reportlab.pdfbase.pdfmetrics import stringWidth
        L_FONT = 7
        DOT_R = 0.075 * inch
        lx = L
        row_y = ly
        for tier, label in legend_items:
            cfg = TIER_DOT_COLOR.get(tier)
            if not cfg: continue
            dot_color, text_color, lbl = cfg
            text_w = stringWidth(label, 'Helvetica', L_FONT)
            item_w = DOT_R*2 + 0.05*inch + text_w
            if lx + item_w > R and lx > L:   # wrap to a second row if needed
                row_y -= 0.22*inch
                lx = L
            c.setFillColor(dot_color)
            c.circle(lx + DOT_R, row_y, DOT_R, fill=1, stroke=0)
            c.setFont('Helvetica-Bold', 6)
            c.setFillColor(text_color)
            c.drawCentredString(lx + DOT_R, row_y - 0.022*inch, lbl)
            c.setFont('Helvetica', L_FONT)
            c.setFillColor(TEXT_MED)
            c.drawString(lx + DOT_R*2 + 0.05*inch, row_y - 0.018*inch, label)
            lx += item_w + 0.18*inch

    c.setFont('Helvetica', 8)
    c.setFillColor(colors.HexColor('#AAAAAA'))
    c.drawCentredString(W/2, 0.20*inch, str(page_num))
    return overflow


def draw_cover(c, event_name, event_dates, teams_by_division, W, H):
    """Draw cover — auto-expands to as many pages as needed.

    Pagination is renderer-driven: draw_cover_page() draws everything that fits
    on the current page and returns the overflow as a list of
    (division, remaining_teams) chunks. A division larger than one page is split
    across pages, repeating its header at the top of each continuation page, so
    no team is ever silently dropped. Legend renders only on the final page.
    """
    remaining = [(div, list(teams)) for div, teams in sorted(teams_by_division.items())]
    page_num = 1
    while remaining:
        if page_num > 1:
            c.showPage()
        remaining = draw_cover_page(c, event_name, event_dates, remaining, W, H,
                                    page_num=page_num, total_pages=0, is_last=False)
        page_num += 1


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


def parse_divisions_pdf(pdf_path):
    """Parse an age-groups PDF (screenshot of event Teams tab) to extract
    ordered division names. Works for PS, PBR, Five Tool pages.

    Looks for lines matching 'Division Name##' followed by ⌄ or ⌃ characters
    (the expand/collapse arrows on the website).

    Returns: ordered list of division names (Exhibition Game filtered out).
    """
    import re
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    divs = []
    seen = set()
    for page in reader.pages:
        text = page.extract_text() or ''
        for line in text.split('\n'):
            line = line.strip()
            m = re.match(r'^(.+?)(\d+)\s*[⌄⌃]\s*$', line)
            if m:
                name = m.group(1).strip()
                count = int(m.group(2))
                if len(name) < 3 or name.lower() in ('page',):
                    continue
                if name not in seen:
                    seen.add(name)
                    divs.append((name, count))
    # Filter out Exhibition Game — those teams are rarely scraped
    result = [name for name, count in divs if name.lower() != 'exhibition game']
    if result:
        print(f'[DIV-PDF] Parsed {len(result)} divisions from {pdf_path}:')
        for name, count in divs:
            if name.lower() != 'exhibition game':
                print(f'  {name}: {count} teams')
    return result


def _stamp_divisions_from_resets(teams, division_names):
    """Detect division boundaries via alphabetical resets and stamp team['division'].

    Works for any event source (PS, PBR, Five Tool, PG) where teams are listed
    alphabetically within each division. Caller provides the ordered division
    names matching the event website's age-group order.

    Args:
        teams: list of team dicts (modified in place)
        division_names: ordered list of division names, one per detected group
    """
    if not teams or not division_names:
        return
    if all(t.get('division') for t in teams):
        return

    # Detect alphabetical resets
    names = [t.get('name', '') for t in teams]
    boundaries = [0]
    for i in range(1, len(names)):
        if names[i].lower().strip() < names[i-1].lower().strip():
            boundaries.append(i)
    groups = []
    for i, start in enumerate(boundaries):
        end = boundaries[i+1] if i+1 < len(boundaries) else len(teams)
        groups.append((start, end))

    # Match groups to division names
    if len(groups) != len(division_names):
        print(f'[DIV] ERROR: detected {len(groups)} alpha-reset groups '
              f'but got {len(division_names)} division names — skipping auto-stamp.')
        print(f'[DIV] Groups detected:')
        for gi, (s, e) in enumerate(groups):
            print(f'  Group {gi+1}: {e-s} teams, first="{names[s]}", last="{names[e-1]}"')
        return

    for (start, end), dname in zip(groups, division_names):
        for i in range(start, end):
            teams[i]['division'] = dname

    print(f'[DIV] Stamped {len(division_names)} divisions:')
    for (start, end), dname in zip(groups, division_names):
        print(f'  {dname}: {end - start} teams')


def _norm_team(s):
    """Space/punctuation-insensitive lowercase key for robust name matching.
    Handles PG's wrapped-text mangling ('WEST COAST' -> 'WESTCOAST',
    'Group 16uNational' -> 'group16unational')."""
    import re
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _pdf_text_blob(pdf_path):
    """Return the full text of a PDF as one normalized blob for containment tests."""
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    return _norm_team(' '.join((p.extract_text() or '') for p in reader.pages))


def assign_divisions_from_pdfs(teams, pdf_specs):
    """Assign team['division'] using one age-group PDF per division.

    This is the robust, no-guessing division path: each PDF is the authoritative
    roster of teams for that age group (e.g. a PG 'Participating Teams' export, a
    Ctrl-P print of a single age group). A roster team is matched to a division if
    its normalized name appears in that division's PDF text. Teams that appear in
    more than one age group (e.g. 'BPA', 'ZT National Prospects' entered in both a
    16U and a 17U event) are split across the matching divisions in roster order.

    Args:
        teams: list of team dicts (modified in place); roster/scrape order matters
               for resolving teams that appear in multiple age groups.
        pdf_specs: ordered list of (division_label, pdf_path) tuples.
    """
    if not teams or not pdf_specs:
        return
    blobs = [(label, _pdf_text_blob(path)) for label, path in pdf_specs]

    deferred = []  # (team, normalized_name, [candidate_labels])
    for team in teams:
        n = _norm_team(team.get('name', ''))
        cands = [label for label, blob in blobs if n and n in blob]
        if len(cands) == 1:
            team['division'] = cands[0]
        elif not cands:
            team['division'] = team.get('division') or 'Unknown'
        else:
            deferred.append((team, n, cands))

    # Teams that match multiple age groups: distribute across candidate labels
    # round-robin, in roster order (1st 'BPA' -> 1st group, 2nd 'BPA' -> 2nd group).
    from collections import defaultdict as _dd
    rr = _dd(int)
    for team, n, cands in deferred:
        team['division'] = cands[rr[n] % len(cands)]
        rr[n] += 1

    # Report
    summary = _dd(list)
    for team in teams:
        summary[team.get('division', 'Unknown')].append(team['name'])
    print(f'[DIV-PDF] Assigned {len(teams)} teams across {len(pdf_specs)} age-group PDF(s):')
    for label, _ in pdf_specs:
        names = summary.get(label, [])
        print(f'  {label}: {len(names)} teams')
    if summary.get('Unknown'):
        print(f'  Unknown (no PDF match — verify manually): {len(summary["Unknown"])} teams')
        for nm in summary['Unknown']:
            print(f'    - {nm}')


def build_cover_data(teams, db_lookup_fn, schedule_team_divs=None, ranked_fn=None):
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
        order = {'0.1':0,'1':1,'2':2,'3':3,'4':4}
        dots.sort(key=lambda t: order.get(t, 99))
        # Count of players with any value in the ranking column (state, national,
        # or PG). Computed per-team here so duplicate team names don't collide.
        ranked = sum(1 for p in team.get('players', []) if ranked_fn(p)) if ranked_fn else 0
        by_div[div].append((team['name'], dots, ranked))
    for div in by_div:
        by_div[div].sort(key=lambda x: x[0].lower())
    return by_div


def build_event_summary_pdf(summary_path, event_name, event_dates, all_teams,
                            db_lookup_fn, abbrev_fn):
    """Write a standalone 'event intel' summary PDF (1+ pages) to summary_path.

    Layout (single event):
      - Big event title + dates
      - Tier-count table (Committed / Tier 1 / 2 / 3 / 4 / board total)
      - Tiered, by-team player lists:
          Committed / Tier 1 / Tier 2  -> named with full ID, grouped by team
          Tier 3 / Tier 4              -> count + by-team compact list

    Reuses the same db_lookup the roster uses, so tiers always match the pages.
    State is taken from the DB entry first, then the roster player's own field,
    abbreviated via the generator's abbrev_fn so it reads 'MA' not 'Massachusetts'.
    Player-name collisions are NOT filtered here — this mirrors exactly what the
    roster tables show, by design (no silent divergence between summary and pages).
    """
    from reportlab.platypus import SimpleDocTemplate as _SDT
    from reportlab.lib.styles import getSampleStyleSheet as _gss

    NAVY = colors.HexColor('#1A3A6B')
    T1C  = DOT_T1
    T2C  = DOT_T2
    MED  = TEXT_MED
    LINE = LINE_LITE

    TIER_META = [
        ('0.1', 'COMMITTED — verbal to Navy', NAVY),
        ('1',   'TIER 1 — Offer',             T1C),
        ('2',   'TIER 2 — High Follow',       T2C),
    ]

    # Collect this event's board players keyed by tier.
    by_tier = defaultdict(list)
    for team in all_teams:
        for p in team.get('players', []):
            entry = db_lookup_fn(p.get('name', ''))
            if not entry:
                continue
            tier = entry.get('tier', '')
            st = (entry.get('state', '') or p.get('state', '')
                  or p.get('home_state', '') or '').strip()
            yr = str(entry.get('class', '') or p.get('grad', '') or '')
            if yr.endswith('.0'):
                yr = yr[:-2]
            by_tier[tier].append({
                'team': team['name'],
                'name': entry.get('canonical_name') or p.get('name', ''),
                'class': yr,
                'pos': entry.get('pos', '') or p.get('pos', ''),
                'state': abbrev_fn(st) if st else '',
                'commit': entry.get('commit', '') or '',
            })

    def _count(t):
        return len(by_tier.get(t, []))

    def _pid(p):
        cls = f"'{p['class'][-2:]}" if p['class'] else ''
        st  = p['state'] or '\u2014'
        s = f"{p['name']}, {cls} {p['pos']}, {st}".replace(' ,', ',')
        if p['commit'] and p['commit'].upper() != 'NAVY':
            s += f"  ({p['commit']})"
        return s

    styles = _gss()
    H1 = ParagraphStyle('SUMH1', parent=styles['Title'], fontSize=26,
                        textColor=NAVY, alignment=TA_CENTER, spaceAfter=2,
                        fontName='Helvetica-Bold', leading=30)
    SUB = ParagraphStyle('SUMSUB', fontSize=11, textColor=MED,
                         alignment=TA_CENTER, spaceAfter=16)
    TIERHEAD = ParagraphStyle('SUMTH', fontSize=11.5, fontName='Helvetica-Bold',
                              spaceBefore=10, spaceAfter=3)
    TEAMLBL = ParagraphStyle('SUMTL', fontSize=8.5, textColor=MED,
                             leftIndent=8, leading=11, spaceBefore=3)
    PLAYER = ParagraphStyle('SUMPL', fontSize=9.5, leading=13,
                            leftIndent=16, textColor=TEXT_DARK)
    COMPACT = ParagraphStyle('SUMCO', fontSize=8, leading=11,
                             textColor=TEXT_DARK, leftIndent=8)

    story = []
    story.append(Spacer(1, 0.15*inch))
    story.append(Paragraph(event_name.upper(), H1))
    if event_dates:
        story.append(Paragraph(event_dates, SUB))
    else:
        story.append(Spacer(1, 10))

    # ---- Tier count table ----
    board_total = sum(_count(t) for t in ['0.1', '1', '2', '3', '4'])
    hdr = ['Committed', 'Tier 1', 'Tier 2', 'Tier 3', 'Tier 4', 'Board Total']
    vals = [_count('0.1'), _count('1'), _count('2'),
            _count('3'), _count('4'), board_total]
    ct = Table([hdr, vals], colWidths=[1.15*inch]*6)
    ct.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME',   (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 9),
        ('FONTSIZE',   (0, 1), (-1, 1), 14),
        ('BACKGROUND', (5, 1), (5, 1), colors.HexColor('#F2F2F2')),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID',       (0, 0), (-1, -1), 0.4, LINE),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(ct)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Committed</b> = verbal to Navy &nbsp;&bull;&nbsp; <b>Tier 1</b> = offer "
        "&nbsp;&bull;&nbsp; <b>Tier 2</b> = high follow &nbsp;&bull;&nbsp; "
        "<b>Tier 3/4</b> = recruiting board",
        ParagraphStyle('SUMNOTE', fontSize=8, textColor=MED, alignment=TA_CENTER)))

    # ---- Named lists: Committed / Tier 1 / Tier 2 by team ----
    for tier, label, col in TIER_META:
        plist = by_tier.get(tier, [])
        if not plist:
            continue
        story.append(Paragraph(
            f"<font color='#{col.hexval()[2:]}'>{label} ({len(plist)})</font>",
            TIERHEAD))
        bt = defaultdict(list)
        for p in plist:
            bt[p['team']].append(p)
        for team in sorted(bt):
            story.append(Paragraph(f"<b>{team}</b>", TEAMLBL))
            for p in sorted(bt[team], key=lambda x: (x['class'], x['name'])):
                story.append(Paragraph("&bull; " + _pid(p), PLAYER))

    # ---- Tier 3 / 4: count + by-team compact ----
    for tier, label in [('3', 'TIER 3'), ('4', 'TIER 4')]:
        plist = by_tier.get(tier, [])
        if not plist:
            continue
        bt = defaultdict(list)
        for p in plist:
            bt[p['team']].append(p)
        story.append(Paragraph(
            f"{label} \u2014 {len(plist)} players on {len(bt)} teams", TIERHEAD))
        lines = []
        for team in sorted(bt):
            nms = '; '.join(
                f"{p['name']} '{p['class'][-2:]} {p['pos']} {p['state'] or '\u2014'}"
                for p in sorted(bt[team], key=lambda x: x['name']))
            lines.append(f"<b>{team}</b> ({len(bt[team])}): {nms}")
        story.append(Paragraph('<br/>'.join(lines), COMPACT))

    if not any(by_tier.get(t) for t in ['0.1', '1', '2', '3', '4']):
        story.append(Spacer(1, 12))
        story.append(Paragraph(
            "No players from the recruiting board were found on this event's rosters.",
            ParagraphStyle('SUMEMPTY', fontSize=10, textColor=MED)))

    sdoc = _SDT(summary_path, pagesize=letter,
                topMargin=0.5*inch, bottomMargin=0.5*inch,
                leftMargin=0.55*inch, rightMargin=0.55*inch)

    def _sum_footer(c, d):
        c.saveState()
        c.setFont('Helvetica', 7.5)
        c.setFillColor(MED)
        c.drawString(0.55*inch, 0.32*inch, 'NAVY BASEBALL RECRUITING — Board Coverage')
        c.setStrokeColor(LINE)
        c.setLineWidth(0.4)
        c.line(0.55*inch, 0.45*inch, letter[0]-0.55*inch, 0.45*inch)
        c.restoreState()

    sdoc.build(story, onFirstPage=_sum_footer, onLaterPages=_sum_footer)
    from pypdf import PdfReader as _PR
    return len(_PR(summary_path).pages)


def build_pdf(json_path, out_path, raw_sheet_text="", proof_only=False,
              divisions_pdf=None, division_pdfs=None, skip_cover=False):
    if raw_sheet_text or _DB is None:
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

    # Division assignment. Priority:
    #   1. division_pdfs  — one PDF per age group (robust, no guessing). Each PDF
    #      is the authoritative team list for its division; teams matched by name.
    #   2. division_names + alphabetical-reset stamp (PS/PBR/Five Tool single PDF).
    #   3. schedule_team_divs / team data / name inference (fallbacks downstream).
    _sched_divs = data.get('schedule_team_divs', {})
    if division_pdfs and not _sched_divs:
        assign_divisions_from_pdfs(all_teams, division_pdfs)
    else:
        _div_names = data.get('division_names')
        if not _div_names and divisions_pdf:
            _div_names = parse_divisions_pdf(divisions_pdf)
        if _div_names and not _sched_divs:
            _stamp_divisions_from_resets(all_teams, _div_names)

    L_MARGIN = 0.30 * inch
    R_MARGIN = 0.30 * inch
    Wp, Hp = letter

    # cover_divs is built later, after pbr_rank_str is defined, so the cover can
    # show each team's count of ranked players.

    # Load PBR rankings
    import pickle as _pickle, os as _os
    _pbr_nat = {}; _pbr_st = {}
    _script_dir = _os.path.dirname(_os.path.abspath(__file__))
    _pkl = next((p for p in [
        _os.path.join(_script_dir, 'data', 'pbr_rankings.pkl'),
        _os.path.join(_script_dir, 'pbr_rankings.pkl'),
        '/home/claude/pbr_rankings.pkl',
    ] if _os.path.exists(p)), None)
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
        if s.lower() == 'new england': return 'NEng'
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

    def _player_is_ranked(p):
        """True if the player has any value in the ranking column — a PBR state
        rank, a PBR national rank, or a numeric PG rank. Uses the same inputs as
        the roster PBR Rank cell so the cover count always matches the page."""
        yr = str(p.get('grad', '')) if str(p.get('grad', '')) not in ('0', '') else ''
        state = (p.get('state', '') or p.get('home_state', '') or '').strip()
        return bool(pbr_rank_str(p.get('name', ''), p.get('pg_rank', ''),
                                 grad_year=yr or None, state=state or None).strip())

    # Now that ranking lookups exist, build the cover with per-team ranked counts.
    cover_divs = build_cover_data(all_teams, db_lookup,
                                  schedule_team_divs=_sched_divs,
                                  ranked_fn=_player_is_ranked)

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
    sBanner = ParagraphStyle('BN', fontName='Helvetica-Bold', fontSize=7.5,
                              textColor=TEXT_DARK, alignment=TA_LEFT, leading=9)
    sDivLabel = ParagraphStyle('DL', fontName='Helvetica-Bold', fontSize=9,
                               textColor=TEXT_MED, alignment=TA_CENTER, spaceBefore=8, spaceAfter=2)
    sHdr    = ParagraphStyle('HD', fontName='Helvetica-Bold', fontSize=5.5,
                              textColor=WHITE, alignment=TA_CENTER, leading=6.5)
    sHdrSm  = ParagraphStyle('HDS', fontName='Helvetica-Bold', fontSize=4.5,
                              textColor=WHITE, alignment=TA_CENTER, leading=5.5)
    sNum    = ParagraphStyle('NM', fontName='Helvetica-Bold', fontSize=6.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=8)
    sName   = ParagraphStyle('NA', fontName='Helvetica-Bold', fontSize=7.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=9)
    sCell   = ParagraphStyle('CE', fontName='Helvetica', fontSize=6.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=8)
    sSchl   = ParagraphStyle('SC', fontName='Helvetica', fontSize=4.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=5.5)
    sCommit = ParagraphStyle('CM', fontName='Helvetica', fontSize=5.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=6.5)
    sStarHL = ParagraphStyle('SH', fontName='Helvetica-Bold', fontSize=7,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=9)
    sNL     = ParagraphStyle('NL', fontName='Helvetica', fontSize=5.5,
                              textColor=colors.HexColor('#BBBBBB'), alignment=TA_LEFT, leading=7)

    # #/First/Last sized individually; everything Pos..Acad shares one even
    # width, except School which is SCHOOL_EXTRA wider. NOTES stays fixed.
    NUM_W, FIRST_W, LAST_W = 0.23*inch, 0.62*inch, 0.80*inch
    SCHOOL_EXTRA = 0.25 * inch
    # 11 columns Pos..Acad: 10 at even_w + School at even_w + SCHOOL_EXTRA
    even_w   = (W - NOTES_W - NUM_W - FIRST_W - LAST_W - SCHOOL_EXTRA) / 11.0
    school_w = even_w + SCHOOL_EXTRA
    CW = [NUM_W, FIRST_W, LAST_W,             # #  First  Last
          even_w, even_w, even_w, even_w,     # Pos Ht Wt Class
          school_w,                           # School (+0.25")
          even_w,                             # St
          even_w, even_w,                     # Cur★ New★
          even_w,                             # PBR Rank
          even_w,                             # Commit
          even_w,                             # Acad
          NOTES_W]                            # NOTES
    HEADERS  = ['#','First','Last','Pos','Ht','Wt','Class','School','St','Cur *','New *','PBR Rank','Commit','Acad','NOTES']
    ROW_H    = 0.46*inch
    HDR_H    = 0.26*inch

    def hdr_row():
        return [Paragraph(h, sHdrSm if h=='Commit' else sHdr) for h in HEADERS]

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
        acad = (p.get('acad','') or p.get('academic','') or '').strip()
        sAcad = ParagraphStyle('AC', fontName='Helvetica', fontSize=4.5,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=5.5)
        sSt = ParagraphStyle('ST', fontName='Helvetica', fontSize=6,
                              textColor=TEXT_DARK, alignment=TA_CENTER, leading=7)
        jlabel = f'#{j} ' if j else ''
        # NOTES label = full player ID: "#22 First Last 'YY POS ST"
        gy = f"'{yr[-2:]}" if yr else ''
        nl_extra = ' '.join(x for x in (gy, pos, state) if x)
        nl_label = f'{jlabel}{first} {last}' + (f' {nl_extra}' if nl_extra else '')
        return [
            Paragraph(j, sNum), Paragraph(first, sName), Paragraph(last, sName),
            Paragraph(pos, sCell), Paragraph(ht, sCell), Paragraph(wt, sCell),
            Paragraph(yr, sCell), Paragraph(sch, sSchl),
            Paragraph(state, sSt),
            Paragraph(cur, sStarHL if db else sCell),
            Paragraph('', sCell),
            Paragraph(pbr_str, sPBR),
            Paragraph(commit_val, sCommit),
            Paragraph(acad, sAcad),
            Paragraph(nl_label, sNL),
        ]

    def team_sort_key(t):
        div = _sched_divs.get(t['name']) or t.get('division') or t.get('age_group') or _infer_division(t['name'])
        return (div, t['name'].lower())

    teams = sorted(all_teams, key=team_sort_key)

    # GoodNotes / Acrobat sidebar outline: record the page each team block lands
    # on. _PageMarker is a zero-size flowable that captures its page number at
    # draw time; after build() we have (division, team, roster_page) for every
    # team and write a Division -> Team outline tree during the merge.
    _page_markers = []  # list of [division, team_name, roster_page]

    class _PageMarker(Flowable):
        def __init__(self, division, team_name):
            super().__init__()
            self._div = division
            self._team = team_name
        def wrap(self, *a):
            return (0, 0)
        def draw(self):
            _page_markers.append([self._div, self._team, self.canv.getPageNumber()])

    story = []
    for ti, team in enumerate(teams):
        players = sorted(team['players'], key=jersey_key)
        div = _sched_divs.get(team['name']) or team.get('division') or team.get('age_group') or _infer_division(team['name'])
        story.append(_PageMarker(div or 'Unknown', team['name']))
        if div and div != 'Unknown':
            story.append(Paragraph(div, sDivLabel))
        story.append(Paragraph(team['name'], sTeam))
        from org_tier import lookup_org_tier
        org_t = lookup_org_tier(team['name'])
        if org_t:
            story.append(Paragraph(f'Tier {org_t}', sDivLabel))
        # Row 0 = thin team banner (spans all cols), Row 1 = column headers,
        # Row 2+ = players. repeatRows=2 repeats BOTH on overflow pages so the
        # continuation page carries the column names AND a team-name indicator
        # for post-event identification.
        BANNER_H = 0.18*inch
        banner_row = [Paragraph(team['name'], sBanner)] + [''] * (len(HEADERS) - 1)
        rows = [banner_row, hdr_row()]
        rh   = [BANNER_H, HDR_H]
        for p in players:
            rows.append(data_row(p))
            rh.append(ROW_H)
        tbl = Table(rows, colWidths=CW, rowHeights=rh, repeatRows=2)
        ts = [
            # team banner (row 0)
            ('SPAN',(0,0),(-1,0)),
            ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#E8E8E8')),
            ('ALIGN',(0,0),(-1,0),'LEFT'), ('VALIGN',(0,0),(-1,0),'MIDDLE'),
            ('LEFTPADDING',(0,0),(-1,0),5),
            ('TOPPADDING',(0,0),(-1,0),2), ('BOTTOMPADDING',(0,0),(-1,0),2),
            # column header (row 1)
            ('BACKGROUND',(0,1),(-1,1),HEADER_BG), ('ALIGN',(0,1),(-1,1),'CENTER'),
            ('VALIGN',(0,1),(-1,1),'MIDDLE'), ('TOPPADDING',(0,1),(-1,1),4),
            ('BOTTOMPADDING',(0,1),(-1,1),4),
            # data rows (row 2+)
            ('ALIGN',(0,2),(-1,-1),'CENTER'),
            ('VALIGN',(0,2),(-1,-1),'MIDDLE'), ('TOPPADDING',(0,2),(-1,-1),0),
            ('BOTTOMPADDING',(0,2),(-1,-1),0), ('LEFTPADDING',(0,0),(-1,-1),3),
            ('RIGHTPADDING',(0,0),(-1,-1),3), ('ALIGN',(14,2),(14,-1),'LEFT'),
            ('VALIGN',(14,2),(14,-1),'TOP'), ('TOPPADDING',(14,2),(14,-1),3),
            ('LEFTPADDING',(14,2),(14,-1),4), ('BOX',(0,0),(-1,-1),0.7,LINE_DARK),
            ('LEFTPADDING',(7,2),(7,-1),1), ('RIGHTPADDING',(7,2),(7,-1),1),
            ('LINEBELOW',(0,0),(-1,-1),0.4,LINE_LITE),
            # vertical column dividers — start at the header row (skip the banner)
            ('LINEAFTER',(0,1),(0,-1),0.4,LINE_LITE), ('LINEAFTER',(1,1),(1,-1),0.4,LINE_LITE),
            ('LINEAFTER',(2,1),(2,-1),0.7,LINE_DARK), ('LINEAFTER',(3,1),(3,-1),0.4,LINE_LITE),
            ('LINEAFTER',(4,1),(4,-1),0.4,LINE_LITE), ('LINEAFTER',(5,1),(5,-1),0.4,LINE_LITE),
            ('LINEAFTER',(6,1),(6,-1),0.4,LINE_LITE), ('LINEAFTER',(7,1),(7,-1),0.4,LINE_LITE),
            ('LINEAFTER',(8,1),(8,-1),0.4,LINE_LITE), ('LINEAFTER',(9,1),(9,-1),0.4,LINE_LITE),
            ('LINEAFTER',(10,1),(10,-1),0.4,LINE_LITE), ('LINEAFTER',(11,1),(11,-1),0.4,LINE_LITE),
            ('LINEAFTER',(12,1),(12,-1),0.4,LINE_LITE), ('LINEAFTER',(13,1),(13,-1),0.7,LINE_DARK),
        ]
        for i, p in enumerate(players):
            ri = i + 2
            is_db = db_lookup(p.get('name','')) is not None
            ts.append(('BACKGROUND',(0,ri),(-1,ri), ROW_ALT if i%2==0 else WHITE))
            if is_db:
                ts.append(('BACKGROUND',(9,ri),(9,ri), DB_YELLOW))
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

    def _write_outline(writer, cover_offset):
        """Build a collapsible Division -> Team sidebar outline from _page_markers.
        cover_offset = number of cover pages prepended before the roster."""
        from collections import OrderedDict
        markers = sorted(_page_markers, key=lambda m: m[2])  # by roster page
        by_div = OrderedDict()
        for div, team, rpage in markers:
            by_div.setdefault(div, []).append((team, rpage))
        for div, entries in by_div.items():
            first_abs = cover_offset + (entries[0][1] - 1)
            try:
                parent = writer.add_outline_item(div, first_abs)
            except Exception:
                parent = None
            for team, rpage in entries:
                abs_pg = cover_offset + (rpage - 1)
                try:
                    writer.add_outline_item(team, abs_pg, parent=parent)
                except Exception:
                    pass

    import pypdf
    if skip_cover:
        # Field Tool / roster-only output: no cover page, just the roster
        # (the page running header is already applied above). Outline still added.
        writer = pypdf.PdfWriter()
        for page in pypdf.PdfReader(tmp).pages:
            writer.add_page(page)
        _write_outline(writer, cover_offset=0)
        with open(out_path, 'wb') as f:
            writer.write(f)
        try: os.remove(tmp)
        except: pass
    else:
        from reportlab.pdfgen.canvas import Canvas as RLCanvas
        cv = RLCanvas(cover_file, pagesize=letter)
        draw_cover(cv, event_name, event_dates, cover_divs, Wp, Hp)
        cv.showPage()
        cv.save()

        # Board-coverage summary page(s): title + tier-count table + tiered,
        # by-team player lists. Sits FIRST in the packet, ahead of the existing
        # division/dots cover. Reuses db_lookup + _abbrev so it never diverges
        # from the roster tables. Best-effort: if it fails, fall back to the
        # cover-only packet rather than aborting the whole build.
        summary_file = out_path + '.summary.pdf'
        summary_pages = 0
        try:
            summary_pages = build_event_summary_pdf(
                summary_file, event_name, event_dates, all_teams,
                db_lookup, _abbrev)
        except Exception as _e:
            print(f'[SUMMARY] WARNING: summary page skipped ({_e})')
            summary_file = None
            summary_pages = 0

        cover_pages = len(pypdf.PdfReader(cover_file).pages)
        writer = pypdf.PdfWriter()
        _merge_srcs = ([summary_file] if summary_file else []) + [cover_file, tmp]
        for src in _merge_srcs:
            for page in pypdf.PdfReader(src).pages:
                writer.add_page(page)
        try:
            if summary_pages:
                writer.add_outline_item('Board Summary', 0)
            writer.add_outline_item('Cover', summary_pages)
        except Exception:
            pass
        # Roster outline pages sit after summary + cover.
        _write_outline(writer, cover_offset=summary_pages + cover_pages)
        with open(out_path, 'wb') as f:
            writer.write(f)

        for f in [tmp, cover_file, summary_file]:
            if not f:
                continue
            try: os.remove(f)
            except: pass

    print(f'Done -> {out_path}')

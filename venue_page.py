"""
venue_page.py — the venue map / drive-times page that opens every event
packet (Chris 2026-07-02: "Start every event with the venue map").

Renders in the packet's own design language (navy header bar, clean table)
and adds a drive-time bar per venue so "can I make this game or is it too
far" reads at a glance — that's the whole job of this page (his words,
re: the hand-built v1, 'PBR 16U Nat'l Champ 2026.pdf').

Data shape:
    hub    = {"name": "LakePoint Sports", "address": "124 LakePoint Pkwy, Emerson GA"}
    venues = [{"venue": "...", "city": "...", "address": "...", "drive_min": 12}, ...]
Venues render sorted by drive_min. Drive times are supplied by the caller —
they come from a maps lookup done at event-setup time, not guessed here.
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch

NAVY = colors.HexColor('#14233B')
GOLD = colors.HexColor('#C9A227')
TEXT_DARK = colors.HexColor('#111111')
TEXT_MED = colors.HexColor('#555555')
ROW_ALT = colors.HexColor('#F2F2F2')
LINE_LITE = colors.HexColor('#CCCCCC')
BAR_BG = colors.HexColor('#E4E8EE')

# bar color by how far the drive is: quick / moderate / far
def _bar_color(minutes):
    if minutes <= 20:
        return colors.HexColor('#2E7D32')
    if minutes <= 35:
        return colors.HexColor('#F9A825')
    return colors.HexColor('#C62828')


def draw_venue_page(c, event_name, hub, venues, W=None, H=None, map_img=None):
    """Draw the venue page on an open reportlab canvas (one full page,
    caller does showPage). map_img: optional PIL image (venue_map.py) drawn
    between the header and the table — pin numbers match table rows."""
    if W is None or H is None:
        W, H = letter
    M = 0.55 * inch

    # header band
    c.setFillColor(NAVY)
    c.rect(0, H - 1.25 * inch, W, 1.25 * inch, stroke=0, fill=1)
    c.setFillColor(GOLD)
    c.setFont('Helvetica-Bold', 9)
    c.drawString(M, H - 0.45 * inch, 'NAVY BASEBALL · RECRUITING')
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 20)
    c.drawString(M, H - 0.78 * inch, event_name.upper())
    c.setFont('Helvetica', 10.5)
    c.drawString(M, H - 1.02 * inch,
                 f"VENUES & DRIVE TIMES FROM {hub['name'].upper()}")

    vs = sorted(venues, key=lambda v: v.get('drive_min', 999))
    max_min = max((v.get('drive_min', 0) for v in vs), default=1) or 1

    map_h = 0.0
    if map_img is not None:
        # shorter map when the venue list is long, so page one stays page one
        map_h = (3.2 if len(vs) <= 11 else 2.4) * inch
        # draw at the image's own aspect, centered - venue_map_for sizes the
        # frame to the venue cluster's shape, so no stretching, no dead space
        iw, ih = map_img.size
        map_w = min(W - 2 * M, map_h * (iw / float(ih)))
        map_h_draw = map_w / (iw / float(ih))
        mx = M + (W - 2 * M - map_w) / 2.0
        from reportlab.lib.utils import ImageReader
        c.drawImage(ImageReader(map_img), mx, H - 1.38 * inch - map_h_draw,
                    width=map_w, height=map_h_draw)
        c.setStrokeColor(LINE_LITE)
        c.setLineWidth(0.8)
        c.rect(mx, H - 1.38 * inch - map_h_draw, map_w, map_h_draw, stroke=1, fill=0)
        map_h = map_h_draw

    y_top = H - 1.62 * inch - (map_h + 0.24 * inch if map_h else 0)
    y_floor = 0.75 * inch  # keep clear of the hub footnote
    # Big events (Boston Classic: 23 sites) overflow a single column below
    # the map — split into two columns when one can't fit. Two-column rows
    # drop CITY/ADDRESS (pin # + venue + drive bar is what a coach uses;
    # addresses stay on the schedule CSV).
    row_h_1 = (0.42 if len(vs) <= 12 else 0.34) * inch
    two_col = len(vs) > int((y_top - y_floor) / row_h_1) - 1

    def _rows(x0, x1, rows, start_i, compact):
        x_num, x_venue = x0, x0 + 0.30 * inch
        if compact:
            bar_w = 0.85 * inch
            x_bar = x1 - 1.35 * inch
            venue_chars = 24
        else:
            bar_w = 1.55 * inch
            x_bar = x1 - 2.05 * inch
            venue_chars = 34
        x_time = x1
        y = y_top
        c.setFillColor(TEXT_MED)
        c.setFont('Helvetica-Bold', 8)
        hdr = [(x_num, '#'), (x_venue, 'VENUE')]
        if not compact:
            hdr += [(x0 + 2.55 * inch, 'CITY'), (x0 + 3.85 * inch, 'ADDRESS')]
        hdr += [(x_bar, 'DRIVE')]
        for x, label in hdr:
            c.drawString(x, y, label)
        c.setStrokeColor(LINE_LITE)
        c.setLineWidth(0.6)
        c.line(x0, y - 5, x1, y - 5)
        row_h = 0.30 * inch if compact else row_h_1
        # very long lists (PG metro events: 40+ venues) compress further so
        # both columns still land above the footnote
        if rows and y_top - (len(rows) + 1) * row_h < y_floor:
            row_h = max(0.20 * inch, (y_top - y_floor) / (len(rows) + 1))
        y -= row_h
        for i, v in enumerate(rows):
            if i % 2 == 0:
                c.setFillColor(ROW_ALT)
                c.rect(x0 - 4, y - 8, x1 - x0 + 8, row_h - 2, stroke=0, fill=1)
            mins = v.get('drive_min')  # None = venue never geocoded/routed
            c.setFillColor(TEXT_DARK)
            c.setFont('Helvetica-Bold', 9 if not compact else 8)
            c.drawString(x_num, y, str(start_i + i + 1))
            c.drawString(x_venue, y, v['venue'][:venue_chars])
            if not compact:
                c.setFont('Helvetica', 9)
                c.drawString(x0 + 2.55 * inch, y, v.get('city', '')[:18])
                c.setFillColor(TEXT_MED)
                c.setFont('Helvetica', 8)
                c.drawString(x0 + 3.85 * inch, y, v.get('address', '')[:40])
            if mins is None:
                # not geocoded — an honest dash beats a fake "~0 min"
                c.setFillColor(TEXT_MED)
                c.setFont('Helvetica-Bold', 9 if not compact else 8)
                c.drawRightString(x_time, y, "—")
            else:
                c.setFillColor(BAR_BG)
                c.roundRect(x_bar, y - 2, bar_w, 8, 2, stroke=0, fill=1)
                c.setFillColor(_bar_color(mins))
                c.roundRect(x_bar, y - 2, bar_w * min(1.0, mins / max_min), 8, 2,
                            stroke=0, fill=1)
                c.setFillColor(TEXT_DARK)
                c.setFont('Helvetica-Bold', 9 if not compact else 8)
                c.drawRightString(x_time, y, f"~{mins}m" if compact else f"~{mins} min")
            y -= row_h

    if two_col:
        half = (len(vs) + 1) // 2
        col_w = (W - 2 * M - 0.35 * inch) / 2.0
        _rows(M, M + col_w, vs[:half], 0, compact=True)
        _rows(M + col_w + 0.35 * inch, W - M, vs[half:], half, compact=True)
    else:
        _rows(M, W - M, vs, 0, compact=False)

    # hub footnote
    c.setFillColor(TEXT_MED)
    c.setFont('Helvetica', 8)
    c.drawString(M, 0.55 * inch,
                 f"★ Starting point: {hub['name']} — {hub.get('address', '')}"
                 f"   |   Drive times approximate")

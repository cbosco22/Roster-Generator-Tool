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


def draw_venue_page(c, event_name, hub, venues, W=None, H=None):
    """Draw the venue page on an open reportlab canvas (one full page,
    caller does showPage)."""
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

    # column layout
    x_num, x_venue, x_city, x_addr = M, M + 0.32 * inch, M + 2.55 * inch, M + 3.85 * inch
    x_bar = W - M - 2.05 * inch
    bar_w_max = 1.55 * inch
    x_time = W - M

    # table header
    y = H - 1.62 * inch
    c.setFillColor(TEXT_MED)
    c.setFont('Helvetica-Bold', 8)
    for x, label in [(x_num, '#'), (x_venue, 'VENUE'), (x_city, 'CITY'),
                     (x_addr, 'ADDRESS'), (x_bar, 'DRIVE TIME')]:
        c.drawString(x, y, label)
    c.setStrokeColor(LINE_LITE)
    c.setLineWidth(0.6)
    c.line(M, y - 5, W - M, y - 5)

    row_h = 0.42 * inch
    y -= row_h
    for i, v in enumerate(vs):
        if i % 2 == 0:
            c.setFillColor(ROW_ALT)
            c.rect(M - 6, y - 10, W - 2 * M + 12, row_h - 2, stroke=0, fill=1)
        mins = v.get('drive_min', 0)
        c.setFillColor(TEXT_DARK)
        c.setFont('Helvetica-Bold', 9)
        c.drawString(x_num, y, str(i + 1))
        c.drawString(x_venue, y, v['venue'][:34])
        c.setFont('Helvetica', 9)
        c.drawString(x_city, y, v.get('city', '')[:18])
        c.setFillColor(TEXT_MED)
        c.setFont('Helvetica', 8)
        c.drawString(x_addr, y, v.get('address', '')[:40])
        # drive-time bar + label
        c.setFillColor(BAR_BG)
        c.roundRect(x_bar, y - 2, bar_w_max, 8, 2, stroke=0, fill=1)
        c.setFillColor(_bar_color(mins))
        c.roundRect(x_bar, y - 2, bar_w_max * min(1.0, mins / max_min), 8, 2,
                    stroke=0, fill=1)
        c.setFillColor(TEXT_DARK)
        c.setFont('Helvetica-Bold', 9)
        c.drawRightString(x_time, y, f"~{mins} min")
        y -= row_h

    # hub footnote
    c.setFillColor(TEXT_MED)
    c.setFont('Helvetica', 8)
    c.drawString(M, 0.55 * inch,
                 f"★ Starting point: {hub['name']} — {hub.get('address', '')}"
                 f"   |   Drive times approximate")

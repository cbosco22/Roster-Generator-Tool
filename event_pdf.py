"""
Whole-event annotated PDF support for the Post-Event tab.

Chris's old flow: open GoodNotes, find each annotated team, export each page
as a JPG, upload the pile. New flow: export the ENTIRE event as one PDF and
drop it in — these helpers find the annotated pages automatically so only
those (~30 of ~200+) go to Vision.

How detection works (validated against a real fully-annotated export,
'PBR 16U Nat'l Champ 2027.pdf', 223 pages, 2026-07-02):
- GoodNotes flattens its export — ink strokes, highlighter lines and text
  boxes are re-encoded INTO each page's single content stream (no separate
  annotation layer/XObject to look for), so presence of ink shows up as
  content-stream growth.
- Roster pages are identified by their table header text ('NOTES' +
  'First' + 'Last'), which skips covers/summary pages (whose own highlight
  marks don't matter post-event).
- A roster page is flagged as annotated when its content stream is
  > RATIO_THRESHOLD x the median roster-page size in the same file
  (self-calibrating — absolute sizes vary with roster length and export
  settings). Observed gap is wide: clean pages topped out at 1.3x median,
  while the lightest real annotation (ONE handwritten note on one player,
  page 131) was 2.8x and heavy pages hit 170x.
"""
import io
import statistics

RATIO_THRESHOLD = 1.8


def analyze_event_pdf(pdf_bytes):
    """Return {'total', 'roster_pages': [int], 'flagged': [(page_1idx, ratio)],
    'median'} for a whole-event PDF (1-indexed page numbers)."""
    import pypdf
    r = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    sizes, roster = [], []
    for i, pg in enumerate(r.pages):
        try:
            c = pg.get_contents()
            size = len(c.get_data()) if c is not None else 0
        except Exception:
            size = 0
        try:
            txt = pg.extract_text() or ''
        except Exception:
            txt = ''
        sizes.append(size)
        if 'NOTES' in txt and 'First' in txt and 'Last' in txt:
            roster.append(i + 1)
    if not roster:
        return {'total': len(r.pages), 'roster_pages': [], 'flagged': [], 'median': 0}
    med = statistics.median([sizes[p - 1] for p in roster]) or 1
    flagged = [(p, round(sizes[p - 1] / med, 1)) for p in roster
               if sizes[p - 1] > RATIO_THRESHOLD * med]
    return {'total': len(r.pages), 'roster_pages': roster,
            'flagged': flagged, 'median': med}


def render_page_jpeg(pdf_bytes, page_1idx, scale=2.0, quality=85):
    """Rasterize one page to JPEG bytes (for Vision or thumbnails)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    img = pdf[page_1idx - 1].render(scale=scale).to_pil().convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    return buf.getvalue()

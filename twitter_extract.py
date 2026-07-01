"""
twitter_extract.py — vision extraction for a single player from a Twitter/X
profile screenshot (or FiveTool/PBR profile, or a simple roster-list image),
for the Add Player tool.

Extraction fields and rules come from Chris's own spec, refined from real
use in a separate Claude Project before this got ported into the app
2026-06-30 — not written from scratch here. The one adaptation: that spec
targeted a copy-paste tab-separated row (the old workflow); this returns
structured JSON instead, since it feeds directly into sheet_write.py's
write path, not a copy/paste box (which Chris had removed from the app the
same night).

Reuses post_event_extractor's image prep + JSON repair helpers rather than
duplicating them.
"""
import base64

try:
    import anthropic
except ImportError:
    anthropic = None

from post_event_extractor import _prepare_image, _repair_json, MODEL

_MAX_TOKENS = 2000

_SYSTEM_PROMPT = """\
You are a college baseball recruiting assistant. You will be shown a
screenshot of a high school or travel baseball player - typically a
Twitter/X profile or post, but sometimes a FiveTool or PBR profile page, or
a simple roster list. Extract every available field.

Look at: the bio, pinned/visible posts, any stat graphic or card in the
image, and visible team/school logos or text.

Return ONLY valid JSON, no markdown fence, no prose, matching this shape:

{
  "first": "", "last": "", "class": "", "pos": "", "pos2": "",
  "bt": "", "hometown": "", "state": "", "hs": "", "team": "",
  "academic": "", "email": "", "phone": "", "commit": "", "notes": ""
}

Rules:
- class: 4-digit grad year like "2028". Blank "" if not stated.
- pos / pos2: if two positions are listed, primary goes in pos, secondary
  in pos2. If three or more are listed, put the primary in pos, the
  secondary in pos2, and fold anything beyond that into notes instead of
  inventing more fields.
- bt: bats/throws, e.g. "R/R", "L/L", "S/R". Blank "" if not stated.
- hometown: city (and state if given as part of the same hometown line).
  Blank "" if not stated.
- state: 2-letter abbreviation, only if actually shown or unambiguous from
  a named hometown/school/team. Do not guess a state from a name alone.
- hs: high school name if mentioned. Blank "" if not.
- team: travel/summer team name exactly as shown. Blank "" if not
  mentioned.
- academic: GPA and/or SAT/ACT if shown (e.g. "3.86 GPA" or "3.86 GPA,
  1310 SAT"). Blank "" if not shown.
- email / phone: only if literally visible in the image (bio link,
  contact card, etc). Blank "" otherwise - do not invent a plausible-
  looking one.
- commit: college committed to, ONLY if explicitly stated. Blank "" if
  uncommitted or not stated - never write "uncommitted" or similar, just
  leave it blank.
- notes: catch-all for anything real but not captured above - height/
  weight, the player's Twitter handle, velocity readings, exit velo, 60
  time, stats, rankings, scouting quotes. Format like:
  6'2" 190lbs | Twitter: @handle | key stat or quote here
  Only include what is actually shown. Leave "" if nothing concrete.
- Never fabricate. Leave a field "" rather than guessing.
- If the image does not show a real player at all, return every field
  blank.
"""


def extract_twitter_player(image_bytes: bytes, media_type: str = "image/png",
                            api_key: str | None = None) -> dict:
    """Extract one player's info from a screenshot. Returns a dict with keys
    first, last, class, pos, pos2, bt, hometown, state, hs, team, academic,
    email, phone, commit, notes - every value a string, "" if not found.
    Never raises for "couldn't find anything" - only for actual API/
    parsing failures."""
    if anthropic is None:
        raise RuntimeError("anthropic package not installed — check requirements.txt and reboot the app")
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    prepared, prepared_mt = _prepare_image(image_bytes, media_type)
    b64 = base64.standard_b64encode(prepared).decode("ascii")

    msg = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": prepared_mt, "data": b64}},
                {"type": "text",
                 "text": "Extract all player info from this screenshot and return the JSON object."},
            ],
        }],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content
                   if getattr(b, "type", "") == "text")
    data = _repair_json(text)

    out = {}
    for key in ("first", "last", "class", "pos", "pos2", "bt", "hometown",
                "state", "hs", "team", "academic", "email", "phone",
                "commit", "notes"):
        v = data.get(key, "")
        out[key] = str(v).strip() if v is not None else ""
    return out

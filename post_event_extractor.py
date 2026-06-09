"""
post_event_extractor.py — vision extraction for annotated post-event roster PNGs.

The input is a PNG exported from GoodNotes after a coach has annotated the
event PDF in the dugout. We need to pull out, per row:
  - All the printed columns (jersey, first, last, pos, ht, wt, class, school,
    pbr_rank, commit, printed_notes)
  - cur_star: the PRINTED Cur★ number if present (yellow-highlighted cell on
    the source PDF). Blank means the player was NOT in the DB at print time.
  - new_star: the HANDWRITTEN number stamped by the coach in the New★ column.
    This is the post-event rating Navy is committing to.
  - Any HANDWRITTEN name correction (red strikethrough + written-in name).
  - Any HANDWRITTEN notes in the NOTES column.
  - Division (age group) from the page header banner.

The cur_star vs. new_star distinction is critical because it drives the split:
  * cur_star populated → player already on the board → UPDATE flow
  * cur_star blank + new_star populated → NEW player → ADD flow
"""

import base64
import io
import json
import re

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = "claude-sonnet-4-6"   # vision-capable Sonnet (matches the Field Tool)
_MAX_TOKENS = 16000


_PROMPT = """\
You are reading a PNG export from GoodNotes. The source is a Navy Baseball
Recruiting roster PDF that a coach has annotated in the dugout during a
recruiting event. Your job is to extract EVERY row of the table exactly as it
appears, including handwritten coach annotations.

THE TABLE has these columns, left to right:
  #  |  First  |  Last  |  Pos  |  Ht  |  Wt  |  Class  |  School  |
  Cur★  |  New★  |  PBR Rank  |  Commit  |  NOTES

CRITICAL DISTINCTIONS — read carefully:

1. Cur★ column:
   - A PRINTED number (clean digital font, often with YELLOW HIGHLIGHTED cell
     background) means the player is already on Navy's recruiting board with
     that current rating.
   - BLANK means the player is NEW to Navy (not previously on the board).
   - Do NOT confuse with handwritten annotations.

2. New★ column:
   - HANDWRITTEN numbers (clearly written by hand, often larger and in pen)
     are coach stamps assigning a new Navy rating after seeing the player.
   - Only extract if it actually appears written in the New★ column.
   - Typical values: 1, 2, 3, 4, or 0.1 (commit).

3. Name corrections:
   - Sometimes a printed name has a RED STRIKETHROUGH/SCRIBBLE over it and a
     HANDWRITTEN CORRECT NAME written nearby. Use the handwritten correction
     as the player's actual name in `first` / `last`.
   - If both the printed and handwritten names look reasonable, prefer the
     handwritten one.

4. Handwritten notes:
   - The NOTES column on the right may have coach handwriting (scouting notes
     like "decent arm, has life" or "FB 86-88, good CH, SL").
   - Extract these verbatim into `notes_handwritten`. Leave blank if the only
     content in the cell is the printed grey label (e.g. "#7 Ethan Noyes").

5. Yellow highlighter on player NAMES (left side, over First/Last):
   - This is just the coach marking interesting players. It is NOT data.
   - DO NOT confuse it with the yellow Cur★ cell background which IS data.

PAGE HEADER:
- The header banner shows the division/age group (e.g. "15/16U", "17U") and
  sometimes a hand-written annotation like "2027's" or "More 2028's".
- Extract the printed division into `division` (e.g. "15/16U", "17U", "18U").
- If only a handwritten age annotation is visible, use that.
- The TEAM NAME appears BIG and BOLD at the very top of the page, above the
  table — typically the travel program (e.g. "9th Inning Royals", "Boston
  Prime", "Tri State Arsenal"). Extract that printed name into `team_name`.
- If the team name has been crossed out and replaced with handwriting (red
  scribble + handwritten new name), use the handwritten replacement.
- If no team name is visible, return "" for team_name.

OUTPUT — return ONLY valid JSON, no markdown fence, no prose:

{
  "team_name": "9th Inning Royals",
  "division": "15/16U",
  "players": [
    {
      "jersey": "7",
      "first": "Ethan",
      "last": "Noyes",
      "pos": "RHP",
      "ht": "6-2",
      "wt": "200",
      "class": "2027",
      "school": "Calvert Hall",
      "cur_star": "",
      "new_star": "2",
      "pbr_rank": "#71 MD",
      "commit": "",
      "notes_handwritten": "nice swing, potential, has power"
    }
  ]
}

RULES:
- One object per visible row, in the order they appear on the page.
- Jersey numbers: digits only. If blank in source, return "".
- Class: 4-digit year like "2027". If blank, return "".
- Cur★: ONLY the printed digital value if visible. Blank string "" if cell
  is empty OR if the only thing in it is handwriting (handwriting goes in
  new_star, not cur_star).
- New★: ONLY handwritten values. Blank string "" if none.
- All other fields: return "" if blank, never null or missing.
- Strip leading "#" from PBR Rank ONLY if it makes the field look wrong;
  normally keep the rank as shown (e.g. "#71 MD").
- If you genuinely cannot read a field, return "" rather than guessing.
- Do NOT skip rows. Even rows with no annotations should be included.
- Do NOT include the header row itself."""


def _prepare_image(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Pass through PNG/JPEG; convert HEIC to JPEG so the API accepts it."""
    mt = (media_type or "").lower()
    if mt in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        return image_bytes, mt
    if mt in ("image/heic", "image/heif"):
        try:
            from PIL import Image
            import pillow_heif
            pillow_heif.register_heif_opener()
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=92)
            return buf.getvalue(), "image/jpeg"
        except Exception as e:
            raise RuntimeError(f"Could not convert HEIC image: {e}")
    # Unknown — assume JPEG and hope for the best
    return image_bytes, "image/jpeg"


def _repair_json(text: str) -> dict:
    """Aggressively recover JSON from a possibly-fenced or truncated reply."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t).strip()

    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    start = t.find("{")
    if start != -1:
        for end in range(len(t), start, -1):
            try:
                return json.loads(t[start:end])
            except json.JSONDecodeError:
                continue

    # Rescue: pull out every complete player object we can find
    div_m = re.search(r'"division"\s*:\s*"([^"]*)"', t)
    division = div_m.group(1) if div_m else ""
    team_m = re.search(r'"team_name"\s*:\s*"([^"]*)"', t)
    team_name = team_m.group(1) if team_m else ""
    players = []
    for m in re.finditer(r'\{(?:[^{}]|\{[^{}]*\})*\}', t):
        chunk = m.group()
        if '"first"' not in chunk and '"last"' not in chunk:
            continue
        try:
            p = json.loads(chunk)
            if p.get("first") or p.get("last"):
                players.append(p)
        except json.JSONDecodeError:
            pass
    if players:
        print(f"[post_event] WARN: incomplete JSON — rescued {len(players)} rows")
        return {"team_name": team_name, "division": division, "players": players}

    raise ValueError(f"Could not parse extractor JSON. First 500 chars:\n{text[:500]}")


def _normalize_player(p: dict) -> dict:
    """Force the player dict into a consistent shape."""
    out = {
        "jersey": "", "first": "", "last": "", "pos": "", "ht": "", "wt": "",
        "class": "", "school": "", "cur_star": "", "new_star": "",
        "pbr_rank": "", "commit": "", "notes_handwritten": "",
    }
    for k in out:
        v = p.get(k, "")
        if v is None:
            v = ""
        out[k] = str(v).strip()

    # Jersey: digits only
    out["jersey"] = re.sub(r"\D", "", out["jersey"])

    # Class: keep 4-digit year only
    yr = re.sub(r"\D", "", out["class"])
    out["class"] = yr if len(yr) == 4 else ""

    # Stars: normalize "1.0" → "1" but keep "0.1" intact (commit tier)
    for k in ("cur_star", "new_star"):
        v = out[k]
        if v.endswith(".0") and v != "0.1":
            v = v[:-2]
        out[k] = v

    return out


def _extract_state_from_pbr(pbr_rank: str) -> str:
    """Pull a 2-letter state abbreviation out of a PBR rank string like '#143 MD'."""
    if not pbr_rank:
        return ""
    m = re.search(r"#\d+\s+([A-Z]{2})\b", pbr_rank)
    return m.group(1) if m else ""


def extract_post_event_page(image_bytes: bytes,
                            media_type: str = "image/png",
                            api_key: str | None = None) -> dict:
    """
    Extract one annotated roster page. Returns:
      {"division": "...", "players": [normalized dicts]}
    Each player dict also carries a derived `state` field (from pbr_rank if
    available) so the new-player CSV can be pre-filled.
    """
    if anthropic is None:
        raise RuntimeError("anthropic package not installed — check requirements.txt and reboot the app")
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    prepared, prepared_mt = _prepare_image(image_bytes, media_type)
    b64 = base64.standard_b64encode(prepared).decode("ascii")

    msg = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": prepared_mt, "data": b64}},
                {"type": "text", "text": _PROMPT},
            ],
        }],
    )

    text = "".join(getattr(b, "text", "") for b in msg.content
                   if getattr(b, "type", "") == "text")
    stop = getattr(msg, "stop_reason", "?")
    print(f"[post_event] stop_reason={stop}  output_chars={len(text)}")

    data = _repair_json(text)
    data.setdefault("team_name", "")
    data.setdefault("division", "")
    data.setdefault("players", [])

    normalized = []
    for p in data["players"]:
        n = _normalize_player(p)
        # Skip empty rows
        if not (n["first"] or n["last"] or n["jersey"]):
            continue
        n["state"] = _extract_state_from_pbr(n["pbr_rank"])
        normalized.append(n)

    return {
        "team_name": data["team_name"],
        "division": data["division"],
        "players": normalized,
    }

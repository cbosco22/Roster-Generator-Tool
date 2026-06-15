"""
photo_to_roster.py — extract a baseball roster from a photo via Claude vision.

Robust against truncation and model looping:
  * max_tokens kept modest (a real roster needs ~2400; a loop gets cut off fast)
  * _repair_json recovers complete player objects even from broken/partial JSON
  * players are de-duplicated by name so repeated/looped rows collapse to one
"""
import os, json, base64, re, io

try:
    import anthropic
except ImportError:
    anthropic = None
from PIL import Image
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    _HEIC_OK = True
except ImportError:
    _HEIC_OK = False

MODEL       = "claude-sonnet-4-6"
_MAX_DIM    = 2000
_MAX_TOKENS = 8192            # ~3x the worst-case real roster; caps runaway loops
_API_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

_PROMPT = """You are looking at a photo of a high school baseball team's printed roster from a tournament.

Extract the roster as JSON. Return ONLY the JSON object as a SINGLE LINE with no whitespace, no indentation, no line breaks, and no markdown fences. Nothing before or after the JSON.

CRITICAL — read the table one row at a time, fully left to right, before moving down to the next row. Every field for a single player — jersey, first name, last name, position, height, weight, school, grad year — sits on the SAME horizontal line. NEVER pair a first name from one row with a last name from a different row. NEVER pull a position, height, or school from an adjacent row. If a row's alignment is unclear or a cell is too blurry to read, leave that field as "" rather than guessing from a neighboring row. Accuracy of alignment matters far more than filling every cell.

Each player appears EXACTLY ONCE. Do not repeat any player. When you have listed every player on the roster once, close the JSON and stop immediately.

Schema (every field is a string; "" if unknown):
{"team_name":"...","players":[{"jersey":"#","name":"First Last","pos":"...","ht":"6-1","wt":"180","grad":"2027","hs":"School","state":"XX","commit":""}]}

Rules:
- One row per player. Skip header rows, coaches, staff.
- jersey: digits only; "" if not shown. Some entries may have a team prefix (e.g. "Slammers 19") — keep only the digits.
- name: "First Last", clean casing ("JOHN SMITH" -> "John Smith"); keep hyphens/apostrophes and accents (Burgueño stays Burgueño).
- pos: position(s) as printed; two positions use slash form (P/OF).
- ht: "F-I" format (e.g. 6'1" -> "6-1").
- wt: digits only.
- grad: 4-digit graduation year.
- hs: high school name only.
- state: 2-letter code (Georgia -> GA).
- commit: college name, or "" if uncommitted.
- Never invent data. "" is always acceptable. If you cannot read any players, return {"team_name":"","players":[]}.
"""


def _prepare_image(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    mt = (media_type or "").lower().strip()
    if mt == "image/jpg":
        mt = "image/jpeg"
    is_heic = mt in ("image/heic", "image/heif")
    needs_decode = is_heic or mt not in _API_MEDIA_TYPES
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:
        return image_bytes, mt if mt in _API_MEDIA_TYPES else "image/jpeg"
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    w, h = img.size
    longest = max(w, h)
    if longest > _MAX_DIM:
        scale = _MAX_DIM / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        needs_decode = True
    if needs_decode:
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88, optimize=True)
        return buf.getvalue(), "image/jpeg"
    return image_bytes, mt


def _dedupe(players: list) -> list:
    """Collapse repeated players (model loops) by name, keeping the richest copy."""
    seen = {}
    order = []
    for p in players:
        key = re.sub(r"\s+", " ", (p.get("name", "") or "").strip().lower())
        if not key:
            order.append(("", p)); continue
        if key not in seen:
            seen[key] = p
            order.append((key, p))
        else:
            # Keep whichever copy has more non-empty fields
            old = seen[key]
            if sum(1 for v in p.values() if v) > sum(1 for v in old.values() if v):
                seen[key] = p
    out, emitted = [], set()
    for key, p in order:
        if key == "":
            out.append(p)
        elif key not in emitted:
            out.append(seen[key]); emitted.add(key)
    return out


def _repair_json(text: str) -> dict:
    """Extract a roster from possibly-truncated or looped model output."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t).strip()

    # Direct parse
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # Try trimming trailing junk back to a valid close
    start = t.find("{")
    if start != -1:
        for end in range(len(t), start, -1):
            try:
                return json.loads(t[start:end])
            except json.JSONDecodeError:
                continue

    # Rescue: pull out every complete player object
    team_m = re.search(r'"team_name"\s*:\s*"([^"]*)"', t)
    team_name = team_m.group(1) if team_m else ""
    players = []
    for m in re.finditer(r'\{(?:[^{}]|\{[^{}]*\})*\}', t):
        chunk = m.group()
        if '"name"' not in chunk:
            continue
        try:
            p = json.loads(chunk)
            if "name" in p:
                players.append(p)
        except json.JSONDecodeError:
            pass
    if players:
        print(f"[photo_to_roster] WARN: incomplete JSON — rescued {len(players)} raw player objects")
        return {"team_name": team_name, "players": players}

    raise ValueError(f"Could not parse roster JSON. First 500 chars:\n{text[:500]}")

def _finalize_roster(text: str) -> dict:
    """Parse model output into a normalized, deduplicated roster dict.
    Shared by the image and PDF extraction paths."""
    data = _repair_json(text)
    data.setdefault("team_name", "")
    data.setdefault("players", [])
    for p in data["players"]:
        for k in ("jersey", "name", "pos", "ht", "wt", "grad", "hs", "state", "commit"):
            p.setdefault(k, "")
        p["jersey"] = re.sub(r"\D", "", str(p["jersey"]))
        g = re.sub(r"\D", "", str(p["grad"]))
        p["grad"] = g if len(g) == 4 else ""
    data["players"] = _dedupe(data["players"])
    return data


def extract_roster_from_image(image_bytes: bytes,
                              media_type: str = "image/jpeg",
                              api_key: str | None = None) -> dict:
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

    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    stop = getattr(msg, "stop_reason", "?")
    print(f"[photo_to_roster] stop_reason={stop}  output_chars={len(text)}")

    return _finalize_roster(text)


def extract_roster_from_images(images: list, api_key: str | None = None) -> dict:
    """
    Process several section photos of ONE team's roster and merge into a single
    deduplicated roster. Each photo is extracted independently at full resolution
    (the whole point: fewer rows per photo => more pixels per row => accurate
    column alignment). Repeated players across overlapping sections collapse via
    the same name-based dedupe.

    images: list of (image_bytes, media_type) tuples.
    """
    team_name = ""
    all_players = []
    for idx, (img_bytes, mt) in enumerate(images):
        result = extract_roster_from_image(img_bytes, media_type=mt, api_key=api_key)
        if not team_name and result.get("team_name"):
            team_name = result["team_name"]
        got = result.get("players", [])
        print(f"[photo_to_roster] photo {idx+1}/{len(images)}: {len(got)} players")
        all_players.extend(got)
    return {"team_name": team_name, "players": _dedupe(all_players)}


def extract_roster_from_pdf(pdf_bytes: bytes, api_key: str | None = None) -> dict:
    """Extract a roster from a PDF.

    The PDF is handed to Claude as a document block (pages read natively — the
    same approach the Importer uses), then parsed/normalized with the same logic
    as the image path. Intended for a SINGLE team's roster (one or more pages).
    """
    if anthropic is None:
        raise RuntimeError("anthropic package not installed — check requirements.txt and reboot the app")
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
    msg = client.messages.create(
        model=MODEL,
        max_tokens=_MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document",
                 "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": _PROMPT},
            ],
        }],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
    print(f"[photo_to_roster] pdf stop_reason={getattr(msg, 'stop_reason', '?')}  output_chars={len(text)}")
    return _finalize_roster(text)


def extract_roster_from_files(files: list, api_key: str | None = None) -> dict:
    """Process several uploads (images and/or PDFs) of ONE team's roster and merge
    into a single deduplicated roster.

    files: list of (data_bytes, media_type) tuples. media_type 'application/pdf'
    routes to the PDF document path; everything else is treated as an image.
    Repeated players across overlapping sources collapse via the name dedupe.
    """
    team_name = ""
    all_players = []
    for idx, (data, mt) in enumerate(files):
        if (mt or "").lower() == "application/pdf":
            result = extract_roster_from_pdf(data, api_key=api_key)
        else:
            result = extract_roster_from_image(data, media_type=mt, api_key=api_key)
        if not team_name and result.get("team_name"):
            team_name = result["team_name"]
        got = result.get("players", [])
        print(f"[photo_to_roster] source {idx+1}/{len(files)} ({mt}): {len(got)} players")
        all_players.extend(got)
    return {"team_name": team_name, "players": _dedupe(all_players)}


def to_pdf_payload(extracted: dict, event_name: str,
                   division: str | None = None) -> dict:
    """Wrap an extracted roster into the multi-team JSON shape build_pdf consumes."""
    team_name = extracted.get("team_name", "") or "Unknown Team"
    team = {"name": team_name, "players": extracted.get("players", [])}
    if division:
        team["division"] = division
    payload = {"event": event_name, "teams": [team]}
    if division:
        payload["schedule_team_divs"] = {team_name: division}
    return payload

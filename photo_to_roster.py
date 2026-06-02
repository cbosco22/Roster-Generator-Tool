"""
photo_to_roster.py — extract a baseball roster from a photo via Claude vision.

Produces a roster JSON in the shape gen_roster_pdf.py expects:
{
  "team_name": "...",
  "players": [
    {"jersey": "12", "name": "John Smith", "pos": "P",
     "ht": "6-1", "wt": "180", "grad": "2027",
     "hs": "...", "state": "GA", "commit": ""}
  ]
}
"""
import os, json, base64, re, io

# Use the Anthropic SDK; key comes from env or Streamlit secrets.
import anthropic

# Pillow handles JPEG/PNG/WEBP natively. Register HEIC if pillow-heif is
# installed so iPhone-default photos work too. (Optional — graceful fallback.)
from PIL import Image
try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
    _HEIC_OK = True
except ImportError:
    _HEIC_OK = False

MODEL = "claude-sonnet-4-6"  # vision-capable, best cost/speed for OCR

# Anthropic accepts jpeg/png/gif/webp. Resize cap keeps payload under limits
# and speeds up extraction; 2000px on the long edge is plenty for roster text.
_MAX_DIM = 2000
_API_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

_PROMPT = """You are looking at a photo of a high school baseball team's printed roster from a tournament.

Extract the roster as JSON. Return ONLY the JSON object — no prose, no markdown fences, nothing else.

Schema:
{
  "team_name": string,        // exact team name as printed (e.g. "Team Elite Prime 2027")
  "players": [
    {
      "jersey": string,       // jersey #, digits only. "" if not shown.
      "name": string,         // "First Last", standard capitalization
      "pos": string,          // position abbreviation: P, C, IF, OF, SS, 1B, 2B, 3B, LHP, RHP, OF/P, etc.
      "ht": string,           // height as "6-1" (feet-inches). "" if missing.
      "wt": string,           // weight in pounds, digits only. "" if missing.
      "grad": string,         // 4-digit graduation year (e.g. "2027"). "" if missing.
      "hs": string,           // high school name. "" if missing.
      "state": string,        // 2-letter state abbreviation (GA, NY, etc.). "" if missing.
      "commit": string        // college commitment, "" if uncommitted/not shown.
    }
  ]
}

Rules:
- One row per player. Skip header rows, coaches, staff.
- If a column is missing on the roster, use "".
- For names: clean up casing ("JOHN SMITH" → "John Smith"). Preserve hyphens and apostrophes.
- For positions: standard baseball abbreviations. If two listed ("P/OF"), use the slash form.
- For height: convert any format to "F-I" (e.g. "6'1\\"" → "6-1", "5'11" → "5-11").
- For state: full names → 2-letter codes (Georgia → GA, etc.).
- If the photo is unclear or you cannot identify any players, return {"team_name":"","players":[]}.
- Do not invent data. Empty string is always acceptable.
"""


def _clean_json(text: str) -> str:
    """Strip markdown fences and any pre/post text around the JSON object."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    # Find first { and matching last }
    if "{" in t and "}" in t:
        t = t[t.find("{"): t.rfind("}") + 1]
    return t


def _prepare_image(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """
    Convert any input image into something the Anthropic API accepts.
    - HEIC/HEIF → JPEG (requires pillow-heif)
    - PNG/JPEG/WEBP/GIF: re-encode as JPEG if oversized, otherwise pass through
    - Strips EXIF/orientation by re-encoding when we touch the image
    Returns (bytes, media_type) ready for the API.
    """
    mt = (media_type or "").lower().strip()
    if mt == "image/jpg":
        mt = "image/jpeg"

    is_heic = mt in ("image/heic", "image/heif") or (not mt and image_bytes[:12].endswith(b"ftypheic"))
    needs_decode = is_heic or mt not in _API_MEDIA_TYPES

    # Try to open and check size. If it's small enough and already an API-friendly
    # type, pass it through; otherwise re-encode.
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception:
        # If we can't decode, send the original bytes and hope the API copes.
        return image_bytes, mt if mt in _API_MEDIA_TYPES else "image/jpeg"

    # Apply EXIF orientation
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    # Resize if too large
    w, h = img.size
    longest = max(w, h)
    if longest > _MAX_DIM:
        scale = _MAX_DIM / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # Decide whether to re-encode
    if needs_decode or longest > _MAX_DIM or mt not in _API_MEDIA_TYPES:
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88, optimize=True)
        return buf.getvalue(), "image/jpeg"

    return image_bytes, mt


def extract_roster_from_image(image_bytes: bytes,
                              media_type: str = "image/jpeg",
                              api_key: str | None = None) -> dict:
    """
    image_bytes: raw image bytes (jpeg/png/heic/webp)
    media_type: mime type of the image; HEIC is converted automatically
    api_key: optional override; otherwise reads ANTHROPIC_API_KEY env var.
    Returns parsed dict matching the schema above.
    """
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    prepared, prepared_mt = _prepare_image(image_bytes, media_type)
    b64 = base64.standard_b64encode(prepared).decode("ascii")

    msg = client.messages.create(
        model=MODEL,
        max_tokens=16384,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64",
                            "media_type": prepared_mt,
                            "data": b64}},
                {"type": "text", "text": _PROMPT},
            ],
        }],
    )

    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    cleaned = _clean_json(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse JSON from model. Raw text:\n{text[:500]}") from e

    # Guarantee shape
    data.setdefault("team_name", "")
    data.setdefault("players", [])
    for p in data["players"]:
        for k in ("jersey", "name", "pos", "ht", "wt", "grad", "hs", "state", "commit"):
            p.setdefault(k, "")
        # Normalize jersey: keep digits only
        p["jersey"] = re.sub(r"\D", "", str(p["jersey"]))
        # Normalize grad: digits only, 4 chars
        g = re.sub(r"\D", "", str(p["grad"]))
        p["grad"] = g if len(g) == 4 else ""
    return data


def to_pdf_payload(extracted: dict, event_name: str,
                   division: str | None = None) -> dict:
    """Wrap an extracted roster into the multi-team JSON shape build_pdf consumes."""
    team_name = extracted.get("team_name", "") or "Unknown Team"
    team = {"name": team_name, "players": extracted.get("players", [])}
    if division:
        team["division"] = division
    payload = {
        "event": event_name,
        "teams": [team],
    }
    if division:
        payload["schedule_team_divs"] = {team_name: division}
    return payload

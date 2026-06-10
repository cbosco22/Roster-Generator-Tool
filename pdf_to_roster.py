"""
pdf_to_roster.py — turn an arbitrary event PDF (showcase roster, tournament
roster export, etc.) into the site-compatible roster JSON the generator eats:

  {"event": "...", "teams": [{"name": "...", "players": [
       {"jersey","name","pos","ht","wt","grad","hs","state","commit",
        "twitter","instagram","academic"} ]}]}

The PDF is handed to Claude as a document (no rasterizing — Claude reads the
pages natively), along with a grouping mode ("one_list" vs "split") and optional
free-text instructions. This reproduces the chat workflow — tell it how to read
the file, regenerate if needed — without leaving the app.

Robust to size: tries one pass, and if the model's output would overflow (big
multi-team events), it re-processes the PDF in page batches (carrying the header
page into each batch) and merges by team name. A truncated reply is salvaged
rather than crashing.
"""
import base64
import io
import json
import re

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    PdfReader = PdfWriter = None

MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 32000          # fits a few hundred players in one pass
_BATCH_PAGES = 3             # pages per batch in the large-PDF fallback

PLAYER_FIELDS = ["jersey", "name", "pos", "ht", "wt", "grad", "hs", "state",
                 "commit", "twitter", "instagram", "academic"]


def _build_prompt(mode, list_name, instructions):
    if mode == "one_list":
        grouping = (f'Treat ALL players as ONE team named "{list_name}". Do NOT '
                    f'split into multiple teams even if the PDF has a team / '
                    f'color / club column — this is a single showcase roster.')
    else:
        grouping = ('Split the players into multiple teams. A team is usually '
                    'marked by a column like "Team", "Color", a team number, or '
                    'a squad name that repeats down the rows. Use that identifier '
                    'as the team "name" (combine number + color if both exist, '
                    'e.g. "2 Red"). A player keeps their team across page breaks — '
                    'group by the identifier, not by page.')
    extra = ""
    if (instructions or "").strip():
        extra = ("\n\nADDITIONAL INSTRUCTIONS FROM THE USER (follow these over the "
                 "defaults above):\n" + instructions.strip())

    return f"""You are reading a baseball event PDF — a showcase or tournament roster. \
Extract EVERY player into JSON.

{grouping}{extra}

Map the PDF's columns onto this exact player schema (every value a STRING, "" if absent):
  - jersey: uniform number, digits only ("" if none)
  - name: full "First Last". If the PDF has separate First and Last columns, combine them. Clean casing.
  - pos: position(s) exactly as printed; keep slash form like "OF/1B"
  - ht: height as F-I (6'1" -> "6-1"); "" if none
  - wt: weight, digits only; "" if none
  - grad: 4-digit graduation/class year (from a GRAD or Class column)
  - hs: high school / school name only
  - state: 2-letter state (from an "St" column); "" if none
  - commit: college commitment if shown, else ""
  - twitter: Twitter/X handle if such a column exists, else ""
  - instagram: Instagram handle if such a column exists, else ""
  - academic: GPA/SAT/ACT text if an Academic column exists, else ""

Return ONLY valid JSON, no markdown fence, no prose. Output COMPACT JSON (no pretty-printing / extra whitespace):
{{"event":"{list_name}","teams":[{{"name":"...","players":[{{"jersey":"","name":"First Last","pos":"","ht":"","wt":"","grad":"","hs":"","state":"","commit":"","twitter":"","instagram":"","academic":""}}]}}]}}

RULES:
- One object per player row. Skip header rows and any coach / staff rows.
- Read each row fully left-to-right; never pair a name from one row with fields from another row.
- If a cell is blank or unreadable, use "" — never guess from a neighboring row.
- Do not invent players and do not repeat players.
- Include every player you can read, across every page."""


def _repair_json(text):
    """Parse the reply; on truncation, salvage every complete player object."""
    t = (text or "").strip()
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
    # Salvage: pull out every complete player object from a truncated reply.
    players = []
    for m in re.finditer(r'\{(?:[^{}]|\{[^{}]*\})*\}', t):
        chunk = m.group()
        if '"name"' not in chunk:
            continue
        try:
            p = json.loads(chunk)
            if p.get("name"):
                players.append(p)
        except json.JSONDecodeError:
            pass
    if players:
        print(f"[pdf_to_roster] WARN: truncated/partial JSON — salvaged {len(players)} players")
        return {"teams": [{"name": "", "players": players}]}
    raise ValueError(f"Could not parse importer JSON. First 500 chars:\n{(text or '')[:500]}")


def _normalize(data, list_name):
    """Force model output into the canonical roster shape."""
    if isinstance(data, list):
        data = {"teams": data}
    teams = data.get("teams") or []
    if not teams and data.get("players"):
        teams = [{"name": list_name, "players": data["players"]}]

    out_teams = []
    for t in teams:
        if not isinstance(t, dict):
            continue
        name = (t.get("name") or list_name).strip() or list_name
        players = []
        for p in t.get("players", []):
            if not isinstance(p, dict):
                continue
            row = {k: str(p.get(k, "") or "").strip() for k in PLAYER_FIELDS}
            row["jersey"] = re.sub(r"\D", "", row["jersey"])
            g = re.sub(r"\D", "", row["grad"])
            row["grad"] = g if len(g) == 4 else ""
            if row["name"]:
                players.append(row)
        if players:
            out_teams.append({"name": name, "players": players})

    return {"event": (data.get("event") or list_name).strip() or list_name,
            "teams": out_teams}


def _call(pdf_bytes, prompt, api_key):
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    b64 = base64.standard_b64encode(pdf_bytes).decode("ascii")
    msg = client.messages.create(
        model=MODEL, max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
            {"type": "text", "text": prompt},
        ]}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content
                   if getattr(b, "type", "") == "text")
    truncated = getattr(msg, "stop_reason", "") == "max_tokens"
    print(f"[pdf_to_roster] stop_reason={getattr(msg,'stop_reason','?')} chars={len(text)}")
    return text, truncated


def _extract_one(pdf_bytes, mode, list_name, instructions, api_key):
    text, truncated = _call(pdf_bytes, _build_prompt(mode, list_name, instructions), api_key)
    try:
        return _repair_json(text), truncated
    except ValueError:
        return None, truncated


def _split_with_header(pdf_bytes, batch_pages):
    """Page batches; every batch after the first carries page 0 (the header)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    n = len(reader.pages)
    batches, i = [], 0
    while i < n:
        w = PdfWriter()
        if i != 0:
            w.add_page(reader.pages[0])
        for j in range(i, min(i + batch_pages, n)):
            w.add_page(reader.pages[j])
        buf = io.BytesIO(); w.write(buf)
        batches.append(buf.getvalue())
        i += batch_pages
    return batches


def _merge(datas, mode, list_name):
    """Merge per-batch results, grouping by team name and de-duping players."""
    from collections import OrderedDict
    teams = OrderedDict()
    for d in datas:
        if not d:
            continue
        for t in _normalize(d, list_name)["teams"]:
            key = list_name if mode == "one_list" else t["name"]
            bucket = teams.setdefault(key, OrderedDict())
            for p in t["players"]:
                pk = (p["name"].lower(), p["jersey"])
                if pk not in bucket:
                    bucket[pk] = p
    return {"event": list_name,
            "teams": [{"name": k, "players": list(v.values())}
                      for k, v in teams.items() if v]}


def extract_roster_from_pdf(pdf_bytes, mode="split", list_name="Event",
                            instructions="", api_key=None):
    """
    PDF bytes -> {"event","teams":[{"name","players":[...]}]}.
      mode: "split" (multiple teams) or "one_list" (single showcase roster)
    """
    if anthropic is None:
        raise RuntimeError("anthropic package not installed — check requirements.txt and reboot the app")

    # 1) one pass — fits the large majority of showcase/tournament PDFs
    data, truncated = _extract_one(pdf_bytes, mode, list_name, instructions, api_key)
    if data is not None and not truncated:
        return _normalize(data, list_name)

    # 2) overflowed or failed to parse -> process in page batches and merge
    if PdfReader is not None:
        try:
            batches = _split_with_header(pdf_bytes, _BATCH_PAGES)
            datas = [_extract_one(b, mode, list_name, instructions, api_key)[0]
                     for b in batches]
            merged = _merge(datas, mode, list_name)
            if merged["teams"]:
                return merged
        except Exception as e:
            print(f"[pdf_to_roster] batch fallback failed: {e}")

    # 3) last resort — whatever the first pass managed to salvage
    if data is not None:
        return _normalize(data, list_name)
    raise ValueError("Could not extract any players from this PDF — try the other "
                     "grouping mode, or split the PDF into smaller files.")

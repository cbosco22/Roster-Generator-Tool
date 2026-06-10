"""
pdf_to_roster.py — turn an arbitrary event PDF (showcase roster, tournament
roster export, etc.) into the site-compatible roster JSON the generator eats:

  {"event": "...", "teams": [{"name": "...", "players": [
       {"jersey","name","pos","ht","wt","grad","hs","state","commit",
        "twitter","instagram","academic"} ]}]}

The PDF is handed to Claude as a document (no rasterizing — Claude reads the
pages natively), along with:
  - a grouping mode: "one_list" (a showcase = one big roster) or "split"
    (multiple squads/teams in the file), and
  - optional free-text instructions (the same clarification you'd type in chat,
    e.g. "split by the Team/Color column" or "ignore the Travel Team column").
This reproduces the chat workflow — tell it how to read the file, regenerate if
the first pass isn't right — without leaving the app.
"""
import base64
import json
import re

try:
    import anthropic
except ImportError:
    anthropic = None

MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 16000

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

Return ONLY valid JSON, no markdown fence, no prose:
{{"event":"{list_name}","teams":[{{"name":"...","players":[{{"jersey":"","name":"First Last","pos":"","ht":"","wt":"","grad":"","hs":"","state":"","commit":"","twitter":"","instagram":"","academic":""}}]}}]}}

RULES:
- One object per player row. Skip header rows and any coach / staff rows.
- Read each row fully left-to-right; never pair a name from one row with fields from another row.
- If a cell is blank or unreadable, use "" — never guess from a neighboring row.
- Do not invent players and do not repeat players.
- Include every player you can read, across every page."""


def _repair_json(text):
    """Recover JSON from a possibly fenced or trailing-truncated reply."""
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
    raise ValueError(f"Could not parse importer JSON. First 500 chars:\n{(text or '')[:500]}")


def _normalize(data, list_name):
    """Force the model output into the canonical roster shape."""
    if isinstance(data, list):
        data = {"teams": data}
    teams = data.get("teams") or []
    # If the model returned a flat players list, wrap it as one team.
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


def extract_roster_from_pdf(pdf_bytes, mode="split", list_name="Event",
                            instructions="", api_key=None):
    """
    PDF bytes -> {"event", "teams":[{"name","players":[...]}]}.
      mode: "split" (multiple teams) or "one_list" (single showcase roster)
      list_name: event/team name (also the single team name in one_list mode)
      instructions: free-text clarification passed straight to the model
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
                {"type": "text", "text": _build_prompt(mode, list_name, instructions)},
            ],
        }],
    )

    text = "".join(getattr(b, "text", "") for b in msg.content
                   if getattr(b, "type", "") == "text")
    stop = getattr(msg, "stop_reason", "?")
    print(f"[pdf_to_roster] stop_reason={stop}  output_chars={len(text)}")

    data = _repair_json(text)
    return _normalize(data, list_name)

import json, re, os

_DIR = os.path.dirname(os.path.abspath(__file__))

def _load():
    with open(os.path.join(_DIR, "travel_programs.json")) as f:
        return json.load(f)

_PROGRAMS = _load()

def lookup_org_tier(team_name):
    """Match a scraped team name to a travel program tier (1-4). Returns int or None."""
    if not team_name:
        return None
    name = team_name.lower().strip()
    cleaned = re.sub(
        r"\b(20\d{2}|scout|national|\d{2}u|black|blue|red|gold|white|3n2|carolina|"
        r"franchise|northeast|northwest|runbird|marucci|baseball|regional)\b",
        "", name
    )
    cleaned = re.sub(r"[\'\\-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    for candidate in [cleaned, name]:
        if candidate in _PROGRAMS:
            return _PROGRAMS[candidate]
        matches = [(k, v) for k, v in _PROGRAMS.items() if k in candidate and len(k) >= 3]
        if matches:
            return max(matches, key=lambda x: len(x[0]))[1]
    return None

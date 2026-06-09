"""
post_event_flow.py — business logic for the Post-Event tab.

Keeps the Streamlit UI in app.py clean by isolating:
  - Pool splitting (updates vs new players)
  - CSV / TSV builders matching the recruiting-sheet column order

Split rule (validated on real annotated pages):
  - A row counts only if it has a hand-written New* value.
  - New* present + printed Cur* present -> UPDATE  (existing board player)
  - New* present + Cur* blank            -> NEW player (never DB-searched)
  - No New*                              -> skipped (coach didn't re-rate)
"""

import csv
import io
import json
from datetime import date


# Columns for new_players.csv — Date Added through Notes (sheet cols F..AA).
NEW_PLAYER_COLUMNS = [
    "Date Added", "By", "First", "Last", "Class", "\u2605", "Commit",
    "Pos", "POS2", "B/T", "Hometown", "State", "High School",
    "Summer Team", "Academic", "Email", "Phone Number", "Seen",
    "Visit Date", "Offer Date", "Comms", "Notes",
]

# Updates output — paste-ready, name-keyed for the sheet's XLOOKUP star update.
UPDATE_COLUMNS = ["Name", "Team", "Cur \u2605", "New \u2605"]


# -------------------- pool splitting ----------------------

def split_pools(extracted_pages, db=None):
    """
    Split every extracted row into:
      - updates:     New* present AND Cur* present (existing board player)
      - new_players: New* present AND Cur* blank   (true new add)
      - skipped:     no New* (nothing to record)

    `db` is accepted for call-signature compatibility but intentionally unused:
    new players are never DB-searched, and updates report the printed Cur*
    straight off the page (which came from the DB at print time).
    """
    updates, new_players, skipped = [], [], []

    for page in extracted_pages:
        division = page.get("division", "")
        team_name = page.get("team_name", "")
        for p in page.get("players", []):
            row = dict(p)
            row["_division"] = division
            row["_team_name"] = team_name

            new_star = (row.get("new_star") or "").strip()
            cur_star = (row.get("cur_star") or "").strip()

            if not new_star:
                skipped.append(row)
            elif cur_star:
                updates.append(row)
            else:
                new_players.append(row)

    stats = {
        "total_rows": sum(len(p.get("players", [])) for p in extracted_pages),
        "updates": len(updates),
        "new_players": len(new_players),
        "skipped": len(skipped),
        "pages": len(extracted_pages),
    }
    return {"updates": updates, "new_players": new_players,
            "skipped": skipped, "stats": stats}


# -------------------- CSV builders ----------------------

def _load_travel_programs(travel_json_path):
    """Return travel program names sorted alphabetically for the UI dropdown."""
    try:
        with open(travel_json_path) as f:
            d = json.load(f)
        return sorted({_title_case_program(k) for k in d.keys()})
    except Exception:
        return []


def _title_case_program(name):
    """'east cobb astros' -> 'East Cobb Astros'; short alpha words -> ACRONYM."""
    LOWER_CONNECTORS = {"of", "and", "the", "for", "in", "to"}
    parts = []
    for w in name.split():
        if w and w[0].isdigit():
            parts.append(w)
        elif w.lower() in LOWER_CONNECTORS:
            parts.append(w.lower())
        elif len(w) <= 3 and w.isalpha():
            parts.append(w.upper())
        else:
            parts.append(w.title())
    return " ".join(parts)


def _split_pos(pos):
    """Split a printed position on '/' into (Pos, POS2). Never combine with a slash."""
    if not pos:
        return "", ""
    parts = [s.strip() for s in pos.replace(",", "/").split("/") if s.strip()]
    if not parts:
        return "", ""
    return parts[0], (parts[1] if len(parts) > 1 else "")


def prefill_new_player_rows(new_players, date_added, by_initials):
    """Raw extracted-row dicts -> editable form rows in NEW_PLAYER_COLUMNS order."""
    rows = []
    for r in new_players:
        pos1, pos2 = _split_pos(r.get("pos", ""))
        rows.append({
            "Date Added": date_added,
            "By": by_initials,
            "First": r.get("first", ""),
            "Last": r.get("last", ""),
            "Class": r.get("class", ""),
            "\u2605": r.get("new_star", ""),
            "Commit": r.get("commit", ""),
            "Pos": pos1,
            "POS2": pos2,
            "B/T": "",
            "Hometown": "",
            "State": r.get("state", ""),          # derived from PBR rank if present
            "High School": r.get("school", ""),
            "Summer Team": r.get("_team_name", ""),  # auto-filled from page header
            "Academic": "",
            "Email": "",
            "Phone Number": "",
            "Seen": "",
            "Visit Date": "",
            "Offer Date": "",
            "Comms": "",
            "Notes": r.get("notes_handwritten", ""),
        })
    return rows


def build_updates_rows(updates):
    """Updates review rows in UPDATE_COLUMNS order: Name | Team | Cur * | New *."""
    rows = []
    for r in updates:
        name = f"{r.get('first', '')} {r.get('last', '')}".strip()
        rows.append({
            "Name": name,
            "Team": r.get("_team_name", ""),
            "Cur \u2605": r.get("cur_star", ""),
            "New \u2605": r.get("new_star", ""),
        })
    return rows


def rows_to_csv(rows, columns, delimiter=",", header=True):
    """Generic builder: only the requested columns, in order.
    delimiter='\\t' => TSV; header=False => data rows only (paste-append)."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore",
                       lineterminator="\n", delimiter=delimiter)
    if header:
        w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in columns})
    return buf.getvalue().encode("utf-8")


def today_str():
    try:
        return date.today().strftime("%-m/%-d/%Y")
    except ValueError:                       # Windows fallback
        return date.today().strftime("%m/%d/%Y")

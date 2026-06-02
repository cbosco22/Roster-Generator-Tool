"""
fetch_db.py
Called by the PDF generator to pull fresh data from Google Sheet.
Since Claude's Drive connector handles auth, this is designed to be
called with the raw sheet content passed in as a string argument.

Usage inside PDF generator:
    from fetch_db import build_db_from_raw
    db = build_db_from_raw(raw_sheet_text)
    entry = db.lookup('Zach Madar')   # → {'tier':..., 'pos':..., etc.} or None
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_loader import parse_sheet_content, lookup as _lookup

class RecruitingDB:
    def __init__(self, raw_text):
        self._db = parse_sheet_content(raw_text)
        print(f"[DB] Loaded {len(self._db)//2:.0f} players from live sheet "
              f"({len(self._db)} name variants)")

    def lookup(self, name):
        return _lookup(self._db, name)

    def all_names(self):
        seen = set()
        result = []
        for entry in self._db.values():
            cn = entry['canonical_name']
            if cn not in seen:
                seen.add(cn)
                result.append(cn)
        return sorted(result)

def build_db_from_raw(raw_text):
    return RecruitingDB(raw_text)

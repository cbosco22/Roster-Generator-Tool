# CLAUDE.md — Roster-Generator-Tool
> Drop this file at the root of cbosco22/Roster-Generator-Tool. Claude Code reads it automatically at session start.

## What This App Is
Navy Baseball recruiting operations toolkit. A Streamlit app that generates roster PDFs,
schedule CSVs, and supports post-event processing for high school baseball recruiting events.
Used by coaches AP, CB, TR, CR, AM on iPads (GoodNotes) and iPhones.

---

## Repo & Deploy Info
- **GitHub:** cbosco22/Roster-Generator-Tool
- **Deploy:** Streamlit Cloud — push to `main` → reboot Streamlit app → hard refresh browser
- **Python path:** Scripts expect `/home/claude/` in sys.path (for pbr_rankings.pkl etc.)
- **PBR rankings pickle:** `pbr_rankings.pkl` at `/home/claude/` and `data/` — 799 national + ~12,341 state rankings, classes 2027-2028, May 2026 vintage

---

## App Tabs (Current)
1. **Field Tool** — at-event use, live tagging interface
2. **Tournament Builder** — pre-event PDF generation
3. **Schedule Refresh** — pulls updated tournament schedule
4. **Post-Event** — processes annotated GoodNotes JPGs into DB updates
5. **Admin** — config, recruiting-sheet sync status, PBR rankings rebuild

Importer tab was removed 2026-06-30 (was unused).

---

## Key Files
| File | Purpose |
|------|---------|
| `gen_roster_pdf.py` | PDF generator — LOCKED FORMAT |
| `db_loader.py` | Parses recruiting xlsx — LOCKED column map |
| `fetch_db.py` | Builds DB from raw sheet text |
| `org_tier.py` | Looks up travel program tier from team name |
| `travel_programs.json` | Program tier definitions (Tier 1–4) |
| `build_rankings.py` | Builds pbr_rankings.pkl from JSON files |
| `gen_schedule_csv.py` | Generates schedule CSV from event JSON |
| `run_event.py` | Single entry point for full event prep workflow |
| `sheet_sync.py` | Pulls Recruiting Sheet 2.0 as xlsx via Drive's public export endpoint (no auth — see file docstring for why) |
| `sheet_write.py` | Builds upsert ops (update/append) for writing post-event data back to Sheet 2.0 |
| `apps_script/Code.gs` | Deployed manually by Chris into the Sheet's own Apps Script editor — the actual write endpoint |

---

## Google Drive Resources
- **Main folder:** `1ChVwd0-0NIS6GCDWXkVA6Az91Cg6stfl`
- **Scripts folder:** `1qMDLz_8cAho3jU4JPim1gla1Tmmh1GmQ`
- **2026 Event Work folder:** `1aHhnwXtIeQaZxzcOQ1C82vIRA9_XGadH`
- **Schedule template sheet:** `1yR5e6ldN-32AnVYulcJNKOYumnBTEGsOth2nIgZfEF4`
- **Recruiting Google Sheet (OLD, retired 2026-06-30):** `1ecpbBbWaVaSlmz4qmHUWJw9Esj6P0x5R4y81QQYhMzE`
  - Owned by USNA staff (treilly@usna.edu), not Chris — was never API-writable
  - Sheet now carries a banner pointing to 2.0; keep it read-only, don't delete it (has years of extra notes/tabs not yet migrated)
- **Recruiting Sheet 2.0 (CURRENT source of truth):** `15XDpXkOLtGqyZaEVq3OvbugnB2e1XPbEzWJowPJCVfs`
  - Cloned from the old sheet, owned by Chris (bosco.chris01@gmail.com) — same "High School Players" tab/column layout, so `db_loader.parse_xlsx()` works against it unchanged
  - Shared as "anyone with the link can view" — **intentional, confirmed with Chris 2026-06-30** (the sheet has sensitive player data including minors' info, so don't change this sharing setting without checking with him first)
  - Auto-synced into `data/recruiting.xlsx` by `sheet_sync.py` via Drive's public export endpoint — no auth, no GCP project, no secrets needed, because of the sharing setting above. No more manual xlsx export/upload or git-commit needed for routine board updates.
  - **Write access:** GCP service-account write access hit the same `iam.disableServiceAccountKeyCreation` org policy as the read path originally did. Solved differently — see `apps_script/` (Apps Script web app bound to the Sheet, runs as Chris, no GCP/OAuth needed at all). `sheet_write.py` is the Python side: builds upsert ops (update existing row vs. append new), `apps_script/Code.gs` is what Chris deploys (one-time, manual — see `apps_script/README.md`). Supports a `dryRun` mode that validates everything without writing, used until a real deployment is confirmed working.
  - **Form-destination gap: FIXED 2026-06-30.** Extended player-submitted columns (GPA, Test Scores, Injury History, etc. — "AUTO PULL FROM RECRUITING FORM" per the sheet header) were empty in 2.0 because the linked Google Form still targeted the old sheet; Chris fixed the Form's destination and confirmed those fields are populating now.

---

## LOCKED: PDF Format (DO NOT CHANGE WITHOUT EXPLICIT INSTRUCTION)

### Page Layout
- Portrait, letter size
- Margins: 0.30" L/R, 0.50" top, 0.30" bottom
- Running header: "NAVY BASEBALL RECRUITING" left | event name center | "Page N" right
- Header underline at 0.36" from top

### Roster Table — 13 Columns (LOCKED)
```
Index:  0    1      2     3    4   5   6      7       8      9      10        11      12
Col:    #  First  Last   Pos  Ht  Wt  Class  School  Cur★  New★  PBR Rank  Commit  NOTES
```

### Column Widths (LOCKED)
| Column | Width | Notes |
|--------|-------|-------|
| NOTES (idx 12) | 2.50" | FIXED — never changes |
| Commit (idx 11) | 0.70" | |
| PBR Rank (idx 10) | 0.48" | |
| St / state | 0.30" | 2-letter abbreviation |
| School (idx 7) | remainder | whatever's left after all fixed cols |

### Fonts (LOCKED)
| Element | Font | Size | Color |
|---------|------|------|-------|
| Header row | Helvetica-Bold | 6.5pt | White on `#1A1A1A` |
| Jersey # | Helvetica-Bold | 7.5pt | |
| First + Last name | Helvetica-Bold | 8.5pt | centered |
| Stats / School / St | Helvetica | 6pt | centered |
| Cur★ | Helvetica-Bold | 7pt | |
| NOTES label | Helvetica | 5.5pt | `#BBBBBB`, top-left, 3pt top, 4pt left |

### Row Heights (LOCKED)
- Data row: 0.46"
- Header row: 0.26"
- Alternating row colors: `#F2F2F2` / white

### Cell Styling (LOCKED)
- Cur★ cell (idx 8): yellow `#FFF176` background for players found in DB
- Heavy border (0.7pt) after Last (idx 2) and before NOTES (after idx 11)
- Internal borders: 0.4pt `#CCCCCC`
- Box border: 0.7pt

### NOTES Cell Label Format (LOCKED)
```
#[jersey] First Last
```
In 5.5pt `#BBBBBB`, top-left corner, 3pt from top, 4pt from left.

---

## LOCKED: PBR Rank Column Format
Line 1: `#N ST` (state rank + 2-letter state abbreviation)
Line 2: `#N Nat'l` (if nationally ranked)
Line 3: `#N PG` (if `pg_rank` field is purely numeric)
Blank if completely unranked.

Cross-validate: grad year + state must match PBR data to prevent false matches (John Smith problem).
New England states (MA/CT/RI/NH/VT/ME) are treated as equivalent region.
National rankings with "- select state -" pass the state check.

---

## LOCKED: Commit Priority
PG roster packet → DB (recruiting sheet) → PBR rankings
Never show a commit value of "None" or blank string — show empty.

---

## LOCKED: Cover Page
- Title ALL CAPS, 28pt
- Event dates below title
- Teams listed alphabetically within age group / division
- RIGHT side: colored dots showing Navy targets per team (C→1→2→3→4)
- LEFT side: team name + "— Tier N" (org tier, 7.5pt `#AAAAAA`) + PBR count
- Legend at bottom: Committed / Offer / High Follow / Follow / Rec
- NEVER remove or replace the dots
- Cover auto-expands to multiple pages if needed; legend always on last cover page

### Cover Dot Colors (LOCKED)
| Tier | Label | Dot Color | Text Color |
|------|-------|-----------|------------|
| 0.1 | C | `#1A3A6B` | white |
| 1 | 1 | `#2E7D32` | white |
| 2 | 2 | `#F9A825` | dark |
| 3 | 3 | purple | white |
| 4 | 4 | `#90CAF9` | navy |
| XX | — | never shown | — |

---

## LOCKED: Player Rating Tiers (CRITICAL)
Tier 3 (Follow) is NOW equal in importance to ALL other tiers.
- Counted in schedule CSV
- Shown on cover page
- Only XX (off list) is filtered out
This supersedes any old rule that said "Tier 3 filtered" or "Tier 3 never shown."

### Tier Labels (Jun 2026 update)
| Tier | Label |
|------|-------|
| 0.1 | Committed |
| 1 | Offer |
| 2 | High Follow |
| 3 | Follow |
| 4 | Rec (Recruiting Board) |
| XX | Off List (filtered) |

---

## LOCKED: Schedule CSV Format
Built by `gen_schedule_csv.py`.
Columns: `Game#, Date, Time, Location, Attend, Division, Team1, Team1★, Team1 Navy Players, Team2, Team2★, Team2 Navy Players, Total★`

- `_COUNTED_TIERS = {'0.1','1','2','3','4'}` — tier 3 included, only XX filtered
- Team★ = count of Navy-listed players on that team
- Navy Players cell format: `"Name (Tier) 'YY POS STATE"` joined by `"; "`
- Tier 0.1 displayed as `C` in this cell
- Upload to Drive as `text/csv`

---

## LOCKED: DB Loader — xlsx Column Map
File: `db_loader.py`, function: `parse_xlsx(path)`
Sheet: "High School Players" tab only
Skip first 3 header rows.

```
xlsx col index → field
[7]  → First name
[8]  → Last name
[9]  → Class (grad year)
[10] → Tier / ★
[11] → Commit
[12] → Pos
```

Float suffixes stripped (e.g., `2027.0` → `2027`), EXCEPT `0.1` is preserved exactly.
ALWAYS use `parse_xlsx()` on the uploaded file — NEVER use Drive text connector (truncates large sheets).

---

## LOCKED: Name Matching Logic
1. `strip_suffix()` — removes Jr., III, etc.
2. Nickname table — 45+ pairs (e.g., jake↔jacob, zach↔zachary)
3. `_fuzzy_lookup()` — exact last name required, first name SequenceMatcher ≥ 0.82
4. `_pbr_match()` — cross-validates grad year + state to prevent false PBR rank matches
Do NOT weaken the 0.82 fuzzy threshold. Do NOT skip the state/grad year cross-check.

---

## LOCKED: run_event.py CLI
Single entry point for full event prep:
```bash
python run_event.py \
  --xlsx path/to/recruiting.xlsx \
  --roster path/to/roster.json \
  [--schedule path/to/schedule.json] \
  [--pbr json1 json2 ...] \
  [--event "Event Name"] \
  [--division "17U/18U"] \
  [--outdir output/]
```
Builds pkl if missing, loads DB, patches event name, stamps divisions, writes PDF + CSV.

---

## LOCKED: Post-Event Flow
Input: Annotated GoodNotes JPGs (coaches annotate printed PDFs with star ratings)
Output: Two files
1. **UPDATES** — 4-col TSV: `Name, Team, Cur★, New★` — name-keyed for XLOOKUP in recruiting sheet
2. **NEW players** — 22-col CSV for blank-Cur★ rows (players not in DB); never DB-searched

Rules:
- Split by Cur★ presence
- No New★ written = row skipped
- Pos field: splits on "/" into Pos + POS2
- NEW players: never run through DB lookup

---

## LOCKED: Division Detection
`parse_divisions_pdf()` — extracts from age-groups PDF (Teams tab screenshots)
`_stamp_divisions_from_resets()` — detects alphabetical resets, maps groups 1:1 to division name list
Plain-list JSONs auto-wrapped as `{"teams":[...]}`

---

## LOCKED: JSON Schema (Chrome Extension Output)
```json
{
  "event": "Event Name",
  "dates": "July 7-12, 2026",
  "source": "pg | fivetool | eventbeacon | prospectselect",
  "scrapedAt": "ISO timestamp",
  "schedule_team_divs": { "Team Name": "17U" },
  "teams": [
    {
      "name": "Team Name",
      "players": [
        {
          "jersey": "12",
          "name": "First Last",
          "pos": "RHP",
          "grad": "2027",
          "hs": "School Name",
          "state": "GA",
          "commit": "Vanderbilt",
          "ht": "6-2",
          "wt": "185",
          "pg_rank": "142",
          "academic": ""
        }
      ]
    }
  ],
  "schedule": [
    {
      "game": "1",
      "date": "7/7/2026",
      "time": "9:00 AM",
      "location": "Field 1",
      "division": "17U",
      "team1": "Team Name",
      "team2": "Team Name",
      "score": ""
    }
  ]
}
```

**CRITICAL:** Team name byte-identity between roster and schedule JSON is required for Navy player count joins. Pool-prefix team names must match exactly.

---

## Org Tier System
`org_tier.py` + `travel_programs.json`
- Cover page: "— Tier N" shown after team name (7.5pt `#AAAAAA`)
- Roster page: "Tier N" small gray label below team name
- No label if team not in programs list — that's acceptable, not a bug

---

## Chrome Extension (LOCKED — v2.9.7)
**NEVER modify without a DevTools screenshot from Chris first.**
- PBR/FT/PS scrapers unchanged from v2.9.2
- PG roster: header-driven column mapping
- v2.9.7 fixes: jersey# glitch (numeric only), PG commit scraping
- Locked at v2.9.7 — no changes without explicit instruction + screenshot

---

## PBR Rankings
- File: `pbr_rankings.pkl` at `/home/claude/` and `data/`
- Current data: 799 national + ~12,341 state rankings, classes 2027–2028, May 2026 vintage
- To rebuild: Chris drops new JSON files → run `build_rankings.py` → new pkl
- Mid-summer 2026 rebuild planned from new JSON files

---

## Backlog (Prioritized)
Build these in order:

### IN PROGRESS / NEXT
1. **PBR player profile crawler** (`pbr_crawler.js` — Node.js, same-origin fetch, ~2s throttle)
   - Broad shallow scrape for Tier 1/Tier 2 enrichment
   - Event-triggered: runs night before each event, ~30–45 min unattended
   - Player DB stored as `players.parquet` with `profile_path` join key
   - "DB Builder" Streamlit tab to ingest crawler JSON with field provenance

2. **PDF visual redesign** — Chris has a sketch of the new layout
   - Will incorporate richer scraped data (velocity, stats, etc.)
   - Wait for sketch before building

3. **Roster preview + column presets**
   - In-app table preview before PDF generation
   - User-selectable columns with width/font controls
   - Saved as presets per event type
   - Incremental Streamlit feature

### QUEUED
4. ~~Remove Importer tab~~ — done 2026-06-30
5. ~~Copy recruiting sheet Chris owns → automatic DB pull~~ — done and LIVE 2026-06-30: `sheet_sync.py` + Admin tab auto-sync from Sheet 2.0 (10-min cache, re-pulls on every container boot), no secrets/credentials needed — see Google Drive Resources above for why. Verified end-to-end against the real production sheet (1,710 players). Manual-upload fallback still works as an override.
6. **Player add from Twitter/X** — housed directly in app. Chris already does this manually via a Claude Project; port that prompt/extraction logic in next, similar pattern to `photo_to_roster.py`
7. ~~Recruiting Tools page redesign~~ — done 2026-06-30 (Event Day brand lockup)
8. **Google Sheet write-back** — now unblocked (Chris owns Sheet 2.0), not yet built
9. **Extension download + scrape-instructions page** — inside the existing app
10. **Capabilities one-pager PDF** — for sharing with other programs
11. **App consolidation** — Chris wants one umbrella app: Big Board view, full player list, schedule, instead of 3 separate apps (this Streamlit tool, navy-event-day, and a legacy AppSheet recruiting-board app). Lean toward expanding this app with Big Board/Player List tabs and retiring AppSheet; keep navy-event-day separate (built for one-handed mobile use at a tournament, which Streamlit doesn't do well). Not started — needs a real design pass, not a quick add.
   - 2026-06-30 update: Chris is now thinking even bigger than this — one site for the *whole* coaching staff (recruiting + visit scheduling + budget + full depth chart, which currently all live as different tabs in the recruiting spreadsheet), plus folding in a separate player-analysis website he built independently. This item may get superseded by that larger scope — ask Chris before assuming which version is current.
12. **Post-event: write ratings straight to DB after review** — write path built 2026-06-30 (`sheet_write.py` + `apps_script/`), tested against real production data in dry-run, all upsert scenarios verified correct (re-seen/no change, new tier, field change, duplicate-event dedupe, brand-new player). **Not yet wired into the Post-Event tab UI** — needs Chris to deploy `apps_script/Code.gs` first (see its README) so the live round-trip can be verified, then a review/confirm screen built before any write fires for real. Don't skip the dry-run verification step once the URL exists — this writes into the live recruiting board.
13. **"Seen" column becomes an append-only history** — done 2026-06-30, Chris chose: comma-space-delimited list in the existing single Seen cell (e.g. "WWBA 16U 2026, NPI 2026"), never overwritten, only appended, with a dedupe guard against re-appending the same event twice. Implemented in `sheet_write.py`, verified. Other fields (tier, state, HS, summer team, etc.) follow Chris's rule: overwrite only if a new value was actually captured this round and differs from what's there — never blank out something just because this round didn't mention it.

---

## Important Engineering Rules
- **No guessing.** Flag anomalies; don't fabricate field names or infer structure without source confirmation.
- **Surgical edits only.** Only modify files/functions directly involved in the current fix.
- **Backward compatibility required.** Don't break existing workflows.
- **Large file writes:** Use chunked `cat >> file << 'EOF'` bash heredoc appends (~400–500 lines per chunk) with line count verification after each chunk. `create_file` with large payloads silently truncates.
- **Drive text connector truncates** large sheets. Always use `parse_xlsx()` on uploaded file directly via openpyxl.
- **PBR "Printable Roster" exports** sometimes scramble Twitter/Instagram/Academic columns. Use "Contact Information" export as authoritative source for those fields.
- **PG event name** often scrapes as "Event" — patch from filename automatically.

---

## Libraries In Use
- **ReportLab** — PDF generation (direct `canvas` for cover, Platypus `BaseDocTemplate` for roster tables)
- **pypdf** — PDF merging, outline/bookmark writing
- **openpyxl** — xlsx parsing
- **pdfplumber** — coordinate-based extraction for scrambled column PDFs
- **matplotlib** — map rendering (Agg backend, manual coordinate plotting)
- **Anthropic Claude API** — vision extraction for Field Tool / Post-Event; PDF Importer tab

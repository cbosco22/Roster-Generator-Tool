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

## App Tabs (Current, order matches the live tab bar)
1. **Field Tool** — at-event use, live tagging interface
2. **Add Player** — screenshot (Twitter/X, FiveTool/PBR) or manual entry, writes straight to Sheet 2.0
3. **Board** — added 2026-07-01, iterated several times same day/next on Chris's direct feedback. Pick one Class + Position group (RHP/LHP/INF/OF/C, via `sheet_write.pos_group()`) at a time; shows tier 0.1/1/2 only, same as the sheet's own `★ < 3` filter. Each row is a real `st.popover` trigger button (emoji tier badge, e.g. "🔵 C", now its own leftmost column - not fused into the name) - clicking it opens an inline panel with that player's notes, tier pills, note field, and save button.
   - Emoji tier badges (🔵🟢🟡🟣🔷 for 0.1/1/2/3/4) stand in for the sheet's colored circular badge - real Streamlit buttons can't be arbitrarily colored, emoji was the closest native equivalent.
   - **2026-07-02: formatting redone against the real sheet's actual cell formatting** (pulled via openpyxl - don't guess this again, re-pull if it ever needs revisiting: `Big Board by Position`, 15pt row height, thin per-cell borders, no zebra fill, position-group header is `fill=#00225B` / `font=#B5A67C` i.e. navy+gold, not black). Fixed three things Chris called out as "ugly": (1) header was a separate raw HTML `<table>` that could never pixel-align with the `st.columns()` body rows below it - both now built from the identical `col_widths` list so they're guaranteed to line up; (2) header recolored from flat `#1A1A1A` to the app's own navy `#14233B`/gold `#C8A24B` (also matches the sheet's own navy/gold, not a coincidence - same design lineage); (3) tier pills inside the popover were sprawling with dead space - `[data-testid="stPopoverBody"]` capped at `max-width:260px` and pill button padding tightened, so they wrap into compact rows instead of spreading across a wide default panel. Row height tightened via `st.container(key="nb_board")` + scoped CSS (~30px/row now, down from default Streamlit spacing) - can't fully reach the sheet's 15pt because real click targets (buttons) have a practical minimum height Streamlit won't go below; said so directly rather than overclaiming an exact match.
   - **2026-07-02, second pass same day:** Chris flagged the pill fix from the first pass hadn't actually done anything, and too much dead space between Name/State/Team. Root cause: the CSS targeted `[data-testid="stPills"]`, which doesn't exist - `st.pills`' real DOM (confirmed via live DOM inspection, not assumed) is `stButtonGroup` wrapping `stBaseButton-pills`/`stBaseButton-pillsActive` buttons. Every rule under that wrong selector was dead on arrival. Fixed with the real testids - verified via direct measurement, pill buttons went from 32-43px (a single digit "1" at 32px) down to 24-35px. Also: all cell text now centered (was left-aligned) per Chris's request, Team allowed to wrap to a second line instead of reserving one-line width for long travel-org names, column width ratios tightened (`[1, 2.2, 1, 1, 1.5]`) since the wider first-pass ratios were leaving visible gaps next to short/small-font State and Team values. Lesson for next time touching this: don't guess Streamlit/BaseWeb internal testids from memory - `preview_eval`-inspect the live DOM first, most guesses here (`stPopoverBody` was actually right; `stPills` was not) turned out wrong in ways that silently no-op instead of erroring.
   - **2026-07-02, third pass: abandoned the popover-per-row approach entirely.** After two rounds of CSS fixes still didn't satisfy Chris ("complete mess," an hour in), he sent a screenshot of a table he'd built directly in Sheets in 5 minutes as the actual target. Root problem wasn't fixable with more CSS: real Streamlit widgets (buttons, popovers) have a practical minimum height/padding and their own icon-font requirements (the popover's chevron rendered as literal text "expand_more" - the app's global `font-family: Inter !important` broke the Material Symbols icon font the chevron needs, invisible until this was the first `st.popover` ever added to the app) that a dense bordered spreadsheet table can't be squeezed into no matter how much padding gets removed. Rebuilt as a static HTML `<table>` matching Chris's mock exactly: solid navy position-group header, light gray column-header row, full thin-border grid (`1px solid #CCCCCC` every cell), ~20px rows via 2px padding + 11px font, tier shown via colored NAME text (green for tier 1, navy+bold for 0.1, plain for 2+) rather than a badge/circle - not guessed, `_BOARD_NAME_COLOR` matches what was actually visible in Chris's screenshot. The table is now display-only; a small "Update a player" form (dropdown + tier selectbox + note + save, plain Streamlit widgets, no popover) sits below it instead of being inline per-cell - a deliberate scope-back from "click any cell" after the interactive version repeatedly fought Streamlit's widget system. Verified: row height ~20-23px (vs ~30px+ for the button-based version), matches the density of Chris's reference.
   - **Lesson:** when a user provides a concrete visual reference (a mock, a screenshot), match it directly and literally before optimizing for a secondary goal (full inline interactivity) that fights the primary one. Two rounds of CSS archaeology on Streamlit internals could have been skipped by asking "can you show me what you mean" after the first "this looks bad" instead of continuing to guess at fixes.
   - **2026-07-02, fourth pass:** Chris also pointed out every verification screenshot up to this point was taken at desktop width (900-1400px), not the ~390px iPhone width coaches actually use - all `preview_resize` calls from here on use 390x844. Final column layout: ★ first (not last) showing "C" for tier 0.1 instead of "0.1", Name widened (34-38% of table width) and made the prominent column, State header shortened to "ST" and narrowed to match B/T's width, Team is the one left-aligned column (deliberately truncates with an ellipsis - "probably won't show all the time" was Chris's own framing, not a bug). Real gotcha hit along the way: narrowing State without `white-space: nowrap` made 2-letter codes like "MN" stack into "M/N" - every column except Team now has `nowrap` + ellipsis overflow handling so nothing wraps unexpectedly at narrow widths.
   - **2026-07-02, fifth pass: real click-to-edit, final architecture.** Chris wanted the bottom "update a player" form gone in favor of clicking a player to open "a little card" with every field editable (rating, summer team, notes, "really all of them if we can"), plus a POS column when Position="ALL" and horizontal scroll instead of squeezing everything into phone width. Two more dead ends before landing here, both confirmed live, not assumed: `st.columns()` stacks vertically below Streamlit's mobile breakpoint (broke the row layout at the real 390px test width - a plain `st.container(horizontal=True)` doesn't stack, but its `width="stretch"` fills the *entire* row by itself rather than "remaining space," which pushed the Team cell onto its own line). Landed on `st.dataframe` instead of any hand-built row layout: native horizontal scroll when content overflows (exactly "scrollable side to side"), native row-click selection (no more per-row `st.button`/`st.popover`), `column_config.Column(alignment=...)` for real per-column text alignment (solves "ST needs to be centered" natively), and a pandas `Styler.apply()` for tier-colored name text. Selecting a row calls `_bd_profile_dialog()`, an `st.dialog`-decorated function (Streamlit's actual modal-card primitive - literally "a little card pop up") showing every field `parse_xlsx()` loads, editable, saved via `sheet_write.build_profile_update_op()` (new: general field-update op, replaces the narrower `build_tier_update_op` - never touches Seen, since a Board edit isn't an event sighting) + `build_note_update_op()` for the append-only notes field. Position filter now has an "ALL" option; the rating filter (previously hardcoded to 0.1/1/2) is now `st.multiselect` defaulting to the same three but expandable to 3/4/XX.
   - **2026-07-02, sixth pass: dropped `st.dataframe`, back to per-row buttons.** The dataframe's row-selection only respended to clicking its own checkbox column - confirmed live by clicking directly on a NAME cell and watching nothing happen. Chris didn't want that checkbox visible at all and wanted the whole row clickable ("its not very intuitive... I dont want to see that and i want to be able to click the name"). Back to a real `st.button` per row inside `st.container(horizontal=True)` (the primitive that doesn't stack on mobile - see the pass above), but every column now gets an explicit fixed pixel width, including TEAM (the "stretch" bug from two passes ago is what pushed me to `st.dataframe` in the first place - the actual fix was just "don't use stretch on a non-last column," not "abandon the whole approach"). Horizontal scroll (still wanted for the ALL-positions case) now comes from wrapping the row group in a `st.container(key=...)` with scoped CSS (`flex-wrap: nowrap; overflow-x: auto` on `[data-testid="stHorizontalBlock"]`) instead of relying on `st.dataframe`'s native scroll - verified live: 486px of row content scrolls cleanly inside a 358px viewport. Team is back to a real HTML `<div style="font-size:9px">` cell (not dataframe canvas), so the smaller-font trade-off noted in the pass above is resolved as a side effect, not the point of this change.
   - **Lesson, reinforced a fourth time this session:** verify Streamlit widget/API behavior live before building on an assumption, even for "should be simple" things like column layout or row-selection. `st.columns()` stacking on mobile, `width="stretch"`'s actual semantics, and `st.dataframe` row-selection requiring its checkbox specifically were all discovered by testing at the real target viewport/interaction (390px, real clicks), not by reading docs or type hints. Also: when an earlier approach gets abandoned for a specific bug, check whether the bug itself was fixable before assuming the whole approach was wrong - `st.dataframe` solved the "stretch" bug by construction, but introduced a worse problem (the checkbox) that a one-line fix to the original approach (fixed width instead of stretch) would have avoided entirely.
   - **2026-07-02, seventh pass: rating as a real colored bubble, column order, vertical alignment.** Rating split out of the name button into its own static HTML circle matching `gen_roster_pdf.TIER_DOT_COLOR` exactly ("show as the bubbles colored like on my pdfs") - a plain `st.button` label can't render a colored circle, so the click target narrowed to just the Name button (left-aligned bubble, centered name, exactly what Chris asked for - the bubble was never required to be part of the click target, only the name was). Column order after Name is now POS, ST, TEAM, B/T (was POS, B/T, ST, TEAM). Vertical alignment fixed with `align-items: center` on the row's `stHorizontalBlock` - verified live, every cell in a row now shares the same computed `centerY`. `_BOARD_NAME_COLOR` (tier-colored name text) removed - dead code once Name became a real button (button labels can't take arbitrary per-instance text color the way a static HTML div could), the bubble carries the color signal now instead.
   - First real step on backlog item #11 (App consolidation / retire AppSheet) — see that item for what's still not done.
4. **Post-Event** — processes annotated GoodNotes JPGs into DB updates
5. **Tournament Builder** — pre-event PDF generation
6. **Schedule Refresh** — pulls updated tournament schedule
7. **Admin** — config, recruiting-sheet sync status, PBR rankings rebuild

Importer tab was removed 2026-06-30 (was unused).

**Planned nav regroup (not started, brain-dumped 2026-07-01):** Chris wants the
app renamed "Navy Baseball" with tabs regrouped into two top-level sections
instead of one flat row — Event Tools (Field Tool, Tournament Builder,
Schedule Refresh, Post-Event) and Players (Add Player, Board) — Admin stays
top-level, not nested. Explicitly deferred until after the Board tab (above)
ships and is verified, so as not to reshuffle navigation twice in one sitting.

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
| `sheet_write.py` | Builds upsert ops (update/append) for writing post-event and Add Player data back to Sheet 2.0. Also `build_profile_update_op()` / `build_note_update_op()` — narrower ops for the Board tab's profile-card edit, used when the exact row is already known (no fuzzy lookup needed); `build_profile_update_op()` takes any subset of `_PROFILE_FIELDS` as kwargs and never touches Seen; notes append instead of overwrite. `pos_group()` (renamed from `_pos_group` 2026-07-01, made public specifically so the Board tab could reuse the exact same RHP/LHP/INF/OF/C bucketing instead of re-deriving it) is the live sheet's own position-group formula, mirrored in Python. |
| `db_loader.all_players()` | Flat, deduped list of every player `parse_xlsx()` parsed — feeds the Board tab. Not a separate loader; same data, same LOCKED column resolution. `parse_xlsx()` now also parses `notes` (added 2026-07-01 — it previously resolved the column but never read it, so nothing could diff/append against the existing value). |
| `apps_script/Code.gs` | Deployed manually by Chris into the Sheet's own Apps Script editor — the actual write endpoint |
| `twitter_extract.py` | Vision extraction for the Add Player tab — Twitter/X, FiveTool/PBR profile, or roster-list screenshots |

---

## Google Drive Resources
- **Main folder:** `1ChVwd0-0NIS6GCDWXkVA6Az91Cg6stfl`
- **Scripts folder:** `1qMDLz_8cAho3jU4JPim1gla1Tmmh1GmQ`
- **2026 Event Work folder:** `1aHhnwXtIeQaZxzcOQ1C82vIRA9_XGadH`
- **Schedule template sheet:** `1yR5e6ldN-32AnVYulcJNKOYumnBTEGsOth2nIgZfEF4`
- **Recruiting Google Sheet (OLD, retired 2026-06-30):** `1ecpbBbWaVaSlmz4qmHUWJw9Esj6P0x5R4y81QQYhMzE`
  - Owned by USNA staff (treilly@usna.edu), not Chris — was never API-writable
  - Sheet now carries a banner pointing to 2.0; keep it read-only, don't delete it (has years of extra notes/tabs not yet migrated)
  - **2026-07-01: fully retired from AppSheet too.** The separate "Navy Baseball Recruiting" AppSheet app (appId `a58635b0-bdf7-4dd7-a00b-d64d16d1496e`, still in daily coach use, distinct from this Streamlit tool) was still bound to this old sheet until tonight — all 5 of its tables (High School Players, Recruiting Calendar Import, Recruiting Form Responses, Stock Text, Travel Program List) now point to Sheet 2.0 instead, verified with real data. Nothing live points to this old sheet anymore. Full migration details, including a not-yet-attempted future cleanup step, in memory: appsheet-sheet2-migration.
- **Recruiting Sheet 2.0 (CURRENT source of truth):** `15XDpXkOLtGqyZaEVq3OvbugnB2e1XPbEzWJowPJCVfs`
  - Cloned from the old sheet, owned by Chris (bosco.chris01@gmail.com) — same "High School Players" tab/column layout, so `db_loader.parse_xlsx()` works against it unchanged
  - Shared as "anyone with the link can view" — **intentional, confirmed with Chris 2026-06-30** (the sheet has sensitive player data including minors' info, so don't change this sharing setting without checking with him first)
  - Auto-synced into `data/recruiting.xlsx` by `sheet_sync.py` via Drive's public export endpoint — no auth, no GCP project, no secrets needed, because of the sharing setting above. No more manual xlsx export/upload or git-commit needed for routine board updates.
  - **Write access:** GCP service-account write access hit the same `iam.disableServiceAccountKeyCreation` org policy as the read path originally did. Solved differently — see `apps_script/` (Apps Script web app bound to the Sheet, runs as Chris, no GCP/OAuth needed at all). `sheet_write.py` is the Python side: builds upsert ops (update existing row vs. append new), `apps_script/Code.gs` is what Chris deploys (one-time, manual — see `apps_script/README.md`). Supports a `dryRun` mode that validates everything without writing, used until a real deployment is confirmed working.
  - **Form-destination gap: FIXED 2026-06-30.** Extended player-submitted columns (GPA, Test Scores, Injury History, etc. — "AUTO PULL FROM RECRUITING FORM" per the sheet header) were empty in 2.0 because the linked Google Form still targeted the old sheet; Chris fixed the Form's destination and confirmed those fields are populating now.
  - **Sheet 2.0 has 27 tabs total**, not just High School Players — schedules, budget, multiple depth-chart tabs by class year, a raw form-responses tab, an "Event Lists" tab, etc. This is the spreadsheet Chris described wanting to eventually move the whole staff onto a real site for (see memory: navy-baseball-umbrella-vision) — High School Players is just the one tab this app touches today.
  - **High School Players structural issues, found 2026-06-30 by inspecting the real formulas (don't trust the rendered values, check `data_only=False`):**
    - Columns C ("ID"), D ("Name"), E ("Pos Group") are spilling array formulas, not real data, and they are NOT safely bounded the way a static export first made them look — confirmed 2026-06-30 when the first real write (row 1982) got corrupted: the live formula reacted to new data written into column D and re-derived a second label on top of it. `sheet_write.py` now computes and writes all three of these itself as plain values on every append/update — correct column roles (fixed same day, were backwards in an earlier version): C=ID (compound label, e.g. "Noah Stead (0.1) - '25 MINF CA"), D=Name (plain "First Last"), E=Pos Group (derived bucket). Also now writes Date Added (col 6) and By (col 7) on append, which the first version of this write path silently dropped. Chris is manually flattening C:E to static values for all pre-existing rows (copy -> paste special -> values only) to remove the live formulas permanently — see `apps_script/README.md`. Row 1982 needs a manual correction pass after that flatten (bad ID label, missing Date Added/By from before this fix).
    - The tab's native Filter range is hardcoded to `$A$3:$AK$1980` — already excludes the last real player row as of 2026-06-30. This is the literal mechanism behind "new players don't show up in the filtered view." One-time fix needed (not handled by Code.gs — see `apps_script/README.md`): extend the filter range manually in Sheets to a generous bound.
    - The "AUTO PULL FROM RECRUITING FORM" columns are not live formulas either. The real chain is: raw Google Form responses live in a *third*, separate spreadsheet -> IMPORTRANGE'd into a "Recruiting Form Responses" tab in this sheet -> some other mechanism (not confirmed — possibly a broken/missing Apps Script trigger, possibly manual) gets it into High School Players' AC-AI columns. A "StarUpdater" tab ("PASTE UPDATED RANKINGS HERE") with Name/Team/Cur★/New★ columns appears to be the literal manual process behind the old TSV-paste workflow this app's write path is meant to replace — its target column ("Update ★") was empty on every row checked, likely unused/vestigial.
  - **Open architecture question, not yet decided:** Chris asked where new write-back data should live — a second "clean" tab in the spreadsheet, or keep High School Players as a plain database (no formulas) and put the actual filterable "browse all players" view in this app instead of in Sheets. Current recommendation (given, not yet confirmed as final): the latter — don't add another Sheets-side abstraction layer, build the view in the app since that's the direction Chris already wants to go (replacing the legacy AppSheet board). See memory: post-event-auto-write-seen-history and navy-baseball-umbrella-vision.
  - **2026-07-01: found and fixed — ★ tier written as text by AppSheet.** AppSheet's rating field was an Enum with a Text base type (kept for the button-style 0.1/1/2/3/4/XX UI), so it wrote e.g. `'2'` instead of `2` into the ★ column. Big Board's `FILTER()` formula does a numeric `<` comparison against that column — a text value silently fails the comparison and the player just vanishes from the board, no error. Confirmed against the real file: 6 players (all 2027s, tier "2") were missing this way; one row also had Class as text for the same reason. Chris fixed the AppSheet field's base type to Number (no sentinel value needed for XX in the end). Existing bad cells were hand-corrected; the Big Board formula was hardened separately (`IFERROR(VALUE(...),9)` wrapper) in case a future writer does the same thing. Same session, Chris also manually restored the ID column's compound-label formula in the live sheet (see the "spilling array formulas" note above) — this app's own writers never depended on that formula (sheet_write.py always wrote the label as a plain value), but AppSheet is still a second, uncoordinated writer today, so a fresh AppSheet-added row's formula can still go missing until AppSheet is actually retired (backlog item #11).

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
6. ~~Player add from Twitter/X~~ — done 2026-06-30, then revised same night to match the live AppSheet form. New "Add Player" tab, second in the tab bar (Field Tool, Add Player, Post-Event, Tournament Builder, Schedule Refresh, Admin). Two modes:
   - **Screenshots** (default, multi-file): upload several Twitter/X, FiveTool/PBR, or roster-list screenshots at once, "Extract all" reads each and populates one editable review table (same pattern as Post-Event's New Players table), one write button processes the whole batch. Extraction fields/rules/prompt came from Chris's own refined spec (`twitter_extract.py`'s system prompt), not written from scratch.
   - **Manual entry**: field order, control types, and option lists copied directly from the live AppSheet "High School Players Form" (checked via a real browser session, not guessed) — `st.pills` for By/Class/★/Pos/B-T (AppSheet uses tap-to-select pill buttons for these, not dropdowns or free text), a real dropdown for POS2, plain text for the rest, in AppSheet's exact field order. Added Comms as a tracked field (real column, was missing before).
   Live duplicate detection via the existing locked fuzzy-match — warns and switches to an update instead of silently creating a duplicate. Verified live against a real existing player (Noah Stead) in a browser preview, including the pill-button interactions specifically since `st.pills` was new to this codebase.
   - **Correction, 2026-07-02:** the note above claiming duplicate detection worked "in both modes" was wrong — it only ever warned in Manual entry. The Screenshots batch path had no pre-write duplicate check at all; `build_upsert_op()`'s fuzzy match still correctly turned a re-added existing player into an update (not a duplicate row) at write time, but nothing told the coach that was happening — Chris hit this directly: added two players by screenshot, the second was already on the board, got no notice, "it just said done." Fixed: the batch review table now shows a warning above it listing any row that matches an existing player and what will happen (update, not duplicate) *before* the write, same as manual entry already did; and the post-write success message now names updated players explicitly instead of only showing a count.
7. ~~Recruiting Tools page redesign~~ — done 2026-06-30 (Event Day brand lockup)
8. ~~Google Sheet write-back~~ — done 2026-06-30: `sheet_write.py` + `apps_script/Code.gs`, used by both Post-Event and Add Player
9. **Extension download + scrape-instructions page** — inside the existing app
10. **Capabilities one-pager PDF** — for sharing with other programs
11. **App consolidation** — Chris wants one umbrella app: Big Board view, full player list, schedule, instead of 3 separate apps (this Streamlit tool, navy-event-day, and a legacy AppSheet recruiting-board app). Lean toward expanding this app with Big Board/Player List tabs and retiring AppSheet; keep navy-event-day separate (built for one-handed mobile use at a tournament, which Streamlit doesn't do well).
   - 2026-06-30 update: Chris is now thinking even bigger than this — one site for the *whole* coaching staff (recruiting + visit scheduling + budget + full depth chart, which currently all live as different tabs in the recruiting spreadsheet), plus folding in a separate player-analysis website he built independently. This item may get superseded by that larger scope — ask Chris before assuming which version is current.
   - **2026-07-01: first real step shipped — Board tab.** Browse/filter/sort (class, position, tier, state, name search) + tier update + note, reusing `db_loader.all_players()` and `sheet_write.build_tier_update_op()`/`build_note_update_op()`. Explicitly NOT done: AppSheet isn't retired (coaches still use it daily — that's Chris's call, after this is verified in real use), and the calendar/questionnaire-status/interactive-lineup pieces of the bigger vision (2026-06-30 update above) are separate, not-yet-scoped passes. Nav regroup into Event Tools / Players sections (see App Tabs above) is the next planned step, deferred on purpose so this shipped first.
12. ~~Post-event: write ratings straight to DB after review~~ — done and wired 2026-06-30. Single "Write to Recruiting Sheet 2.0" button (not a separate dry-run-then-confirm flow — Chris didn't want that), `st.status()` progress, verified with real writes against production data. Real bugs found and fixed the same night in production use: corrupted row (formula/column mixup), missing Date Added/By/Notes, hardcoded column numbers going stale when Chris restructured the sheet, and Apps Script falsely reporting write success — see `sheet_write.py` and `apps_script/Code.gs` docstrings for the full history. Not yet done: a full click-through with a real GoodNotes photo through the current UI.
14. **App-wide visual redesign** — done 2026-06-30 (first pass): Inter + Fraunces (serif on headers/brand only, for a more premium/editorial feel per direct feedback that Inter alone still read as generic), refined buttons/tabs/metrics/tables/file-uploader via injected CSS in `app.py`, goal was "look like it costs $20k/year, not JV." Kept the existing navy/gold brand. Room for more polish later (backlog item 2, PDF visual redesign, is separate — that's the actual roster PDF output, not the web app chrome).
13. **"Seen" column becomes an append-only history** — done 2026-06-30, Chris chose: comma-space-delimited list in the existing single Seen cell (e.g. "WWBA 16U 2026, NPI 2026"), never overwritten, only appended, with a dedupe guard against re-appending the same event twice. Implemented in `sheet_write.py`, verified. Other fields (tier, state, HS, summer team, etc.) follow Chris's rule: overwrite only if a new value was actually captured this round and differs from what's there — never blank out something just because this round didn't mention it.
15. **Travel program tier list should live in the spreadsheet, not `travel_programs.json`** — brain-dumped 2026-06-30, explicitly NOT to be built yet ("don't execute this, just add it to the future list"). Chris's reasoning: the tier assignments change over time (as programs rise/fall in value each summer/year), and right now that only lives in a static backend JSON file he can't edit himself — it should be connected to an actual sheet tab he can maintain directly. Needs a real design pass: which tab, how `org_tier.lookup_org_tier()` reads it (still cached/local copy, or live lookup like the recruiting sheet), whether it becomes another `sheet_sync.py`-style pull.
16. **Show a player's travel PROGRAM name on the board, not the specific event-team name they happened to play under that day** — brain-dumped 2026-06-30 alongside item 15, same explicit instruction not to build yet. Chris's framing: when a player gets added (post-event or Add Player), the "Summer Team" field currently holds whatever team name was on the roster/screenshot for that one event (which can be a temporary all-star/scout-team name), not the player's actual home travel org. Needs matching the raw extracted/event team name against a known travel-org database — closely tied to item 15 (needs an actual maintained, matchable list) — and a decision on what happens when there's no match: Chris's own words were "if it's not in it, add them to the database," meaning new travel orgs should get captured, not silently dropped. Not scoped further than that; a real design pass needed before building.

---

## Important Engineering Rules
- **Explicit `color`, not inherited, on any custom button/text styling.** Found 2026-07-02: the global primary-button CSS set `background: #14233B !important` but never set `color`, relying on inherited/default text color for white text. That assumption silently broke somewhere (Chris reported black text on navy background) - the Board tab's popover is a portaled/detached part of the DOM tree (confirmed earlier the same day while debugging pill CSS), and portaled content doesn't reliably inherit the same cascade as the main tree. Fixed by hardcoding `color: #FFFFFF !important` on both the base and `:hover` primary-button rules, plus added `[data-testid^="stBaseButton-primary"]` alongside the original `[kind="primary"]` selector (the real testid, confirmed via DOM inspection the same day) so the rule doesn't depend on a single selector matching. Verified: Field Tool's "Generate PDF" button now computes `color: rgb(255,255,255)` on `background: rgb(20,35,59)`.
- **Don't put imports inside `if`/state-gated blocks in app.py.** Found and fixed 2026-07-01: `import pandas as pd` lived inside `if "tb_pdf" in st.session_state:` (Tournament Builder) and `if "pe_stats" in st.session_state:` (Post-Event) — both only true after that specific tab had already produced output *in the current session*. A coach going straight to Add Player → screenshots without visiting those tabs first hit `NameError: name 'pd' is not defined` at the `pd.DataFrame(ap_batch_rows)` call. Streamlit reruns the whole script top-to-bottom on every interaction and executes every `with tabX:` block regardless of which tab is visually active, so any import needed by more than one tab belongs at the top of the file, unconditional — not re-declared locally "just in case." Fixed by moving `import pandas as pd` to the top-level imports and removing the three local copies (two pre-existing, one added the same session while building Board).
- **Streamlit Cloud `ImportError: cannot import name X` pointing at a name that genuinely exists in the pushed code** is almost always a stale/incomplete deploy, not a code bug. Confirmed 2026-07-02: Chris hit `ImportError` on `from db_loader import all_players` right after a push; `git fetch` + `git diff HEAD origin/main` showed zero drift and the function was exactly where expected in the pushed commit, and a fresh local `streamlit run` reproduced nothing. Streamlit Cloud's auto-redeploy-on-push doesn't always fully complete/restart cleanly. Fix is on the Streamlit Cloud side, not this repo: **Manage app → Reboot app**. Verify the actual pushed commit matches `origin/main` and compiles clean *before* touching the code — don't start guessing at a code fix for a deploy-infra problem.
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

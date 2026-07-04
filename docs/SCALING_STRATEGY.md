# Scaling Navy Baseball → a Multi-Program Recruiting Platform

_Draft strategy, 2026-07-04. Written to be argued with, not followed blindly._

## Where we are today (be honest about it)

One program (Navy) runs on three surfaces held together with good glue:

- **Event Day** (React/Vercel/Supabase) — the live at-event app. Clean, fast, coach-facing.
- **Roster Tool** (Streamlit) — event prep, PDF books, post-event writeback, the Board. Powerful but single-tenant and Streamlit-flavored.
- **The recruiting workbook** (Google Sheet, **29 tabs**) — the actual system of record: High School Players, Big Board, depth charts by class, 6+ schedule tabs, budget, visit dates, travel programs, form responses, stock text.

The workbook is both the strength (Chris owns it, edits it live, it already works) and the ceiling. It cannot be handed to a second program without either cloning the whole mess or exposing everyone's data to everyone. **The 29-tab sheet is the thing that has to be replaced to scale — not the apps.**

## The core decision: what "the backend" becomes

Recommendation: **a real multi-tenant database (Postgres, via Supabase — we already run it) with the sheet demoted to an import/export format, not the source of truth.**

Why Supabase Postgres specifically:
- We already use it (Event Day). No new vendor, no new bill, one auth system.
- Row-Level Security gives per-program data isolation for free — Navy sees only Navy, Program X sees only X, off the same tables.
- It speaks both SQL (for us) and REST/realtime (for the apps) with no middle layer.
- A Google Sheet can still be generated _from_ it on demand for any coach who wants their familiar grid — so nobody loses the spreadsheet they like, it just stops being load-bearing.

The mental model shift: **the sheet becomes a view, not the database.** Coaches who love the grid keep a grid (synced, read-mostly). The database underneath is clean, typed, and shared-safe.

## Target data model (the clean core the 29 tabs collapse into)

Six real tables replace the tab sprawl:

| Table | Replaces (today's tabs) | Notes |
|---|---|---|
| `programs` | — (new) | one row per school. The tenancy key on everything. |
| `players` | High School Players, Big Board, StarUpdater | one row per prospect, typed columns, no formulas |
| `evaluations` | the ★ ratings + Seen history + notes | append-only; every sighting is a row, not a mutated cell |
| `depth_chart` | 25/26/27/28 Depth tabs, Depth Chart Input | (program_id, class, position, player_id) |
| `events` | Event Lists + the schedule tabs | already half-live in Event Day |
| `visits_budget` | Fall Visit Dates ×3, Recruiting Budget, VisitOffer Checklist | the ops side, one program's calendar + money |

Reference data shared across programs (not per-tenant): `travel_programs` (the tier list), `pbr_rankings`, `stock_text` templates. These are league-wide facts; every program benefits from one maintained copy.

Two design rules learned the hard way this summer, baked in from day one:
1. **No formulas in the system of record.** Every corruption incident traced back to a spilling array formula reacting to a write. Values only; compute in the app.
2. **Evaluations are append-only.** The "Seen" history model (comma-appended, never overwritten) generalizes: never destroy a coach's prior read; stack them with timestamps.

## How another program comes aboard (the transition workflow)

This is the part that sells it. A new program shows up with their board in _their_ format — a Google Sheet, an Excel file, a shared doc, whatever. The onboarding is a wizard, not a migration project:

1. **Upload their board.** One file. We already parse messy tabular data (`db_loader`, the xlsx skill, the post-event photo reader). We map their columns to ours with a preview-and-confirm screen — same "review table before write" pattern the post-event flow already uses, so a coach sees exactly what's landing before it does.
2. **Auto-enrich on import.** The moment their names are in, run the existing public PBR measurables crawl against their board — they instantly get velo/exit-velo/60/pop on their own guys, data most programs don't have. _This is the hook._ They came to move a spreadsheet; they leave with a scouting database.
3. **Their sheet keeps working.** We generate a synced Google Sheet from their new database rows so the coach who lives in the grid still has one. Read-mostly, writes go through the app.
4. **They get the apps.** Event Day and the roster books, scoped to their program, their brand colors, their events.

The migration is intentionally _low-commitment_: they don't abandon their spreadsheet, they get a cleaner one plus everything around it. That's a much easier "yes" than "rip out your system."

## What we can offer that a spreadsheet never will (the pitch, per surface)

- **The one-link event pipeline.** Paste a tournament link → rosters, measurables, a printable book with a venue map, a live phone app. No other program has this. It's the wedge.
- **Live at-event coordination.** Multiple coaches, one board, real-time, tag-who's-attending, AI note-filing. Spreadsheets can't be at a ballpark on five phones at once.
- **Cross-referenced rosters.** Tap any team, see who's already on your board. This is the daily-value feature that keeps them logged in.
- **A board that maintains itself.** Post-event photos → ratings written back, measurables refreshed nightly, rankings updated. The board stops being manual data entry.

## Rollout without breaking Navy

Navy is the live proving ground; don't disrupt it to build the platform.

- **Phase 0 (now):** dual-write. Keep the sheet as source of truth, but start writing every board change into Supabase tables in parallel. Zero user-visible change; we're just building the real database underneath the working system. Low risk, high learning.
- **Phase 1:** flip Navy's _reads_ to Postgres (the Board tab, Event Day cross-ref) while writes still hit both. The sheet becomes a generated mirror. If anything's wrong, the sheet is still there.
- **Phase 2:** onboard **one** friendly second program as a design partner. Everything multi-tenant gets stress-tested by a real outside user before we scale the pitch. Their feedback is worth more than our guesses (see the Board-tab lesson: build against a real user's reaction, not in the abstract).
- **Phase 3:** self-serve onboarding wizard, per-program branding, a real sign-up. Only after Phase 2 proves the model.

**Deploy discipline carries over and gets stricter:** the Streamlit "every push restarts everyone" incident becomes unacceptable at multi-program scale. Platform pieces move to a deploy model where a bad push can't kill a coach mid-entry (Vercel-style atomic deploys, or blue-green). This is a real reason to migrate the Roster Tool's heavy flows (event build, post-event) off Streamlit eventually — not today, but on the roadmap.

## Other cleanups worth doing regardless of scaling

- **Kill the 29 tabs down to the 6 that matter** even for Navy alone — the depth-chart-by-year and dated-schedule tabs are archive material, not live data.
- **One identity system.** Right now there's no login anywhere by design. Multi-tenant needs auth; do it once, in Supabase, and let both apps share it. Coaches log in as themselves, so "By: TR" is automatic, not a dropdown.
- **A single events table** already exists in Event Day; the Roster Tool should read/write the same one instead of its own event-dir files. One source for "what events exist."
- **Retire the AppSheet app** (already half-done) — it's a third writer to the same data and every uncoordinated writer is a corruption risk.
- **Measurables/academics as a provider abstraction.** PBR just removed academic access (2026-07-04); the enrichment layer should treat each source as a plug-in so losing one (or adding FiveTool/Twitter) is a config change, not a rewrite.

## The honest risks

- **Multi-tenant data isolation is unforgiving.** One RLS mistake leaks Program A's board to Program B. This has to be tested adversarially before any second program touches real data.
- **Coaches don't want to learn new software mid-season.** The "keep your spreadsheet" escape hatch isn't a nicety, it's the adoption strategy. Never force the grid-lovers off the grid.
- **Support burden.** One program = Chris texts himself. Ten programs = a support inbox. Scaling the software is easy; scaling the humans behind it is the real cost — price and staff for that, not just servers.

---

_Next concrete step if Chris wants to move: Phase 0 dual-write is buildable now with zero user impact — start writing board changes into Supabase tables alongside the sheet, and watch the clean database assemble itself from real usage over a few weeks before betting anything on it._

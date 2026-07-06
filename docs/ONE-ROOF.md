# Recruiting AI — College Baseball
## (the One Roof multi-program platform)

_v2 blueprint, 2026-07-05 (late night). Supersedes nothing — extends
SCALING_STRATEGY.md (2026-07-04) with Chris's product requirements from
tonight. That doc is the "why Postgres/Supabase"; this one is the "what we
are actually building and in what order."_

## The one-sentence product

One app — phone, tablet, and browser — where a program's staff logs in and
gets their entire recruiting operation: the board (as an app AND as a full
editable spreadsheet view), live event day, roster books, post-event
writeback, and a shared pool of public player data — with every program's
own evaluations sealed off from every other program **and from us**.

## Platform: website that becomes an app

**Recommendation: PWA-first, App Store second — same codebase.**

1. **Now:** Event Day is already a React web app. We grow it into the whole
   product and ship it as a **PWA** (installable from the browser: icon on
   the home screen, full screen, push notifications, stays logged in).
   Coaches "install" it in 10 seconds with no App Store review cycle, and
   desktop/browser access is the same URL. This is how we iterate fast.
2. **Then:** wrap the identical codebase with **Capacitor** and submit to
   the App Store / Play Store when we want the legitimacy of "search
   NavyRecruit in the App Store." One codebase, three surfaces. The App
   Store build is a marketing artifact, not a separate product.

Why not native-first: App Store review adds days to every fix (tonight we
shipped five fixes in five hours — that cadence dies in review queues), and
our coaches already live in Safari/GoodNotes flows.

**"Stays logged in":** Supabase Auth persistent sessions (refresh tokens).
Log in once per device; sessions live for months. Password + optional
magic-link email login for the less password-inclined coach.

## Tenancy model

```
program (tenant)            ← "Navy Baseball", "Program X"
 ├─ members                 ← coaches; one or more ADMINs
 │    role: admin | coach   ← admin invites/removes members, sets config
 │    initials: "TR"        ← auto-stamped on every eval/note they write
 ├─ board (players + evaluations)     ← PRIVATE, RLS-sealed
 ├─ config
 │    rating scale labels   ← default 0.1/1/2/3/4/XX with Navy's meanings,
 │                            each program can rename ("Commit/Priority/…")
 │    travel program tiers  ← seeded from Navy's cleaned list, editable,
 │                            additions allowed (private to the program)
 │    pdf preferences       ← column preset, logo, colors, cover text
 └─ events                  ← their tournaments, books, tags, notes
```

- **Admin flow:** one person creates the program, becomes admin, invites
  staff by email. Members log in as themselves → "By: TR" is automatic,
  never a dropdown.
- **Rating labels:** the *values* stay canonical internally (so tooling
  works for everyone); the *labels and meanings* are per-program config.
- **Travel program tiers:** two-layer. A shared **catalog** of travel
  programs (names, so everyone spells "Canes National" the same way) +
  per-program **tier assignments** seeded from Navy's cleaned list at
  onboarding. Their tiers are theirs; nobody sees how a rival ranks Scout
  Team X.

## The two faces of the board

Same data, two views, both first-class:

1. **The app view** — what Event Day's Board tab becomes: cards, filters,
   position groups, tap-a-player profile. Phone-friendly.
2. **The spreadsheet view** — a full-width, every-column, click-and-type
   editable grid *inside the product* (AG Grid or Glide Data Grid — battle-
   tested React data grids). Sort, filter, multi-select, paste from Excel.
   This is the "traditionalist" answer: it *feels* like their sheet, but
   it's typed, formula-free, and can't be corrupted by a stray paste.
   - **No more text-vs-number stars, no array formulas, no hidden columns**
     — every data-corruption incident this summer came from the sheet
     being both UI and database. The grid is UI; Postgres is the database.
   - Optional **Google Sheet export** (one tap, read-only snapshot) for
     anyone who wants to take the grid to Sheets — an export format, never
     the system of record.

**Own-opinion vs public-fact columns (Chris confirmed the model 2026-07-06
night):** the board table stores ONLY the program's own opinions — tier,
notes, Seen, tags, contact history. Public facts (commitment, academics,
measurables, ranks, links) are never written into any tenant's board:
every view (grid, app, PDF, schedule chips, big board) JOINS them live
from public_players by identity hash at render time. One overnight scrape
catches a commitment → every tenant's every surface shows it on next
render, zero propagation jobs. The commitment write-back in
MASS-EVENT-SWEEP.md is only the bridge for the Google-Sheet era (Navy,
pre-Phase-1); born-in-Postgres boards get this by construction. Standing
rule: a coach's manually-entered value that CONFLICTS with the pool shows
his value + a "pool disagrees" flag — coach opinion outranks the crawler
on his own screen, always.

## Event Day: three tabs per event (Chris 2026-07-06 night)

Opening an event offers three pages, matching the three ways coaches
actually work an event:

1. **Schedule** — what exists today (game cards, tags, DK links, venue
   maps, mini-rosters, player cards).
2. **Rosters** — every team's full roster as a browsable in-app table:
   the event website's roster page but with our spin — board marks/tiers,
   metrics, academics, rank/commit chips, profile links, and tap-a-kid →
   player card (rating + notes into the system). Mostly assembled from
   shipped parts: the full-event roster JSON is already parsed per event,
   the row renderer is the existing mini-roster component, board cross-ref
   already merges, the card already attaches to roster rows. Add a team
   index + event-wide player search.
3. **Book PDF** — the existing in-app download (routes to GoodNotes on
   iPads) for the annotate-then-upload crowd.

Phone-only coach: tabs 1+2 + player card. iPad coach: tab 3 + post-event
upload. Both funnel into the same backend, and both see the results at
the next event.

The Schedule tab renders only when the event HAS a schedule —
schedule-less events (emailed-PDF showcases, camps, one-offs from the
lane-3 wizard in MASS-EVENT-SWEEP.md) open straight to Rosters + Book.
Events list shows a type chip per event: tournament / showcase / camp /
custom.

## Confidentiality: sealed from each other AND from the operator

This is the make-or-break feature since we are a competitor to every
customer. Three layers, honestly described:

1. **Program-to-program isolation — absolute, enforced by the database.**
   Postgres Row-Level Security on every tenant table: a Program X session
   physically cannot SELECT a Navy row. Tested adversarially before any
   second program touches real data (an automated test suite that logs in
   as X and attempts to read Navy — red team our own RLS).
2. **Operator blindness — engineered, then contractual.**
   - The public-data pool (below) joins on **hashed identity keys**
     (sha256 of normalized `name|state|grad`), so cross-tenant tooling
     (enrichment, dedup checks) runs without any human-readable names
     crossing tenant boundaries.
   - Admin/service-role access is **audit-logged** (who queried what,
     when) and the log is visible to program admins — they can see we
     never looked.
   - Support access to a tenant's data requires the tenant admin to grant
     a time-boxed support session (a button they click), not standing
     access.
   - What we do NOT promise: true zero-knowledge encryption. Server-side
     features (PDF books, enrichment, the AI tagger) need to read names to
     work. The honest promise is *engineered blindness + auditability +
     contract*, and we say exactly that in writing (see DATA-PRIVACY.md).
3. **The signed agreement** — a plain-English data agreement every program
   gets: their evaluations are theirs, we never view or use them, no
   cross-tenant visibility ever, audit logs prove it, and they can export
   everything and delete their tenant at any time. Draft in DATA-PRIVACY.md.

## The shared public-data pool (the moat)

One league-wide `public_players` store, maintained centrally, readable by
every tenant:

| Data | Source | Already built? |
|---|---|---|
| PBR measurables (velo, EV, 60, pop) | public profile crawl | ✅ crawler + checkpointing |
| PBR national/state rankings | public rankings pages | ✅ tonight's in-page pull |
| PG ranks | event roster scrapes | ✅ |
| Academics (GPA/SAT/ACT) | FiveTool harvest + cache waterfall | ✅ academics.json → table |
| Commitments | PBR/PG/rankings | ✅ |

Tenants' boards JOIN to the pool by identity hash — every program gets
enrichment on *their* guys without their guys being visible to anyone.
Navy's 1,365-player academics cache and full crawl history seed the pool on
day one; every event any tenant runs grows it for everyone. **The pool is
the network effect: each new program makes the product better for all.**

## Onboarding: the Claude-assisted one-time transition

The wizard, upgraded with what we learned doing this by hand all summer
(Hoover recovery, Sheet 2.0 migration, the text-star hunt):

1. **Upload the board** (Google Sheet link, xlsx, CSV — any shape).
2. **Claude maps and cleans it** — one AI-assisted pass that does what we
   did manually for Navy: map their columns to ours, flag junk ratings
   ("/", "4!"), find duplicates, normalize text-vs-number fields, convert
   formula columns to values, split combined fields. Output = a
   **preview-and-confirm table** (the post-event review pattern): the coach
   sees every row exactly as it will land, fixes anything inline, taps
   Import. Nothing writes without their eyes on it.
3. **Instant enrichment** — the moment their names land, the pool attaches
   measurables/rankings/academics to everyone it knows. They uploaded a
   spreadsheet; they get back a scouting database. *This is the demo
   moment.*
4. **Seeded config** — Navy's cleaned travel-program tier list, default
   rating labels, a starter PDF preset. Everything editable.

Tenant #2 (Chris's friend) runs the same-style sheet as Navy — his import
is the easy case, which is exactly right for a design partner: we validate
the wizard's happy path with him, then harden it on messier boards.

## PDF customization

Per-program: logo + program name on cover and page headers, color accents,
column preset (navy/classic/custom picks from the existing preset system),
cover text. The book pipeline already supports presets and custom column
lists — this is config plumbing, not new rendering.

## Instructions for everything

- **In-app**: a "?" on every screen opening the relevant how-to (short,
  screenshot-led, written once per feature as we port it).
- **The runbook**: the "running an event solo" guide we already wrote for
  Navy becomes the template — one per workflow (new event, event day,
  post-event, board upkeep, admin/member management, board import).
- Docs live in the product (a /help route), not a PDF nobody opens.

## What replaces what (migration map)

| Today | Under one roof |
|---|---|
| Event Day app | grows into THE app (it's already multi-event, Supabase, deployed right) |
| Streamlit Roster Tool | its flows port into the app one at a time: Board → post-event → event builder → PDF builder. Streamlit retires last. |
| Recruiting Sheet 2.0 (29 tabs) | 6 Postgres tables + the in-app grid; optional read-only Sheets export |
| Apps Script write endpoint | direct Postgres writes through the app (auth'd, typed, per-op resilient by construction) |
| AppSheet | already retired ✅ |
| Public gviz/export reads | RLS'd REST — no more link-shared sheet holding minors' data |

## Phase 0 status — Mon Jul 6 (foundation day): DONE

Executed 2026-07-06 while Boston/WWBA ran, touching zero coach surfaces:

- **Schema deployed** to production Supabase (all 10 platform tables + RLS
  + a `feedback` table). Three bugs found and fixed pre-deploy — see the
  header of `supabase/platform_schema.sql` (that file is now the
  AS-DEPLOYED schema): sha256→pgcrypto digest, members-policy RLS
  recursion, cross-tenant player_id references in evaluations/depth_chart.
- **public_players seeded: 11,127 players** (6,422 measurables, 1,364
  academics, 380 nat + 2,645 state PBR ranks, 966 PG ranks, 251 commits)
  from the 3 live event rosters + academics.json + pbr_rankings.pkl.
  Re-runnable: `supabase/seed_public_players.py`. travel_programs
  catalog seeded (142 names).
- **Adversarial RLS suite GREEN: 27/27** (`supabase/rls_suite.py`,
  fixtures in `supabase/rls_fixtures.sql` — two rls-test-* tenants).
  The tenant-#2 gate is already satisfied.
- **Feedback button + crash beacon** built in navy-event-day (commit
  pending deploy window); Sentry wired behind VITE_SENTRY_DSN.
- Supabase **Pro confirmed** (org shows PRO). Still on Chris: Sentry
  account/DSN, attorney call, Nate text.

## Rollout — ACCELERATED (Chris 2026-07-05 night: "I want to run this now.
## I need to beat the competition to market.")

Key insight that unlocks speed: the original "freeze during event week"
protected the surfaces coaches USE. Additive work — new tables, auth, new
routes, the wizard — touches none of them. So Phase 0 runs **during** the
event week, in parallel with event support.

- **Mon–Tue Jul 6–7 (foundation):** deploy `platform_schema.sql`
  (additive), Supabase → Pro ($25/mo: daily backups, no pausing — required
  before anyone else's data), Sentry error tracking + in-app feedback
  table, seed `public_players` from the existing caches (academics.json,
  crawls, rankings pkl). Org accounts + LLC/entity question to Chris.
- **Wed–Thu Jul 8–9 (tenancy):** Supabase Auth in Event Day (Navy staff
  get logins; "By: TR" from identity), program-scoped events + board API,
  import-wizard MVP. The friend runs the SAME sheet format as Navy —
  `db_loader` already parses it, so his import path is literally built.
- **Fri–Sat Jul 10–11 (tenant #2 sandbox):** friend's board imported into
  a sandbox program; instant enrichment demo; books + one-link pipeline run
  for HIS program; **adversarial RLS test suite green before any real
  data.** His post-event writes go straight to Postgres — no sheet, no
  Apps Script; his stack is born clean.
- **Sun–Mon Jul 12–13 (handoff):** data agreement signed (attorney pass is
  the one external dependency — a mutual NDA + the DATA-PRIVACY draft
  bridges if the attorney is slow), logins delivered. **Friend starts.**
- **Rest of July:** his feedback + Navy dual-write (board changes mirror
  into Postgres). In-app grid view ships. Navy reads flip when stable.
- **Fall:** PWA install polish, Capacitor App Store build, Claude Design
  pass, self-serve onboarding, pricing.

Honest risks of the compressed path: attorney timing; build hours compete
with live event support during WWBA week; the friend's first weeks run on
Event Day + books + wizard (Streamlit's flows port later — he never sees
Streamlit at all).

## Feedback, errors, and the improvement loop

- **In-app "Send feedback" on every screen** → `feedback` table
  (program, member, screen, text, optional screenshot) + instant push to
  Chris (email/webhook). Doubles as the per-tenant feature-request backlog.
- **Sentry** (free tier) in the app + serverless functions: every crash
  reports itself with stack, device, and tenant before the coach even
  texts.
- **Uptime monitor** (UptimeRobot free) on the app + board/tag APIs.
- **A changelog screen** — coaches see the product moving; momentum is a
  retention feature.

## Storage (scalable from day one)

- **Stay Supabase Postgres + Vercel** — right tools, already proven, one
  bill each. Upgrade Supabase to **Pro** before tenant #2 (backups!).
- **PDFs and photos move to Supabase Storage buckets**, not base64 rows —
  tonight's book-push statement timeouts (57014) are the symptom; Storage
  is CDN-served, cheaper, and size-unbounded.
- **Backups:** Pro dailies + a weekly `pg_dump` shipped off-site.
- **Org accounts** for Vercel/Supabase/GitHub under the company, not
  Chris's personal logins — cheapest to fix now, painful at 10 tenants.

## Name & legal protection (asked 2026-07-05; DECIDED 2026-07-06)

**DECIDED (Chris, 2026-07-06): company = "Bosco Technology", product =
"Recruiting AI — College Baseball".** Two-layer naming is the right
structure: the LLC/trademark/contracts live under Bosco Technology (a
distinctive, protectable mark), while the product name stays descriptive
and swappable per sport. Domain check 2026-07-06: **boscotechnology.com
AVAILABLE** (grab it), boscotech.io / recruitingai.io / getrecruitingai.com
also open; recruitingai.com + recruiting-ai.com taken. Sentry org already
created under `bosco-technology` — the name is in use.

**"Recruiting AI — College Baseball"** — workable launch name; the
`— <Sport>` suffix scales exactly as intended (Football, Hockey, Softball).
Eyes open on the tradeoffs: it is *descriptive*, which makes it a weak
trademark (descriptive marks get refused or land on the Supplemental
Register) and "recruiting AI" collides with a crowded HR-tech phrase in
search results and app stores. Verdict: launch privately under it now —
naming must not delay tenant #2 — and before PUBLIC launch do the
30-minute check: USPTO TESS search, domain grabs, App Store search test;
consider a coined brand ("the product formerly known as…" is cheap before
you have customers, expensive after).

**Patents: no (for now).** Nothing here clears the novelty bar —
multi-tenant SaaS, data aggregation, and AI-assisted import are prior art
everywhere, and post-*Alice* software patents are weak, slow (2–3 years),
and expensive ($15–30k+). The real moats, in order: **speed to market, the
shared data pool (network effect), the trademark (~$350/class — worth
filing), automatic copyright on the code, the signed data agreement, and
trade-secret treatment of the pipelines.** A ~$2–3k provisional buys
12 months of "patent pending" as marketing if an attorney pushes for it —
ask when the data-agreement attorney is already on the phone.

**Entity:** form the LLC before holding another program's data or money.
Same attorney call.

## Open decisions for Chris (the real forks)

1. **Name/brand** for the platform (it stops being "Navy Baseball" the
   moment tenant #2 signs — Navy becomes customer #1 of the product).
2. **Design-partner terms** for tenant #2: free-for-feedback? founding-
   customer price? This shapes the contract draft.
3. **App Store timing**: PWA-only through the fall, or push for App Store
   presence before next spring's recruiting cycle?
4. **Who hosts**: today everything runs on Chris's personal Vercel/
   Supabase/GitHub. A platform with customers wants its own org accounts
   (clean billing, no personal-account risk). Cheap to do early.

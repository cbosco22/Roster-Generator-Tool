# One Roof — the Multi-Program Recruiting Platform

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

## Rollout (real dates)

- **This week (Jul 6–12): freeze.** Boston/Mattingly/WWBA run on what we
  have. Zero architecture changes during events. (Tonight = blueprint,
  schema, agreement drafts only.)
- **Phase 0 (Jul 13–20): the schema goes live, dual-write starts.**
  `supabase/platform_schema.sql` deploys alongside the existing tables;
  every board write (post-event, Add Player, Board edits) mirrors into
  Postgres. The sheet stays source of truth; the real database assembles
  itself from live usage. Auth ships (Navy staff get logins; "By: TR"
  becomes automatic).
- **Phase 1 (late Jul): Navy reads flip.** Board tab + Event Day cross-ref
  read Postgres. Sheet becomes a generated mirror. The in-app grid view
  ships here — Chris lives in it for two weeks and hates/loves it into
  shape.
- **Phase 2 (Aug): tenant #2.** The friend's program onboards via the
  wizard with Claude-assisted import, on the signed data agreement, after
  the adversarial RLS test suite passes. Their feedback drives a month of
  polish.
- **Phase 3 (fall): the roof widens.** PWA install flow, per-program
  branding, self-serve onboarding, Capacitor App Store build, the Claude
  Design pass over every surface, pricing.

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

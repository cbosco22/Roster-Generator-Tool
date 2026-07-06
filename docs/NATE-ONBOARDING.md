# Tenant #2 onboarding runbook — Nate Cole (Harvard)

_Target: logins in his hands by **July 13**. Written 2026-07-06, the day
the foundation went live. Owner of each step in brackets._

## Already done (2026-07-06)

- Platform schema LIVE in production Supabase — 11 tables, RLS everywhere,
  evaluations append-only, feedback insert-only.
- `public_players` pool seeded: **11,127 players** (6,422 with PBR
  measurables, 1,364 academics, 3,025 PBR ranks, 966 PG ranks) + 142-name
  travel catalog. His board enriches the moment it lands.
- **Adversarial RLS suite 27/27 green** (`supabase/rls_suite.py`) — the
  contractual "sealed from each other and from us" claim is now a tested
  property, rerunnable before his real data imports.
- Coach sign-in + identity context built into Event Day (opt-in, not yet
  deployed); feedback button + crash beacon + Sentry DSN wired.
- Company/product naming locked: **Bosco Technology / Recruiting AI —
  College Baseball**.

## Remaining, in order

1. **[Chris — one tap]** Run `supabase/navy_program.sql` in the SQL editor
   (creates the Navy Baseball tenant row + travel tiers).
2. **[Chris — after games]** Push windows: navy-event-day (feedback +
   sign-in, activates Sentry) and Roster-Generator-Tool (docs + SQL +
   suite; restarts Streamlit — evening only).
3. **[Chris — 5 min]** Supabase Auth hygiene before real users:
   dashboard → Authentication → SMTP: built-in sender is 2 emails/hour —
   either wire a real SMTP (Resend free tier) or create users manually
   and skip magic links for week one. Also set Site URL to the app URL
   (magic-link redirects).
4. **[Chris]** Create auth users (Authentication → Users → Add user) for
   himself + staff; run `supabase/link_coach_logins.sql` to attach them
   to the Navy program. Same two steps create Nate's login later.
5. **[me — Wed/Thu]** Import wizard MVP: his sheet is the same format as
   Navy's (`db_loader` already parses it) → map/clean/preview/import into
   `players` under his program, enrichment joins by identity hash.
6. **[me — Fri/Sat]** Harvard sandbox program, his board imported, books +
   one-link pipeline run under his tenant; rerun the RLS suite against
   REAL tenant rows (fixtures stay, suite is idempotent).
7. **[Chris — attorney]** LLC (Bosco Technology), data agreement from
   `docs/DATA-PRIVACY.md`, trademark question in the same call. A mutual
   NDA bridges if the attorney is slow — his data doesn't import until
   something is signed.
8. **[Chris]** Text Nate: what he gets week one is Event Day + roster
   books + the import wizard under his own login — not Streamlit.

## Auth setting to flip at Navy migration (NOT now)

Event Day auth is opt-in so this week's coaches never hit a wall. When
Navy's board reads flip to Postgres (late July), decide whether the app
requires sign-in or keeps a public read-only mode.

## Test fixtures cleanup (whenever)

`rls-test-*@rlstest.gmail.com` users + `rls-test-navy`/`rls-test-rival`
programs are throwaway. Keep them — the suite reuses them — or delete via:
`delete from programs where slug like 'rls-test-%';` +
`delete from auth.users where email like 'rls-test-%';`

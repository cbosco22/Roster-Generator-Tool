# Mass Event Sweep — design draft (2026-07-06)

Broaden the public_players pool from "events Navy happens to attend" to
"every PBR / FiveTool / PG event we can see": automatic event discovery +
an overnight crawl queue, running unattended on a $5 VPS, upserting into
public_players. This is the moat-builder from ONE-ROOF §shared pool —
every tenant's board joins the pool by identity hash, so pool breadth is
directly product value.

Status: DESIGN ONLY. Nothing here is built or deployed. Frozen like
everything else until after the Jul 6–12 events unless Chris pulls it
forward.

## Why now (and the immediate gap it fixes)

The three July event crawls (Boston, Mattingly, WWBA — 9,787 matched
profiles) all finished by Jul 4. X/Twitter capture was added to
pbr_crawler.py on Jul 5 (26e7d5f). **So none of the local pbr_crawl.json
files contain X handles — the links backfill Chris asked for has no
source data.** First job in the sweep queue: re-crawl those same profile
paths (we already have them — no search step needed, just profile fetches)
to harvest X handles and refresh measurables. ~9.8k pages at polite pacing
is one overnight run.

## Architecture

```
discovery (daily, cheap)          worker (overnight, rate-limited)
┌─────────────────────┐   queue   ┌──────────────────────────────┐
│ PBR event calendar  │──────────▶│ sweep_events: pending → done │
│ FiveTool event list │  Supabase │ per-player JSONL checkpoint  │
│ PG event schedule   │           │ upsert → public_players      │
└─────────────────────┘           └──────────────────────────────┘
```

Both halves are one Python process each on the VPS, run by systemd timers.
No headless browser — all three sources serve rosters server-rendered;
requests + BeautifulSoup only (this is what keeps the $5 box sufficient).
Anything that turns out to need JS or a login does NOT run on the VPS —
see the PG section.

### Event discovery (daily, ~09:00 ET)

- **PBR**: state/region event calendar pages (public). Emit events in a
  rolling window: next 21 days (pre-crawl for books) + past 7 days
  (post-event refresh — measurables update after events).
- **FiveTool**: public events index. Same window. FiveTool is also the
  academics source, so its events carry extra weight (Mattingly harvest
  hit 61% GPA coverage via direct profile URLs — the what-works pattern
  from the academics cache).
- **PG**: public tournament schedule (WWBA/BCS etc.). Rosters public;
  academics are NOT (login-gated — see entitlement).

Each discovered event → one row in `sweep_events` (new table):

```sql
create table sweep_events (
  id           bigint generated always as identity primary key,
  source       text not null check (source in ('pbr','fivetool','pg')),
  source_key   text not null,          -- source's own event id/slug
  name         text, url text not null,
  starts_on    date, ends_on date,
  status       text not null default 'pending'
               check (status in ('pending','crawling','done','failed','skipped')),
  priority     int default 0,          -- manual bumps; re-crawls of our own events = high
  attempts     int default 0, last_error text,
  discovered_at timestamptz default now(), crawled_at timestamptz,
  stats        jsonb default '{}',     -- {players, matched, x_handles, gpa_hits}
  unique (source, source_key)
);
-- RLS on, no tenant policies: operator-only, invisible to the API.
```

Discovery is idempotent (`on conflict do nothing`), so re-running it is
always safe.

### Crawl worker (overnight, ~22:00–06:00 ET)

- Pops the highest-priority pending event, sets `crawling`, streams the
  roster, then walks player profiles. Reuses pbr_crawler.py's
  search→resolve→scrape logic (with the two server-filter fixes and the
  X capture) — lifted into a `sweep/` module, not forked.
- **Rate limit: 1 request / 2.5s per source** (sources run interleaved,
  so wall-clock is shared). ~11.5k pages per 8h night per source is the
  ceiling; a WWBA-sized event (5.5k profiles) is one night.
- **Checkpoint**: per-player JSONL on disk exactly like the existing
  crawler (`pbr_checkpoint.jsonl` pattern — resume-from-checkpoint is
  already proven). An event resumes mid-roster after any crash/reboot.
- **Never-retry-real-writes policy applies** (post-event write
  reliability lesson): DB writes are idempotent upserts, and a failed
  write is logged + re-queued, never blind-retried in a loop.
- Politeness: honest UA string, robots.txt respected, hard cap per night
  per source, and a `SWEEP_PAUSE=1` env kill-switch checked between
  requests.

### Writing to public_players

public_players is deliberately not writable through the PostgREST API
(pool_read only). The VPS gets a **dedicated Postgres role**
(`sweep_writer`) with INSERT/UPDATE on public_players + sweep_events and
nothing else, connecting over the Supabase pooler connection string.
Credential lives only in the VPS env file (root-only), never in the repo.
(Alternative — service_role key on the VPS — rejected: it bypasses RLS on
tenant tables; a box that crawls the public internet all night should not
hold a key that can read boards.)

Merge policy (matches the seeder's semantics):
- key = identity_hash (same sha256 formula; states normalized the same
  region-aware way as seed_public_players.py).
- fill-if-empty for scalar fields; **dated measurables: newer date wins**;
  `links` jsonb merges per key (`{"pbr":…, "x":…, "fivetool":…, "pg":…}`);
  `sources` tags every field it touches (provenance is what the
  entitlement gate keys on).
- Players that fail the name|state|grad hash requirements are written to
  the event's `stats` as unmatched, not to the pool (same rule as the
  seeder: unhashable-to-tenants = useless to tenants).

## PG academics + the entitlement flag

Decided 7/6, restated here as the implementation spec:

- PG profile academics are login-gated. **The VPS never logs in
  anywhere** — it crawls anonymous/public pages only. PG-academics
  harvesting runs, when it runs, in Chris's logged-in Chrome session on
  his machine (the sanctioned pattern), producing a file the sweep
  ingests like any other source.
- Storage: academics fields land with `sources.academics = 'pg'`.
- Gate: `program_config.pg_entitled boolean default false`. Pool reads
  move from the bare table to a security-invoker **view** that nulls any
  field whose source tag is `'pg'` unless the reader's program has
  `pg_entitled = true`:

```sql
create view public_players_v as
select identity_hash, name, grad_year, state, position, measurables,
       pbr_rank_nat, pbr_rank_state, pbr_rank_state_code, pg_rank,
       case when sources->>'academics' = 'pg'
                 and not exists (select 1 from program_config pc
                                 where pc.program_id in (select my_programs())
                                   and pc.pg_entitled)
            then null else academics end as academics,
       commit, links, sources, updated_at
from public_players;
```

  Apps read the view; direct table grants get revoked from
  authenticated. (pg_rank stays visible — PG *rankings* are public;
  only login-gated academics are entitled.)
- Wording on the flag ("access to data they've paid for, different
  venue") goes past the attorney on the LLC call before tenant #2 sees
  any pg-sourced field.

## VPS sizing ($5 tier is genuinely enough)

| Resource | Need | $5 box (DO/Vultr/Hetzner ~$4–6) |
|---|---|---|
| CPU | parse HTML, hash names | 1 shared vCPU — fine |
| RAM | requests+bs4, one event in memory | 1 GB (512 MB works; 1 GB = headroom) |
| Disk | checkpoints + logs, rotated | 10–25 GB — fine |
| Bandwidth | ~80 KB/page × ~12k pages/night ≈ 1 GB/night | 500 GB–1 TB/mo — fine |

Explicitly out of scope for this box: headless browsers, PDF book
builds, anything holding tenant data, anything logged in. If a source
breaks server-rendering, that source moves to a laptop-assisted flow
rather than upgrading the box.

Ops: systemd timers (discovery daily, worker nightly), journald + a
heartbeat row in sweep_events stats, and failures surface through the
existing morning health check (it queries `sweep_events where status =
'failed' or (status = 'crawling' and crawled_at is null and started
yesterday)`). No new notification channel.

## Tenant event ingestion — the three lanes (Chris, 2026-07-06 evening)

The coach-facing side of the sweep. Design goal, verbatim intent: a coach
at another program adds an event in a few clicks and has the app live in
a few minutes — book, schedule, and their own board cross-ref — without
ever knowing what a scraper is. All crawling is server-side; no tenant
ever runs tooling locally (today's flow — Chris running pbr_crawler.py /
FiveTool harvest / push_event.py by hand — is the operator bootstrap, not
the product).

**Overlap between tenants is the point, with one privacy rule.** Events
are public facts and get crawled ONCE (`sweep_events` is already unique
on source+source_key); a second program "adding" WWBA is a subscription
to data that already exists — instant for them, free for us. But WHICH
programs subscribed to WHICH events is competitive intel (a rival seeing
Navy's event list = exactly what DATA-PRIVACY promises against), so:

```sql
create table program_events (       -- per-tenant, RLS like players
  program_id uuid references programs(id),
  sweep_event_id bigint references sweep_events(id),
  source     text default 'catalog',  -- catalog | url | pdf
  private_roster jsonb,               -- pdf-lane only (see lane 3)
  added_at   timestamptz default now(),
  primary key (program_id, sweep_event_id)
);
-- policy: program_id in (select my_programs()) — nobody sees another
-- program's subscriptions. sweep_events itself gets a read policy for
-- authenticated (the catalog is shared).
```

**Lane 1 — catalog drop-down (THE default; Chris upgraded it 7/6 late:
crawl EVERYTHING).** Not just discovery — every PBR / FiveTool / PG /
Prospect Select event gets its rosters crawled and loaded, whether anyone
subscribed or not. A coach's whole flow is: pick the source, pick the
event from the list, done — it connects to their database and runs.
Events they don't want, they never click. No coach ever pastes a link in
the normal path, and Chris + Claude own making sure every event has
rosters + rankings before it starts.

What keeps crawl-everything inside a $5 box — split the work:
- **Roster sweep (universal, cheap):** an event's roster pages are ~1
  page per team (~30-60 pages/event). Crawling EVERY event's rosters,
  plus the universal **T-24h final-roster re-crawl** (teams post final
  rosters the day before — this pass is what makes the books right), is
  hundreds of pages a night, not thousands.
- **Profile enrichment (incremental, cached):** per-player profile
  fetches are the expensive part, but the pool caches by identity hash —
  a kid enriched at one event is already enriched at his next five. Order:
  subscribed events first, then event start date; skip players whose pool
  data is fresh (<30 days). Enrichment converges fast: by mid-summer most
  kids at any event are already in the pool.
Subscribed events additionally re-crawl nightly while running
(measurables and DK links move during play).

**"Event not listed?" submit box.** On the event-picker screen. A
submission writes a `sweep_events` row (source='request',
status='triage') with whatever the coach knows (name, source, link if
they have one, or "PDF only"). Triage chain, per Chris: **Claude first**
— a session picks up triage rows (surfaceable via the morning check),
tries to resolve them (find the event on a source, run the crawl, or
route a PDF to lane 3) — **then escalates to Chris** only when blocked
(new source, weird format, needs a login). The coach just sees their
event appear.

**Lane 2 — paste a URL.** Recognized event-URL patterns (PBR/PG/5T)
insert a high-priority sweep_events row; the worker picks it up
immediately (on-demand lane runs at the same polite rate — a ~300-player
event ≈ 15 min). UI shows pending → crawling (n/total) → ready.
Unrecognized domains are rejected with a "send us the link" contact path
rather than crawling arbitrary sites.

**Lane 3 — upload a PDF or spreadsheet** (the PBR Pennsylvania Showcase
case: roster exists only as an emailed file; also camps and one-off
events). Server-side Claude-assisted import — pdf_to_roster.py's
extraction grown into the same preview-and-confirm wizard as the
ONE-ROOF board import: upload → extract → editable preview table →
confirm → event created. Two rules: (a) PDF-sourced rosters are
**tenant-private by default** (`private_roster` on their program_events
row, NOT the shared catalog — the file was given to that program); (b)
players in it are still enriched from the shared pool by identity hash,
so even a PDF-only event comes back with measurables/ranks/links
attached. Schedules ride the same lanes: URL, PDF, or CSV upload.

**Schedule-less events + event types (Chris 7/6 late).** A schedule is
OPTIONAL. An emailed-PDF showcase, a random local event, or a program's
own camp (spreadsheet of names + details) becomes a first-class event:
it shows on the events page with its name and dates, opens to just the
**Rosters** tab and the **Book PDF** download — no Schedule tab — and
the book generator must handle roster-only events (no schedule section).
Every event carries a type chip on the events list:
`tournament | showcase | camp | custom` (`sweep_events.event_type` /
set in the lane-3 wizard). "Northeastern Baseball camp, Jul 20 — open
the roster or download the booklet" is the acceptance test.

Every lane converges: event live in their tenant, book in their branding,
cross-ref against THEIR board, pg-sourced academics gated by
`pg_entitled`. PDF extraction (Claude API) runs in the web app's backend,
not on the crawl box (the VPS stays dumb: fetch, parse, upsert).

## Fourth source: Prospect Select (verified live 2026-07-06)

Chris asked for a look at PS profiles — verified by fetching real pages:

- Platform: `play.ps-baseball.com` (Playbook365). Everything checked is
  **server-rendered and public, no login** — requests+bs4 works, VPS-safe.
- Team/roster pages: `/public/team/details/<event-slug>/<team-uuid>` —
  full roster with grad year, HS + HS coach, city/state, both positions,
  commit, H/T, height/weight (this is already what feeds Boston's
  roster.json), plus links to each player's profile uuid.
- Player profiles: `/public/player-profile/baseball/<uuid>`. PUBLIC:
  player info, commitment, and **live in-game velocities per pitch type**
  (verified: FB 86 / SL 78 / CB 77 on a Boston Classic kid) — in-game
  tournament velo is data PBR profiles don't carry; showcase metrics
  (60, position velos, pop, EV, bat speed, attack angle…) populate when
  the kid has done a PS showcase. MEMBERSHIP-GATED: event video, advanced
  hitting metrics, Scorebook365 game stats. **We scrape public fields
  only — gated PS content is their paid product; if we ever want it,
  that's a license/entitlement conversation like PG academics, not a
  crawl.**
- Name→profile resolution: the player-search page has a public
  autocomplete endpoint; roster pages carry profile uuids directly, so
  event crawls don't need search at all.
- Schema impact: add `'ps'` to the sweep_events source enum, `links.ps`
  in the pool, `sources` tags `ps` per field. Merge rule: PS in-game
  velos land in measurables with dates like everything else.

## Commitment sync to tenant boards (Chris, 7/6)

Every crawl already reads commitments; the pool should push changes OUT,
not just collect them. Nightly after crawls:

1. Diff pass: pool rows whose `commit` changed since last sync (keep a
   `commit_changed_at` timestamp; optionally a small history jsonb).
2. For each tenant, match changed rows to their board by identity hash.
3. Write the commit to the tenant's board — Sheets via the Apps Script
   path for Navy today, Postgres `players` when boards move in-product.
   Write rules carry the hard-won lessons: resolve columns dynamically,
   read back to verify, never blind-retry a real write.
4. **Conflict rule:** if the tenant's cell already has a DIFFERENT
   non-empty value than the pool, don't overwrite — flag it (same diff-
   flag pattern as Event Day refresh) and let the coach decide. Empty or
   matching cells update silently. Every write is logged per tenant.

This is the first case of pool→tenant write-back, so it sets the
pattern (rankings refresh and measurables freshness can ride the same
rail later).

## Adjacent product adds (routed to app backlogs, recorded here 7/6)

- **Google-the-player button**: in Event Day player rows/cards — one tap
  opens a Google search of `"Name" baseball <grad> <state>`, next to
  brand-icon links (PBR / PG / X / PS) drawn from `public_players.links`.
  Pure frontend + pool read; lands in navy-event-day.
- **Inline rating edit from the schedule**: change a kid's rating
  directly on the game card in the schedule view — writes an evaluation
  (append-only, tagger initials) and syncs the board like the existing
  tagger flow. Lands in navy-event-day.
- **Hosted player video as an upcharge**: coaches attach their own
  scouting video to a player; stored in Supabase Storage buckets
  (ONE-ROOF storage section), gated by a billing/entitlement flag —
  first concrete paid add-on. Boundary: **coach-shot/uploaded video
  only; never rehost PBR/PG/PS video** (PS literally sells video
  memberships — rehosting is a legal fight we'd lose and a partner
  bridge we'd burn). Public video links (a kid's X highlight) are links,
  not hosted copies.

## Queue seeding order (first nights)

1. **Re-crawl Boston / Mattingly / WWBA profile paths for X handles**
   (the task this design was born from) — profile fetches only, ~9.8k
   pages, one night. Then backfill `links.x` by identity hash.
2. PBR rankings refresh (already-built flow, moves off the laptop).
3. Discovery goes live and the window fills organically.

## Open decisions for Chris

- **Provider**: Hetzner CX22 (~€4.5) / DigitalOcean $6 / Vultr $5 — any
  works; pick by billing preference. (Recommend Hetzner on price, DO if
  he wants the friendlier console.)
- **DB credential**: dedicated `sweep_writer` role as specced (recommend)
  vs service key on the box (rejected above, but it's his call).
- **X-handle re-crawl timing**: wait for the VPS, or run one overnight
  pass from the laptop this week (crawler already does it; laptop must
  stay awake).
- **PG crawl posture**: rosters-only from the VPS now, or hold all PG
  crawling until the attorney call clears the entitlement wording.

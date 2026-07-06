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

**Lane 1 — catalog drop-down.** Weekly discovery already builds the
catalog of every upcoming PBR/PG/FiveTool event. Freshness is
demand-driven, not size-guessed: **any event with ≥1 subscriber is
auto-re-crawled the night before it starts, and nightly while it runs.**
No subscriber = no refresh spend.

**Lane 2 — paste a URL.** Recognized event-URL patterns (PBR/PG/5T)
insert a high-priority sweep_events row; the worker picks it up
immediately (on-demand lane runs at the same polite rate — a ~300-player
event ≈ 15 min). UI shows pending → crawling (n/total) → ready.
Unrecognized domains are rejected with a "send us the link" contact path
rather than crawling arbitrary sites.

**Lane 3 — upload a PDF** (the PBR Pennsylvania Showcase case: roster
exists only as an emailed file). Server-side Claude-assisted import —
pdf_to_roster.py's extraction grown into the same preview-and-confirm
wizard as the ONE-ROOF board import: upload → extract → editable preview
table → confirm → event created. Two rules: (a) PDF-sourced rosters are
**tenant-private by default** (`private_roster` on their program_events
row, NOT the shared catalog — the file was given to that program); (b)
players in it are still enriched from the shared pool by identity hash,
so even a PDF-only event comes back with measurables/ranks/links
attached. Schedules ride the same lanes: URL, PDF, or CSV upload.

Every lane converges: event live in their tenant, book in their branding,
cross-ref against THEIR board, pg-sourced academics gated by
`pg_entitled`. PDF extraction (Claude API) runs in the web app's backend,
not on the crawl box (the VPS stays dumb: fetch, parse, upsert).

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

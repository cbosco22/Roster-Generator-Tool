-- ============================================================
-- ONE ROOF: multi-tenant platform schema (DRAFT — NOT DEPLOYED)
-- Written 2026-07-05 alongside docs/ONE-ROOF.md. Deploys in
-- Phase 0 (after the Jul 6-12 event week). Additive only: touches
-- nothing Event Day uses today (events, event_files stay as-is;
-- events gains program_id in Phase 0 via the ALTER at the bottom).
--
-- Design rules (paid for in blood this summer, see ONE-ROOF.md):
--   * values only, no formulas — the DB is never also a UI
--   * evaluations append-only — never destroy a coach's prior read
--   * RLS on EVERY tenant table — isolation enforced by Postgres,
--     not by app code remembering to filter
--   * public pool joins on identity HASH — cross-tenant tooling
--     never moves human-readable names across tenant lines
-- ============================================================

-- ---------- tenancy ----------
create table programs (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,                 -- "Navy Baseball"
  slug        text unique not null,          -- "navy"
  colors      jsonb default '{}',            -- {"primary":"#14233B","accent":"#C5A253"}
  logo_url    text,
  created_at  timestamptz default now()
);

create table members (
  id          uuid primary key default gen_random_uuid(),
  program_id  uuid not null references programs(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  role        text not null check (role in ('admin','coach')),
  initials    text not null,                 -- "TR" — stamped on evals/notes
  display_name text,
  created_at  timestamptz default now(),
  unique (program_id, user_id),
  unique (program_id, initials)
);

-- current user's program memberships (used by every policy below)
create or replace function my_programs() returns setof uuid
language sql stable security definer set search_path = public as
$$ select program_id from members where user_id = auth.uid() $$;

-- ---------- per-program config ----------
create table program_config (
  program_id  uuid primary key references programs(id) on delete cascade,
  -- canonical rating values stay fixed; labels/meanings are theirs
  rating_labels jsonb not null default
    '{"0.1":"Committed","1":"Offer","2":"High Follow","3":"Follow","4":"Need to See","XX":"Pass"}',
  pdf_prefs   jsonb default '{}',            -- preset, cover text, columns
  created_at  timestamptz default now()
);

-- shared CATALOG of travel programs (names only — spelling authority)…
create table travel_programs (
  id    uuid primary key default gen_random_uuid(),
  name  text unique not null
);
-- …with PRIVATE per-program tier assignments (seeded from Navy's list)
create table program_travel_tiers (
  program_id  uuid references programs(id) on delete cascade,
  travel_id   uuid references travel_programs(id) on delete cascade,
  tier        text not null,                 -- "1" | "2" | "3" …
  primary key (program_id, travel_id)
);

-- ---------- the board (tenant-private) ----------
create table players (
  id          uuid primary key default gen_random_uuid(),
  program_id  uuid not null references programs(id) on delete cascade,
  first_name  text not null,
  last_name   text not null,
  grad_year   int,
  pos         text, pos2 text, bats_throws text,
  hometown    text, state text,
  high_school text, summer_team text,
  academic    text,                          -- program's own academic notes
  email       text, phone text,
  commit      text,
  -- join key to the public pool; app-computed, never contains the name
  identity_hash text generated always as
    (encode(sha256(lower(trim(first_name) || ' ' || trim(last_name))
      || '|' || coalesce(upper(state),'') || '|' || coalesce(grad_year::text,''))::bytea, 'hex')) stored,
  created_by  uuid references members(id),
  created_at  timestamptz default now(),
  updated_at  timestamptz default now()
);
create index players_program on players(program_id);
create index players_identity on players(identity_hash);

-- append-only: every rating/sighting/note is a ROW (the "Seen" model,
-- generalized). Current rating = latest eval with a rating set.
create table evaluations (
  id          uuid primary key default gen_random_uuid(),
  program_id  uuid not null references programs(id) on delete cascade,
  player_id   uuid not null references players(id) on delete cascade,
  member_id   uuid references members(id),   -- who (initials render from here)
  event_name  text,                          -- "Hoover 16u 2026" (the Seen entry)
  rating      text check (rating in ('0.1','1','2','3','4','XX') or rating is null),
  note        text,
  created_at  timestamptz default now()
);
create index evals_player on evaluations(player_id, created_at desc);

create table depth_chart (
  program_id  uuid references programs(id) on delete cascade,
  grad_year   int not null,
  position    text not null,
  slot        int not null,
  player_id   uuid references players(id) on delete cascade,
  primary key (program_id, grad_year, position, slot)
);

-- ---------- the shared public pool (league-wide, read-only to tenants) ----------
-- Seeded from Navy's crawls/caches; grown by every event any tenant runs.
-- No tenant evaluations ever enter this table — public facts only.
create table public_players (
  identity_hash text primary key,            -- same hash formula as players
  name          text not null,               -- public data is public
  grad_year     int, state text, position text,
  measurables   jsonb,                       -- {"FB":"88","EV":"95.4",...} + dates
  pbr_rank_nat  int, pbr_rank_state int, pbr_rank_state_code text,
  pg_rank       int,
  academics     text,                        -- "GPA 3.9 · SAT 1280" (public/harvested)
  commit        text,
  sources       jsonb default '{}',          -- provenance per field
  updated_at    timestamptz default now()
);

-- ---------- row-level security ----------
alter table programs             enable row level security;
alter table members              enable row level security;
alter table program_config       enable row level security;
alter table program_travel_tiers enable row level security;
alter table players              enable row level security;
alter table evaluations          enable row level security;
alter table depth_chart          enable row level security;
alter table travel_programs      enable row level security;
alter table public_players       enable row level security;

-- members see their own programs; admins manage membership
create policy prog_read  on programs  for select using (id in (select my_programs()));
create policy mem_read   on members   for select using (program_id in (select my_programs()));
create policy mem_admin  on members   for all
  using (program_id in (select program_id from members
                        where user_id = auth.uid() and role = 'admin'));

-- tenant tables: full access within your own program, nothing outside it
create policy cfg_rw    on program_config       for all using (program_id in (select my_programs()));
create policy tiers_rw  on program_travel_tiers for all using (program_id in (select my_programs()));
create policy players_rw on players             for all using (program_id in (select my_programs()));
create policy depth_rw  on depth_chart          for all using (program_id in (select my_programs()));

-- evaluations: readable in-program; INSERT only (append-only — no update/
-- delete policy exists, so PostgREST cannot mutate history)
create policy evals_read   on evaluations for select using (program_id in (select my_programs()));
create policy evals_insert on evaluations for insert with check (program_id in (select my_programs()));

-- shared reference: readable by any signed-in member; write via service role only
create policy travel_read on travel_programs for select using (auth.uid() is not null);
create policy pool_read   on public_players  for select using (auth.uid() is not null);

-- ---------- operator-blindness audit ----------
-- Every service-role/admin read of tenant tables is logged; program admins
-- can SELECT their own program's audit rows and see nobody ever looked.
create table access_audit (
  id          bigint generated always as identity primary key,
  program_id  uuid,
  actor       text not null,                 -- 'service_role' | support session id
  action      text not null,
  detail      jsonb,
  at          timestamptz default now()
);
alter table access_audit enable row level security;
create policy audit_read on access_audit for select
  using (program_id in (select program_id from members
                        where user_id = auth.uid() and role = 'admin'));

-- ---------- Phase 0 ALTERs (existing Event Day tables) ----------
-- run when dual-write begins; null program_id = legacy Navy rows
-- alter table events add column if not exists program_id uuid references programs(id);

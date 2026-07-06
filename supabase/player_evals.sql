-- player_evals: in-app player evaluations from Event Day (Chris 2026-07-06:
-- "add a note on a single kid that then goes into our system... if anything
-- adjusts for a kid, append that he was seen at that event").
--
-- The phone-first replacement for the GoodNotes-on-the-PDF loop: a coach
-- taps a kid on the roster sheet, changes his rating and/or writes a note,
-- and the row lands here IMMEDIATELY (durable, no sheet risk mid-event).
-- sync_player_evals.py then projects unsynced rows into Recruiting Sheet
-- 2.0 through the existing Apps Script path (build_upsert_op = Seen append
-- with dedupe + tier only-if-changed; build_note_update_op = stamped note
-- append) and stamps synced_at after a clean write. The Supabase row is
-- the record; the sheet write is a replayable projection — same dual-write
-- direction as Phase 0.
--
-- RLS posture matches events/marks: the Event Day app runs on the anon key
-- without sign-in, so anon can insert and read. synced_at is stamped by the
-- flush script (also anon-key today — same trust level as every other
-- write in this stack). No delete via the API: evals are append-only like
-- evaluations in the platform schema; a wrong eval is corrected by a newer
-- one. Tighten to per-program policies when this table gains tenancy.

create table player_evals (
  id           bigint generated always as identity primary key,
  event_id     uuid references events(id) on delete set null,
  event_name   text,
  player_name  text not null,
  state        text,
  grad         text,
  team         text,
  pos          text,
  hs           text,
  new_tier     text,                 -- '0.1'|'1'|'2'|'3'|'4'|'XX'; null = note-only
  note         text,                 -- null = rating-only
  by_initials  text,
  created_at   timestamptz default now(),
  synced_at    timestamptz           -- set by sync_player_evals.py post-verify
);

create index player_evals_unsynced on player_evals (created_at) where synced_at is null;
create index player_evals_player on player_evals (player_name, state, grad);

alter table player_evals enable row level security;
create policy evals_app_read   on player_evals for select using (true);
create policy evals_app_insert on player_evals for insert with check (true);
create policy evals_app_sync   on player_evals for update using (true) with check (true);

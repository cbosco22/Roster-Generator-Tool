-- player_drafts: the "Name Drop" inbox (Chris 2026-07-07). A coach texts you
-- a name, or you get an email — dump it in as text or a screenshot and it
-- lands here as a partial-info lead. Drafts hang here (NOT on the board) until
-- you've added enough info, then you PUBLISH them into `players`.
--
-- Separate from `players` on purpose: a draft is an unfinished lead, not a
-- board entry. Program-scoped RLS exactly like players/evaluations. Publish =
-- app inserts into players (+ an evaluation if a rating/note was set) and
-- deletes the draft.

create table player_drafts (
  id           uuid primary key default gen_random_uuid(),
  program_id   uuid not null references programs(id) on delete cascade,
  first_name   text, last_name text, grad_year int,
  pos          text, pos2 text, bats_throws text,
  state        text, hometown text, high_school text, summer_team text,
  academic     text, commit text, email text, phone text,
  notes        text, rating text,          -- optional first read
  source       text,                       -- 'text' | 'email' | 'screenshot'
  created_by   uuid references members(id),
  created_at   timestamptz default now(),
  updated_at   timestamptz default now()
);
create index player_drafts_program on player_drafts(program_id, created_at desc);

alter table player_drafts enable row level security;
create policy drafts_rw on player_drafts for all
  using (program_id in (select my_programs()))
  with check (program_id in (select my_programs()));

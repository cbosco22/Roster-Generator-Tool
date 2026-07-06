-- ============================================================
-- RLS adversarial test fixtures (Phase 0, 2026-07-06)
-- Two throwaway TEST tenants + users. Idempotent. Everything is
-- prefixed rls-test / RLS TEST so it is unmistakably not real data.
-- Cleanup: delete from auth.users where email like 'rls-test-%@rlstest.navyeventday.example.com'
--          (cascades through members; programs deleted separately by slug).
-- ============================================================

-- test users (created directly: built-in SMTP is rate-limited, and
-- these logins exist only to attack our own RLS)
do $$
declare
  uid uuid;
  em text;
  pw text := current_setting('app.rls_test_pw', true);
begin
  if pw is null or pw = '' then
    raise exception 'set app.rls_test_pw first';
  end if;
  foreach em in array array['rls-test-navy@rlstest.gmail.com','rls-test-rival@rlstest.gmail.com'] loop
    if not exists (select 1 from auth.users where email = em) then
      uid := gen_random_uuid();
      insert into auth.users (instance_id, id, aud, role, email, encrypted_password,
        email_confirmed_at, raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
        confirmation_token, recovery_token, email_change, email_change_token_new, email_change_token_current)
      values ('00000000-0000-0000-0000-000000000000', uid, 'authenticated', 'authenticated',
        em, crypt(pw, gen_salt('bf')), now(),
        '{"provider":"email","providers":["email"]}', '{}', now(), now(), '', '', '', '', '');
      insert into auth.identities (id, user_id, identity_data, provider, provider_id,
        created_at, updated_at, last_sign_in_at)
      values (gen_random_uuid(), uid,
        jsonb_build_object('sub', uid::text, 'email', em, 'email_verified', true),
        'email', uid::text, now(), now(), now());
    end if;
  end loop;
end $$;

-- two test programs
insert into programs (name, slug) values
  ('RLS TEST Navy',  'rls-test-navy'),
  ('RLS TEST Rival', 'rls-test-rival')
on conflict (slug) do nothing;

-- memberships (each user is admin of exactly one program)
insert into members (program_id, user_id, role, initials, display_name)
select p.id, u.id, 'admin', 'TN', 'RLS Test Navy Admin'
from programs p, auth.users u
where p.slug = 'rls-test-navy' and u.email = 'rls-test-navy@rlstest.gmail.com'
on conflict (program_id, user_id) do nothing;

insert into members (program_id, user_id, role, initials, display_name)
select p.id, u.id, 'admin', 'TR', 'RLS Test Rival Admin'
from programs p, auth.users u
where p.slug = 'rls-test-rival' and u.email = 'rls-test-rival@rlstest.gmail.com'
on conflict (program_id, user_id) do nothing;

-- one secret player per program (the thing the other side must never see)
insert into players (program_id, first_name, last_name, grad_year, state, pos)
select p.id, 'NavyOnly', 'Secretplayer', 2027, 'MD', 'RHP'
from programs p where p.slug = 'rls-test-navy'
  and not exists (select 1 from players x where x.program_id = p.id and x.last_name = 'Secretplayer');

insert into players (program_id, first_name, last_name, grad_year, state, pos)
select p.id, 'RivalOnly', 'Secretplayer', 2028, 'MA', 'C'
from programs p where p.slug = 'rls-test-rival'
  and not exists (select 1 from players x where x.program_id = p.id and x.last_name = 'Secretplayer');

-- one evaluation per program (append-only + confidentiality target)
insert into evaluations (program_id, player_id, event_name, rating, note)
select pl.program_id, pl.id, 'RLS test event', '1', 'navy secret evaluation'
from players pl join programs pr on pr.id = pl.program_id
where pr.slug = 'rls-test-navy' and pl.last_name = 'Secretplayer'
  and not exists (select 1 from evaluations e where e.player_id = pl.id);

insert into evaluations (program_id, player_id, event_name, rating, note)
select pl.program_id, pl.id, 'RLS test event', '2', 'rival secret evaluation'
from players pl join programs pr on pr.id = pl.program_id
where pr.slug = 'rls-test-rival' and pl.last_name = 'Secretplayer'
  and not exists (select 1 from evaluations e where e.player_id = pl.id);

-- audit rows (admins should each see only their own program's)
insert into access_audit (program_id, actor, action, detail)
select p.id, 'rls-suite', 'fixture-seed', '{"note":"test row"}'::jsonb
from programs p
where p.slug in ('rls-test-navy','rls-test-rival')
  and not exists (select 1 from access_audit a where a.program_id = p.id and a.action = 'fixture-seed');

-- hand the suite what it needs (ids only; password came from the setting)
select p.slug, p.id as program_id,
       (select id from players where program_id = p.id and last_name='Secretplayer') as player_id,
       (select u.id from members m join auth.users u on u.id = m.user_id where m.program_id = p.id limit 1) as user_id
from programs p where p.slug in ('rls-test-navy','rls-test-rival');

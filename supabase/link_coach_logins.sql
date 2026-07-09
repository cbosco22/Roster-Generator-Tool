-- Link coach logins to the Navy Baseball program (run AFTER each coach's
-- auth user exists — create users in Supabase dashboard: Authentication →
-- Users → Add user, or via the app's invite flow once built).
-- Edit the emails, then run. Idempotent.
insert into members (program_id, user_id, role, initials, display_name)
select p.id, u.id, v.role, v.initials, v.display_name
from (values
  ('bosco.chris01@gmail.com', 'admin', 'CB', 'Chris Bosco'),
  ('ristano@usna.edu',        'coach', 'CR', 'Coach Ristano'),
  ('moritz@usna.edu',         'coach', 'AM', 'Coach Moritz')
  -- ('coach-ap@usna.edu',  'coach', 'AP', 'Coach AP'),
  -- ('coach-tr@usna.edu',  'coach', 'TR', 'Coach TR')
) as v(email, role, initials, display_name)
join programs p on p.slug = 'navy'
join auth.users u on lower(u.email) = lower(v.email)
on conflict (program_id, user_id) do nothing;

select m.initials, m.role, u.email from members m
join auth.users u on u.id = m.user_id
join programs p on p.id = m.program_id where p.slug = 'navy';

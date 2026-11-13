begin;
create table if not exists public.p2x4_admins (
 user_id uuid primary key references auth.users(id) on delete cascade,
 granted_at timestamptz not null default now()
);
alter table public.p2x4_admins enable row level security;
revoke all on public.p2x4_admins from anon, authenticated;
create or replace function public.p2x4_is_admin() returns boolean
language sql stable security definer set search_path = ''
as $$ select exists(select 1 from public.p2x4_admins where user_id = auth.uid()); $$;
revoke all on function public.p2x4_is_admin() from public, anon;
grant execute on function public.p2x4_is_admin() to authenticated;
do $$
declare target uuid;
begin
 select id into strict target from auth.users
 where lower(email) = 'oavillalobos@ust.edu.ph' and email_confirmed_at is not null;
 insert into public.p2x4_admins(user_id) values(target) on conflict do nothing;
end $$;
commit;

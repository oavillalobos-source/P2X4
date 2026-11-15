-- Reversible owner-scoped registry deletion. Existing RLS applies unchanged.
begin;
alter table public.p2x4_jobs add column if not exists deleted_at timestamptz;
commit;

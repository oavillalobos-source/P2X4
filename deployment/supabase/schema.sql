-- P2X4 Streamlit pilot: owner-isolated registry and private evidence artifacts.
-- Apply in a NEW Supabase project using the SQL editor. No service key in app.
-- Does not import or modify existing local researcher accounts or docking data.
begin;
create table if not exists public.p2x4_jobs (
  job_id text primary key check (job_id ~ '^[0-9a-f]{32}$'),
  owner uuid not null references auth.users(id),
  compound_id text not null check (length(compound_id) between 1 and 80),
  compound_name text not null check (length(compound_name) between 1 and 500),
  smiles text not null check (length(smiles) between 1 and 4000),
  state text not null check (state in ('queued','running','complete','failed','cancelled')),
  created double precision not null,
  updated_at timestamptz not null default now(),
  result jsonb,
  error text,
  archive_sha256 text check (archive_sha256 is null or archive_sha256 ~ '^[0-9a-f]{64}$'),
  archive_size bigint check (archive_size is null or archive_size between 0 and 26214400),
  instance_id uuid not null
);
create index if not exists p2x4_jobs_owner_created on public.p2x4_jobs(owner, created);
alter table public.p2x4_jobs enable row level security;
alter table public.p2x4_jobs force row level security;
revoke all on public.p2x4_jobs from anon, authenticated;
grant select, insert, update on public.p2x4_jobs to authenticated;
create policy p2x4_read_own on public.p2x4_jobs for select to authenticated
  using (owner = (select auth.uid()));
create policy p2x4_insert_own on public.p2x4_jobs for insert to authenticated
  with check (owner = (select auth.uid()));
create policy p2x4_update_own on public.p2x4_jobs for update to authenticated
  using (owner = (select auth.uid())) with check (owner = (select auth.uid()));
-- No delete grant or delete policy: evidence is not silently removed by the app.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('p2x4-evidence', 'p2x4-evidence', false, 26214400, array['application/zip'])
on conflict (id) do nothing;
-- An existing bucket must be private before activation; do not alter other buckets.
do $$ begin
  if exists (select 1 from storage.buckets where id='p2x4-evidence' and public) then
    raise exception 'p2x4-evidence already exists as a public bucket; activation blocked';
  end if;
end $$;
create policy p2x4_evidence_read on storage.objects for select to authenticated
  using (bucket_id = 'p2x4-evidence' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy p2x4_evidence_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'p2x4-evidence' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy p2x4_evidence_update on storage.objects for update to authenticated
  using (bucket_id = 'p2x4-evidence' and (storage.foldername(name))[1] = (select auth.uid())::text)
  with check (bucket_id = 'p2x4-evidence' and (storage.foldername(name))[1] = (select auth.uid())::text);
commit;

-- Transactional RLS checks on actual Postgres roles; all fixtures roll back.
-- This tests database and storage-object policies, not email or binary delivery.
begin;
insert into auth.users(id,email) values
 ('f0a00000-0000-4000-8000-000000000001','p2x4-rls-a@example.invalid'),
 ('f0b00000-0000-4000-8000-000000000002','p2x4-rls-b@example.invalid');
set local role authenticated;
select set_config('request.jwt.claims','{"sub":"f0a00000-0000-4000-8000-000000000001","role":"authenticated"}',true);
insert into public.p2x4_jobs(job_id,owner,compound_id,compound_name,smiles,state,created,instance_id)
values('f0a00000000040008000000000000001',auth.uid(),'RLS-A','Ethanol','CCO','queued',0,'00000000-0000-4000-8000-000000000000');
insert into storage.objects(bucket_id,name) values('p2x4-evidence',auth.uid()::text||'/rls-check.zip');
do $$ begin
 if (select count(*) from public.p2x4_jobs where job_id='f0a00000000040008000000000000001')<>1 then raise exception 'A cannot read own row'; end if;
 if (select count(*) from storage.objects where name=auth.uid()::text||'/rls-check.zip' and bucket_id='p2x4-evidence')<>1 then raise exception 'A cannot read own object'; end if;
 begin
  update public.p2x4_jobs set owner='f0b00000-0000-4000-8000-000000000002' where job_id='f0a00000000040008000000000000001';
  raise exception 'Owner reassignment was permitted';
 exception when insufficient_privilege then null; end;
end $$;
select set_config('request.jwt.claims','{"sub":"f0b00000-0000-4000-8000-000000000002","role":"authenticated"}',true);
do $$ declare n integer; begin
 if exists(select 1 from public.p2x4_jobs where job_id='f0a00000000040008000000000000001') then raise exception 'B can read A row'; end if;
 update public.p2x4_jobs set compound_name='Unauthorized' where job_id='f0a00000000040008000000000000001';
 get diagnostics n=row_count;
 if n<>0 then raise exception 'B can update A row'; end if;
 if exists(select 1 from storage.objects where bucket_id='p2x4-evidence' and name='f0a00000-0000-4000-8000-000000000001/rls-check.zip') then raise exception 'B can read A object'; end if;
 update storage.objects set metadata='{"unauthorized":true}' where bucket_id='p2x4-evidence' and name='f0a00000-0000-4000-8000-000000000001/rls-check.zip';
 get diagnostics n=row_count;
 if n<>0 then raise exception 'B can update A object'; end if;
 begin
  insert into storage.objects(bucket_id,name) values('p2x4-evidence','f0a00000-0000-4000-8000-000000000001/forbidden.zip');
  raise exception 'B can insert into A folder';
 exception when insufficient_privilege then null; end;
 begin
  insert into public.p2x4_jobs(job_id,owner,compound_id,compound_name,smiles,state,created,instance_id) values('f0a00000000040008000000000000002','f0a00000-0000-4000-8000-000000000001','BAD','Bad','CCO','queued',0,'00000000-0000-4000-8000-000000000000');
  raise exception 'B can insert A row';
 exception when insufficient_privilege then null; end;
end $$;
reset role;
set local role anon;
select set_config('request.jwt.claims','{"role":"anon"}',true);
do $$ begin
 begin
  perform 1 from public.p2x4_jobs;
  raise exception 'Anonymous registry read was permitted';
 exception when insufficient_privilege then null; end;
 if exists(select 1 from storage.objects where bucket_id='p2x4-evidence') then raise exception 'Anonymous evidence read permitted'; end if;
end $$;
reset role;
select 'PASS: owner access, cross-user isolation, anonymous denial; fixtures rolled back' as verification;
rollback;

-- Administrator-only operational metadata; no structures or result access.
begin;
alter table public.p2x4_jobs add column if not exists campaign_id text;
create table if not exists public.p2x4_queue_audit (
 id bigint generated always as identity primary key,
 actor uuid not null, researcher uuid not null, campaign_id text,
 instance_id uuid not null, action text not null, created_at timestamptz not null default now()
);
alter table public.p2x4_queue_audit enable row level security;
revoke all on public.p2x4_queue_audit from public,anon,authenticated;
create or replace function public.p2x4_admin_campaigns() returns table (
 researcher uuid,email text,campaign text,instance_id uuid,submitted_at double precision,
 queued bigint,running bigint,completed bigint,failed bigint,cancelled bigint)
language plpgsql security definer set search_path='' as $$
begin
 if not public.p2x4_is_admin() then raise exception 'Administrator access required' using errcode='42501'; end if;
 return query select j.owner,u.email::text,coalesce(j.campaign_id,'legacy-'||j.job_id),j.instance_id,min(j.created),
 count(*) filter(where j.state='queued'),count(*) filter(where j.state='running'),
 count(*) filter(where j.state='complete'),count(*) filter(where j.state='failed'),count(*) filter(where j.state='cancelled')
 from public.p2x4_jobs j join auth.users u on u.id=j.owner
 group by j.owner,u.email,coalesce(j.campaign_id,'legacy-'||j.job_id),j.instance_id
 order by min(j.created) desc;
end $$;
create or replace function public.p2x4_admin_queue_action(target_owner uuid,target_campaign text,worker_instance uuid,queue_action text)
returns bigint language plpgsql security definer set search_path='' as $$
declare audit_id bigint;
begin
 if not public.p2x4_is_admin() then raise exception 'Administrator access required' using errcode='42501'; end if;
 if queue_action is null or queue_action not in ('prioritize','stop_waiting','stop_all') then raise exception 'Invalid queue action'; end if;
 if not exists(select 1 from public.p2x4_jobs j where j.owner=target_owner and j.instance_id=worker_instance
 and (target_campaign is null or coalesce(j.campaign_id,'legacy-'||j.job_id)=target_campaign)) then raise exception 'Unknown researcher campaign'; end if;
 insert into public.p2x4_queue_audit(actor,researcher,campaign_id,instance_id,action)
 values(auth.uid(),target_owner,target_campaign,worker_instance,queue_action) returning id into audit_id;
 if queue_action in ('stop_waiting','stop_all') then
 update public.p2x4_jobs j set state='cancelled',error='Stopped by administrator.',updated_at=now()
 where j.owner=target_owner and j.instance_id=worker_instance
 and (target_campaign is null or coalesce(j.campaign_id,'legacy-'||j.job_id)=target_campaign)
 and (j.state='queued' or (queue_action='stop_all' and j.state='running'));
 end if;
 return audit_id;
end $$;
revoke all on function public.p2x4_admin_campaigns() from public,anon;
revoke all on function public.p2x4_admin_queue_action(uuid,text,uuid,text) from public,anon;
grant execute on function public.p2x4_admin_campaigns() to authenticated;
grant execute on function public.p2x4_admin_queue_action(uuid,text,uuid,text) to authenticated;
commit;

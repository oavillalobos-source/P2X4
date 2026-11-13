"""Role-checked, metadata-only researcher queue operations."""
import os
import signal
from datetime import datetime, timezone


def rpc(client, name, payload):
    with client.lock:
        client._ready()
        return client._raw('POST','/rest/v1/rpc/'+name,payload=payload)


def campaign(job):
    return job.get('campaign_id') or 'legacy-'+job['job_id']


def apply(engine, client, owner, selected_campaign, action):
    if action not in ('prioritize','stop_waiting','stop_all'):
        raise ValueError('Invalid action.')
    if not client.is_admin():
        raise PermissionError('Administrator access required.')
    changed=[]
    with engine.lock:
        # RPC rechecks role atomically and records the action before local mutation.
        audit = rpc(client,'p2x4_admin_queue_action',dict(target_owner=owner,target_campaign=selected_campaign,
                    worker_instance=engine.instance_id,queue_action=action))
        if action=='prioritize':
            return {'audit_id':audit,'prioritized':engine.pool.prioritize(owner,selected_campaign)}
        engine.pool.cancel(owner,selected_campaign)
        targets=[]
        for jid,job in engine.jobs.items():
            if job['owner']!=owner or (selected_campaign and campaign(job)!=selected_campaign):continue
            if job['state']=='queued' or (action=='stop_all' and job['state']=='running'):
                job.update(state='cancelled',cancel_requested=True,error='Stopped by administrator.')
                changed.append(jid);targets.append(('dock',jid))
        for (task_owner,jid),task in getattr(engine,'_admet_tasks',{}).items():
            if task_owner!=owner or (selected_campaign and task.get('campaign')!=selected_campaign):continue
            if task['state']=='queued' or (action=='stop_all' and task['state']=='running'):
                task.update(state='cancelled',cancel_requested=True);targets.append(('admet',task_owner,jid))
        for key in targets:
            proc=engine._processes.get(key)
            if proc and proc.poll() is None:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
        engine.dispatch.notify_all()
    # Owner callbacks may be expired; DB cancellation was already saved by the RPC.
    for jid in changed:engine._notify(jid)
    return {'audit_id':audit,'stopped':len(targets)}


def render(engine, client):
    import streamlit as st
    st.subheader('Researcher campaigns')
    st.caption('Queue participation, not a list of currently signed-in users. Structures and scientific results remain private. Controls apply to this worker; older-worker records are historical.')
    try:
        records=rpc(client,'p2x4_admin_campaigns',{})
    except ValueError:
        st.warning('Researcher queue permissions are not configured yet. The administrator must apply researcher_queue.sql.')
        return
    if not records:
        st.info('No submitted campaigns.');return
    display=[]
    for row in records:
        display.append({'Researcher':row['email'],'Campaign':row['campaign'],
            'Submitted (UTC)':datetime.fromtimestamp(row['submitted_at'],timezone.utc).isoformat(),
            **{s:row[s] for s in ('queued','running','completed','failed','cancelled')},
            'Worker':'Current' if row['instance_id']==engine.instance_id else 'Historical / other worker'})
    st.dataframe(display,hide_index=True)
    current=[r for r in records if r['instance_id']==engine.instance_id]
    if not current:return
    owners={r['researcher']:r['email'] for r in current}
    owner=st.selectbox('Researcher',list(owners),format_func=lambda o:owners[o])
    campaigns=[r['campaign'] for r in current if r['researcher']==owner]
    selected=st.selectbox('Scope',['All current campaigns']+campaigns)
    selected=None if selected=='All current campaigns' else selected
    st.caption('Prioritize moves waiting docking and ADMET tasks ahead of other waiting tasks without interrupting the current calculation. Stop is cancellation, not deletion; saved completed results remain available.')
    confirmed=st.checkbox('I intend to cancel the selected researcher’s work (required for stop actions).')
    a,b,c=st.columns(3)
    action=None
    if a.button('Prioritize waiting work'):action='prioritize'
    if b.button('Stop waiting work',disabled=not confirmed):action='stop_waiting'
    if c.button('Stop waiting + running',disabled=not confirmed):action='stop_all'
    if action:
        try:
            response=apply(engine,client,owner,selected,action)
            st.success('Queue action applied. Audit event '+str(response['audit_id']))
            st.rerun()
        except (ValueError,PermissionError,OSError) as exc:st.error(str(exc))
    if st.button('Refresh researcher queue'):st.rerun()

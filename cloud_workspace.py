"""Supabase sign-in and durable-result facade around the unchanged serial runner."""
import json
import time
from pathlib import Path
from datetime import datetime, timezone

import streamlit as st
from supabase_client import CloudError, SupabaseClient


class CloudEngine:
    def __init__(self, engine, client):
        self.engine, self.client, self.root = engine, client, engine.root
        self.owner = client.user['id']
        self._rows, self._at = [], float("-inf")
        self._download_key, self._download_data = None, None
        with engine.lock:
            for job in engine.jobs.values():
                if job['owner'] == self.owner:
                    engine._listeners[job['job_id']] = self._change

    def _check(self, owner):
        if owner != self.owner or not self.client.user or self.client.user['id'] != owner:
            raise CloudError('Sign in to access this researcher’s workspace.')

    def _change(self, event, jobs):
        self._check(self.owner)
        if event == 'submitted':
            self.client.insert_jobs(jobs, self.engine.instance_id)
        else:
            for job in jobs:
                changes = {'state': job['state'], 'error': job.get('error'),
                    'updated_at': datetime.now(timezone.utc).isoformat()}
                if job['state'] in ('complete', 'failed'):
                    path = self.root / job['job_id'] / 'result.json'
                    if job['state'] == 'complete':
                        changes['result'] = json.loads(path.read_text())
                    # Save results even if quota/auth prevents the ZIP upload.
                    self.client.update_job(job['job_id'], changes)
                    data = self.engine.download(self.owner, job['job_id'])
                    digest = self.client.save_archive(job['job_id'], data)
                    changes.update(archive_sha256=digest, archive_size=len(data))
                self.client.update_job(job['job_id'], changes)
        self._at = float("-inf")

    def submit(self, owner, rows):
        self._check(owner)
        return self.engine.submit(owner, rows, on_change=self._change)

    def owned(self, owner):
        self._check(owner)
        if time.monotonic() - self._at > 10:
            self._rows = self.client.jobs()
            self._at = time.monotonic()
        records = {j['job_id']: dict(j) for j in self._rows}
        live = {j['job_id']: j for j in self.engine.owned(owner)}
        for job_id, job in records.items():
            if job_id not in live and job['state'] in ('queued', 'running'):
                job.update(state='interrupted', error='The worker that owned this run is no longer available. The submission is saved, but the calculation is incomplete. Submit a new run with the same structure; partial checkpoint resume is not supported.')
        for job_id, job in live.items():
            records[job_id] = dict(records.get(job_id, {}), **job)
        return sorted(records.values(), key=lambda job: job['created'])

    def result(self, job):
        self._check(job['owner'])
        if job['state'] != 'complete':
            return None
        path = self.root / job['job_id'] / 'result.json'
        if path.is_file():
            return json.loads(path.read_text())
        return job.get('result')

    def cancel_waiting(self, owner):
        self._check(owner)
        self.engine.cancel_waiting(owner)
        self._at = float("-inf")

    def retry_save(self, owner, job_id):
        self._check(owner)
        jobs = {j['job_id']: j for j in self.engine.owned(owner)}
        if job_id not in jobs or jobs[job_id]['state'] not in ('complete', 'failed', 'cancelled'):
            raise CloudError('Only finished jobs still on this worker can be saved again.')
        with self.engine.lock:
            self.engine._listeners[job_id] = self._change
        self.engine._notify(job_id)
        self._at = float("-inf")
        if self.engine.jobs[job_id].get('sync_error'):
            raise CloudError(self.engine.jobs[job_id]['sync_error'])

    def download(self, owner, job_id):
        self._check(owner)
        live = {j['job_id']: j for j in self.engine.owned(owner)}
        if job_id in live:
            return self.engine.download(owner, job_id)
        jobs = {j['job_id']: j for j in self.owned(owner)}
        if job_id not in jobs:
            raise CloudError('This job is not in your private registry.')
        job = jobs[job_id]
        key = (job_id, job.get('archive_sha256'))
        if self._download_key != key:
            self._download_data = self.client.download(job)
            self._download_key = key
        return self._download_data


def sign_in(url, key, signup_enabled=False):
    """Returns one client per Streamlit session. No token in URLs or caches."""
    config = (url, key)
    if st.session_state.get('_supabase_config') != config:
        st.session_state['_supabase_client'] = SupabaseClient(url, key)
        st.session_state['_supabase_config'] = config
        st.session_state.pop('_cloud_worker', None)
    client = st.session_state['_supabase_client']
    if client.user:
        a, b = st.columns([5, 1])
        a.caption('Signed in as ' + client.user['email'])
        if b.button('Sign out'):
            try:
                client.logout()
            except CloudError:
                pass  # Locally cleared regardless; never retain identity after logout.
            for name in ('_cloud_worker', 'selected_job', 'nav'):
                st.session_state.pop(name, None)
            st.rerun()
        return client
    video = Path(__file__).resolve().parent / 'pathway.mp4'
    if video.is_file():
        st.video(str(video), autoplay=True, muted=True, loop=True)
    with st.form('cloud-sign-in', clear_on_submit=True):
        email = st.text_input('Email address', max_chars=254)
        password = st.text_input('Password', type='password')
        submitted = st.form_submit_button('Sign in', type='primary')
    if submitted:
        try:
            client.login(email, password)
            st.rerun()
        except CloudError as exc:
            st.error(str(exc))
    if signup_enabled:
        with st.expander('Create a researcher account'):
            with st.form('cloud-sign-up', clear_on_submit=True):
                email = st.text_input('Your email', max_chars=254)
                first = st.text_input('Choose password', type='password')
                second = st.text_input('Confirm password', type='password')
                consent = st.checkbox('I understand that submitted structures and results will be stored in this platform’s private Supabase project.')
                submitted = st.form_submit_button('Create account')
            if submitted:
                if not consent or first != second or len(first) < 12:
                    st.error('Accept the storage notice and enter matching passwords of at least 12 characters.')
                else:
                    try:
                        client.signup(email, first)
                        st.success('If registration is available for this address, check your email to confirm it, then sign in here.')
                    except CloudError as exc:
                        st.error(str(exc))
        with st.expander('Forgot password'):
            st.caption('Use the recovery code from the email. Requesting a code does not change your password.')
            with st.form('cloud-recover-request', clear_on_submit=True):
                email = st.text_input('Recovery email', max_chars=254)
                submitted = st.form_submit_button('Email recovery code')
            if submitted:
                try:
                    client.request_recovery(email)
                    st.success('If this address has an account, a recovery email has been requested.')
                except CloudError as exc:
                    st.error(str(exc))
            with st.form('cloud-recover-verify', clear_on_submit=True):
                email = st.text_input('Account email', max_chars=254)
                code = st.text_input('Email recovery code')
                first = st.text_input('New password', type='password')
                second = st.text_input('Repeat new password', type='password')
                submitted = st.form_submit_button('Set new password')
            if submitted:
                if first != second or len(first) < 12:
                    st.error('Enter matching passwords of at least 12 characters.')
                else:
                    try:
                        client.recover(email, code, first)
                        st.success('Password updated. Sign in with your new password.')
                    except CloudError as exc:
                        client.clear()
                        st.error(str(exc))
    else:
        st.info('Public registration and password-recovery email are not enabled yet. The project administrator must configure email delivery first.')
    st.stop()

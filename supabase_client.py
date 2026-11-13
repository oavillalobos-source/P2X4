"""User-token-only Supabase REST client. Never put this in a global UI cache."""
import hashlib
import re
import threading
import time
import uuid
from urllib.parse import urlsplit

import requests

MAX_ARCHIVE = 25 * 1024 * 1024


class CloudError(ValueError):
    pass


class SupabaseClient:
    def __init__(self, url, publishable_key, http=None):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not re.fullmatch(r'[a-z0-9]+\.supabase\.co', parsed.hostname or '')
                or parsed.port or parsed.path not in ('', '/') or parsed.query or parsed.fragment
                or parsed.username or parsed.password):
            raise CloudError('Use the HTTPS project URL from Supabase (https://PROJECT_REF.supabase.co).')
        if not re.fullmatch(r'sb_publishable_[A-Za-z0-9_-]+', publishable_key):
            raise CloudError('Use a Supabase publishable key, never a secret or service-role key.')
        self.url, self.key = url.rstrip('/'), publishable_key
        self.http = http or requests.Session()
        self.lock = threading.RLock()
        self.access = self.refresh = None
        self.expires = 0
        self.user = None

    def _raw(self, method, path, *, payload=None, data=None, params=None, headers=None,
             auth=True, binary=False):
        if not path.startswith(('/auth/v1/', '/rest/v1/', '/storage/v1/')) or '..' in path or '?' in path:
            raise CloudError('Invalid cloud API path.')
        request_headers = {'apikey': self.key}
        if auth:
            if not self.access:
                raise CloudError('Sign in to access your private workspace.')
            request_headers['Authorization'] = 'Bearer ' + self.access
        request_headers.update(headers or {})
        try:
            response = self.http.request(method, self.url + path, headers=request_headers,
                json=payload, data=data, params=params, timeout=(10, 90), allow_redirects=False)
        except requests.RequestException:
            raise CloudError('Supabase is unavailable. No successful save has been confirmed; retry when connected.') from None
        if not 200 <= response.status_code < 300:
            # Never expose raw response bodies: they can contain tokens or user data.
            if response.status_code in (401, 403):
                raise CloudError('Access denied or session expired. Sign in again; email confirmation may be required.')
            if response.status_code == 429:
                raise CloudError('Supabase request/email limit reached. Wait before retrying.')
            raise CloudError(f'Supabase returned HTTP {response.status_code}. Check project, email delivery, storage quota and schema configuration.')
        if binary:
            return response.content
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise CloudError('Supabase returned an invalid response.') from None

    def _accept(self, response):
        if not response or not response.get('access_token') or not response.get('refresh_token'):
            raise CloudError('Supabase did not establish a session.')
        previous = self.user and self.user['id']
        user_id = str(uuid.UUID(response['user']['id']))
        if previous and user_id != previous:
            raise CloudError('Session identity changed unexpectedly. Sign out and sign in again.')
        self.access, self.refresh = response['access_token'], response['refresh_token']
        self.expires = time.time() + int(response.get('expires_in', 3600))
        self.user = {'id': user_id, 'email': response['user'].get('email', '')}
        return self.user

    def _ready(self):
        if not self.user:
            raise CloudError('Sign in to access your private workspace.')
        if time.time() >= self.expires - 90:
            self._accept(self._raw('POST', '/auth/v1/token', auth=False,
                params={'grant_type': 'refresh_token'}, payload={'refresh_token': self.refresh}))

    def login(self, email, password):
        with self.lock:
            self.clear()
            return self._accept(self._raw('POST', '/auth/v1/token', auth=False,
                params={'grant_type': 'password'}, payload={'email': email.strip(), 'password': password}))

    def signup(self, email, password):
        with self.lock:
            self._raw('POST', '/auth/v1/signup', auth=False,
                payload={'email': email.strip(), 'password': password})

    def request_recovery(self, email):
        with self.lock:
            self._raw('POST', '/auth/v1/recover', auth=False, payload={'email': email.strip()})

    def recover(self, email, code, password):
        with self.lock:
            self.clear()
            self._accept(self._raw('POST', '/auth/v1/verify', auth=False,
                payload={'email': email.strip(), 'token': code.strip(), 'type': 'recovery'}))
            self._raw('PUT', '/auth/v1/user', payload={'password': password})
            self.logout()

    def clear(self):
        self.access = self.refresh = self.user = None
        self.expires = 0
        self.http.cookies.clear()

    def logout(self):
        with self.lock:
            try:
                if self.access:
                    self._raw('POST', '/auth/v1/logout', params={'scope': 'local'})
            finally:
                self.clear()

    @staticmethod
    def job_id(value):
        if not re.fullmatch(r'[0-9a-f]{32}', value):
            raise CloudError('Invalid cloud job identifier.')
        return value

    def is_admin(self):
        """Server-authoritative role check; never trust email or user_metadata."""
        with self.lock:
            self._ready()
            return self._raw('POST', '/rest/v1/rpc/p2x4_is_admin', payload={}) is True

    def jobs(self):
        with self.lock:
            self._ready()
            rows, offset = [], 0
            while True:
                page = self._raw('GET', '/rest/v1/p2x4_jobs', params={'select': '*',
                    'owner': 'eq.' + self.user['id'], 'order': 'created.asc,job_id.asc',
                    'limit': 200, 'offset': offset})
                if not isinstance(page, list) or any(row.get('owner') != self.user['id'] for row in page):
                    raise CloudError('Cloud ownership verification failed.')
                rows.extend(page)
                if len(page) < 200:
                    return rows
                offset += 200

    def insert_jobs(self, jobs, instance_id):
        with self.lock:
            self._ready()
            rows = [{k: job.get(k) for k in ('job_id', 'owner', 'compound_id', 'compound_name', 'smiles', 'state', 'created', 'campaign_id')}
                    for job in jobs]
            for row in rows:
                self.job_id(row['job_id'])
                if row['owner'] != self.user['id']:
                    raise CloudError('Cannot submit another researcher’s job.')
                row['instance_id'] = instance_id
            # A single PostgREST insert is transactional: enqueue only after success.
            self._raw('POST', '/rest/v1/p2x4_jobs', payload=rows,
                headers={'Prefer': 'return=minimal'})

    def update_job(self, job_id, changes):
        allowed = {'state', 'error', 'result', 'archive_sha256', 'archive_size', 'updated_at'}
        if set(changes) - allowed:
            raise CloudError('Invalid registry update.')
        with self.lock:
            self._ready()
            result = self._raw('PATCH', '/rest/v1/p2x4_jobs', params={
                'job_id': 'eq.' + self.job_id(job_id), 'owner': 'eq.' + self.user['id']},
                payload=changes, headers={'Prefer': 'return=representation'})
            if not isinstance(result, list) or len(result) != 1 or result[0].get('owner') != self.user['id']:
                raise CloudError('The private record could not be updated.')

    def save_archive(self, job_id, data):
        if len(data) > MAX_ARCHIVE:
            raise CloudError('Evidence ZIP exceeds this pilot’s 25 MB per-file limit. Download it locally; cloud archive was not saved.')
        digest = hashlib.sha256(data).hexdigest()
        with self.lock:
            self._ready()
            self._raw('POST', f'/storage/v1/object/p2x4-evidence/{self.user["id"]}/{self.job_id(job_id)}.zip',
                data=data, headers={'Content-Type': 'application/zip', 'x-upsert': 'true'})
        return digest

    def download(self, job):
        with self.lock:
            self._ready()
            if job.get('owner') != self.user['id'] or not job.get('archive_sha256'):
                raise CloudError('No verified private archive is available for this job.')
            data = self._raw('GET', f'/storage/v1/object/authenticated/p2x4-evidence/{self.user["id"]}/{self.job_id(job["job_id"])}.zip', binary=True)
            if len(data) != job.get('archive_size') or hashlib.sha256(data).hexdigest() != job['archive_sha256']:
                raise CloudError('Evidence archive failed its integrity check. Do not use this download.')
            return data

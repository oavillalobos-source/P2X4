"""Per-researcher backend session. Never cache this client across Streamlit users."""
import ipaddress
import re
from urllib.parse import urlsplit, unquote
import requests


class BackendError(RuntimeError):
    def __init__(self, message, status=None, details=None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


class BackendClient:
    def __init__(self, base_url, allow_local=False):
        parsed = urlsplit(base_url)
        local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/') or not parsed.hostname:
            raise ValueError('Backend URL must be an origin without credentials, path, query or fragment.')
        if parsed.scheme != 'https' and not (allow_local and local and parsed.scheme == 'http'):
            raise ValueError('Backend connections require HTTPS. HTTP loopback is allowed only for explicit local testing.')
        if local and not allow_local:
            raise ValueError('A laptop localhost address cannot be used as a cloud backend.')
        try:
            if not ipaddress.ip_address(parsed.hostname).is_global and not (allow_local and local):
                raise ValueError('Backend IP must be publicly routable.')
        except ValueError as exc:
            if str(exc) == 'Backend IP must be publicly routable.':
                raise
        self.base_url = base_url.rstrip('/')
        self.http = requests.Session()
        self.csrf = None
        self.user = None

    def _url(self, path):
        parsed = urlsplit(path)
        decoded = unquote(parsed.path)
        if parsed.scheme or parsed.netloc or parsed.fragment or not decoded.startswith('/api/') or '\\' in decoded or '..' in decoded.split('/'):
            raise ValueError('Only relative API paths on the configured backend are allowed.')
        return self.base_url + path

    def request(self, method, path, payload=None, binary=False):
        headers = {}
        if method != 'GET' and self.csrf:
            headers['X-CSRF-Token'] = self.csrf
        try:
            response = self.http.request(method, self._url(path), json=payload, headers=headers,
                                         timeout=(10, 240), allow_redirects=False)
        except requests.RequestException:
            raise BackendError('The backend could not be reached. Check its availability before retrying; a submitted action may already have been accepted.') from None
        if response.status_code == 401:
            self.clear()
        if not 200 <= response.status_code < 300:
            try:
                detail = response.json()
            except ValueError:
                detail = {}
            raise BackendError(detail.get('error') or detail.get('reason') or f'Backend returned HTTP {response.status_code}.', response.status_code, detail)
        if binary:
            return response.content
        try:
            return response.json()
        except ValueError:
            raise BackendError('The backend response was not valid JSON.') from None

    def login(self, email, password):
        self.clear()
        result = self.request('POST', '/api/auth/login', {'email': email, 'password': password})
        if not result.get('authenticated') or not result.get('csrf_token'):
            raise BackendError('The backend did not establish an authenticated session.')
        self.csrf = result['csrf_token']
        self.user = result['user']
        return result

    def session(self):
        result = self.request('GET', '/api/auth/session')
        if result.get('authenticated'):
            self.user, self.csrf = result['user'], result['csrf_token']
        else:
            self.clear()
        return result

    def clear(self):
        self.http.cookies.clear()
        self.csrf = None
        self.user = None

    def logout(self):
        try:
            self.request('POST', '/api/auth/logout', {})
        finally:
            self.clear()

    @staticmethod
    def job_path(job_id, suffix=''):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', job_id):
            raise ValueError('Invalid job identifier.')
        return f'/api/jobs/{job_id}' + suffix

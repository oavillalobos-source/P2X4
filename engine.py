"""One process at a time across all sessions; temporary, session-owned jobs."""
import io
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
import shutil
import platform
from urllib.request import urlopen
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent

class Engine:
    def __init__(self):
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.root = Path(tempfile.mkdtemp(prefix='p2x4-live-'))
        self.jobs = {}
        self.instance_id = str(uuid.uuid4())
        self._listeners = {}
        self.dispatch = threading.Condition(self.lock)
        self.paused = False
        if platform.system() == 'Linux':
            manifest = json.loads((ROOT / 'bundle_manifest.json').read_text())
            binary = self.root / 'vina'
            with urlopen(manifest['vina_source'], timeout=90) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != manifest['files']['bin/vina']:
                raise RuntimeError('Vina download failed its frozen SHA-256 check.')
            binary.write_bytes(data)
            binary.chmod(0o755)
            self.vina = str(binary)
        else:
            self.vina = shutil.which('vina') or str(Path.home() / '.local/bin/vina')

    def submit(self, owner, rows, on_change=None):
        with self.lock:
            active = sum(j['state'] in ('queued', 'running') for j in self.jobs.values())
            if len(self.jobs) + len(rows) > 50:
                raise ValueError('This temporary pilot has reached 50 stored jobs. Download results before the app administrator restarts it.')
            if not 1 <= len(rows) <= 25 or active + len(rows) > 25:
                raise ValueError('The shared queue holds at most 25 waiting or running compounds. Try again later.')
            ids, prepared = [], []
            for row in rows:
                job_id = uuid.uuid4().hex
                prepared.append(dict(row, owner=owner, state='queued', job_id=job_id, created=time.time()))
                ids.append(job_id)
            if on_change:
                # Fail closed before starting any calculation when persistence fails.
                on_change('submitted', prepared)
            for job in prepared:
                job_id = job['job_id']
                self.jobs[job_id] = job
                if on_change:
                    self._listeners[job_id] = on_change
                self.pool.submit(self._run, job_id)
            return ids

    def _notify(self, job_id):
        with self.lock:
            callback = self._listeners.get(job_id)
            job = dict(self.jobs[job_id])
        if callback:
            try:
                callback('changed', [job])
                with self.lock:
                    self.jobs[job_id].pop('sync_error', None)
            except Exception as exc:
                with self.lock:
                    self.jobs[job_id]['sync_error'] = str(exc)

    def _run(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            while self.paused and job['state'] == 'queued':
                self.dispatch.wait()
            if job['state'] != 'queued':
                return
            job['state'] = 'running'
        self._notify(job_id)
        path = self.root / job_id
        command = [sys.executable, str(ROOT / 'launch.py'), '--compound-id', job['compound_id'],
                   '--job-id', job_id, '--smiles', job['smiles'], '--output-root', str(self.root),
                   '--mode', 'confirmation', '--microspecies', '--ph-min', '6.8', '--ph-max', '8.0',
                   '--max-microspecies', '8', '--workers', '1', '--cpu-per-job', '1']
        env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', P2X4_LIVE_VINA=self.vina)
        try:
            with (self.root / f'{job_id}.log').open('w') as log:
                proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
                try:
                    code = proc.wait(timeout=7200)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                    raise RuntimeError('Two-hour runtime limit reached. Partial output is downloadable; this run is incomplete.')
            if code != 0 or not (path / 'result.json').is_file():
                raise RuntimeError('Docking did not complete. Download the log and partial output for diagnosis.')
            result = json.loads((path / 'result.json').read_text())
            result['submitted_identity'] = {'compound_id': job['compound_id'], 'compound_name': job['compound_name']}
            result['hosting'] = {'edition': 'Streamlit experimental', 'storage': 'temporary', 'cpu_per_job': 1}
            if job_id in self._listeners:
                result['hosting']['storage'] = 'Private Supabase archive requested; verify cloud-save status in registry'
            (path / 'result.json').write_text(json.dumps(result, indent=2))
            with self.lock:
                job['state'] = 'complete'
        except Exception as exc:
            with self.lock:
                job.update(state='failed', error=str(exc))
        self._notify(job_id)

    def admin_queue(self, client, paused=None):
        # Check authorization again for every action, including stale admin pages.
        if not client.is_admin():
            raise PermissionError('Administrator access required.')
        with self.dispatch:
            if paused is not None:
                self.paused = bool(paused)
                self.dispatch.notify_all()
            return {'paused': self.paused, 'counts': {
                state: sum(j['state'] == state for j in self.jobs.values())
                for state in ('queued', 'running', 'complete', 'failed', 'cancelled')}}

    def owned(self, owner):
        with self.lock:
            return [dict(j) for j in self.jobs.values() if j['owner'] == owner]

    def cancel_waiting(self, owner):
        cancelled = []
        with self.lock:
            for job in self.jobs.values():
                if job['owner'] == owner and job['state'] == 'queued':
                    job['state'] = 'cancelled'
                    cancelled.append(job['job_id'])
            self.dispatch.notify_all()
        for job_id in cancelled:
            self._notify(job_id)

    def download(self, owner, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or job['owner'] != owner:
                raise PermissionError('This job belongs to a different session.')
            if job['state'] in ('queued', 'running'):
                raise ValueError('Download becomes available when the process finishes.')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in (self.root / job_id).rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(self.root / job_id))
            log = self.root / f'{job_id}.log'
            if log.exists():
                archive.write(log, 'runner.log')
        return buffer.getvalue()

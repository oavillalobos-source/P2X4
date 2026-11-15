"""Owner-scoped retry and reversible registry deletion; no protocol changes."""
from datetime import datetime, timezone

TERMINAL = {'complete', 'failed', 'cancelled', 'interrupted'}
RETRYABLE = {'failed', 'cancelled', 'interrupted'}


def _job(worker, owner, job_id):
    jobs = {j['job_id']: j for j in worker.owned(owner)}
    if job_id not in jobs or jobs[job_id]['owner'] != owner:
        raise ValueError('This record is not in your private registry.')
    return jobs[job_id]


def restart(worker, owner, job_id):
    engine = getattr(worker, 'engine', worker)
    with engine.lock:
        job = _job(worker, owner, job_id)
        if job.get('deleted_at') or job['state'] not in RETRYABLE:
            raise ValueError('Only failed, cancelled or interrupted runs can be restarted.')
        # Retain the original attempt. No outputs or partial checkpoints are reused.
        row = {k: job[k] for k in ('compound_id', 'compound_name', 'smiles')}
        return worker.submit(owner, [row])[0]


def set_deleted(worker, owner, job_id, deleted=True):
    engine = getattr(worker, 'engine', worker)
    with engine.lock:
        job = _job(worker, owner, job_id)
        if job['state'] not in TERMINAL:
            raise ValueError('Waiting or running docking jobs cannot be deleted.')
        if any(key == (owner, job_id) and t.get('state') in ('queued', 'running')
               for key, t in getattr(engine, '_admet_tasks', {}).items()):
            raise ValueError('Wait for the ADMET follow-up to finish before deleting this record.')
        timestamp = datetime.now(timezone.utc).isoformat() if deleted else None
        client = getattr(worker, 'client', None)
        if client is not None:
            worker._check(owner)
            with client.lock:
                client._ready()
                rows = client._raw('PATCH', '/rest/v1/p2x4_jobs', params={
                    'job_id': 'eq.' + client.job_id(job_id), 'owner': 'eq.' + owner},
                    payload={'deleted_at': timestamp}, headers={'Prefer': 'return=representation'})
                if not isinstance(rows, list) or len(rows) != 1 or rows[0].get('owner') != owner:
                    raise ValueError('The private registry record could not be updated.')
            worker._at = float('-inf')
        if job_id in engine.jobs:
            engine.jobs[job_id]['deleted_at'] = timestamp

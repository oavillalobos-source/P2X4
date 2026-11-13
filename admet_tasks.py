"""Owner-scoped ADMET tasks share the docking executor and release model memory."""
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile


def get_task(engine, owner, job_id):
    with engine.lock:
        task = getattr(engine, '_admet_tasks', {}).get((owner,job_id))
        return dict(task) if task else None


def submit(engine, owner, job, save):
    if job.get('owner') != owner or job.get('state') != 'complete':
        raise ValueError('Select a completed compound belonging to your account.')
    with engine.lock:
        if not hasattr(engine,'_admet_tasks'):
            engine._admet_tasks = {}
        key = (owner,job['job_id'])
        previous = engine._admet_tasks.get(key)
        if previous and previous['state'] in ('queued','running'):
            return
        active = sum(t['state'] in ('queued','running') for t in engine._admet_tasks.values())
        if active >= 25:
            raise ValueError('The ADMET queue is full; try again after a request finishes.')
        task = {'state':'queued', 'campaign':job.get('campaign_id') or 'legacy-'+job['job_id']}
        if not hasattr(engine, '_processes'): engine._processes = {}
        engine._admet_tasks[key] = task
        def run():
            try:
                with engine.lock:
                    while getattr(engine,'paused',False):
                        engine.dispatch.wait()
                    if task['state'] == 'cancelled': return
                    task['state'] = 'running'
                with tempfile.TemporaryDirectory(prefix='p2x4-admet-') as folder:
                    root = Path(folder)
                    request, output = root/'request.json', root/'report.json'
                    request.write_text(json.dumps({'smiles':job['smiles']}))
                    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                               CUDA_VISIBLE_DEVICES='', MPLCONFIGDIR=str(root/'matplotlib'))
                    with (root/'inference.log').open('w') as log:
                        proc = subprocess.Popen([sys.executable,str(Path(__file__).with_name('admet_infer.py')),str(request),str(output)],
                                              stdout=log,stderr=log,env=env,start_new_session=True)
                        with engine.lock:
                            engine._processes[('admet',owner,job['job_id'])] = proc
                            if task.get('cancel_requested'):
                                try: os.killpg(proc.pid,signal.SIGKILL)
                                except ProcessLookupError: pass
                        try:
                            proc.wait(timeout=600)
                        except subprocess.TimeoutExpired:
                            try: os.killpg(proc.pid,signal.SIGKILL)
                            except ProcessLookupError: pass
                            proc.wait()
                            raise
                        finally:
                            with engine.lock: engine._processes.pop(('admet',owner,job['job_id']),None)
                    if task.get('cancel_requested'): return
                    if proc.returncode != 0 or not output.exists():
                        raise RuntimeError('ADMET inference failed or exceeded available resources. No prediction was generated. Retry later or ask the administrator to check model installation and host memory.')
                    report = json.loads(output.read_text())
                with engine.lock:
                    if task.get('cancel_requested'): return
                    task['report'] = report
                    try:
                        save(report)
                    except Exception:
                        task['save_error'] = 'Prediction finished, but saving failed. Sign in again if necessary, then retry saving or download the report.'
                    task['state'] = 'complete'
            except subprocess.TimeoutExpired:
                with engine.lock:
                    task.update(state='cancelled' if task.get('cancel_requested') else 'failed',error='ADMET exceeded its 10-minute limit. No successful prediction is reported.')
            except Exception as exc:
                with engine.lock:
                    task.update(state='cancelled' if task.get('cancel_requested') else 'failed',error=str(exc))
        if getattr(engine.pool,'version',None) == 1:
            engine.pool.submit(run,owner=owner,campaign=task['campaign'])
        else:
            engine.pool.submit(run)

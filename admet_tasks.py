"""Owner-scoped ADMET tasks share the docking executor and release model memory."""
import json
import os
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
        task = {'state':'queued'}
        engine._admet_tasks[key] = task
        def run():
            try:
                with engine.lock:
                    while getattr(engine,'paused',False):
                        engine.dispatch.wait()
                    task['state'] = 'running'
                with tempfile.TemporaryDirectory(prefix='p2x4-admet-') as folder:
                    root = Path(folder)
                    request, output = root/'request.json', root/'report.json'
                    request.write_text(json.dumps({'smiles':job['smiles']}))
                    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                               CUDA_VISIBLE_DEVICES='', MPLCONFIGDIR=str(root/'matplotlib'))
                    with (root/'inference.log').open('w') as log:
                        proc = subprocess.run([sys.executable,str(Path(__file__).with_name('admet_infer.py')),str(request),str(output)],
                                              stdout=log,stderr=log,env=env,timeout=600)
                    if proc.returncode != 0 or not output.exists():
                        raise RuntimeError('ADMET inference failed or exceeded available resources. No prediction was generated. Retry later or ask the administrator to check model installation and host memory.')
                    report = json.loads(output.read_text())
                with engine.lock:
                    task['report'] = report
                try:
                    save(report)
                except Exception:
                    with engine.lock:
                        task['save_error'] = 'Prediction finished, but saving failed. Sign in again if necessary, then retry saving or download the report.'
                with engine.lock:
                    task['state'] = 'complete'
            except subprocess.TimeoutExpired:
                with engine.lock:
                    task.update(state='failed',error='ADMET exceeded its 10-minute limit. No successful prediction is reported.')
            except Exception as exc:
                with engine.lock:
                    task.update(state='failed',error=str(exc))
        engine.pool.submit(run)

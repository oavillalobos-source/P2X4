"""Upgrade an idle cached worker without discarding its records or executor."""
import importlib
import threading


def ensure_admin_worker(worker):
    with worker.lock:
        if callable(getattr(worker, 'admin_queue', None)) and hasattr(worker, 'dispatch'):
            return worker
        if any(job['state'] in ('queued', 'running') for job in worker.jobs.values()):
            raise RuntimeError('Queue controls are waiting for a worker update. Existing queued and running jobs will continue. Reopen Administration after they finish; do not restart the app while calculations are active.')
        # Streamlit can retain instances of the previous class after a code update.
        # Only upgrade at an idle boundary: bound tasks already running stay untouched.
        current = importlib.reload(importlib.import_module('engine')).Engine
        worker.dispatch = threading.Condition(worker.lock)
        worker.paused = False
        worker.__class__ = current
        return worker

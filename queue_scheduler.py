"""Single-consumer queue with explicit owner priority; never preempts for priority."""
from concurrent.futures import Future
import threading

class WorkQueue:
    _max_workers = 1
    version = 1
    def __init__(self, engine):
        self.engine = engine
        self.pending = []
        self.serial = 0
        self.rank = 0
        self.closed = False
        self.thread = threading.Thread(target=self._work, daemon=True, name='p2x4-dispatch')
        self.thread.start()

    def submit(self, fn, *args, owner=None, campaign=None):
        with self.engine.dispatch:
            if self.closed: raise RuntimeError('Worker queue is closed.')
            future = Future()
            self.serial += 1
            self.pending.append(dict(future=future,fn=fn,args=args,owner=owner,campaign=campaign,rank=0,serial=self.serial))
            self.engine.dispatch.notify_all()
            return future

    def prioritize(self, owner, campaign=None):
        with self.engine.dispatch:
            self.rank -= 1
            count = 0
            for item in self.pending:
                if item['owner']==owner and (campaign is None or item['campaign']==campaign) and not item['future'].cancelled():
                    item['rank']=self.rank; count+=1
            self.engine.dispatch.notify_all()
            return count

    def cancel(self, owner, campaign=None):
        with self.engine.dispatch:
            count=0
            for item in self.pending:
                if item['owner']==owner and (campaign is None or item['campaign']==campaign):
                    count += item['future'].cancel()
            self.engine.dispatch.notify_all()
            return count

    def _work(self):
        while True:
            with self.engine.dispatch:
                self.pending = [i for i in self.pending if not i['future'].cancelled()]
                eligible = [i for i in self.pending if not self.engine.paused or i['owner'] is None]
                while not eligible:
                    if self.closed and not self.pending: return
                    self.engine.dispatch.wait()
                    self.pending = [i for i in self.pending if not i['future'].cancelled()]
                    eligible = [i for i in self.pending if not self.engine.paused or i['owner'] is None]
                item = min(eligible,key=lambda i:(i['rank'],i['serial']))
                self.pending.remove(item)
                if not item['future'].set_running_or_notify_cancel(): continue
            try: item['future'].set_result(item['fn'](*item['args']))
            except BaseException as exc: item['future'].set_exception(exc)

    def shutdown(self, wait=True):
        with self.engine.dispatch:
            self.closed=True
            self.engine.paused=False
            self.engine.dispatch.notify_all()
        if wait: self.thread.join()

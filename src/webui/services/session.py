"""Session generations fence every cache; the fingerprint never reads secrets."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor


class SessionScope:
    def __init__(self):
        self.lock = threading.RLock()
        self._fingerprint = None
        self._epoch = 0

    def current(self, auth_path, db_path):
        try:
            stat = os.stat(auth_path)
            signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None
        fingerprint = (os.path.realpath(auth_path), os.path.realpath(db_path), signature)
        with self.lock:
            if fingerprint != self._fingerprint:
                self._fingerprint = fingerprint
                self._epoch += 1
            return self._epoch

    def invalidate(self):
        with self.lock:
            self._fingerprint = None
            self._epoch += 1


class SingleFlight:
    """Coalesce network work for identical keys, without locking unrelated resources."""
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs = {}

    def run(self, key, work):
        with self._lock:
            job = self._jobs.get(key)
            owner = job is None
            if owner:
                job = {"event": threading.Event(), "value": None, "error": None, "waiters": 0}
                self._jobs[key] = job
            else:
                job["waiters"] += 1
        if owner:
            try:
                job["value"] = work()
            except BaseException as error:
                job["error"] = error
            finally:
                with self._lock:
                    self._jobs.pop(key, None)
                    job["event"].set()
        else:
            job["event"].wait()
        if job["error"]:
            raise job["error"]
        return job["value"]


class Refresher:
    """Bound background live requests on the Pi; never queue unbounded work."""
    def __init__(self, workers=2):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vrcx-refresh")
        self._capacity = threading.BoundedSemaphore(workers)
        self._lock = threading.Lock()
        self._active = set()

    def submit(self, key, work):
        with self._lock:
            if key in self._active or not self._capacity.acquire(blocking=False):
                return False
            self._active.add(key)

        def run():
            try:
                work()
            finally:
                with self._lock:
                    self._active.discard(key)
                    self._capacity.release()
        try:
            self._pool.submit(run)
        except RuntimeError:
            with self._lock:
                self._active.discard(key)
                self._capacity.release()
            return False
        return True

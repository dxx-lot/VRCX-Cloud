"""Bounded live-response cache with session fencing and background refresh."""
from collections import OrderedDict
from copy import deepcopy
import threading
import time

from .session import SingleFlight


class ResponseCache:
    def __init__(self, refresher, limit=128, clock=time.monotonic):
        self.refresher = refresher
        self.limit = limit
        self.clock = clock
        self.lock = threading.RLock()
        self.entries = OrderedDict()
        self.generation = 0
        self.flights = SingleFlight()

    def clear(self):
        with self.lock:
            self.entries.clear()
            self.generation += 1

    def read(self, key, ttl, work):
        with self.lock:
            generation = self.generation
            hit = self.entries.get(key)

        def refresh():
            def load():
                # Another owner may have completed after our initial miss.
                with self.lock:
                    existing = self.entries.get(key)
                    if generation != self.generation:
                        return {"error": "账号数据已更新，请刷新"}
                    if existing and self.clock()-existing[0] < ttl:
                        return deepcopy(existing[1])
                value = work()
                with self.lock:
                    if generation != self.generation:
                        return {"error": "账号数据已更新，请刷新"}
                    if isinstance(value, (dict, list)) and not (isinstance(value, dict) and value.get("error")):
                        self.entries.pop(key, None)
                        self.entries[key] = (self.clock(), deepcopy(value))
                        while len(self.entries) > self.limit:
                            self.entries.popitem(last=False)
                return value
            return self.flights.run((generation, key), load)

        if hit:
            age = self.clock() - hit[0]
            if age < ttl:
                return deepcopy(hit[1])
            if age < max(ttl * 5, 120):
                self.refresher.submit(("response", generation, key), refresh)
                value = deepcopy(hit[1])
                if isinstance(value, dict):
                    value["_stale"] = True
                return value
        return deepcopy(refresh())

"""Tiny in-process pub/sub for live dashboard streams (SSE). One queue per subscriber, per tenant."""
import asyncio
from collections import defaultdict


class Bus:
    def __init__(self):
        self.subs: dict[str, set] = defaultdict(set)

    def subscribe(self, tenant: str) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=500)
        self.subs[tenant].add(q)
        return q

    def unsubscribe(self, tenant: str, q):
        self.subs[tenant].discard(q)

    def publish(self, tenant: str, kind: str, data: dict):
        for q in list(self.subs[tenant]):
            if q.full():                                   # slow consumer: drop oldest, never block ingest
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait({"type": kind, "data": data})

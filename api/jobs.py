"""In-memory job store with per-job event streams (SSE-friendly).

Each job accumulates an ordered event list; SSE consumers replay history
then tail the live queue, so a reconnecting browser never misses events.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    kind: str                      # "ingest" | "generate"
    status: str = "running"        # running | done | error
    events: list = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    _queues: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, event: dict) -> None:
        event = {"ts": time.time(), **event}
        with self._lock:
            self.events.append(event)
            for q in self._queues:
                q.put(event)

    def finish(self, result: dict | None = None, error: str | None = None) -> None:
        self.status = "error" if error else "done"
        self.result = result
        self.error = error
        self.emit({"type": "job_done", "status": self.status, "error": error})

    def subscribe(self):
        """Yields SSE-formatted strings: full history, then live events."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            history = list(self.events)
            self._queues.append(q)
        try:
            for e in history:
                yield _sse(e)
            if any(e.get("type") == "job_done" for e in history):
                return
            while True:
                try:
                    e = q.get(timeout=15)
                except queue.Empty:
                    yield ": heartbeat\n\n"
                    continue
                yield _sse(e)
                if e.get("type") == "job_done":
                    return
        finally:
            with self._lock:
                if q in self._queues:
                    self._queues.remove(q)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)


STORE = JobStore()

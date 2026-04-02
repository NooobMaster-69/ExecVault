"""
job_queue/queue_manager.py — Pluggable job queue and job store.

- In-memory: deque + threading (single-process, embedded worker).
- Redis: LPUSH/BRPOP + JSON job documents (horizontally scalable workers).

Set REDIS_URL (e.g. redis://localhost:6379/0) to use Redis.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from typing import Dict, List, Optional, Tuple, Union

from models.job import Job, JobStatus

log = logging.getLogger("queue_manager")


# ──────────────────────────────────────────────────────────────
# In-memory queue
# ──────────────────────────────────────────────────────────────
class JobQueue:
    """Thread-safe FIFO job queue backed by collections.deque."""

    def __init__(self) -> None:
        self._deque: deque[Job] = deque()
        self._condition = threading.Condition()

    def put(self, job: Job) -> None:
        with self._condition:
            self._deque.append(job)
            self._condition.notify()
            log.info(
                "Enqueued job %s (%s) — queue size: %d",
                job.job_id,
                job.language,
                len(self._deque),
            )

    def get(self, timeout: float = 1.0) -> Optional[Job]:
        with self._condition:
            while not self._deque:
                if not self._condition.wait(timeout=timeout):
                    return None
            return self._deque.popleft()

    @property
    def size(self) -> int:
        with self._condition:
            return len(self._deque)


# ──────────────────────────────────────────────────────────────
# In-memory store
# ──────────────────────────────────────────────────────────────
class JobStore:
    """Thread-safe dict-backed job storage."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: Dict[str, Job] = {}

    def save(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_by_status(self, status: JobStatus) -> List[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.status == status]

    def count(self) -> Dict[str, int]:
        with self._lock:
            counts: Dict[str, int] = {}
            for job in self._jobs.values():
                key = job.status.value
                counts[key] = counts.get(key, 0) + 1
            return counts


# ──────────────────────────────────────────────────────────────
# Redis queue (job_ids); payloads in RedisJobStore
# ──────────────────────────────────────────────────────────────
class RedisJobQueue:
    def __init__(self, client, key_prefix: str, store: "RedisJobStore") -> None:
        self._r = client
        self._qkey = f"{key_prefix}queue"
        self._store = store

    def put(self, job: Job) -> None:
        self._r.lpush(self._qkey, job.job_id)
        log.info("Redis enqueued job %s — queue len: %d", job.job_id, self.size)

    def get(self, timeout: float = 1.0) -> Optional[Job]:
        t = int(max(1, min(60, timeout)))
        item = self._r.brpop(self._qkey, timeout=t)
        if not item:
            return None
        job_id = item[1]
        job = self._store.get(job_id)
        if job is None:
            log.error("Missing job payload for queued id %s", job_id)
        return job

    @property
    def size(self) -> int:
        return int(self._r.llen(self._qkey))


class RedisJobStore:
    def __init__(self, client, key_prefix: str) -> None:
        self._r = client
        self._prefix = key_prefix

    def _job_key(self, job_id: str) -> str:
        return f"{self._prefix}job:{job_id}"

    def _jobs_set_key(self) -> str:
        return f"{self._prefix}job_ids"

    def save(self, job: Job) -> None:
        payload = json.dumps(job.to_dict(), ensure_ascii=False)
        self._r.set(self._job_key(job.job_id), payload)
        self._r.sadd(self._jobs_set_key(), job.job_id)

    def get(self, job_id: str) -> Optional[Job]:
        raw = self._r.get(self._job_key(job_id))
        if not raw:
            return None
        try:
            return Job.from_dict(json.loads(raw))
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            log.error("Corrupt job %s: %s", job_id, exc)
            return None

    def list_by_status(self, status: JobStatus) -> List[Job]:
        out: List[Job] = []
        for jid in self._r.smembers(self._jobs_set_key()):
            j = self.get(jid)
            if j and j.status == status:
                out.append(j)
        return out

    def count(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for jid in self._r.smembers(self._jobs_set_key()):
            j = self.get(jid)
            if j:
                key = j.status.value
                counts[key] = counts.get(key, 0) + 1
        return counts


def build_queue_backend() -> Tuple[
    Union[JobQueue, RedisJobQueue],
    Union[JobStore, RedisJobStore],
]:
    """
    In-memory by default. If REDIS_URL is set, use Redis for queue + store
    so API and worker processes can share state.
    """
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return JobQueue(), JobStore()

    import redis

    client = redis.Redis.from_url(url, decode_responses=True)
    prefix = os.getenv("REDIS_KEY_PREFIX", "exec:")
    store = RedisJobStore(client, prefix)
    queue = RedisJobQueue(client, prefix, store)
    log.info("Queue backend: Redis (%s, prefix=%s)", url.split("@")[-1], prefix)
    return queue, store

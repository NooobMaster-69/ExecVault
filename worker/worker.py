"""
worker/worker.py — Pulls jobs from the queue and executes them via CodeExecutor.

Run standalone:  python -m worker.worker
(requires REDIS_URL if API uses Redis; same env as API)
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from typing import Union

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from executor.docker_executor import CodeExecutor
from models.job import Job, JobStatus
from job_queue.queue_manager import (
    JobQueue,
    JobStore,
    RedisJobQueue,
    RedisJobStore,
    build_queue_backend,
)

log = logging.getLogger("worker")


class Worker:
    """Thread pool that consumes jobs from a shared queue."""

    def __init__(
        self,
        job_queue: Union[JobQueue, RedisJobQueue],
        job_store: Union[JobStore, RedisJobStore],
        num_threads: int = 4,
    ):
        self.job_queue = job_queue
        self.job_store = job_store
        self.num_threads = num_threads
        self.executor = CodeExecutor()
        self._threads: list[threading.Thread] = []
        self._running = False

    def start(self) -> None:
        if self._running:
            log.warning("Worker already running")
            return

        self._running = True

        for i in range(self.num_threads):
            name = f"worker-{i}"
            t = threading.Thread(target=self._loop, name=name, daemon=True)
            t.start()
            self._threads.append(t)

        log.info(
            "Worker started: %d threads, executor=%s",
            self.num_threads,
            "docker" if self.executor.docker_available else "subprocess",
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._running = False
        for t in self._threads:
            t.join(timeout=timeout)
        self._threads.clear()
        log.info("Worker stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def _loop(self) -> None:
        thread_name = threading.current_thread().name

        while self._running:
            job = self.job_queue.get(timeout=1.0)
            if job is None:
                continue

            log.info(
                "[%s] Processing job %s (%s, %d bytes)",
                thread_name,
                job.job_id,
                job.language,
                len(job.code),
            )

            try:
                self.executor.execute(job)
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = f"Worker error: {exc}"
                log.exception("[%s] Unhandled error on job %s", thread_name, job.job_id)

            try:
                self.job_store.save(job)
            except Exception as exc:
                log.exception("[%s] Failed to persist job %s: %s", thread_name, job.job_id, exc)

            log.info(
                "[%s] Job %s → %s (%.1fms)",
                thread_name,
                job.job_id,
                job.status.value,
                job.execution_time_ms,
            )


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    from utils.config import WORKER_THREADS

    jq, js = build_queue_backend()
    if not os.getenv("REDIS_URL", "").strip():
        log.warning(
            "REDIS_URL not set — standalone worker shares nothing with API unless "
            "you use in-memory (not possible across processes). Set REDIS_URL for distributed mode."
        )

    w = Worker(jq, js, num_threads=WORKER_THREADS)
    w.start()

    stop = threading.Event()

    def _handle_signal(*_: object) -> None:
        log.info("Shutdown signal received")
        stop.set()

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        while not stop.wait(0.5):
            pass
    finally:
        w.stop()


if __name__ == "__main__":
    _main()

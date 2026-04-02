"""
api/main.py — FastAPI REST server for the distributed code execution system.

POST /execute, GET /status/{job_id}, GET /result/{job_id}, GET /health, GET /stats

Queue + store: in-memory (default) or Redis (REDIS_URL). Worker can run embedded
(RUN_EMBEDDED_WORKER=true) or as a separate process (false).
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.job import Job, JobStatus
from job_queue.queue_manager import build_queue_backend
from utils.config import (
    API_HOST,
    API_PORT,
    RUN_EMBEDDED_WORKER,
    WORKER_THREADS,
)
from worker.worker import Worker

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("api")

job_queue, job_store = build_queue_backend()
embedded_worker: Optional[Worker] = None
if RUN_EMBEDDED_WORKER:
    embedded_worker = Worker(
        job_queue,
        job_store,
        num_threads=WORKER_THREADS,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if embedded_worker:
        embedded_worker.start()
        log.info("Embedded worker started (%d threads)", WORKER_THREADS)
    log.info("API server ready (embedded_worker=%s)", bool(embedded_worker))
    yield
    if embedded_worker:
        embedded_worker.stop()
    log.info("API server shut down")


app = FastAPI(
    title="Code Execution Platform",
    description="Submit code for sandboxed execution and retrieve results via REST API.",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "message": "Request validation failed"},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    log.error("Unhandled error on %s: %s", request.url, exc)
    log.debug(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


class ExecuteRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50_000, description="Source code to execute")
    language: str = Field("python", description="Language: python, node, bash, powershell")
    timeout: int = Field(10, ge=1, le=30, description="Execution timeout in seconds")


class ExecuteResponse(BaseModel):
    job_id: str
    status: str
    message: str


class StatusResponse(BaseModel):
    job_id: str
    status: str


class ResultResponse(BaseModel):
    job_id: str
    status: str
    output: str
    stdout: str
    stderr: str
    error: str
    exit_code: int
    timed_out: bool
    language: str
    execution_time: float
    execution_time_ms: float
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]


class HealthResponse(BaseModel):
    status: str
    worker_running: bool
    embedded_worker: bool
    executor_mode: str
    queue_backend: str


class StatsResponse(BaseModel):
    queue_size: int
    job_counts: dict


def _executor_mode() -> str:
    if not embedded_worker:
        return "unknown"
    return "docker" if embedded_worker.executor.docker_available else "subprocess"


@app.post("/execute", response_model=ExecuteResponse, status_code=202)
async def execute_code(req: ExecuteRequest):
    try:
        job = Job(
            code=req.code,
            language=req.language.lower().strip(),
            timeout=req.timeout,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid job parameters: {exc}") from exc

    job_store.save(job)
    job_queue.put(job)

    log.info("POST /execute → job %s (%s, %d bytes)", job.job_id, job.language, len(job.code))

    return ExecuteResponse(
        job_id=job.job_id,
        status=job.status.value,
        message="Job queued for execution.",
    )


@app.get("/status/{job_id}", response_model=StatusResponse)
async def get_status(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return StatusResponse(job_id=job.job_id, status=job.status.value)


@app.get("/result/{job_id}", response_model=ResultResponse)
async def get_result(job_id: str):
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")

    et = job.execution_time_ms / 1000.0
    return ResultResponse(
        job_id=job.job_id,
        status=job.status.value,
        output=job.stdout,
        stdout=job.stdout,
        stderr=job.stderr,
        error=job.error,
        exit_code=job.exit_code,
        timed_out=job.timed_out,
        language=job.language,
        execution_time=round(et, 4),
        execution_time_ms=round(job.execution_time_ms, 2),
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@app.get("/health", response_model=HealthResponse)
async def health_check():
    backend = "redis" if os.getenv("REDIS_URL", "").strip() else "memory"
    wr = embedded_worker.is_running if embedded_worker else False
    mode = _executor_mode() if embedded_worker else "n/a (no embedded worker)"
    return HealthResponse(
        status="ok",
        worker_running=wr,
        embedded_worker=bool(embedded_worker),
        executor_mode=mode,
        queue_backend=backend,
    )


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    return StatsResponse(
        queue_size=job_queue.size,
        job_counts=job_store.count(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level="info",
    )

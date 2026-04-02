"""
executor/docker_executor.py — Code execution with Docker sandbox + subprocess fallback.

Resource limits are read from environment (see utils/config.py).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

from models.job import Job, JobStatus

log = logging.getLogger("executor")

DOCKER_LANGUAGES = {
    "python": {"image": "python:3.11-slim", "cmd": ["python", "-u"], "ext": ".py"},
    "node": {"image": "node:20-slim", "cmd": ["node"], "ext": ".js"},
    "bash": {"image": "bash:latest", "cmd": ["bash"], "ext": ".sh"},
}

SUBPROCESS_LANGUAGES = {
    "python": {"cmd": ["python", "-u"], "ext": ".py"},
    "node": {"cmd": ["node"], "ext": ".js"},
    "bash": {"cmd": ["bash"], "ext": ".sh"},
    "powershell": {"cmd": ["powershell", "-NoProfile", "-File"], "ext": ".ps1"},
}

_DANGEROUS_PATTERNS = [
    r"\bshutil\.rmtree\b",
    r"\bos\.remove\b",
    r"\bos\.unlink\b",
    r"\bos\.rmdir\b",
    r"\bos\.system\b",
    r"\b__import__\b",
    r"\bimport\s+subprocess\b",
    r"\bfrom\s+subprocess\b",
    r"\bimport\s+ctypes\b",
    r"\bfrom\s+ctypes\b",
    r"\bimport\s+socket\b",
    r"\bfrom\s+socket\b",
    r"\bimport\s+requests\b",
    r"\bfrom\s+urllib\b",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    r"\brm\s+-rf\b",
    r"\brmdir\b",
    r"\bdel\s+/",
    r"\bformat\s+[a-zA-Z]:",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERNS]


def _docker_resource_args() -> list[str]:
    try:
        from utils.config import (
            DOCKER_CPU_LIMIT,
            DOCKER_MEMORY_LIMIT,
            DOCKER_PIDS_LIMIT,
            DOCKER_STOP_TIMEOUT_SEC,
        )
    except ImportError:
        DOCKER_MEMORY_LIMIT = os.getenv("DOCKER_MEMORY_LIMIT", "50m")
        DOCKER_CPU_LIMIT = os.getenv("DOCKER_CPU_LIMIT", "0.5")
        DOCKER_PIDS_LIMIT = os.getenv("DOCKER_PIDS_LIMIT", "64")
        DOCKER_STOP_TIMEOUT_SEC = int(os.getenv("DOCKER_STOP_TIMEOUT_SEC", "1"))

    return [
        f"--memory={DOCKER_MEMORY_LIMIT}",
        f"--cpus={DOCKER_CPU_LIMIT}",
        f"--pids-limit={DOCKER_PIDS_LIMIT}",
        f"--stop-timeout={DOCKER_STOP_TIMEOUT_SEC}",
    ]


def _validate_code(code: str) -> Optional[str]:
    for pat in _COMPILED:
        m = pat.search(code)
        if m:
            return f"Blocked: potentially dangerous pattern '{m.group()}' detected."
    return None


def _validate_language(lang: str, docker: bool) -> Optional[str]:
    pool = DOCKER_LANGUAGES if docker else SUBPROCESS_LANGUAGES
    if lang not in pool:
        return f"Unsupported language '{lang}'. Available: {', '.join(sorted(pool))}"
    return None


class CodeExecutor:
    """Executes jobs in Docker (preferred) or local subprocess."""

    def __init__(self) -> None:
        self.docker_available = self._probe_docker()
        mode = "Docker" if self.docker_available else "subprocess (fallback)"
        log.info("CodeExecutor initialized — mode: %s", mode)

    def execute(self, job: Job) -> Job:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc).isoformat()

        use_docker = self.docker_available and job.language in DOCKER_LANGUAGES
        lang_err = _validate_language(job.language, use_docker)
        if lang_err:
            return self._fail(job, lang_err)

        sec_err = _validate_code(job.code)
        if sec_err:
            return self._fail(job, sec_err)

        if use_docker:
            return self._docker_execute(job)
        return self._subprocess_execute(job)

    def _docker_execute(self, job: Job) -> Job:
        cfg = DOCKER_LANGUAGES[job.language]
        tmp_dir = None

        try:
            tmp_dir = tempfile.mkdtemp(prefix="exec_docker_")
            filename = f"main{cfg['ext']}"
            filepath = os.path.join(tmp_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(job.code)

            res_args = _docker_resource_args()
            cmd = [
                "docker",
                "run",
                "--rm",
                *res_args,
                "--network=none",
                "--read-only",
                "-v",
                f"{tmp_dir}:/code:ro",
                "-w",
                "/code",
                cfg["image"],
                *cfg["cmd"],
                filename,
            ]

            log.info("[%s] Docker run (resource limits from env)", job.job_id)
            return self._run_process(job, cmd, job.timeout)

        except Exception as exc:
            log.exception("[%s] Docker setup failed", job.job_id)
            return self._fail(job, f"Docker execution error: {exc}")
        finally:
            if tmp_dir and os.path.exists(tmp_dir):
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _subprocess_execute(self, job: Job) -> Job:
        cfg = SUBPROCESS_LANGUAGES[job.language]
        tmp_path = None

        try:
            fd, tmp_path = tempfile.mkstemp(suffix=cfg["ext"], prefix="exec_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(job.code)

            cmd = cfg["cmd"] + [tmp_path]
            log.info("[%s] Subprocess run: %s", job.job_id, " ".join(cmd))
            return self._run_process(job, cmd, job.timeout, env=self._sandboxed_env())

        except Exception as exc:
            log.exception("[%s] Subprocess setup failed", job.job_id)
            return self._fail(job, f"Subprocess execution error: {exc}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _run_process(
        self,
        job: Job,
        cmd: list,
        timeout: int,
        env: Optional[dict] = None,
    ) -> Job:
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            elapsed = (time.perf_counter() - start) * 1000

            job.stdout = proc.stdout or ""
            job.stderr = proc.stderr or ""
            job.exit_code = proc.returncode
            job.execution_time_ms = elapsed
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.status = JobStatus.SUCCESS if proc.returncode == 0 else JobStatus.FAILED

            log.info("[%s] Completed: exit=%d, %.1fms", job.job_id, proc.returncode, elapsed)

        except subprocess.TimeoutExpired as exc:
            elapsed = (time.perf_counter() - start) * 1000
            job.timed_out = True
            job.status = JobStatus.TIMEOUT
            job.error = f"Execution timed out after {timeout}s."
            job.execution_time_ms = elapsed
            if getattr(exc, "stdout", None):
                job.stdout = exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode(errors="replace")
            if getattr(exc, "stderr", None):
                job.stderr = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode(errors="replace")
            job.completed_at = datetime.now(timezone.utc).isoformat()
            log.warning("[%s] Timed out after %ds", job.job_id, timeout)

        except FileNotFoundError:
            return self._fail(job, f"Runtime for '{job.language}' not found on PATH.")

        except Exception as exc:
            log.exception("[%s] Process run failed", job.job_id)
            return self._fail(job, f"Execution error: {exc}")

        return job

    @staticmethod
    def _fail(job: Job, error: str) -> Job:
        job.status = JobStatus.FAILED
        job.error = error
        job.completed_at = datetime.now(timezone.utc).isoformat()
        log.warning("[%s] %s", job.job_id, error)
        return job

    @staticmethod
    def _sandboxed_env() -> dict:
        safe = {"PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "LANG", "COMSPEC"}
        return {k: v for k, v in os.environ.items() if k.upper() in safe}

    @staticmethod
    def _probe_docker() -> bool:
        try:
            r = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            return r.returncode == 0
        except Exception:
            return False

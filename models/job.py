"""
models/job.py — Core job data model and status enum.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


@dataclass
class Job:
    """Represents a single code execution job throughout its lifecycle."""

    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    code: str = ""
    language: str = "python"
    timeout: int = 10
    status: JobStatus = JobStatus.QUEUED

    stdout: str = ""
    stderr: str = ""
    error: str = ""
    exit_code: int = -1
    timed_out: bool = False

    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    execution_time_ms: float = 0.0

    @property
    def output(self) -> str:
        """Primary captured output (stdout)."""
        return self.stdout

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON / Redis storage."""
        return {
            "job_id": self.job_id,
            "code": self.code,
            "language": self.language,
            "timeout": self.timeout,
            "status": self.status.value if isinstance(self.status, JobStatus) else str(self.status),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "execution_time_ms": self.execution_time_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        """Deserialize from dict (e.g. Redis JSON)."""
        d = dict(data)
        st = d.get("status", JobStatus.QUEUED.value)
        d["status"] = JobStatus(st) if isinstance(st, str) else st
        return cls(
            job_id=str(d.get("job_id", "")),
            code=str(d.get("code", "")),
            language=str(d.get("language", "python")),
            timeout=int(d.get("timeout", 10)),
            status=d["status"],
            stdout=str(d.get("stdout", "")),
            stderr=str(d.get("stderr", "")),
            error=str(d.get("error", "")),
            exit_code=int(d.get("exit_code", -1)),
            timed_out=bool(d.get("timed_out", False)),
            created_at=d.get("created_at") or datetime.now(timezone.utc).isoformat(),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            execution_time_ms=float(d.get("execution_time_ms", 0.0)),
        )

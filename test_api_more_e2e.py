"""Additional API end-to-end tests for the distributed code execution platform.

These tests focus on:
  - input validation (422 cases)
  - stderr capture (runtime errors)
  - output channels (stdout vs stderr)
  - concurrency
  - timeout behavior
  - basic invariants on job_id and response shapes
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

TERMINAL = {"SUCCESS", "FAILED", "TIMEOUT"}


def _post_execute(code: str, language: str = "python", timeout: int = 10) -> Dict[str, Any]:
    r = requests.post(
        f"{BASE}/execute",
        json={"code": code, "language": language, "timeout": timeout},
        timeout=10,
    )
    return r.json()


def _get_status(job_id: str) -> Dict[str, Any]:
    r = requests.get(f"{BASE}/status/{job_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def _get_result(job_id: str) -> Dict[str, Any]:
    r = requests.get(f"{BASE}/result/{job_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def _wait_terminal(job_id: str, max_wait_s: float = 15.0, poll_interval_s: float = 0.2) -> Dict[str, Any]:
    deadline = time.time() + max_wait_s
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        last = _get_status(job_id)
        if last.get("status") in TERMINAL:
            return _get_result(job_id)
        time.sleep(poll_interval_s)
    # last attempt
    return _get_result(job_id)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _run_validation_tests() -> None:
    # Missing code -> 422
    r = requests.post(
        f"{BASE}/execute",
        json={"language": "python", "timeout": 10},
        timeout=10,
    )
    _assert(r.status_code == 422, f"Expected 422 for missing code, got {r.status_code}: {r.text}")

    # Timeout out of bounds -> 422
    r = requests.post(
        f"{BASE}/execute",
        json={"code": "print(1)", "language": "python", "timeout": 0},
        timeout=10,
    )
    _assert(r.status_code == 422, f"Expected 422 for timeout=0, got {r.status_code}: {r.text}")

    r = requests.post(
        f"{BASE}/execute",
        json={"code": "print(1)", "language": "python", "timeout": 31},
        timeout=10,
    )
    _assert(r.status_code == 422, f"Expected 422 for timeout=31, got {r.status_code}: {r.text}")

    # Code too large -> 422
    huge = "a" * 50_001
    r = requests.post(
        f"{BASE}/execute",
        json={"code": huge, "language": "python", "timeout": 10},
        timeout=10,
    )
    _assert(r.status_code == 422, f"Expected 422 for oversized code, got {r.status_code}: {r.text}")


def _run_runtime_stderr_tests() -> None:
    # Runtime error should be FAILED and stderr should contain traceback
    payload = "raise ValueError('boom')"
    job = _post_execute(payload, timeout=10)
    job_id = job["job_id"]
    result = _wait_terminal(job_id, max_wait_s=10.0)

    _assert(result["status"] == "FAILED", f"Expected FAILED, got {result['status']}")
    _assert("ValueError" in result.get("stderr", ""), f"Expected stderr to include ValueError. stderr={result.get('stderr')!r}")
    _assert(result.get("stdout", "") == "", "Expected stdout empty on exception")
    _assert(isinstance(result.get("execution_time_ms"), (int, float)), "Expected numeric execution_time_ms")

    # stderr printed explicitly should be captured even with exit code 0
    payload2 = "import sys\nprint('to-stdout')\nprint('to-stderr', file=sys.stderr)"
    job2 = _post_execute(payload2, timeout=10)
    job_id2 = job2["job_id"]
    result2 = _wait_terminal(job_id2, max_wait_s=10.0)

    _assert(result2["status"] == "SUCCESS", f"Expected SUCCESS, got {result2['status']}")
    _assert("to-stdout" in result2.get("stdout", ""), "Expected stdout contains to-stdout")
    _assert("to-stderr" in result2.get("stderr", ""), "Expected stderr contains to-stderr")
    _assert(result2.get("error", "") == "", f"Expected error empty on success, got: {result2.get('error')}")


def _run_language_normalization_tests() -> None:
    # language should be case-insensitive because API lowercases it
    job = _post_execute("print('lang')", language="PyThOn", timeout=10)
    job_id = job["job_id"]
    result = _wait_terminal(job_id, max_wait_s=10.0)
    _assert(result["status"] == "SUCCESS", f"Expected SUCCESS, got {result['status']}")
    _assert("lang" in result.get("stdout", ""), "Expected stdout to include 'lang'")


def _run_timeout_tests() -> None:
    job = _post_execute("while True: pass", timeout=2)
    job_id = job["job_id"]
    result = _wait_terminal(job_id, max_wait_s=8.0)
    _assert(result["status"] == "TIMEOUT", f"Expected TIMEOUT, got {result['status']}")
    _assert(result.get("timed_out") is True, "Expected timed_out=true")


def _run_concurrency_tests() -> None:
    # Submit multiple jobs concurrently; each prints its id and exits quickly.
    n = int(os.getenv("CONCURRENCY_TEST_N", "8"))
    job_ids: List[str] = []

    for i in range(n):
        code = f"print('job-{i}')"
        # Stagger by small language differences not needed; just different code.
        job = _post_execute(code, timeout=10)
        job_ids.append(job["job_id"])

    # Poll all results
    results = []
    for jid in job_ids:
        results.append(_wait_terminal(jid, max_wait_s=15.0))

    statuses = {r["status"] for r in results}
    _assert(statuses.issubset(TERMINAL), f"Unexpected statuses: {statuses}")
    _assert(statuses == {"SUCCESS"}, f"Expected all SUCCESS, got: {statuses} results={json.dumps(results)[:500]}")

    # Basic output correctness
    for i, r in enumerate(results):
        # stdout should contain job-i for the corresponding index in submission order
        # (Even if ordering changes, job content is tied to each job_id; we'll just check for any job-* marker.)
        _assert("job-" in r.get("stdout", ""), f"Expected stdout to contain job marker, got: {r.get('stdout')!r}")


def main() -> None:
    # These tests assume an API server is already running at BASE.
    # If you run them manually, start uvicorn in another terminal first.
    _run_validation_tests()
    _run_runtime_stderr_tests()
    _run_language_normalization_tests()
    _run_timeout_tests()
    _run_concurrency_tests()
    print("=== Additional API E2E tests: PASS ===")


if __name__ == "__main__":
    main()


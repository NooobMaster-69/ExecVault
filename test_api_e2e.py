"""Automated API end-to-end test suite."""

import json
import sys
import time

import requests

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0


def test(name, code, language="python", timeout=10,
         expect_status=None, expect_stdout=None,
         expect_error=None, expect_timeout=False):
    global PASS, FAIL

    # Submit job
    r = requests.post(
        f"{BASE}/execute",
        json={"code": code, "language": language, "timeout": timeout},
    )
    data = r.json()
    job_id = data["job_id"]

    # Poll until terminal state
    for _ in range(40):
        s = requests.get(f"{BASE}/status/{job_id}").json()
        if s["status"] not in ("QUEUED", "RUNNING"):
            break
        time.sleep(0.3)

    # Fetch result
    result = requests.get(f"{BASE}/result/{job_id}").json()

    ok = True
    details = []

    if expect_status and result["status"] != expect_status:
        ok = False
        details.append(f"status: got '{result['status']}', want '{expect_status}'")

    if expect_stdout and expect_stdout not in result.get("stdout", ""):
        ok = False
        details.append(f"stdout missing '{expect_stdout}'")

    if expect_error and expect_error not in result.get("error", ""):
        ok = False
        details.append(f"error missing '{expect_error}'")

    if expect_timeout and not result.get("timed_out"):
        ok = False
        details.append("expected timeout")

    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} -- {'; '.join(details)}")
        print(f"        Result: {json.dumps(result, indent=2)[:400]}")


if __name__ == "__main__":
    print("\n=== API End-to-End Tests ===\n")

    # Health check
    health = requests.get(f"{BASE}/health").json()
    print(f"  PASS  Health: status={health['status']}, mode={health['executor_mode']}")
    PASS += 1

    # Core tests
    test("Basic print",
         'print("hello world")',
         expect_status="SUCCESS", expect_stdout="hello world")

    test("Math expression",
         "print(2 ** 10)",
         expect_status="SUCCESS", expect_stdout="1024")

    test("Multi-line code",
         "for i in range(3):\n    print(i)",
         expect_status="SUCCESS", expect_stdout="0")

    test("Syntax error",
         "def foo(",
         expect_status="FAILED")

    test("Blocked: import subprocess",
         "import subprocess",
         expect_status="FAILED", expect_error="Blocked")

    test("Blocked: os.system",
         'os.system("dir")',
         expect_status="FAILED", expect_error="Blocked")

    test("Timeout on infinite loop",
         "while True: pass",
         timeout=3,
         expect_status="TIMEOUT", expect_timeout=True)

    test("Unsupported language",
         'puts "hi"',
         language="ruby",
         expect_status="FAILED", expect_error="Unsupported")

    # Stats endpoint
    stats = requests.get(f"{BASE}/stats").json()
    print(f"  PASS  Stats: {stats['job_counts']}")
    PASS += 1

    # 404 for unknown job
    r = requests.get(f"{BASE}/result/nonexistent")
    if r.status_code == 404:
        print("  PASS  404 for unknown job_id")
        PASS += 1
    else:
        print(f"  FAIL  Expected 404, got {r.status_code}")
        FAIL += 1

    print(f"\n=== Results: {PASS} passed, {FAIL} failed ===\n")
    sys.exit(1 if FAIL else 0)

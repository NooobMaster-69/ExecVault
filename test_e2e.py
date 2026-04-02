"""Automated end-to-end test for the distributed code execution system."""

import json
import socket
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

from utils import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    send_msg,
    recv_msg,
    generate_auth_token,
)

PASS = 0
FAIL = 0


def run_test(name, code, language="python", expect_stdout=None, expect_error=None, expect_timeout=False):
    global PASS, FAIL

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((DEFAULT_HOST, DEFAULT_PORT))

    try:
        # Auth
        raw = recv_msg(sock)
        challenge_msg = json.loads(raw.decode())
        token = generate_auth_token(challenge_msg["challenge"])
        send_msg(sock, json.dumps({"token": token}).encode())
        auth_resp = json.loads(recv_msg(sock).decode())
        assert auth_resp["status"] == "authenticated", f"Auth failed: {auth_resp}"

        # Send code
        payload = {"code": code, "language": language, "timeout": 5}
        send_msg(sock, json.dumps(payload).encode())
        result = json.loads(recv_msg(sock).decode())

        ok = True
        details = []

        if expect_stdout is not None:
            actual = result.get("stdout", "").strip()
            if expect_stdout not in actual:
                ok = False
                details.append(f"stdout mismatch: expected '{expect_stdout}' in '{actual}'")

        if expect_error is not None:
            actual_err = result.get("error", "")
            if expect_error not in actual_err:
                ok = False
                details.append(f"error mismatch: expected '{expect_error}' in '{actual_err}'")

        if expect_timeout:
            if not result.get("timed_out", False):
                ok = False
                details.append("expected timeout but did not get one")

        if ok:
            PASS += 1
            print(f"  ✓ {name}")
        else:
            FAIL += 1
            print(f"  ✗ {name} — {'; '.join(details)}")
            print(f"    Full result: {json.dumps(result, indent=2)}")

    finally:
        sock.close()


if __name__ == "__main__":
    print("\n═══ End-to-End Tests ═══\n")

    run_test(
        "Basic print",
        'print("hello world")',
        expect_stdout="hello world",
    )

    run_test(
        "Math expression",
        'print(2 ** 10)',
        expect_stdout="1024",
    )

    run_test(
        "Multi-line code",
        'for i in range(3):\n    print(i)',
        expect_stdout="0\n1\n2",
    )

    run_test(
        "Syntax error returns stderr",
        'def foo(',
        expect_stdout=None,  # don't check stdout
    )

    run_test(
        "Blocked dangerous code (import subprocess)",
        'import subprocess',
        expect_error="Blocked",
    )

    run_test(
        "Blocked dangerous code (os.system)",
        'os.system("dir")',
        expect_error="Blocked",
    )

    run_test(
        "Timeout on infinite loop",
        'while True: pass',
        expect_timeout=True,
    )

    run_test(
        "Unsupported language",
        'puts "hello"',
        language="ruby",
        expect_error="Unsupported language",
    )

    print(f"\n═══ Results: {PASS} passed, {FAIL} failed ═══\n")
    sys.exit(1 if FAIL else 0)

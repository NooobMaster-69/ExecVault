"""
executor.py — Sandboxed code execution engine.

Runs user-submitted code in an isolated subprocess with:
  • stdout / stderr capture
  • configurable timeout
  • dangerous-pattern pre-screening
  • multi-language support (Python, Node.js, Bash, PowerShell)
"""

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional

from utils import (
    LANGUAGE_MAP,
    validate_code,
    validate_language,
    setup_logger,
)

log = setup_logger("executor")

DEFAULT_TIMEOUT = 10  # seconds


@dataclass
class ExecutionResult:
    """Structured result of a code execution run."""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    error: str = ""
    language: str = "python"
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "error": self.error,
            "language": self.language,
            "duration_ms": round(self.duration_ms, 2),
        }


def execute_code(
    code: str,
    language: str = "python",
    timeout: int = DEFAULT_TIMEOUT,
) -> ExecutionResult:
    """
    Execute *code* in the requested language inside an isolated subprocess.

    Steps:
      1. Validate language support.
      2. Screen code against dangerous-pattern blocklist.
      3. Write code to a temp file.
      4. Run via subprocess with timeout.
      5. Return structured result.
    """
    result = ExecutionResult(language=language)

    # ── 1. Language check ──
    lang_err = validate_language(language)
    if lang_err:
        result.error = lang_err
        log.warning("Language rejected: %s", lang_err)
        return result

    # ── 2. Security pre-screen ──
    sec_err = validate_code(code)
    if sec_err:
        result.error = sec_err
        log.warning("Code blocked: %s", sec_err)
        return result

    lang_cfg = LANGUAGE_MAP[language]
    ext = lang_cfg["ext"]
    cmd_prefix = lang_cfg["cmd"]

    # ── 3. Write to temp file ──
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="exec_")
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(code)

        # ── 4. Execute ──
        cmd = cmd_prefix + [tmp_path]
        log.info("Running [%s]: %s", language, " ".join(cmd))

        start = time.perf_counter()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            # Restrict the child process environment
            env=_sandboxed_env(),
        )
        elapsed = (time.perf_counter() - start) * 1000

        result.stdout = proc.stdout
        result.stderr = proc.stderr
        result.exit_code = proc.returncode
        result.duration_ms = elapsed

        log.info(
            "Finished [%s] exit=%d duration=%.1fms",
            language,
            proc.returncode,
            elapsed,
        )

    except subprocess.TimeoutExpired:
        result.timed_out = True
        result.error = f"Execution timed out after {timeout}s."
        log.warning("Timeout: code exceeded %ds limit.", timeout)

    except FileNotFoundError:
        result.error = (
            f"Runtime for '{language}' not found. "
            f"Ensure '{cmd_prefix[0]}' is installed and on PATH."
        )
        log.error(result.error)

    except Exception as exc:
        result.error = f"Execution error: {exc}"
        log.exception("Unexpected execution failure")

    finally:
        # ── 5. Cleanup temp file ──
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return result


def _sandboxed_env() -> dict:
    """
    Return a minimal environment dict for the child process.
    Strips most inherited variables to reduce attack surface.
    """
    safe_keys = {"PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "LANG", "COMSPEC"}
    return {k: v for k, v in os.environ.items() if k.upper() in safe_keys}

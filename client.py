"""
client.py — Interactive CLI client for the distributed code execution system.

Connects to the server, completes HMAC-SHA256 authentication, then enters an
interactive REPL where users can submit code snippets or files for remote execution.
"""

import json
import os
import socket
import sys

from utils import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    send_msg,
    recv_msg,
    generate_auth_token,
    setup_logger,
)

log = setup_logger("client")

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────
HOST = os.getenv("EXEC_HOST", DEFAULT_HOST)
PORT = int(os.getenv("EXEC_PORT", str(DEFAULT_PORT)))

# ──────────────────────────────────────────────────────────────
# Display helpers
# ──────────────────────────────────────────────────────────────
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _banner():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════╗
║       Distributed Code Execution Client          ║
╚══════════════════════════════════════════════════╝{RESET}
{DIM}Commands:{RESET}
  {GREEN}:file <path>{RESET}   — send a file for execution
  {GREEN}:lang <name>{RESET}   — switch language (python, node, bash, powershell)
  {GREEN}:timeout <s>{RESET}   — set execution timeout in seconds
  {GREEN}:quit{RESET}          — disconnect and exit
  {DIM}(enter a blank line to finish multi-line input){RESET}
""")


def _print_result(data: dict) -> None:
    """Pretty-print an execution result from the server."""
    status = data.get("status", "unknown")

    if status == "error":
        print(f"\n{RED}✖ Server Error:{RESET} {data.get('error', 'Unknown error')}\n")
        return

    stdout = data.get("stdout", "")
    stderr = data.get("stderr", "")
    error = data.get("error", "")
    exit_code = data.get("exit_code", -1)
    timed_out = data.get("timed_out", False)
    duration = data.get("duration_ms", 0)
    lang = data.get("language", "?")

    print(f"\n{CYAN}{'─' * 50}")
    print(f" Result  │  lang={lang}  exit={exit_code}  {duration:.1f}ms")
    print(f"{'─' * 50}{RESET}")

    if timed_out:
        print(f"{RED}⏱  Execution timed out.{RESET}")

    if error:
        print(f"{RED}⚠  {error}{RESET}")

    if stdout:
        print(f"{GREEN}stdout:{RESET}")
        print(stdout.rstrip())

    if stderr:
        print(f"{YELLOW}stderr:{RESET}")
        print(stderr.rstrip())

    print(f"{CYAN}{'─' * 50}{RESET}\n")


# ──────────────────────────────────────────────────────────────
# Core client logic
# ──────────────────────────────────────────────────────────────
class ExecutionClient:
    """Manages connection, auth, and request/response cycle."""

    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self.sock = None
        self.language = "python"
        self.timeout = 10

    # ──────── connection ────────
    def connect(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            log.info("Connected to %s:%d", self.host, self.port)
            return True
        except ConnectionRefusedError:
            log.error("Connection refused — is the server running on %s:%d?", self.host, self.port)
            return False
        except Exception as exc:
            log.error("Connection failed: %s", exc)
            return False

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None
            log.info("Disconnected.")

    # ──────── authentication ────────
    def authenticate(self) -> bool:
        raw = recv_msg(self.sock)
        if raw is None:
            log.error("No auth challenge received.")
            return False

        msg = json.loads(raw.decode())
        if msg.get("type") != "auth_challenge":
            log.error("Unexpected initial message: %s", msg)
            return False

        challenge = msg["challenge"]
        token = generate_auth_token(challenge)
        send_msg(self.sock, json.dumps({"token": token}).encode())

        raw = recv_msg(self.sock)
        if raw is None:
            log.error("No auth response received.")
            return False

        resp = json.loads(raw.decode())
        if resp.get("status") == "authenticated":
            log.info("Authenticated ✓")
            return True

        log.error("Authentication failed: %s", resp.get("error", "unknown"))
        return False

    # ──────── execution ────────
    def send_code(self, code: str):
        payload = {
            "code": code,
            "language": self.language,
            "timeout": self.timeout,
        }
        send_msg(self.sock, json.dumps(payload).encode())

        raw = recv_msg(self.sock)
        if raw is None:
            log.error("Server closed connection.")
            return None

        return json.loads(raw.decode())

    # ──────── REPL ────────
    def repl(self) -> None:
        _banner()

        while True:
            try:
                code = self._read_input()
                if code is None:
                    break  # :quit
                if not code.strip():
                    continue

                result = self.send_code(code)
                if result is None:
                    print(f"{RED}Lost connection to server.{RESET}")
                    break
                _print_result(result)

            except KeyboardInterrupt:
                print(f"\n{DIM}(Ctrl+C — type :quit to exit){RESET}")
            except Exception as exc:
                log.error("Client error: %s", exc)

    def _read_input(self):
        """Read multi-line input, or handle : commands."""
        prompt = f"{GREEN}{self.language}{RESET}» "
        try:
            first_line = input(prompt)
        except EOFError:
            return None

        # ── : commands ──
        if first_line.startswith(":"):
            return self._handle_meta(first_line)

        lines = [first_line]
        while True:
            try:
                line = input(f"{DIM}...{RESET} ")
            except EOFError:
                break
            if line == "":
                break
            lines.append(line)

        return "\n".join(lines)

    def _handle_meta(self, cmd: str):
        parts = cmd.split(maxsplit=1)
        directive = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if directive == ":quit":
            return None

        if directive == ":lang":
            if arg:
                self.language = arg
                print(f"{DIM}Language set to: {arg}{RESET}")
            else:
                print(f"{DIM}Current language: {self.language}{RESET}")
            return ""

        if directive == ":timeout":
            if arg.isdigit():
                self.timeout = int(arg)
                print(f"{DIM}Timeout set to: {self.timeout}s{RESET}")
            else:
                print(f"{DIM}Current timeout: {self.timeout}s{RESET}")
            return ""

        if directive == ":file":
            if not arg:
                print(f"{RED}Usage: :file <path>{RESET}")
                return ""
            return self._load_file(arg)

        print(f"{YELLOW}Unknown command: {directive}{RESET}")
        return ""

    @staticmethod
    def _load_file(path: str) -> str:
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            print(f"{RED}File not found: {path}{RESET}")
            return ""
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        print(f"{DIM}Loaded {len(code)} bytes from {path}{RESET}")
        return code


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────
def main():
    client = ExecutionClient()

    if not client.connect():
        sys.exit(1)

    try:
        if not client.authenticate():
            sys.exit(1)
        client.repl()
    finally:
        client.close()


if __name__ == "__main__":
    main()
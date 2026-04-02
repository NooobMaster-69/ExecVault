"""
server.py — Multi-client code execution server.

Accepts TCP connections, authenticates clients via HMAC-SHA256 challenge/response,
receives JSON-encoded execution requests, delegates to executor.py, and returns
structured results — all over a length-prefixed binary protocol.
"""

import json
import os
import socket
import threading
import uuid
from typing import Optional

from utils import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    send_msg,
    recv_msg,
    generate_auth_token,
    verify_auth_token,
    setup_logger,
)
from executor import execute_code

log = setup_logger("server")

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────
HOST = os.getenv("EXEC_HOST", DEFAULT_HOST)
PORT = int(os.getenv("EXEC_PORT", str(DEFAULT_PORT)))
MAX_CLIENTS = int(os.getenv("EXEC_MAX_CLIENTS", "20"))
EXECUTION_TIMEOUT = int(os.getenv("EXEC_TIMEOUT", "10"))


class ClientHandler(threading.Thread):
    """Handle a single client connection on its own thread."""

    def __init__(self, conn: socket.socket, addr: tuple):
        super().__init__(daemon=True)
        self.conn = conn
        self.addr = addr
        self.client_id = str(uuid.uuid4())[:8]
        self.authenticated = False

    # ──────── lifecycle ────────
    def run(self) -> None:
        tag = f"[{self.client_id}@{self.addr[0]}:{self.addr[1]}]"
        log.info("%s Connected", tag)
        try:
            if not self._authenticate(tag):
                self._send_error("Authentication failed.")
                return

            self.authenticated = True
            log.info("%s Authenticated ✓", tag)
            self._send_json({"status": "authenticated", "message": "Ready for code execution."})

            # ── Main request loop ──
            while True:
                raw = recv_msg(self.conn)
                if raw is None:
                    log.info("%s Disconnected", tag)
                    break

                self._handle_request(raw, tag)

        except ConnectionResetError:
            log.warning("%s Connection reset", tag)
        except Exception as exc:
            log.exception("%s Unexpected error: %s", tag, exc)
        finally:
            self.conn.close()
            log.info("%s Socket closed", tag)

    # ──────── authentication ────────
    def _authenticate(self, tag: str) -> bool:
        """HMAC-SHA256 challenge/response authentication."""
        challenge = uuid.uuid4().hex
        self._send_json({"type": "auth_challenge", "challenge": challenge})

        raw = recv_msg(self.conn)
        if raw is None:
            return False

        try:
            msg = json.loads(raw.decode())
            token = msg.get("token", "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.warning("%s Malformed auth response", tag)
            return False

        if not verify_auth_token(challenge, token):
            log.warning("%s Invalid auth token", tag)
            return False

        return True

    # ──────── request handling ────────
    def _handle_request(self, raw: bytes, tag: str) -> None:
        """Parse and dispatch a single execution request."""
        try:
            request = json.loads(raw.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_error("Invalid JSON payload.")
            return

        code = request.get("code")
        if not code or not isinstance(code, str):
            self._send_error("Missing or invalid 'code' field.")
            return

        language = request.get("language", "python").lower().strip()
        timeout = min(int(request.get("timeout", EXECUTION_TIMEOUT)), 30)  # cap at 30s

        log.info(
            "%s Executing %d bytes of %s (timeout=%ds)",
            tag,
            len(code),
            language,
            timeout,
        )

        result = execute_code(code, language=language, timeout=timeout)
        self._send_json({"status": "result", **result.to_dict()})

    # ──────── helpers ────────
    def _send_json(self, obj: dict) -> None:
        send_msg(self.conn, json.dumps(obj).encode())

    def _send_error(self, message: str) -> None:
        self._send_json({"status": "error", "error": message})


# ──────────────────────────────────────────────────────────────
# Server entry point
# ──────────────────────────────────────────────────────────────
def start_server(host: str = HOST, port: int = PORT) -> None:
    """Bind, listen, and dispatch client threads."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(MAX_CLIENTS)

    log.info("═" * 55)
    log.info("  Code Execution Server listening on %s:%d", host, port)
    log.info("  Max clients: %d | Timeout: %ds", MAX_CLIENTS, EXECUTION_TIMEOUT)
    log.info("═" * 55)

    try:
        while True:
            conn, addr = srv.accept()
            handler = ClientHandler(conn, addr)
            handler.start()
    except KeyboardInterrupt:
        log.info("Shutting down (Ctrl+C)…")
    finally:
        srv.close()
        log.info("Server socket closed.")


if __name__ == "__main__":
    start_server()
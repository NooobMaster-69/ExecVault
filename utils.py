"""
utils.py — Shared utilities for the distributed code execution system.

Handles protocol framing, logging setup, auth tokens, and input validation.
"""

import hashlib
import hmac
import logging
import os
import re
import struct
from typing import Optional

# ──────────────────────────────────────────────────────────────
# Protocol Constants
# ──────────────────────────────────────────────────────────────
HEADER_SIZE = 4  # 4-byte big-endian length prefix
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9900
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024  # 5 MB hard cap
RECV_CHUNK = 4096
AUTH_SECRET = os.getenv("AUTH_SECRET", "s3cur3-sh4red-k3y-2026")

# Supported languages and their interpreters (cross-platform)
LANGUAGE_MAP = {
    "python": {"cmd": ["python", "-u"], "ext": ".py"},
    "node": {"cmd": ["node"], "ext": ".js"},
    "bash": {"cmd": ["bash"], "ext": ".sh"},
    "powershell": {"cmd": ["powershell", "-NoProfile", "-Command"], "ext": ".ps1"},
}

# ──────────────────────────────────────────────────────────────
# Dangerous Pattern Blocklist
# ──────────────────────────────────────────────────────────────
DANGEROUS_PATTERNS = [
    # File-system destruction
    r"\bshutil\.rmtree\b",
    r"\bos\.remove\b",
    r"\bos\.unlink\b",
    r"\bos\.rmdir\b",
    r"\bos\.system\b",
    # Process / import abuse
    r"\b__import__\b",
    r"\bimport\s+subprocess\b",
    r"\bfrom\s+subprocess\b",
    r"\bimport\s+ctypes\b",
    r"\bfrom\s+ctypes\b",
    # Network exfiltration
    r"\bimport\s+socket\b",
    r"\bfrom\s+socket\b",
    r"\bimport\s+requests\b",
    r"\bfrom\s+urllib\b",
    # Eval / exec chains
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    # Windows-specific destructive commands (for non-python languages)
    r"\brmdir\b",
    r"\bdel\s+/",
    r"\bformat\s+[a-zA-Z]:",
    r"\brm\s+-rf\b",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]


# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────
def setup_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    """Create a consistently formatted logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


# ──────────────────────────────────────────────────────────────
# Length-prefixed framing  (4-byte big-endian + payload)
# ──────────────────────────────────────────────────────────────
def send_msg(sock, data: bytes) -> None:
    """Send a length-prefixed message over a socket."""
    length = len(data)
    header = struct.pack("!I", length)
    sock.sendall(header + data)


def recv_msg(sock) -> Optional[bytes]:
    """Receive a length-prefixed message. Returns None on disconnect."""
    raw_header = _recv_exact(sock, HEADER_SIZE)
    if raw_header is None:
        return None
    (msg_len,) = struct.unpack("!I", raw_header)
    if msg_len > MAX_PAYLOAD_BYTES:
        raise ValueError(f"Payload too large: {msg_len} bytes (max {MAX_PAYLOAD_BYTES})")
    return _recv_exact(sock, msg_len)


def _recv_exact(sock, n: int) -> Optional[bytes]:
    """Read exactly *n* bytes from socket. Returns None on clean disconnect."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(RECV_CHUNK, n - len(buf)))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# ──────────────────────────────────────────────────────────────
# Authentication helpers  (HMAC-SHA256 challenge / response)
# ──────────────────────────────────────────────────────────────
def generate_auth_token(challenge: str, secret: str = AUTH_SECRET) -> str:
    """Produce HMAC-SHA256 hex digest for a given challenge string."""
    return hmac.new(
        secret.encode(), challenge.encode(), hashlib.sha256
    ).hexdigest()


def verify_auth_token(challenge: str, token: str, secret: str = AUTH_SECRET) -> bool:
    """Constant-time comparison of the expected token."""
    expected = generate_auth_token(challenge, secret)
    return hmac.compare_digest(expected, token)


# ──────────────────────────────────────────────────────────────
# Input Validation
# ──────────────────────────────────────────────────────────────
def validate_code(code: str) -> Optional[str]:
    """
    Scan *code* against the blocklist.
    Returns an error message if dangerous content detected, else None.
    """
    for pattern in _COMPILED_PATTERNS:
        match = pattern.search(code)
        if match:
            return f"Blocked: potentially dangerous pattern '{match.group()}' detected."
    return None


def validate_language(lang: str) -> Optional[str]:
    """Return error string if lang is unsupported, else None."""
    if lang not in LANGUAGE_MAP:
        supported = ", ".join(sorted(LANGUAGE_MAP.keys()))
        return f"Unsupported language '{lang}'. Supported: {supported}"
    return None

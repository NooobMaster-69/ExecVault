"""
utils package — Shared utilities for the code execution platform.

This __init__.py contains the original socket-protocol utilities (auth, framing,
validation, logging) so that existing imports like `from utils import send_msg`
continue to work unchanged.
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
HEADER_SIZE = 4
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9900
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024
RECV_CHUNK = 4096
AUTH_SECRET = os.getenv("AUTH_SECRET", "s3cur3-sh4red-k3y-2026")

LANGUAGE_MAP = {
    "python":     {"cmd": ["python", "-u"],                          "ext": ".py"},
    "node":       {"cmd": ["node"],                                  "ext": ".js"},
    "bash":       {"cmd": ["bash"],                                  "ext": ".sh"},
    "powershell": {"cmd": ["powershell", "-NoProfile", "-Command"],  "ext": ".ps1"},
}

# ──────────────────────────────────────────────────────────────
# Dangerous Pattern Blocklist
# ──────────────────────────────────────────────────────────────
DANGEROUS_PATTERNS = [
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
# Length-prefixed framing
# ──────────────────────────────────────────────────────────────
def send_msg(sock, data: bytes) -> None:
    length = len(data)
    header = struct.pack("!I", length)
    sock.sendall(header + data)


def recv_msg(sock) -> Optional[bytes]:
    raw_header = _recv_exact(sock, HEADER_SIZE)
    if raw_header is None:
        return None
    (msg_len,) = struct.unpack("!I", raw_header)
    if msg_len > MAX_PAYLOAD_BYTES:
        raise ValueError(f"Payload too large: {msg_len} bytes (max {MAX_PAYLOAD_BYTES})")
    return _recv_exact(sock, msg_len)


def _recv_exact(sock, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(RECV_CHUNK, n - len(buf)))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# ──────────────────────────────────────────────────────────────
# Authentication (HMAC-SHA256)
# ──────────────────────────────────────────────────────────────
def generate_auth_token(challenge: str, secret: str = AUTH_SECRET) -> str:
    return hmac.new(
        secret.encode(), challenge.encode(), hashlib.sha256
    ).hexdigest()


def verify_auth_token(challenge: str, token: str, secret: str = AUTH_SECRET) -> bool:
    expected = generate_auth_token(challenge, secret)
    return hmac.compare_digest(expected, token)


# ──────────────────────────────────────────────────────────────
# Input Validation
# ──────────────────────────────────────────────────────────────
def validate_code(code: str) -> Optional[str]:
    for pattern in _COMPILED_PATTERNS:
        match = pattern.search(code)
        if match:
            return f"Blocked: potentially dangerous pattern '{match.group()}' detected."
    return None


def validate_language(lang: str) -> Optional[str]:
    if lang not in LANGUAGE_MAP:
        supported = ", ".join(sorted(LANGUAGE_MAP.keys()))
        return f"Unsupported language '{lang}'. Supported: {supported}"
    return None

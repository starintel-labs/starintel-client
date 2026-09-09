"""Correlation id generation and validation.

Mirrors the server's acceptance rule (starintel-server ``http-auth.lisp``):
length 1..128, ASCII alphanumeric plus ``-`` ``_`` ``.`` ``:``. Ids outside
those bounds are replaced server-side, so the client validates up front.
"""

from __future__ import annotations

import re
import secrets
import time

__all__ = ["new_correlation_id", "validate_correlation_id"]

_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")


def new_correlation_id() -> str:
    """Generate a time-ordered, charset-valid correlation id."""
    timestamp = format(time.time_ns() & ((1 << 48) - 1), "012x")
    return f"{timestamp}{secrets.token_hex(8)}"


def validate_correlation_id(value: str) -> str:
    """Return ``value`` when it fits the server's bounded correlation id rule."""
    if not _CORRELATION_ID_RE.fullmatch(value):
        raise ValueError(
            "correlation id must be 1..128 chars of [A-Za-z0-9_.:-], got: "
            f"{value[:16]!r}..."
        )
    return value

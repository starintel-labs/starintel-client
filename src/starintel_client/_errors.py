"""Normalized StarIntel client errors."""

from __future__ import annotations

from typing import Any

__all__ = [
    "ManifestError",
    "StarIntelApiError",
    "StarIntelClientError",
    "StarIntelConnectionError",
    "UnknownOperationError",
    "error_from_payload",
]


class StarIntelClientError(Exception):
    """Base class for every starintel-client failure."""


class StarIntelConnectionError(StarIntelClientError):
    """The transport failed (connection error, timeout) after bounded retries."""


class ManifestError(StarIntelClientError):
    """The contract registry payload is invalid, inconsistent, or forbidden."""


class UnknownOperationError(StarIntelClientError):
    """The requested operation id is not in the validated registry."""


class StarIntelApiError(StarIntelClientError):
    """Normalized server error envelope.

    Carries the HTTP status, the human message, the correlation id, and the
    server's stable error code when present.
    """

    def __init__(
        self,
        status_code: int,
        msg: str,
        correlation_id: str | None = None,
        code: str | None = None,
        info: Any = None,
    ) -> None:
        detail = f"[{status_code}] {msg} (code={code!r}, correlation_id={correlation_id!r})"
        super().__init__(detail)
        self.status_code = status_code
        self.msg = msg
        self.correlation_id = correlation_id
        self.code = code
        self.info = info


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def error_from_payload(status_code: int, payload: Any) -> StarIntelApiError:
    """Build a :class:`StarIntelApiError` from any server error body.

    Tolerates non-JSON bodies and envelopes missing optional fields; the
    contract only pins ``msg``/``status``/``correlation_id`` with ``code``
    usually present.
    """
    if isinstance(payload, dict):
        msg = payload.get("msg")
        if not isinstance(msg, str) or not msg:
            msg = f"request failed with HTTP status {status_code}"
        info = payload.get("info")
        return StarIntelApiError(
            status_code=status_code,
            msg=msg,
            correlation_id=_optional_str(payload, "correlation_id"),
            code=_optional_str(payload, "code"),
            info=info,
        )
    return StarIntelApiError(
        status_code=status_code,
        msg=f"request failed with HTTP status {status_code}",
    )

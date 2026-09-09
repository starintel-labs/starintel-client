"""Typed payload models for the contract-pinned response schemas.

Only the schemas the contract pins (user metadata, credential metadata and
their envelopes) get dataclasses; free-form payloads stay parsed JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "CredentialMetadata",
    "CredentialSecret",
    "CredentialStatus",
    "LoginResult",
    "UserMetadata",
    "UserStatus",
]


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"expected string field {key!r}, got {value!r}")
    return value


def _require_str_list(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"expected string list field {key!r}, got {value!r}")
    return tuple(value)


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class UserMetadata:
    """``user-metadata-schema`` from the contract."""

    username: str
    principal_type: str
    scopes: tuple[str, ...]
    status: str
    created_at: int | None = None
    password_updated_at: int | None = None
    must_change_password: bool | None = None

    @classmethod
    def from_payload(cls, payload: Any) -> UserMetadata:
        if not isinstance(payload, dict):
            raise ValueError("user metadata must be a JSON object")
        must_change = payload.get("must_change_password")
        return cls(
            username=_require_str(payload, "username"),
            principal_type=_require_str(payload, "principal_type"),
            scopes=_require_str_list(payload, "scopes"),
            status=_require_str(payload, "status"),
            created_at=_optional_int(payload, "created_at"),
            password_updated_at=_optional_int(payload, "password_updated_at"),
            must_change_password=must_change if isinstance(must_change, bool) else None,
        )


@dataclass(frozen=True)
class CredentialMetadata:
    """``credential-metadata-schema`` from the contract."""

    id: str
    owner: str
    principal_type: str
    scopes: tuple[str, ...]
    status: str
    created_at: int | None = None

    @classmethod
    def from_payload(cls, payload: Any) -> CredentialMetadata:
        if not isinstance(payload, dict):
            raise ValueError("credential metadata must be a JSON object")
        credential_id = payload.get("credential_id")
        if not isinstance(credential_id, str):
            credential_id = _require_str(payload, "id")
        return cls(
            id=credential_id,
            owner=_require_str(payload, "owner"),
            principal_type=_require_str(payload, "principal_type"),
            scopes=_require_str_list(payload, "scopes"),
            status=_require_str(payload, "status"),
            created_at=_optional_int(payload, "created_at"),
        )


@dataclass(frozen=True)
class LoginResult:
    """200 response of ``auth.login``."""

    api_key: str
    credential: CredentialMetadata
    user: UserMetadata
    correlation_id: str | None = None

    @classmethod
    def from_payload(cls, payload: Any) -> LoginResult:
        if not isinstance(payload, dict):
            raise ValueError("login result must be a JSON object")
        return cls(
            api_key=_require_str(payload, "api_key"),
            credential=CredentialMetadata.from_payload(payload.get("credential")),
            user=UserMetadata.from_payload(payload.get("user")),
            correlation_id=payload.get("correlation_id")
            if isinstance(payload.get("correlation_id"), str)
            else None,
        )


@dataclass(frozen=True)
class CredentialSecret:
    """201 response of credential creation/rotation (secret shown once)."""

    api_key: str
    credential: CredentialMetadata
    correlation_id: str | None = None

    @classmethod
    def from_payload(cls, payload: Any) -> CredentialSecret:
        if not isinstance(payload, dict):
            raise ValueError("credential secret must be a JSON object")
        return cls(
            api_key=_require_str(payload, "api_key"),
            credential=CredentialMetadata.from_payload(payload.get("credential")),
            correlation_id=payload.get("correlation_id")
            if isinstance(payload.get("correlation_id"), str)
            else None,
        )


@dataclass(frozen=True)
class UserStatus:
    """Envelope of user lifecycle operations carrying the affected user."""

    status: str
    msg: str
    user: UserMetadata
    correlation_id: str | None = None

    @classmethod
    def from_payload(cls, payload: Any) -> UserStatus:
        if not isinstance(payload, dict):
            raise ValueError("user status must be a JSON object")
        return cls(
            status=_require_str(payload, "status"),
            msg=_require_str(payload, "msg"),
            user=UserMetadata.from_payload(payload.get("user")),
            correlation_id=payload.get("correlation_id")
            if isinstance(payload.get("correlation_id"), str)
            else None,
        )


@dataclass(frozen=True)
class CredentialStatus:
    """Envelope of credential revoke/disable operations."""

    status: str
    msg: str
    credential: CredentialMetadata
    correlation_id: str | None = None

    @classmethod
    def from_payload(cls, payload: Any) -> CredentialStatus:
        if not isinstance(payload, dict):
            raise ValueError("credential status must be a JSON object")
        return cls(
            status=_require_str(payload, "status"),
            msg=_require_str(payload, "msg"),
            credential=CredentialMetadata.from_payload(payload.get("credential")),
            correlation_id=payload.get("correlation_id")
            if isinstance(payload.get("correlation_id"), str)
            else None,
        )


def _envelope_field(payload: Any, key: str) -> str | None:
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return None

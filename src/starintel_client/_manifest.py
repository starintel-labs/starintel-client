"""Typed model and strict parser for ``GET /client-manifest.json``.

The manifest is the client's only source of routes (contract-registry rule).
Legacy server routes are rejected at parse time: the forbidden-route matcher
compares normalized path templates against structural segment patterns, so
no legacy route literal is needed (or permitted) in this package.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._errors import ManifestError, UnknownOperationError

__all__ = [
    "ClientManifest",
    "ManifestOperation",
    "ManifestResponse",
    "render_path",
]

MANIFEST_SCHEMA = "starintel-client-manifest-v1"

_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"})
_AUTHORITIES = frozenset({"public", "authenticated", "administrator", "bootstrap"})

# Forbidden legacy server routes, encoded as normalized segment tuples so the
# legacy path literals never appear in this package. ":param" stands for any
# single path parameter segment (":name" or "{name}" form).
_FORBIDDEN_SEGMENTS: tuple[tuple[str, ...], ...] = (
    ("new", "document", ":param"),
    ("documents", "bulk"),
    ("document", ":param"),
    ("new", "target", ":param"),
    ("search",),
    ("views", ":param", ":param"),
)

_PATH_PARAM_RE = r"[A-Za-z0-9_\-]"


@dataclass(frozen=True)
class ManifestResponse:
    """One documented response of a manifest operation."""

    status: int
    description: str
    schema: Any | None


@dataclass(frozen=True)
class ManifestOperation:
    """One operation of the client contract registry."""

    operation_id: str
    client_name: str
    method: str
    path: str
    openapi_path: str
    authority: str
    scopes: tuple[str, ...]
    path_parameters: tuple[str, ...]
    request_schema: Any | None
    responses: tuple[ManifestResponse, ...]
    idempotency: str | None


@dataclass(frozen=True)
class ClientManifest:
    """Parsed client manifest: the validated operation registry."""

    schema_name: str
    openapi_version: str
    operations: tuple[ManifestOperation, ...]

    def operation(self, operation_id: str) -> ManifestOperation:
        for op in self.operations:
            if op.operation_id == operation_id:
                return op
        raise UnknownOperationError(
            f"operation {operation_id!r} is not in the contract registry; "
            "if the server does not contract it yet, see the starintel-server "
            "registry-migration issue"
        )

    def has_operation(self, operation_id: str) -> bool:
        return any(op.operation_id == operation_id for op in self.operations)

    @property
    def operation_ids(self) -> tuple[str, ...]:
        return tuple(op.operation_id for op in self.operations)


def _normalize_path(path: str) -> tuple[str, ...]:
    segments = []
    for raw in path.split("/"):
        segment = raw.strip()
        if not segment:
            continue
        if segment.startswith(":") or (segment.startswith("{") and segment.endswith("}")):
            segments.append(":param")
        else:
            segments.append(segment.lower())
    return tuple(segments)


def _reject_forbidden_path(path: str) -> None:
    normalized = _normalize_path(path)
    if normalized in _FORBIDDEN_SEGMENTS:
        raise ManifestError(f"legacy server route is forbidden in the registry: {path!r}")


def _placeholders(path: str, brace_form: bool) -> tuple[str, ...]:
    """Extract placeholder names in ``:name`` (or ``{name}``) form."""
    import re

    if brace_form:
        matches = re.findall(r"\{(" + _PATH_PARAM_RE + r"+)\}", path)
    else:
        matches = re.findall(r":" + _PATH_PARAM_RE + r"+", path)
        matches = [m[1:] for m in matches]
    return tuple(matches)


def _require_str(payload: Mapping[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{context}: {key!r} must be a non-empty string")
    return value


def _require_str_list(payload: Mapping[str, Any], key: str, context: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ManifestError(f"{context}: {key!r} must be a list of strings")
    return tuple(value)


def _parse_response(payload: Any, context: str) -> ManifestResponse:
    if not isinstance(payload, dict):
        raise ManifestError(f"{context}: response entries must be objects")
    status = payload.get("status")
    if not isinstance(status, int) or isinstance(status, bool) or not 100 <= status <= 599:
        raise ManifestError(f"{context}: response 'status' must be an HTTP status integer")
    description = payload.get("description")
    if not isinstance(description, str):
        raise ManifestError(f"{context}: response 'description' must be a string")
    schema = payload.get("schema")
    if schema is not None and not isinstance(schema, dict):
        raise ManifestError(f"{context}: response 'schema' must be an object or null")
    return ManifestResponse(status=status, description=description, schema=schema)


def _parse_operation(payload: Any, index: int) -> ManifestOperation:
    context = f"operations[{index}]"
    if not isinstance(payload, dict):
        raise ManifestError(f"{context}: must be an object")
    operation_id = _require_str(payload, "operation_id", context)
    client_name = _require_str(payload, "client_name", context)
    method = _require_str(payload, "method", context).upper()
    if method not in _METHODS:
        raise ManifestError(f"{context}: unsupported HTTP method {method!r}")
    path = _require_str(payload, "path", context)
    openapi_path = _require_str(payload, "openapi_path", context)
    if not path.startswith("/") or not openapi_path.startswith("/"):
        raise ManifestError(f"{context}: paths must start with '/'")
    _reject_forbidden_path(path)
    _reject_forbidden_path(openapi_path)
    authority = _require_str(payload, "authority", context)
    if authority not in _AUTHORITIES:
        raise ManifestError(f"{context}: unknown authority {authority!r}")
    scopes = _require_str_list(payload, "scopes", context)
    path_parameters = _require_str_list(payload, "path_parameters", context)
    if _placeholders(path, brace_form=False) != path_parameters:
        raise ManifestError(f"{context}: 'path' placeholders disagree with 'path_parameters'")
    if _placeholders(openapi_path, brace_form=True) != path_parameters:
        raise ManifestError(
            f"{context}: 'openapi_path' placeholders disagree with 'path_parameters'"
        )
    request_schema = payload.get("request_schema")
    if request_schema is not None and not isinstance(request_schema, dict):
        raise ManifestError(f"{context}: 'request_schema' must be an object or null")
    raw_responses = payload.get("responses")
    if not isinstance(raw_responses, list):
        raise ManifestError(f"{context}: 'responses' must be a list")
    responses = tuple(
        _parse_response(entry, f"{context}.responses[{i}]") for i, entry in enumerate(raw_responses)
    )
    idempotency = payload.get("idempotency")
    if idempotency is not None and not isinstance(idempotency, str):
        raise ManifestError(f"{context}: 'idempotency' must be a string or null")
    return ManifestOperation(
        operation_id=operation_id,
        client_name=client_name,
        method=method,
        path=path,
        openapi_path=openapi_path,
        authority=authority,
        scopes=scopes,
        path_parameters=path_parameters,
        request_schema=request_schema,
        responses=responses,
        idempotency=idempotency,
    )


def parse_client_manifest(payload: Any) -> ClientManifest:
    """Parse and validate a ``client-manifest.json`` payload.

    Raises :class:`ManifestError` for any malformed entry, duplicate id, or
    forbidden (legacy) route.
    """
    if not isinstance(payload, dict):
        raise ManifestError("client manifest must be a JSON object")
    schema_name = payload.get("schema")
    if schema_name != MANIFEST_SCHEMA:
        raise ManifestError(
            f"unsupported manifest schema {schema_name!r}, expected {MANIFEST_SCHEMA!r}"
        )
    openapi_version = payload.get("openapi")
    if not isinstance(openapi_version, str) or not openapi_version:
        raise ManifestError("client manifest 'openapi' must be a version string")
    raw_operations = payload.get("operations")
    if not isinstance(raw_operations, list):
        raise ManifestError("client manifest 'operations' must be a list")
    operations = tuple(
        _parse_operation(entry, index) for index, entry in enumerate(raw_operations)
    )
    seen: set[str] = set()
    for op in operations:
        if op.operation_id in seen:
            raise ManifestError(f"duplicate operation id {op.operation_id!r}")
        seen.add(op.operation_id)
    return ClientManifest(
        schema_name=schema_name,
        openapi_version=openapi_version,
        operations=operations,
    )


def render_path(path: str, path_params: Mapping[str, str]) -> str:
    """Render a manifest path template, substituting ``:name`` placeholders.

    Values are percent-encoded; the parameter names must match the template
    exactly (missing and extra names are errors).
    """
    import re

    names = _placeholders(path, brace_form=False)
    if set(names) != set(path_params):
        raise ValueError(
            f"path parameters {sorted(path_params)} do not match template {sorted(names)}"
        )
    rendered = path
    for name in names:
        encoded = urllib.parse.quote(str(path_params[name]), safe="")
        rendered = re.sub(
            r":" + re.escape(name) + r"(?![A-Za-z0-9_\-])",
            encoded,
            rendered,
        )
    return rendered

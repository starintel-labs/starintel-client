"""Typed model and parser for ``GET /openapi.json`` plus registry cross-check."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ._errors import ManifestError
from ._manifest import ClientManifest

__all__ = ["OpenApiDocument", "OpenApiOperation", "cross_check", "parse_openapi_document"]

_METHODS = frozenset({"get", "post", "put", "delete", "patch", "head"})


@dataclass(frozen=True)
class OpenApiOperation:
    """One operation object of the OpenAPI document."""

    operation_id: str
    authority: str | None
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class OpenApiDocument:
    """Parsed OpenAPI document: ``paths`` keyed by path then uppercase method."""

    version: str
    title: str
    paths: Mapping[str, Mapping[str, OpenApiOperation]] = field(default_factory=dict)

    def operation(self, path: str, method: str) -> OpenApiOperation | None:
        entry = self.paths.get(path)
        if entry is None:
            return None
        return entry.get(method.upper())


def _parse_operation(payload: Any, path: str, method: str) -> OpenApiOperation:
    context = f"paths[{path!r}][{method!r}]"
    if not isinstance(payload, dict):
        raise ManifestError(f"openapi {context}: must be an object")
    operation_id = payload.get("operationId")
    if not isinstance(operation_id, str) or not operation_id:
        raise ManifestError(f"openapi {context}: 'operationId' must be a non-empty string")
    authority = payload.get("x-starintel-authority")
    if authority is not None and not isinstance(authority, str):
        raise ManifestError(f"openapi {context}: 'x-starintel-authority' must be a string")
    raw_scopes = payload.get("x-starintel-scopes")
    if raw_scopes is not None and (
        not isinstance(raw_scopes, list) or not all(isinstance(s, str) for s in raw_scopes)
    ):
        raise ManifestError(f"openapi {context}: 'x-starintel-scopes' must be a list of strings")
    scopes = tuple(raw_scopes) if isinstance(raw_scopes, list) else ()
    return OpenApiOperation(operation_id=operation_id, authority=authority, scopes=scopes)


def parse_openapi_document(payload: Any) -> OpenApiDocument:
    """Parse and validate an ``openapi.json`` payload."""
    if not isinstance(payload, dict):
        raise ManifestError("openapi document must be a JSON object")
    version = payload.get("openapi")
    if not isinstance(version, str) or not version:
        raise ManifestError("openapi document 'openapi' must be a version string")
    info = payload.get("info")
    if not isinstance(info, dict):
        raise ManifestError("openapi document 'info' must be an object")
    title = info.get("title")
    if not isinstance(title, str) or not title:
        raise ManifestError("openapi document 'info.title' must be a non-empty string")
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, dict):
        raise ManifestError("openapi document 'paths' must be an object")
    paths: dict[str, dict[str, OpenApiOperation]] = {}
    for path, path_item in raw_paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            raise ManifestError(f"openapi path entry {path!r} must be an object")
        methods: dict[str, OpenApiOperation] = {}
        for method, operation in path_item.items():
            if method.lower() not in _METHODS:
                continue
            if method != method.lower():
                raise ManifestError(f"openapi path {path!r}: method keys must be lowercase")
            methods[method.upper()] = _parse_operation(operation, path, method)
        paths[path] = methods
    return OpenApiDocument(version=version, title=title, paths=paths)


def cross_check(manifest: ClientManifest, document: OpenApiDocument) -> None:
    """Verify every manifest operation is present in the OpenAPI document.

    Raises :class:`ManifestError` when the two registry documents drift.
    """
    for op in manifest.operations:
        entry = document.operation(op.openapi_path, op.method)
        if entry is None:
            raise ManifestError(
                f"registry drift: operation {op.operation_id!r} ({op.method} "
                f"{op.openapi_path!r}) is missing from the OpenAPI document"
            )
        if entry.operation_id != op.client_name:
            raise ManifestError(
                f"registry drift: operation {op.operation_id!r} has client_name "
                f"{op.client_name!r} but OpenAPI operationId {entry.operation_id!r}"
            )

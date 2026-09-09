"""Hermetic tests for registry parsing, legacy rejection, correlation, errors.

The fixtures mirror the shapes emitted by starintel-server's
STAR.HTTP.CONTRACT package (verified 2026-09-08).
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from starintel_client._correlation import new_correlation_id, validate_correlation_id
from starintel_client._errors import (
    ManifestError,
    StarIntelApiError,
    UnknownOperationError,
    error_from_payload,
)
from starintel_client._manifest import parse_client_manifest, render_path
from starintel_client._openapi import parse_openapi_document

# ---- Contract fixtures ------------------------------------------------------


def _op(**overrides: Any) -> dict[str, Any]:
    op: dict[str, Any] = {
        "operation_id": "health.get",
        "client_name": "health",
        "method": "get",
        "path": "/health",
        "openapi_path": "/health",
        "authority": "public",
        "scopes": [],
        "path_parameters": [],
        "request_schema": None,
        "responses": [{"status": 200, "description": "ok", "schema": None}],
        "idempotency": None,
    }
    op.update(overrides)
    return op


def fixture_manifest(operations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema": "starintel-client-manifest-v1",
        "openapi": "3.1.2",
        "operations": operations
        if operations is not None
        else [
            _op(),
            _op(
                operation_id="auth.credentials.rotate",
                client_name="auth-rotate-credential",
                method="post",
                path="/auth/credentials/:credential-id/rotate",
                openapi_path="/auth/credentials/{credential-id}/rotate",
                authority="administrator",
                scopes=["admin"],
                path_parameters=["credential-id"],
                request_schema={
                    "type": "object",
                    "properties": {
                        "overlap_seconds": {"type": "integer", "minimum": 0}
                    },
                    "required": ["overlap_seconds"],
                    "additionalProperties": False,
                },
                responses=[
                    {
                        "status": 201,
                        "description": "Credential rotated.",
                        "schema": {"type": "object"},
                    }
                ],
            ),
        ],
    }


def fixture_openapi() -> dict[str, Any]:
    return {
        "openapi": "3.1.2",
        "info": {"title": "StarIntel GServer HTTP API", "version": "1.0.0"},
        "paths": {
            "/health": {
                "get": {"operationId": "health", "responses": {}},
            },
            "/auth/credentials/{credential-id}/rotate": {
                "post": {
                    "operationId": "auth-rotate-credential",
                    "responses": {},
                    "parameters": [
                        {"name": "credential-id", "in": "path", "required": True}
                    ],
                },
            },
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
            },
        },
    }


def _dump(payload: Any) -> bytes:
    return json.dumps(payload).encode()


# ---- Manifest parsing -------------------------------------------------------


def test_parse_manifest_typed_operations() -> None:
    manifest = parse_client_manifest(fixture_manifest())
    assert manifest.schema_name == "starintel-client-manifest-v1"
    assert manifest.openapi_version == "3.1.2"
    rotate = manifest.operation("auth.credentials.rotate")
    assert rotate.method == "POST"
    assert rotate.path == "/auth/credentials/:credential-id/rotate"
    assert rotate.path_parameters == ("credential-id",)
    assert rotate.authority == "administrator"
    assert rotate.scopes == ("admin",)
    assert rotate.request_schema is not None
    assert rotate.responses[0].status == 201
    assert manifest.operation("health.get").method == "GET"


def test_parse_manifest_rejects_bad_schema_name() -> None:
    payload = fixture_manifest()
    payload["schema"] = "something-else"
    with pytest.raises(ManifestError):
        parse_client_manifest(payload)


def test_parse_manifest_rejects_missing_keys() -> None:
    payload = fixture_manifest()
    del payload["operations"]
    with pytest.raises(ManifestError):
        parse_client_manifest(payload)


def test_parse_manifest_rejects_bad_method() -> None:
    with pytest.raises(ManifestError):
        parse_client_manifest(
            fixture_manifest([_op(method="purge")])
        )


def test_parse_manifest_rejects_unknown_authority() -> None:
    with pytest.raises(ManifestError):
        parse_client_manifest(fixture_manifest([_op(authority="root")]))


def test_parse_manifest_rejects_path_parameter_mismatch() -> None:
    with pytest.raises(ManifestError):
        parse_client_manifest(
            fixture_manifest(
                [_op(path_parameters=["wrong-id"], openapi_path="/x/{wrong-id}")]
            )
        )


def test_parse_manifest_rejects_legacy_routes() -> None:
    """Every forbidden legacy server route must abort registry parsing."""
    legacy_openapi_paths = [
        "/new/document/:dtype",
        "/documents/bulk",
        "/document/:id",
        "/new/target/:actor",
        "/search",
        "/api/v1/dtype/:dtype/view/:view",
    ]
    legacy_openapi_forms = [
        "/new/document/{dtype}",
        "/documents/bulk",
        "/document/{id}",
        "/new/target/{actor}",
        "/search",
        "/api/v1/dtype/{dtype}/view/{view}",
    ]
    for path, openapi_path in zip(legacy_openapi_paths, legacy_openapi_forms, strict=True):
        with pytest.raises(ManifestError):
            parse_client_manifest(
                fixture_manifest([_op(path=path, openapi_path=openapi_path)])
            )


def test_parse_manifest_rejects_duplicate_operation_ids() -> None:
    with pytest.raises(ManifestError):
        parse_client_manifest(fixture_manifest([_op(), _op()]))


# ---- Path rendering ---------------------------------------------------------


def test_render_path_substitutes_parameters() -> None:
    rendered = render_path("/auth/credentials/:credential-id/rotate", {"credential-id": "cred-01"})
    assert rendered == "/auth/credentials/cred-01/rotate"


def test_render_path_quotes_values() -> None:
    rendered = render_path("/auth/users/:username/password", {"username": "a b/c"})
    assert rendered == "/auth/users/a%20b%2Fc/password"


def test_render_path_requires_all_parameters() -> None:
    with pytest.raises(ValueError):
        render_path("/auth/users/:username/password", {})


def test_render_path_rejects_extra_parameters() -> None:
    with pytest.raises(ValueError):
        render_path("/health", {"username": "x"})


# ---- OpenAPI cross-check ----------------------------------------------------


def test_parse_openapi_document() -> None:
    doc = parse_openapi_document(fixture_openapi())
    assert doc.version == "3.1.2"
    assert doc.title == "StarIntel GServer HTTP API"
    entry = doc.operation("/health", "GET")
    assert entry is not None and entry.operation_id == "health"


def test_cross_check_detects_missing_openapi_operation() -> None:
    openapi = fixture_openapi()
    del openapi["paths"]["/auth/credentials/{credential-id}/rotate"]
    doc = parse_openapi_document(openapi)
    manifest = parse_client_manifest(fixture_manifest())
    from starintel_client._openapi import cross_check

    with pytest.raises(ManifestError):
        cross_check(manifest, doc)


def test_cross_check_detects_operation_id_drift() -> None:
    openapi = fixture_openapi()
    openapi["paths"]["/health"]["get"]["operationId"] = "renamed"
    doc = parse_openapi_document(openapi)
    manifest = parse_client_manifest(fixture_manifest())
    from starintel_client._openapi import cross_check

    with pytest.raises(ManifestError):
        cross_check(manifest, doc)


def test_cross_check_accepts_consistent_registry() -> None:
    from starintel_client._openapi import cross_check

    cross_check(
        parse_client_manifest(fixture_manifest()), parse_openapi_document(fixture_openapi())
    )


# ---- Correlation ids --------------------------------------------------------


def test_new_correlation_id_charset_and_shape() -> None:
    cid = new_correlation_id()
    assert re.fullmatch(r"[0-9a-f]{28}", cid)


def test_new_correlation_ids_are_unique() -> None:
    assert len({new_correlation_id() for _ in range(50)}) == 50


def test_validate_correlation_id_accepts_server_bounds() -> None:
    assert validate_correlation_id("01HZX-abc_.:42") == "01HZX-abc_.:42"
    assert validate_correlation_id("a" * 128) == "a" * 128


def test_validate_correlation_id_rejects_out_of_bounds() -> None:
    with pytest.raises(ValueError):
        validate_correlation_id("")
    with pytest.raises(ValueError):
        validate_correlation_id("a" * 129)
    with pytest.raises(ValueError):
        validate_correlation_id("bad id!")
    with pytest.raises(ValueError):
        validate_correlation_id("bad\nid")


# ---- Error normalization ----------------------------------------------------


def test_error_from_envelope_payload() -> None:
    err = error_from_payload(
        401,
        {
            "status": "error",
            "msg": "Authentication failed.",
            "correlation_id": "c1",
            "code": "auth_failed",
        },
    )
    assert isinstance(err, StarIntelApiError)
    assert err.status_code == 401
    assert err.msg == "Authentication failed."
    assert err.correlation_id == "c1"
    assert err.code == "auth_failed"
    assert "Authentication failed." in str(err)
    assert "401" in str(err)


def test_error_from_invalid_payload_falls_back() -> None:
    err = error_from_payload(503, None)
    assert err.status_code == 503
    assert err.msg
    assert err.correlation_id is None
    assert err.code is None


def test_error_from_envelope_missing_optional_fields() -> None:
    err = error_from_payload(400, {"status": "error", "msg": "bad", "correlation_id": "c2"})
    assert err.code is None


def test_unknown_operation_error_is_starintel_error() -> None:
    assert issubclass(UnknownOperationError, StarIntelApiError) is False
    from starintel_client._errors import StarIntelClientError

    assert issubclass(UnknownOperationError, StarIntelClientError)
    assert issubclass(ManifestError, StarIntelClientError)
    assert issubclass(StarIntelApiError, StarIntelClientError)


"""Stdlib mock StarIntel server for hermetic tests.

Serves fixture ``/client-manifest.json`` and ``/openapi.json`` documents plus
the endpoints the current contract defines. Response shapes mirror
starintel-server's boundary (verified 2026-09-08): status/msg/correlation_id
envelopes, ``X-Correlation-ID`` echo, Bearer auth, error ``code`` fields.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
from typing import Any

API_KEY = "star_sk_v1_mock"
BOOTSTRAP_SECRET = "mock-bootstrap-secret"
VALID_USERNAME = "analyst"
VALID_PASSWORD = "correct-horse-battery"


def _op(
    operation_id: str,
    client_name: str,
    method: str,
    path: str,
    authority: str,
    *,
    scopes: list[str] | None = None,
    path_parameters: list[str] | None = None,
    request_schema: dict[str, Any] | None = None,
    status: int = 200,
    description: str = "ok",
    response_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "client_name": client_name,
        "method": method,
        "path": path,
        "openapi_path": re.sub(
            r":([A-Za-z0-9_\-]+)", r"{\1}", path
        ),
        "authority": authority,
        "scopes": scopes or [],
        "path_parameters": path_parameters or [],
        "request_schema": request_schema,
        "responses": [
            {"status": status, "description": description, "schema": response_schema}
        ],
        "idempotency": None,
    }


_ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "msg": {"type": "string"},
        "code": {"type": "string"},
        "correlation_id": {"type": "string"},
    },
    "required": ["status", "msg", "correlation_id"],
}


def _user(username: str, scopes: list[str]) -> dict[str, Any]:
    return {
        "username": username,
        "principal_type": "human",
        "scopes": scopes,
        "status": "active",
        "created_at": 1757328000,
        "password_updated_at": 1757328000,
        "must_change_password": False,
    }


def _credential(credential_id: str, owner: str, scopes: list[str]) -> dict[str, Any]:
    return {
        "id": credential_id,
        "owner": owner,
        "principal_type": "api",
        "scopes": scopes,
        "status": "active",
        "created_at": 1757328000,
    }


def fixture_manifest() -> dict[str, Any]:
    """The 16 currently-contracted operations, exactly as the server emits."""
    operations = [
        _op("health.get", "health", "get", "/health", "public"),
        _op(
            "server.get",
            "server-info",
            "get",
            "/",
            "public",
            description="Server metadata.",
        ),
        _op(
            "schema.openapi.get",
            "openapi-document",
            "get",
            "/openapi.json",
            "public",
        ),
        _op(
            "schema.client-manifest.get",
            "client-manifest",
            "get",
            "/client-manifest.json",
            "public",
        ),
        _op(
            "auth.login",
            "auth-login",
            "post",
            "/auth/login",
            "public",
            request_schema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "minLength": 1},
                    "password": {"type": "string", "minLength": 1, "writeOnly": True},
                },
                "required": ["username", "password"],
            },
            status=200,
            description="Authenticated session.",
            response_schema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string"},
                    "credential": {"type": "object"},
                    "user": {"type": "object"},
                    "correlation_id": {"type": "string"},
                },
                "required": ["api_key", "credential", "user", "correlation_id"],
            },
        ),
        _op(
            "auth.bootstrap",
            "auth-bootstrap",
            "post",
            "/auth/bootstrap",
            "bootstrap",
            request_schema={
                "type": "object",
                "properties": {"owner": {"type": "string", "minLength": 1}},
            },
            status=201,
            description="Bootstrap credential created.",
        ),
        _op(
            "auth.context.get",
            "auth-context",
            "get",
            "/auth/context",
            "authenticated",
        ),
        _op(
            "auth.users.create",
            "auth-create-user",
            "post",
            "/auth/users",
            "administrator",
            scopes=["admin"],
            request_schema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "minLength": 1},
                    "password": {"type": "string", "minLength": 1, "writeOnly": True},
                    "principal_type": {"type": "string"},
                    "scopes": {"type": "array", "items": {"type": "string"}},
                    "must_change_password": {"type": "boolean"},
                },
                "required": ["username", "password", "scopes"],
            },
            status=201,
            description="User created.",
        ),
        _op(
            "auth.users.list",
            "auth-list-users",
            "get",
            "/auth/users",
            "administrator",
            scopes=["admin"],
            description="User metadata list.",
        ),
        _op(
            "auth.users.password.reset",
            "auth-reset-user-password",
            "post",
            "/auth/users/:username/password",
            "administrator",
            scopes=["admin"],
            path_parameters=["username"],
            request_schema={
                "type": "object",
                "properties": {
                    "password": {"type": "string", "minLength": 1, "writeOnly": True},
                    "must_change_password": {"type": "boolean"},
                },
                "required": ["password"],
            },
            description="Password reset.",
        ),
        _op(
            "auth.password.change",
            "auth-change-password",
            "post",
            "/auth/password",
            "authenticated",
            request_schema={
                "type": "object",
                "properties": {
                    "current_password": {"type": "string", "writeOnly": True},
                    "new_password": {"type": "string", "writeOnly": True},
                },
                "required": ["current_password", "new_password"],
            },
            description="Password changed.",
        ),
        _op(
            "auth.credentials.create",
            "auth-create-credential",
            "post",
            "/auth/credentials",
            "administrator",
            scopes=["admin"],
            request_schema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "minLength": 1},
                    "principal_type": {"type": "string"},
                    "scopes": {"type": "array", "items": {"type": "string"}},
                    "expires_in_seconds": {"type": "integer", "minimum": 1},
                },
                "required": ["owner", "principal_type", "scopes"],
            },
            status=201,
            description="Credential created.",
        ),
        _op(
            "auth.credentials.list",
            "auth-list-credentials",
            "get",
            "/auth/credentials",
            "administrator",
            scopes=["admin"],
            description="Credential metadata list.",
        ),
        _op(
            "auth.credentials.rotate",
            "auth-rotate-credential",
            "post",
            "/auth/credentials/:credential-id/rotate",
            "administrator",
            scopes=["admin"],
            path_parameters=["credential-id"],
            request_schema={
                "type": "object",
                "properties": {"overlap_seconds": {"type": "integer", "minimum": 0}},
                "required": ["overlap_seconds"],
            },
            status=201,
            description="Credential rotated.",
        ),
        _op(
            "auth.credentials.revoke",
            "auth-revoke-credential",
            "post",
            "/auth/credentials/:credential-id/revoke",
            "administrator",
            scopes=["admin"],
            path_parameters=["credential-id"],
            description="Credential revoked.",
        ),
        _op(
            "auth.credentials.disable",
            "auth-disable-credential",
            "post",
            "/auth/credentials/:credential-id/disable",
            "administrator",
            scopes=["admin"],
            path_parameters=["credential-id"],
            description="Credential disabled.",
        ),
    ]
    return {
        "schema": "starintel-client-manifest-v1",
        "openapi": "3.1.2",
        "operations": operations,
    }


def fixture_openapi(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Derive a consistent OpenAPI 3.1 document from the fixture manifest."""
    manifest = manifest or fixture_manifest()
    paths: dict[str, Any] = {}
    for op in manifest["operations"]:
        path_item = paths.setdefault(op["openapi_path"], {})
        entry: dict[str, Any] = {
            "operationId": op["client_name"],
            "summary": op["operation_id"],
            "tags": [],
            "x-starintel-authority": op["authority"],
            "x-starintel-scopes": op["scopes"],
            "responses": {},
        }
        if op["authority"] not in ("public", "bootstrap"):
            entry["security"] = [{"bearerAuth": []}]
        for name in op["path_parameters"]:
            entry.setdefault("parameters", []).append(
                {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}
            )
        if op["authority"] == "bootstrap":
            entry.setdefault("parameters", []).append(
                {
                    "name": "X-Star-Bootstrap-Secret",
                    "in": "header",
                    "required": True,
                    "schema": {"type": "string"},
                }
            )
        if op["request_schema"] is not None:
            entry["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": op["request_schema"]}},
            }
        for response in op["responses"]:
            entry["responses"][str(response["status"])] = {"description": response["description"]}
        path_item[op["method"]] = entry
    return {
        "openapi": "3.1.2",
        "info": {
            "title": "StarIntel GServer HTTP API",
            "version": "1.0.0",
            "description": "Machine-readable contracted StarIntel control-plane HTTP surface.",
        },
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "StarIntel API key",
                },
            },
        },
    }


class MockStarIntelHandler(http.server.BaseHTTPRequestHandler):
    """Request handler with contract-shaped responses and request recording."""

    server_version = "MockStarIntel/1.0"

    # (method, path) -> attempt count, for retry tests.
    def _attempts(self, key: tuple[str, str]) -> int:
        counts: dict[tuple[str, str], int] = self.server.attempt_counts  # type: ignore[attr-defined]
        counts[key] = counts.get(key, 0) + 1
        return counts[key]

    def log_message(self, *args: object) -> None:  # silence
        pass

    # -- helpers ------------------------------------------------------------

    def _correlation_id(self) -> str:
        provided = self.headers.get("X-Correlation-ID")
        if provided and re.fullmatch(r"[A-Za-z0-9_.:\-]{1,128}", provided):
            return provided
        counter = self.server.cid_counter  # type: ignore[attr-defined]
        counter[0] += 1
        return f"mock-cid-{counter[0]:04d}"

    def _send_json(self, status: int, payload: Any, cid: str) -> None:
        if isinstance(payload, dict):
            payload = {**payload, "correlation_id": cid}
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Correlation-ID", cid)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, msg: str, code: str) -> None:
        self._send_json(
            status, {"status": "error", "msg": msg, "code": code}, self._correlation_id()
        )

    def _read_body(self) -> dict[str, Any]:
        if not self._body:
            return {}
        parsed = json.loads(self._body.decode())
        if not isinstance(parsed, dict):
            raise ValueError("body must be a JSON object")
        return parsed

    def _bearer(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[len("Bearer ") :]
        return None

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self._body = self.rfile.read(length) if length else b""
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "body": self._body,
            }
        )

    # -- dispatch -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._record()
        cid = self._correlation_id()
        path = self.path.split("?")[0]
        if path == "/_retry/flaky":
            if self._attempts(("GET", path)) < 3:
                self._send_json(
                    503, {"status": "error", "msg": "unavailable", "code": "unavailable"}, cid
                )
                return
            self._send_json(200, {"status": "ok", "msg": "recovered"}, cid)
            return
        if path == "/_retry/always-503":
            self._attempts(("GET", path))
            self._send_json(503, {"status": "error", "msg": "down", "code": "unavailable"}, cid)
            return
        if path == "/_retry/ok":
            self._attempts(("GET", path))
            self._send_json(200, {"status": "ok", "msg": "fine"}, cid)
            return
        if path == "/health":
            self._send_json(200, {"status": "ok", "msg": "OK"}, cid)
            return
        if path == "/":
            self._send_json(
                200,
                {
                    "doc_spec_version": "0.9.0",
                    "default-dataset": "starintel",
                    "event_log": "starintel-events",
                    "server": "starintel-gserver",
                    "version": "test",
                    "openapi": "/openapi.json",
                    "client_manifest": "/client-manifest.json",
                },
                cid,
            )
            return
        if path == "/openapi.json":
            self._send_json(200, fixture_openapi(), cid)
            return
        if path == "/client-manifest.json":
            self._send_json(200, fixture_manifest(), cid)
            return
        if path == "/auth/context":
            if not self._bearer():
                self._error(401, "Authentication required.", "auth_required")
                return
            self._send_json(
                200,
                {
                    "status": "ok",
                    "msg": "context",
                    "username": VALID_USERNAME,
                    "principal_type": "human",
                    "scopes": ["search:read"],
                },
                cid,
            )
            return
        if path == "/auth/users":
            if not self._bearer():
                self._error(401, "Authentication required.", "auth_required")
                return
            self._send_json(
                200, [_user("analyst", ["admin"]), _user("viewer", ["search:read"])], cid
            )
            return
        if path == "/auth/credentials":
            if not self._bearer():
                self._error(401, "Authentication required.", "auth_required")
                return
            self._send_json(
                200,
                [
                    _credential("cred-1", "analyst", ["admin"]),
                    _credential("cred-2", "viewer", ["read"]),
                ],
                cid,
            )
            return
        if path == "/missing-envelope":
            body = b"<html>not json</html>"
            self.send_response(500)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Correlation-ID", cid)
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/no-content":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("X-Correlation-ID", cid)
            self.end_headers()
            return
        self._error(404, "Resource not found.", "not_found")

    def do_POST(self) -> None:  # noqa: N802
        self._record()
        cid = self._correlation_id()
        path = self.path.split("?")[0]
        if path == "/_retry/post-503":
            self._attempts(("POST", path))
            self._send_json(503, {"status": "error", "msg": "down", "code": "unavailable"}, cid)
            return
        if path == "/auth/login":
            try:
                body = self._read_body()
            except ValueError:
                self._error(400, "Malformed JSON body.", "malformed_body")
                return
            if body.get("username") == VALID_USERNAME and body.get("password") == VALID_PASSWORD:
                self._send_json(
                    200,
                    {
                        "api_key": "star_sk_v1_minted",
                        "credential": _credential("cred-session", VALID_USERNAME, ["search:read"]),
                        "user": _user(VALID_USERNAME, ["search:read"]),
                        "correlation_id": cid,
                    },
                    cid,
                )
            else:
                self._error(401, "Authentication failed.", "auth_failed")
            return
        if path == "/auth/bootstrap":
            if self.headers.get("X-Star-Bootstrap-Secret") != BOOTSTRAP_SECRET:
                self._error(401, "Bootstrap secret required.", "bootstrap_required")
                return
            try:
                body = self._read_body()
            except ValueError:
                self._error(400, "Malformed JSON body.", "malformed_body")
                return
            self._send_json(
                201,
                {
                    "api_key": "star_sk_v1_bootstrapped",
                    "credential": _credential("cred-root", body.get("owner", ""), ["admin"]),
                },
                cid,
            )
            return
        if not self._bearer():
            self._error(401, "Authentication required.", "auth_required")
            return
        if path == "/auth/users":
            try:
                body = self._read_body()
            except ValueError:
                self._error(400, "Malformed JSON body.", "malformed_body")
                return
            self._send_json(
                200,
                {
                    "status": "created",
                    "msg": "User created.",
                    "user": _user(body.get("username", ""), body.get("scopes", [])),
                },
                cid,
            )
            return
        if path == "/auth/password":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "msg": "Password changed.",
                    "user": _user(VALID_USERNAME, ["admin"]),
                },
                cid,
            )
            return
        match = re.fullmatch(r"/auth/users/([^/]+)/password", path)
        if match:
            username = match.group(1)
            self._send_json(
                200,
                {"status": "ok", "msg": "Password reset.", "user": _user(username, ["admin"])},
                cid,
            )
            return
        if path == "/auth/credentials":
            self._send_json(
                201,
                {
                    "api_key": "star_sk_v1_newcred",
                    "credential": _credential("cred-new", "analyst", ["admin"]),
                },
                cid,
            )
            return
        match = re.fullmatch(r"/auth/credentials/([^/]+)/(rotate|revoke|disable)", path)
        if match:
            credential_id, action = match.groups()
            if action == "rotate":
                self._send_json(
                    201,
                    {
                        "api_key": "star_sk_v1_rotated",
                        "credential": _credential(credential_id, "analyst", ["admin"]),
                    },
                    cid,
                )
            else:
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "msg": f"Credential {action}d.",
                        "credential": _credential(credential_id, "analyst", ["admin"]),
                    },
                    cid,
                )
            return
        self._error(404, "Resource not found.", "not_found")


class MockStarIntelServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), MockStarIntelHandler)
        self.requests: list[dict[str, Any]] = []
        self.attempt_counts: dict[tuple[str, str], int] = {}
        self.cid_counter = [0]


def make_server() -> tuple[MockStarIntelServer, str]:
    server = MockStarIntelServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def stop_server(server: MockStarIntelServer) -> None:
    server.shutdown()
    server.server_close()

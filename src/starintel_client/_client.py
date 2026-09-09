"""Discovery-driven StarIntel clients (sync facade + async core).

Routes come exclusively from the contract registry fetched from
``GET /client-manifest.json`` and cross-checked against ``GET /openapi.json``.
New server operations become callable through :meth:`call` automatically once
the server contracts them; no route is ever hardcoded here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from ._correlation import new_correlation_id, validate_correlation_id
from ._errors import ManifestError, UnknownOperationError
from ._manifest import (
    MANIFEST_SCHEMA,
    ClientManifest,
    ManifestOperation,
    parse_client_manifest,
    render_path,
)
from ._models import (
    CredentialMetadata,
    CredentialSecret,
    CredentialStatus,
    LoginResult,
    UserMetadata,
    UserStatus,
    _envelope_field,
)
from ._openapi import OpenApiDocument, cross_check, parse_openapi_document
from ._transport import AsyncTransport, SyncTransport, parse_json_content

__all__ = [
    "ApiResponse",
    "AsyncStarIntelClient",
    "DEFAULT_BASE_URL",
    "StarIntelClient",
]

DEFAULT_BASE_URL = "http://127.0.0.1:5000"

DISCOVERY_MANIFEST_PATH = "/client-manifest.json"
DISCOVERY_OPENAPI_PATH = "/openapi.json"


@dataclass(frozen=True)
class ApiResponse:
    """A successful (2xx) server response with correlation capture."""

    status_code: int
    correlation_id: str | None
    data: Any
    headers: Mapping[str, str]


def _prepare_headers(
    api_key: str | None,
    correlation_id: str,
    extra: Mapping[str, str] | None,
) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    headers["X-Correlation-ID"] = correlation_id
    if extra:
        headers.update(extra)
    return headers


def _plan_call(
    manifest: ClientManifest,
    operation_id: str,
    path_params: Mapping[str, str] | None,
) -> tuple[ManifestOperation, str]:
    operation = manifest.operation(operation_id)
    return operation, render_path(operation.path, path_params or {})


def _interpret(status_code: int, headers: Mapping[str, str], content: bytes) -> ApiResponse:
    data = parse_json_content(content)
    header_cid = headers.get("x-correlation-id")
    body_cid = _envelope_field(data, "correlation_id")
    return ApiResponse(
        status_code=status_code,
        correlation_id=header_cid or body_cid,
        data=data,
        headers=headers,
    )


class _RegistryMixin:
    """State shared by the sync and async clients."""

    _manifest: ClientManifest | None
    _openapi: OpenApiDocument | None
    _fixed_correlation_id: str | None

    def _registry_state(
        self,
        manifest: ClientManifest | None,
        openapi: OpenApiDocument | None,
        correlation_id: str | None,
    ) -> None:
        self._manifest = manifest
        self._openapi = openapi
        self._fixed_correlation_id = (
            validate_correlation_id(correlation_id) if correlation_id else None
        )

    @property
    def manifest(self) -> ClientManifest:
        if self._manifest is None:
            raise UnknownOperationError(
                "the contract registry has not been discovered yet; call discover() first"
            )
        return self._manifest

    @property
    def openapi_document(self) -> OpenApiDocument | None:
        return self._openapi

    def has_operation(self, operation_id: str) -> bool:
        try:
            return self.manifest.has_operation(operation_id)
        except UnknownOperationError:
            return False

    def _correlation_id_for(self, correlation_id: str | None) -> str:
        if correlation_id:
            return validate_correlation_id(correlation_id)
        if self._fixed_correlation_id:
            return self._fixed_correlation_id
        return new_correlation_id()


class StarIntelClient(_RegistryMixin):
    """Sync StarIntel API client driven by the contract registry."""

    api_key: str | None

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
        retry: Any = None,
        sleep: Callable[[float], None] | None = None,
        manifest: ClientManifest | None = None,
        openapi: OpenApiDocument | None = None,
        correlation_id: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"timeout": timeout}
        if retry is not None:
            kwargs["retry"] = retry
        if sleep is not None:
            kwargs["sleep"] = sleep
        self._transport = SyncTransport(base_url, **kwargs)
        self.api_key = api_key
        self.base_url = httpx.URL(base_url)
        self.timeout = self._transport.timeout
        self._registry_state(manifest, openapi, correlation_id)

    @classmethod
    def from_registry(
        cls,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
        manifest: ClientManifest,
        openapi: OpenApiDocument | None = None,
        correlation_id: str | None = None,
    ) -> StarIntelClient:
        """Build a client from already-fetched registry documents."""
        return cls(
            base_url,
            api_key=api_key,
            timeout=timeout,
            manifest=manifest,
            openapi=openapi,
            correlation_id=correlation_id,
        )

    # -- discovery ----------------------------------------------------------

    def discover(self) -> ClientManifest:
        """Fetch, parse, and cross-check the contract registry."""
        manifest_response = self._transport.request(
            "GET", DISCOVERY_MANIFEST_PATH, headers={"Accept": "application/json"}
        )
        openapi_response = self._transport.request(
            "GET", DISCOVERY_OPENAPI_PATH, headers={"Accept": "application/json"}
        )
        manifest = parse_client_manifest(parse_json_content(manifest_response.content))
        if manifest.schema_name != MANIFEST_SCHEMA:
            raise ValueError("registry schema mismatch")
        openapi = parse_openapi_document(parse_json_content(openapi_response.content))
        cross_check(manifest, openapi)
        self._manifest = manifest
        self._openapi = openapi
        return manifest

    def _ensure_registry(self) -> ClientManifest:
        if self._manifest is None:
            return self.discover()
        return self._manifest

    # -- generic dispatch ---------------------------------------------------

    def call(
        self,
        operation_id: str,
        *,
        path_params: Mapping[str, str] | None = None,
        json: Any = None,
        correlation_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ApiResponse:
        """Invoke any operation from the validated contract registry."""
        manifest = self._ensure_registry()
        operation, path = _plan_call(manifest, operation_id, path_params)
        headers_out = _prepare_headers(
            self.api_key, self._correlation_id_for(correlation_id), headers
        )
        response = self._transport.request(
            operation.method,
            path,
            headers=headers_out,
            json_body=json,
        )
        return _interpret(response.status_code, response.headers, response.content)

    def publish_document(
        self,
        document: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> ApiResponse:
        """Ingest one canonical document via ``documents.create``."""
        return self.call(
            "documents.create", json=document, correlation_id=correlation_id
        )

    def publish_documents_bulk(
        self,
        documents: list[dict[str, Any]],
        *,
        correlation_id: str | None = None,
    ) -> ApiResponse:
        """Ingest a bounded batch via ``documents.bulk.create``.

        The server answers with an aggregate envelope (inline:
        ``total``/``succeeded``/``failed``/``correlation_id``; or an async
        job acceptance with ``job_id``/``status_url``). Per-document
        attribution is not part of the wire contract.
        """
        return self.call(
            "documents.bulk.create", json=documents, correlation_id=correlation_id
        )

    # -- typed convenience methods (currently-contracted operations) --------

    def health(self, *, correlation_id: str | None = None) -> ApiResponse:
        return self.call("health.get", correlation_id=correlation_id)

    def server_metadata(self, *, correlation_id: str | None = None) -> ApiResponse:
        return self.call("server.get", correlation_id=correlation_id)

    def fetch_client_manifest(self, *, correlation_id: str | None = None) -> ApiResponse:
        return self.call("schema.client-manifest.get", correlation_id=correlation_id)

    def fetch_openapi_document(self, *, correlation_id: str | None = None) -> ApiResponse:
        return self.call("schema.openapi.get", correlation_id=correlation_id)

    def login(
        self,
        username: str,
        password: str,
        *,
        correlation_id: str | None = None,
    ) -> LoginResult:
        response = self.call(
            "auth.login",
            json={"username": username, "password": password},
            correlation_id=correlation_id,
        )
        return LoginResult.from_payload(response.data)

    def bootstrap(
        self,
        owner: str,
        *,
        bootstrap_secret: str,
        correlation_id: str | None = None,
    ) -> CredentialSecret:
        response = self.call(
            "auth.bootstrap",
            json={"owner": owner},
            headers={"X-Star-Bootstrap-Secret": bootstrap_secret},
            correlation_id=correlation_id,
        )
        return CredentialSecret.from_payload(response.data)

    def auth_context(self, *, correlation_id: str | None = None) -> ApiResponse:
        return self.call("auth.context.get", correlation_id=correlation_id)

    def create_user(
        self,
        username: str,
        password: str,
        scopes: list[str],
        *,
        principal_type: str | None = None,
        must_change_password: bool | None = None,
        correlation_id: str | None = None,
    ) -> UserStatus:
        body: dict[str, Any] = {"username": username, "password": password, "scopes": scopes}
        if principal_type is not None:
            body["principal_type"] = principal_type
        if must_change_password is not None:
            body["must_change_password"] = must_change_password
        response = self.call("auth.users.create", json=body, correlation_id=correlation_id)
        return UserStatus.from_payload(response.data)

    def list_users(self, *, correlation_id: str | None = None) -> list[UserMetadata]:
        response = self.call("auth.users.list", correlation_id=correlation_id)
        return [UserMetadata.from_payload(entry) for entry in response.data or []]

    def reset_user_password(
        self,
        username: str,
        password: str,
        *,
        must_change_password: bool | None = None,
        correlation_id: str | None = None,
    ) -> UserStatus:
        body: dict[str, Any] = {"password": password}
        if must_change_password is not None:
            body["must_change_password"] = must_change_password
        response = self.call(
            "auth.users.password.reset",
            path_params={"username": username},
            json=body,
            correlation_id=correlation_id,
        )
        return UserStatus.from_payload(response.data)

    def change_password(
        self,
        current_password: str,
        new_password: str,
        *,
        correlation_id: str | None = None,
    ) -> UserStatus:
        response = self.call(
            "auth.password.change",
            json={"current_password": current_password, "new_password": new_password},
            correlation_id=correlation_id,
        )
        return UserStatus.from_payload(response.data)

    def create_credential(
        self,
        owner: str,
        principal_type: str,
        scopes: list[str],
        *,
        expires_in_seconds: int | None = None,
        correlation_id: str | None = None,
    ) -> CredentialSecret:
        body: dict[str, Any] = {
            "owner": owner,
            "principal_type": principal_type,
            "scopes": scopes,
        }
        if expires_in_seconds is not None:
            body["expires_in_seconds"] = expires_in_seconds
        response = self.call("auth.credentials.create", json=body, correlation_id=correlation_id)
        return CredentialSecret.from_payload(response.data)

    def list_credentials(
        self, *, correlation_id: str | None = None
    ) -> list[CredentialMetadata]:
        response = self.call("auth.credentials.list", correlation_id=correlation_id)
        return [CredentialMetadata.from_payload(entry) for entry in response.data or []]

    def rotate_credential(
        self,
        credential_id: str,
        *,
        overlap_seconds: int = 0,
        correlation_id: str | None = None,
    ) -> CredentialSecret:
        response = self.call(
            "auth.credentials.rotate",
            path_params={"credential-id": credential_id},
            json={"overlap_seconds": overlap_seconds},
            correlation_id=correlation_id,
        )
        return CredentialSecret.from_payload(response.data)

    def revoke_credential(
        self, credential_id: str, *, correlation_id: str | None = None
    ) -> CredentialStatus:
        response = self.call(
            "auth.credentials.revoke",
            path_params={"credential-id": credential_id},
            correlation_id=correlation_id,
        )
        return CredentialStatus.from_payload(response.data)

    def disable_credential(
        self, credential_id: str, *, correlation_id: str | None = None
    ) -> CredentialStatus:
        response = self.call(
            "auth.credentials.disable",
            path_params={"credential-id": credential_id},
            correlation_id=correlation_id,
        )
        return CredentialStatus.from_payload(response.data)

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> StarIntelClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class AsyncStarIntelClient(_RegistryMixin):
    """Async StarIntel API client driven by the contract registry."""

    api_key: str | None

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
        retry: Any = None,
        sleep: Callable[[float], Any] | None = None,
        manifest: ClientManifest | None = None,
        openapi: OpenApiDocument | None = None,
        correlation_id: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"timeout": timeout}
        if retry is not None:
            kwargs["retry"] = retry
        if sleep is not None:
            kwargs["sleep"] = sleep
        self._transport = AsyncTransport(base_url, **kwargs)
        self.api_key = api_key
        self.base_url = httpx.URL(base_url)
        self.timeout = self._transport.timeout
        self._registry_state(manifest, openapi, correlation_id)

    @classmethod
    def from_registry(
        cls,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
        manifest: ClientManifest,
        openapi: OpenApiDocument | None = None,
        correlation_id: str | None = None,
    ) -> AsyncStarIntelClient:
        return cls(
            base_url,
            api_key=api_key,
            timeout=timeout,
            manifest=manifest,
            openapi=openapi,
            correlation_id=correlation_id,
        )

    async def discover(self) -> ClientManifest:
        manifest_response = await self._transport.request(
            "GET", DISCOVERY_MANIFEST_PATH, headers={"Accept": "application/json"}
        )
        openapi_response = await self._transport.request(
            "GET", DISCOVERY_OPENAPI_PATH, headers={"Accept": "application/json"}
        )
        manifest = parse_client_manifest(parse_json_content(manifest_response.content))
        openapi = parse_openapi_document(parse_json_content(openapi_response.content))
        cross_check(manifest, openapi)
        self._manifest = manifest
        self._openapi = openapi
        return manifest

    async def _aensure_registry(self) -> ClientManifest:
        if self._manifest is None:
            return await self.discover()
        return self._manifest

    async def call(
        self,
        operation_id: str,
        *,
        path_params: Mapping[str, str] | None = None,
        json: Any = None,
        correlation_id: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ApiResponse:
        """Invoke any operation from the validated contract registry."""
        manifest = await self._aensure_registry()
        operation, path = _plan_call(manifest, operation_id, path_params)
        headers_out = _prepare_headers(
            self.api_key, self._correlation_id_for(correlation_id), headers
        )
        response = await self._transport.request(
            operation.method,
            path,
            headers=headers_out,
            json_body=json,
        )
        return _interpret(response.status_code, response.headers, response.content)

    async def publish_document(
        self,
        document: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> ApiResponse:
        """Ingest one canonical document via ``documents.create``."""
        return await self.call(
            "documents.create", json=document, correlation_id=correlation_id
        )

    async def publish_documents_bulk(
        self,
        documents: list[dict[str, Any]],
        *,
        correlation_id: str | None = None,
    ) -> ApiResponse:
        """Ingest a bounded batch via ``documents.bulk.create`` (aggregate envelope)."""
        return await self.call(
            "documents.bulk.create", json=documents, correlation_id=correlation_id
        )

    async def health(self, *, correlation_id: str | None = None) -> ApiResponse:
        return await self.call("health.get", correlation_id=correlation_id)

    async def server_metadata(self, *, correlation_id: str | None = None) -> ApiResponse:
        return await self.call("server.get", correlation_id=correlation_id)

    async def fetch_client_manifest(self, *, correlation_id: str | None = None) -> ApiResponse:
        return await self.call("schema.client-manifest.get", correlation_id=correlation_id)

    async def fetch_openapi_document(self, *, correlation_id: str | None = None) -> ApiResponse:
        return await self.call("schema.openapi.get", correlation_id=correlation_id)

    async def login(
        self,
        username: str,
        password: str,
        *,
        correlation_id: str | None = None,
    ) -> LoginResult:
        response = await self.call(
            "auth.login",
            json={"username": username, "password": password},
            correlation_id=correlation_id,
        )
        return LoginResult.from_payload(response.data)

    async def bootstrap(
        self,
        owner: str,
        *,
        bootstrap_secret: str,
        correlation_id: str | None = None,
    ) -> CredentialSecret:
        response = await self.call(
            "auth.bootstrap",
            json={"owner": owner},
            headers={"X-Star-Bootstrap-Secret": bootstrap_secret},
            correlation_id=correlation_id,
        )
        return CredentialSecret.from_payload(response.data)

    async def auth_context(self, *, correlation_id: str | None = None) -> ApiResponse:
        return await self.call("auth.context.get", correlation_id=correlation_id)

    async def create_user(
        self,
        username: str,
        password: str,
        scopes: list[str],
        *,
        principal_type: str | None = None,
        must_change_password: bool | None = None,
        correlation_id: str | None = None,
    ) -> UserStatus:
        body: dict[str, Any] = {"username": username, "password": password, "scopes": scopes}
        if principal_type is not None:
            body["principal_type"] = principal_type
        if must_change_password is not None:
            body["must_change_password"] = must_change_password
        response = await self.call("auth.users.create", json=body, correlation_id=correlation_id)
        return UserStatus.from_payload(response.data)

    async def list_users(self, *, correlation_id: str | None = None) -> list[UserMetadata]:
        response = await self.call("auth.users.list", correlation_id=correlation_id)
        return [UserMetadata.from_payload(entry) for entry in response.data or []]

    async def reset_user_password(
        self,
        username: str,
        password: str,
        *,
        must_change_password: bool | None = None,
        correlation_id: str | None = None,
    ) -> UserStatus:
        body: dict[str, Any] = {"password": password}
        if must_change_password is not None:
            body["must_change_password"] = must_change_password
        response = await self.call(
            "auth.users.password.reset",
            path_params={"username": username},
            json=body,
            correlation_id=correlation_id,
        )
        return UserStatus.from_payload(response.data)

    async def change_password(
        self,
        current_password: str,
        new_password: str,
        *,
        correlation_id: str | None = None,
    ) -> UserStatus:
        response = await self.call(
            "auth.password.change",
            json={"current_password": current_password, "new_password": new_password},
            correlation_id=correlation_id,
        )
        return UserStatus.from_payload(response.data)

    async def create_credential(
        self,
        owner: str,
        principal_type: str,
        scopes: list[str],
        *,
        expires_in_seconds: int | None = None,
        correlation_id: str | None = None,
    ) -> CredentialSecret:
        body: dict[str, Any] = {
            "owner": owner,
            "principal_type": principal_type,
            "scopes": scopes,
        }
        if expires_in_seconds is not None:
            body["expires_in_seconds"] = expires_in_seconds
        response = await self.call(
            "auth.credentials.create", json=body, correlation_id=correlation_id
        )
        return CredentialSecret.from_payload(response.data)

    async def list_credentials(
        self, *, correlation_id: str | None = None
    ) -> list[CredentialMetadata]:
        response = await self.call("auth.credentials.list", correlation_id=correlation_id)
        return [CredentialMetadata.from_payload(entry) for entry in response.data or []]

    async def rotate_credential(
        self,
        credential_id: str,
        *,
        overlap_seconds: int = 0,
        correlation_id: str | None = None,
    ) -> CredentialSecret:
        response = await self.call(
            "auth.credentials.rotate",
            path_params={"credential-id": credential_id},
            json={"overlap_seconds": overlap_seconds},
            correlation_id=correlation_id,
        )
        return CredentialSecret.from_payload(response.data)

    async def revoke_credential(
        self, credential_id: str, *, correlation_id: str | None = None
    ) -> CredentialStatus:
        response = await self.call(
            "auth.credentials.revoke",
            path_params={"credential-id": credential_id},
            correlation_id=correlation_id,
        )
        return CredentialStatus.from_payload(response.data)

    async def disable_credential(
        self, credential_id: str, *, correlation_id: str | None = None
    ) -> CredentialStatus:
        response = await self.call(
            "auth.credentials.disable",
            path_params={"credential-id": credential_id},
            correlation_id=correlation_id,
        )
        return CredentialStatus.from_payload(response.data)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def __aenter__(self) -> AsyncStarIntelClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def open_document_client(
    *,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
    **kwargs: Any,
) -> AsyncStarIntelClient:
    """Build an async client after verifying the registry contracts documents.

    Performs a synchronous capability probe: fetches the client manifest and
    requires the ``documents.create`` operation. Raises :class:`ManifestError`
    when the server does not contract document operations yet (tracked as
    starintel-labs/starintel-server#5); legacy routes are never used.
    """
    probe = StarIntelClient(base_url, api_key=api_key, **kwargs)
    manifest = probe.discover()
    contracted = {operation.operation_id for operation in manifest.operations}
    if "documents.create" not in contracted:
        raise ManifestError(
            "the server contract registry does not expose document operations "
            "(documents.create missing); tracked as "
            "starintel-labs/starintel-server#5; legacy routes are not a "
            "permitted fallback"
        )
    return AsyncStarIntelClient(base_url, api_key=api_key, **kwargs)

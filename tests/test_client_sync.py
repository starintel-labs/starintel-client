"""Hermetic tests for the sync discovery-driven client."""

from __future__ import annotations

from typing import Any

import pytest

from starintel_client import (
    ApiResponse,
    AsyncStarIntelClient,
    CredentialMetadata,
    CredentialSecret,
    CredentialStatus,
    LoginResult,
    StarIntelApiError,
    StarIntelClient,
    UnknownOperationError,
    UserMetadata,
    UserStatus,
    parse_client_manifest,
)
from starintel_client._openapi import cross_check, parse_openapi_document
from tests.mock_starintel import (
    API_KEY,
    BOOTSTRAP_SECRET,
    VALID_PASSWORD,
    VALID_USERNAME,
    fixture_manifest,
    fixture_openapi,
)


@pytest.fixture()
def client(mock_base_url: str) -> StarIntelClient:
    return StarIntelClient(base_url=mock_base_url, api_key=API_KEY)


# ---- Discovery --------------------------------------------------------------


def test_discover_builds_registry(client: StarIntelClient) -> None:
    manifest = client.discover()
    assert manifest.schema_name == "starintel-client-manifest-v1"
    assert len(manifest.operations) == 16
    assert client.has_operation("health.get")
    assert client.has_operation("auth.credentials.disable")


def test_discover_cross_checks_openapi(client: StarIntelClient) -> None:
    client.discover()
    assert client.openapi_document is not None
    cross_check(client.manifest, client.openapi_document)


def test_document_operations_are_not_contracted(client: StarIntelClient) -> None:
    """Document ops are blocked on starintel-server#5 and must not be hardcoded."""
    client.discover()
    assert not any("document" in op_id for op_id in client.manifest.operation_ids)
    assert not any("search" in op_id for op_id in client.manifest.operation_ids)


def test_discover_twice_is_idempotent(client: StarIntelClient) -> None:
    first = client.discover()
    second = client.discover()
    assert first.operation_ids == second.operation_ids


def test_from_registry_skips_discovery_fetch(mock_base_url: str) -> None:
    client = StarIntelClient.from_registry(
        base_url=mock_base_url,
        api_key=API_KEY,
        manifest=parse_client_manifest(fixture_manifest()),
        openapi=parse_openapi_document(fixture_openapi()),
    )
    client.health()
    assert client.manifest.has_operation("auth.login")


# ---- Simple GET operations --------------------------------------------------


def test_health(client: StarIntelClient) -> None:
    response = client.health()
    assert isinstance(response, ApiResponse)
    assert response.status_code == 200
    assert response.data["status"] == "ok"
    assert response.correlation_id is not None


def test_server_metadata(client: StarIntelClient) -> None:
    response = client.server_metadata()
    assert response.data["server"] == "starintel-gserver"
    assert response.data["openapi"] == "/openapi.json"


def test_client_manifest_and_openapi_convenience(client: StarIntelClient) -> None:
    client.discover()
    raw = client.fetch_client_manifest()
    assert raw.data["schema"] == "starintel-client-manifest-v1"
    raw_openapi = client.fetch_openapi_document()
    assert raw_openapi.data["openapi"] == "3.1.2"


# ---- Auth operations --------------------------------------------------------


def test_login_returns_typed_result(client: StarIntelClient) -> None:
    result = client.login(VALID_USERNAME, VALID_PASSWORD)
    assert isinstance(result, LoginResult)
    assert result.api_key == "star_sk_v1_minted"
    assert result.credential.id == "cred-session"
    assert result.user.username == VALID_USERNAME
    assert result.correlation_id is not None


def test_login_failure_normalized(client: StarIntelClient) -> None:
    with pytest.raises(StarIntelApiError) as excinfo:
        client.login(VALID_USERNAME, "wrong-password")
    assert excinfo.value.status_code == 401
    assert excinfo.value.msg == "Authentication failed."
    assert excinfo.value.code == "auth_failed"
    assert excinfo.value.correlation_id is not None


def test_bootstrap_requires_secret(mock_base_url: str) -> None:
    client = StarIntelClient(base_url=mock_base_url)
    with pytest.raises(TypeError):
        client.bootstrap("root")
    with pytest.raises(StarIntelApiError) as excinfo:
        client.bootstrap("root", bootstrap_secret="not-the-secret")
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "bootstrap_required"


def test_bootstrap_with_secret(mock_base_url: str) -> None:
    client = StarIntelClient(base_url=mock_base_url)
    result = client.bootstrap("root", bootstrap_secret=BOOTSTRAP_SECRET)
    assert isinstance(result, CredentialSecret)
    assert result.api_key == "star_sk_v1_bootstrapped"
    assert result.credential.owner == "root"


def test_auth_context_bearer_sent(
    client: StarIntelClient, recorded_requests: list[dict[str, Any]]
) -> None:
    response = client.auth_context()
    assert response.data["username"] == VALID_USERNAME
    auth_header = recorded_requests[-1]["headers"].get("Authorization")
    assert auth_header == f"Bearer {API_KEY}"


def test_auth_context_without_api_key_is_401(mock_base_url: str) -> None:
    client = StarIntelClient(base_url=mock_base_url)
    with pytest.raises(StarIntelApiError) as excinfo:
        client.auth_context()
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "auth_required"


# ---- User lifecycle ---------------------------------------------------------


def test_create_user(client: StarIntelClient) -> None:
    result = client.create_user(
        "new-analyst", "hunter2", ["search:read"], must_change_password=True
    )
    assert isinstance(result, UserStatus)
    assert result.user.username == "new-analyst"
    assert result.status == "created"


def test_list_users(client: StarIntelClient) -> None:
    users = client.list_users()
    assert [u.username for u in users] == ["analyst", "viewer"]
    assert all(isinstance(u, UserMetadata) for u in users)
    assert users[0].scopes == ("admin",)
    assert users[0].created_at == 1757328000


def test_reset_user_password(client: StarIntelClient) -> None:
    result = client.reset_user_password("analyst", "new-password")
    assert result.user.username == "analyst"


def test_change_password(client: StarIntelClient) -> None:
    result = client.change_password("old", "new")
    assert result.user.username == VALID_USERNAME


# ---- Credential lifecycle ---------------------------------------------------


def test_create_credential(client: StarIntelClient) -> None:
    result = client.create_credential("analyst", "api", ["admin"], expires_in_seconds=3600)
    assert isinstance(result, CredentialSecret)
    assert result.api_key == "star_sk_v1_newcred"
    assert result.credential.id == "cred-new"


def test_list_credentials(client: StarIntelClient) -> None:
    credentials = client.list_credentials()
    assert [c.id for c in credentials] == ["cred-1", "cred-2"]
    assert all(isinstance(c, CredentialMetadata) for c in credentials)
    assert credentials[0].owner == "analyst"


def test_rotate_revoke_disable(client: StarIntelClient) -> None:
    rotated = client.rotate_credential("cred-1", overlap_seconds=60)
    assert isinstance(rotated, CredentialSecret)
    assert rotated.api_key == "star_sk_v1_rotated"
    revoked = client.revoke_credential("cred-1")
    assert isinstance(revoked, CredentialStatus)
    assert revoked.credential.id == "cred-1"
    disabled = client.disable_credential("cred-2")
    assert disabled.credential.id == "cred-2"


# ---- Generic manifest-driven dispatch ---------------------------------------


def test_generic_call_dispatches_by_operation_id(client: StarIntelClient) -> None:
    response = client.call("auth.users.list")
    assert response.status_code == 200
    assert isinstance(response.data, list)


def test_generic_call_with_path_params(client: StarIntelClient) -> None:
    response = client.call(
        "auth.users.password.reset",
        path_params={"username": "analyst"},
        json={"password": "reset-1"},
    )
    assert response.data["user"]["username"] == "analyst"


def test_generic_call_unknown_operation_mentions_blocker(client: StarIntelClient) -> None:
    client.discover()
    with pytest.raises(UnknownOperationError) as excinfo:
        client.call("document.publish")
    assert "registry-migration" in str(excinfo.value)


def test_call_before_discovery_is_lazy(client: StarIntelClient) -> None:
    response = client.call("health.get")
    assert response.status_code == 200
    assert client.has_operation("health.get")


# ---- Correlation ids --------------------------------------------------------


def test_explicit_correlation_id_is_propagated(
    client: StarIntelClient, recorded_requests: list[dict[str, Any]]
) -> None:
    response = client.health(correlation_id="my-task-42")
    assert response.correlation_id == "my-task-42"
    assert (
        recorded_requests[-1]["headers"].get("X-Correlation-ID") == "my-task-42"
    )


def test_each_request_gets_fresh_correlation_id(
    client: StarIntelClient, recorded_requests: list[dict[str, Any]]
) -> None:
    client.health()
    client.health()
    first = recorded_requests[-2]["headers"].get("X-Correlation-ID")
    second = recorded_requests[-1]["headers"].get("X-Correlation-ID")
    assert first and second and first != second


def test_invalid_correlation_id_rejected(client: StarIntelClient) -> None:
    with pytest.raises(ValueError):
        client.health(correlation_id="bad cid with spaces")


def test_correlation_id_echo_captured_from_header(mock_base_url: str) -> None:
    client = StarIntelClient(base_url=mock_base_url, correlation_id="fixed-cid-1")
    assert client.health().correlation_id == "fixed-cid-1"
    assert client.health().correlation_id == "fixed-cid-1"


def test_reused_correlation_id_across_retries(mock_base_url: str) -> None:
    client = StarIntelClient(base_url=mock_base_url, sleep=lambda _s: None)
    response = client.call("health.get")
    assert response.status_code == 200


# ---- Client lifecycle -------------------------------------------------------


def test_context_manager(mock_base_url: str) -> None:
    with StarIntelClient(base_url=mock_base_url, api_key=API_KEY) as client:
        assert client.health().status_code == 200


def test_default_base_url_is_local() -> None:
    client = StarIntelClient(api_key=API_KEY)
    assert str(client.base_url).startswith("http://127.0.0.1:5000")


def test_timeout_is_bounded() -> None:
    client = StarIntelClient(timeout=10_000.0)
    assert client.timeout.read == 120.0


@pytest.mark.asyncio
async def test_async_client_discover_and_health(mock_base_url: str) -> None:
    client = AsyncStarIntelClient(base_url=mock_base_url, api_key=API_KEY)
    manifest = await client.discover()
    assert len(manifest.operations) == 16
    response = await client.health()
    assert response.status_code == 200
    await client.aclose()


@pytest.mark.asyncio
async def test_async_client_login_and_users(mock_base_url: str) -> None:
    client = AsyncStarIntelClient(base_url=mock_base_url, api_key=API_KEY)
    async with client:
        result = await client.login(VALID_USERNAME, VALID_PASSWORD)
        assert result.api_key == "star_sk_v1_minted"
        client.api_key = result.api_key
        users = await client.list_users()
        assert len(users) == 2
        with pytest.raises(StarIntelApiError):
            await client.login(VALID_USERNAME, "nope")


@pytest.mark.asyncio
async def test_async_client_generic_call_unknown_operation(mock_base_url: str) -> None:
    async with AsyncStarIntelClient(base_url=mock_base_url) as client:
        with pytest.raises(UnknownOperationError):
            await client.call("documents.bulk")

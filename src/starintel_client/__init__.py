"""StarIntel Python API client (contract-registry driven).

Public API: the discovery-driven clients plus the typed registry, error, and
payload models. Routes are never hardcoded; they come from the server's
contract registry documents.
"""

from ._client import (
    DEFAULT_BASE_URL,
    ApiResponse,
    AsyncStarIntelClient,
    StarIntelClient,
)
from ._correlation import new_correlation_id, validate_correlation_id
from ._errors import (
    ManifestError,
    StarIntelApiError,
    StarIntelClientError,
    StarIntelConnectionError,
    UnknownOperationError,
)
from ._manifest import (
    ClientManifest,
    ManifestOperation,
    ManifestResponse,
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
)
from ._openapi import (
    OpenApiDocument,
    OpenApiOperation,
    cross_check,
    parse_openapi_document,
)
from ._transport import AsyncTransport, RetryPolicy, SyncTransport

__version__ = "0.1.0"

__all__ = [
    "ApiResponse",
    "AsyncStarIntelClient",
    "AsyncTransport",
    "ClientManifest",
    "CredentialMetadata",
    "CredentialSecret",
    "CredentialStatus",
    "DEFAULT_BASE_URL",
    "LoginResult",
    "ManifestError",
    "ManifestOperation",
    "ManifestResponse",
    "OpenApiDocument",
    "OpenApiOperation",
    "RetryPolicy",
    "StarIntelApiError",
    "StarIntelClient",
    "StarIntelClientError",
    "StarIntelConnectionError",
    "SyncTransport",
    "UnknownOperationError",
    "UserMetadata",
    "UserStatus",
    "cross_check",
    "new_correlation_id",
    "parse_client_manifest",
    "parse_openapi_document",
    "render_path",
    "validate_correlation_id",
]

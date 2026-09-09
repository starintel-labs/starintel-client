"""Tests for the open_document_client factory (capability probe)."""

from __future__ import annotations

from typing import Any

import pytest

from starintel_client import AsyncStarIntelClient, open_document_client
from starintel_client._errors import ManifestError


def test_factory_returns_async_client_when_documents_contracted(mock_server: Any) -> None:
    mock_server.disable_document_ops()
    mock_server.enable_document_ops()
    client = open_document_client(base_url=mock_server.base_url, api_key="k")
    assert isinstance(client, AsyncStarIntelClient)
    assert client.api_key == "k"


def test_factory_raises_manifest_error_when_documents_missing(mock_server: Any) -> None:
    mock_server.disable_document_ops()
    with pytest.raises(ManifestError) as exc:
        open_document_client(base_url=mock_server.base_url, api_key="k")
    assert "documents.create" in str(exc.value)
    assert "starintel-server#5" in str(exc.value)

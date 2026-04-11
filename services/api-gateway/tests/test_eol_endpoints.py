"""Unit tests for the EOL batch endpoint (POST /api/v1/vms/eol).

Covers:
- _parse_os_for_eol normalisation (Windows Server variants, Ubuntu, unknown)
- Cache hit path
- Cache miss + endoflife.date API fallback + cache write
- Empty os_names list
- Unrecognised OS name
- DB connection failure (graceful degradation)
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("API_GATEWAY_AUTH_MODE", "disabled")

from services.api_gateway.eol_endpoints import (
    EolBatchRequest,
    EolBatchResponse,
    EolResult,
    _parse_os_for_eol,
)


# ---------------------------------------------------------------------------
# _parse_os_for_eol tests
# ---------------------------------------------------------------------------


class TestParseOsForEol:
    def test_windows_server_2025_standard(self):
        result = _parse_os_for_eol("Windows Server 2025 Standard")
        assert result == ("windows-server-2025", "2025")

    def test_windows_server_2019_datacenter(self):
        result = _parse_os_for_eol("Windows Server 2019 Datacenter")
        assert result == ("windows-server-2019", "2019")

    def test_windows_server_2012_r2_standard(self):
        result = _parse_os_for_eol("Windows Server 2012 R2 Standard")
        assert result == ("windows-server-2012-r2", "2012-r2")

    def test_windows_server_2008_r2(self):
        result = _parse_os_for_eol("Windows Server 2008 R2 Datacenter")
        assert result == ("windows-server-2008-r2", "2008-r2")

    def test_windows_server_2022(self):
        result = _parse_os_for_eol("Windows Server 2022")
        assert result == ("windows-server-2022", "2022")

    def test_windows_server_2016_essentials(self):
        result = _parse_os_for_eol("Windows Server 2016 Essentials")
        assert result == ("windows-server-2016", "2016")

    def test_ubuntu_2204_lts(self):
        result = _parse_os_for_eol("Ubuntu 22.04 LTS")
        assert result == ("ubuntu", "22.04")

    def test_ubuntu_2004(self):
        result = _parse_os_for_eol("Ubuntu 20.04")
        assert result == ("ubuntu", "20.04")

    def test_unrecognised_os(self):
        assert _parse_os_for_eol("Red Hat Enterprise Linux 9") is None

    def test_empty_string(self):
        assert _parse_os_for_eol("") is None

    def test_case_insensitive(self):
        result = _parse_os_for_eol("windows server 2025 standard")
        assert result == ("windows-server-2025", "2025")


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """FastAPI TestClient for the api-gateway."""
    from fastapi.testclient import TestClient
    from services.api_gateway.main import app

    app.state.credential = MagicMock(name="DefaultAzureCredential")
    app.state.cosmos_client = MagicMock(name="CosmosClient")
    return TestClient(app)


class TestBatchEolEndpoint:
    """Tests for POST /api/v1/vms/eol."""

    def test_empty_os_names(self, client):
        """Empty list returns empty results."""
        resp = client.post("/api/v1/vms/eol", json={"os_names": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []

    def test_unrecognised_os_returns_null_fields(self, client):
        """Unrecognised OS names return null eol_date and is_eol."""
        with patch(
            "services.api_gateway.eol_endpoints._resolve_dsn",
            return_value="postgresql://test:test@localhost:5432/test",
        ), patch("services.api_gateway.eol_endpoints.asyncpg") as mock_asyncpg:
            mock_conn = AsyncMock()
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            mock_conn.close = AsyncMock()

            resp = client.post(
                "/api/v1/vms/eol",
                json={"os_names": ["Red Hat Enterprise Linux 9"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["results"]) == 1
            result = data["results"][0]
            assert result["os_name"] == "Red Hat Enterprise Linux 9"
            assert result["eol_date"] is None
            assert result["is_eol"] is None

    def test_cache_hit(self, client):
        """When eol_cache has a valid row, return it without calling the API."""
        with patch(
            "services.api_gateway.eol_endpoints._resolve_dsn",
            return_value="postgresql://test:test@localhost:5432/test",
        ), patch("services.api_gateway.eol_endpoints.asyncpg") as mock_asyncpg:
            mock_conn = AsyncMock()
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            mock_conn.close = AsyncMock()

            # Simulate cache hit
            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "eol_date": date(2026, 10, 14),
                    "is_eol": False,
                    "source": "endoflife.date",
                }
            )

            resp = client.post(
                "/api/v1/vms/eol",
                json={"os_names": ["Windows Server 2025 Standard"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["results"]) == 1
            result = data["results"][0]
            assert result["os_name"] == "Windows Server 2025 Standard"
            assert result["eol_date"] == "2026-10-14"
            assert result["is_eol"] is False
            assert result["source"] == "endoflife.date"

    def test_cache_miss_api_fallback(self, client):
        """Cache miss triggers endoflife.date API call, then cache upsert."""
        with patch(
            "services.api_gateway.eol_endpoints._resolve_dsn",
            return_value="postgresql://test:test@localhost:5432/test",
        ), patch("services.api_gateway.eol_endpoints.asyncpg") as mock_asyncpg, patch(
            "services.api_gateway.eol_endpoints.httpx"
        ) as mock_httpx:
            mock_conn = AsyncMock()
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            mock_conn.close = AsyncMock()

            # Cache miss
            mock_conn.fetchrow = AsyncMock(return_value=None)
            mock_conn.execute = AsyncMock()

            # Mock httpx response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"eol": "2026-10-14"}

            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_http_client

            resp = client.post(
                "/api/v1/vms/eol",
                json={"os_names": ["Windows Server 2025 Standard"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["results"]) == 1
            result = data["results"][0]
            assert result["os_name"] == "Windows Server 2025 Standard"
            assert result["eol_date"] == "2026-10-14"
            assert result["source"] == "endoflife.date"

            # Verify cache write was called
            mock_conn.execute.assert_called_once()

    def test_cache_miss_api_failure_returns_unknown(self, client):
        """When both cache and API fail, return null fields."""
        with patch(
            "services.api_gateway.eol_endpoints._resolve_dsn",
            return_value="postgresql://test:test@localhost:5432/test",
        ), patch("services.api_gateway.eol_endpoints.asyncpg") as mock_asyncpg, patch(
            "services.api_gateway.eol_endpoints.httpx"
        ) as mock_httpx:
            mock_conn = AsyncMock()
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            mock_conn.close = AsyncMock()

            # Cache miss
            mock_conn.fetchrow = AsyncMock(return_value=None)

            # API returns 404
            mock_response = MagicMock()
            mock_response.status_code = 404

            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_http_client

            resp = client.post(
                "/api/v1/vms/eol",
                json={"os_names": ["Windows Server 2025 Standard"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            result = data["results"][0]
            assert result["eol_date"] is None
            assert result["is_eol"] is None

    def test_db_connection_failure_returns_unknowns(self, client):
        """DB unavailable returns null fields for all OS names — never raises."""
        with patch(
            "services.api_gateway.eol_endpoints._resolve_dsn",
            return_value="postgresql://test:test@localhost:5432/test",
        ), patch("services.api_gateway.eol_endpoints.asyncpg") as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(
                side_effect=ConnectionError("Connection refused")
            )

            resp = client.post(
                "/api/v1/vms/eol",
                json={"os_names": ["Windows Server 2025 Standard", "Ubuntu 22.04 LTS"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["results"]) == 2
            for result in data["results"]:
                assert result["eol_date"] is None
                assert result["is_eol"] is None

    def test_deduplicates_os_names(self, client):
        """Duplicate OS names are deduplicated but all appear in results."""
        with patch(
            "services.api_gateway.eol_endpoints._resolve_dsn",
            return_value="postgresql://test:test@localhost:5432/test",
        ), patch("services.api_gateway.eol_endpoints.asyncpg") as mock_asyncpg:
            mock_conn = AsyncMock()
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            mock_conn.close = AsyncMock()

            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "eol_date": date(2026, 10, 14),
                    "is_eol": False,
                    "source": "endoflife.date",
                }
            )

            resp = client.post(
                "/api/v1/vms/eol",
                json={
                    "os_names": [
                        "Windows Server 2025 Standard",
                        "Windows Server 2025 Standard",
                    ]
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            # Only one result because dedup keeps unique names
            assert len(data["results"]) == 1
            # fetchrow called once (deduped)
            assert mock_conn.fetchrow.call_count == 1

    def test_eol_boolean_true(self, client):
        """When endoflife.date returns eol:true (boolean), is_eol should be True."""
        with patch(
            "services.api_gateway.eol_endpoints._resolve_dsn",
            return_value="postgresql://test:test@localhost:5432/test",
        ), patch("services.api_gateway.eol_endpoints.asyncpg") as mock_asyncpg, patch(
            "services.api_gateway.eol_endpoints.httpx"
        ) as mock_httpx:
            mock_conn = AsyncMock()
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            mock_conn.close = AsyncMock()
            mock_conn.fetchrow = AsyncMock(return_value=None)
            mock_conn.execute = AsyncMock()

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"eol": True}

            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_http_client

            resp = client.post(
                "/api/v1/vms/eol",
                json={"os_names": ["Windows Server 2008 Standard"]},
            )
            assert resp.status_code == 200
            result = resp.json()["results"][0]
            assert result["is_eol"] is True
            assert result["eol_date"] is None

    def test_mixed_recognised_and_unrecognised(self, client):
        """Mix of recognised and unrecognised OS names."""
        with patch(
            "services.api_gateway.eol_endpoints._resolve_dsn",
            return_value="postgresql://test:test@localhost:5432/test",
        ), patch("services.api_gateway.eol_endpoints.asyncpg") as mock_asyncpg:
            mock_conn = AsyncMock()
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            mock_conn.close = AsyncMock()

            mock_conn.fetchrow = AsyncMock(
                return_value={
                    "eol_date": date(2029, 1, 9),
                    "is_eol": False,
                    "source": "endoflife.date",
                }
            )

            resp = client.post(
                "/api/v1/vms/eol",
                json={
                    "os_names": [
                        "Windows Server 2022 Datacenter",
                        "Unknown Linux Distro",
                    ]
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["results"]) == 2

            # First: recognised
            assert data["results"][0]["os_name"] == "Windows Server 2022 Datacenter"
            assert data["results"][0]["eol_date"] == "2029-01-09"

            # Second: unrecognised
            assert data["results"][1]["os_name"] == "Unknown Linux Distro"
            assert data["results"][1]["eol_date"] is None
            assert data["results"][1]["is_eol"] is None

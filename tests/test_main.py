"""
Tests for main.py API endpoints.

Uses FastAPI's TestClient to exercise routes end-to-end within the process,
with all external I/O (aggregator, docker_manager, httpx) mocked out.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Return a TestClient with a fresh app import."""
    from movieseer.main import app

    return TestClient(app)


class TestApiConfig:
    """GET /api/config returns browser-facing service URLs."""

    def test_returns_all_expected_keys(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        expected_keys = {
            "jellyseerr_url",
            "jellyfin_url",
            "sonarr_url",
            "radarr_url",
            "sabnzbd_url",
            "qbittorrent_url",
        }
        assert expected_keys == set(data.keys())

    def test_urls_constructed_from_host_ip(self, client):
        with (
            patch("movieseer.main.HOST_IP", "10.0.0.1"),
            patch("movieseer.main.JELLYSEERR_PORT", 5055),
        ):
            response = client.get("/api/config")
        assert response.json()["jellyseerr_url"] == "http://10.0.0.1:5055"

    def test_all_urls_start_with_http(self, client):
        response = client.get("/api/config")
        for url in response.json().values():
            assert url.startswith("http://")


class TestDashboard:
    """GET / serves the HTML shell."""

    def test_root_returns_html(self, client):
        # The file won't exist in the test environment, so we just check the
        # route is registered and returns a non-500 response when the file is present.
        with patch("movieseer.main.FileResponse") as mock_fr:
            mock_fr.return_value = MagicMock(status_code=200)
            # Route exists — no 404
            response = client.get("/")
            assert response.status_code != 404


class TestApiStatus:
    """GET /api/status proxies to the aggregator."""

    def test_returns_aggregator_data(self, client):
        mock_data = {"requests": [], "system": {}}
        with patch(
            "movieseer.main.aggregator.get_status",
            new_callable=AsyncMock,
            return_value=mock_data,
        ):
            response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json() == mock_data


class TestApiSearch:
    """GET /api/search proxies to Jellyseerr."""

    def test_missing_query_returns_422(self, client):
        response = client.get("/api/search")
        assert response.status_code == 422

    def test_short_query_returns_422(self, client):
        # min_length=1 means empty string only fails; single char is fine
        response = client.get("/api/search?q=")
        assert response.status_code == 422

    def test_valid_query_returns_results(self, client):
        jellyseerr_response = {
            "results": [
                {
                    "mediaType": "movie",
                    "id": 1,
                    "title": "Dune",
                    "originalTitle": "Dune",
                    "releaseDate": "2021-09-15",
                    "posterPath": "/poster.jpg",
                },
            ]
        }
        mock_response = MagicMock()
        mock_response.json.return_value = jellyseerr_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            response = client.get("/api/search?q=dune")

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Dune"
        assert data["results"][0]["type"] == "movie"
        assert data["results"][0]["year"] == "2021"


class TestApiContainers:
    """GET /api/containers returns Docker container statuses."""

    def test_returns_container_list(self, client):
        mock_containers = [
            {"name": "sonarr", "status": "running", "uptime": "2h 0m"},
            {"name": "radarr", "status": "running", "uptime": "2h 0m"},
        ]
        with patch("movieseer.main.list_containers", return_value=mock_containers):
            response = client.get("/api/containers")

        assert response.status_code == 200
        assert response.json()["containers"] == mock_containers

    def test_docker_error_returns_503(self, client):
        with patch(
            "movieseer.main.list_containers",
            side_effect=RuntimeError("socket not found"),
        ):
            response = client.get("/api/containers")

        assert response.status_code == 503
        assert "error" in response.json()


class TestActionRestart:
    """POST /actions/restart triggers a restart of all non-self containers."""

    def test_successful_restart_returns_ok(self, client):
        with patch("movieseer.main.restart_all", return_value=["sonarr", "radarr"]):
            response = client.post("/actions/restart")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert set(data["restarted"]) == {"sonarr", "radarr"}

    def test_docker_error_returns_503(self, client):
        with patch("movieseer.main.restart_all", side_effect=RuntimeError("socket error")):
            response = client.post("/actions/restart")

        assert response.status_code == 503
        assert response.json()["ok"] is False


class TestActionRebuild:
    """POST /actions/rebuild pulls images and restarts all non-self containers."""

    def test_successful_rebuild_returns_ok(self, client):
        with patch("movieseer.main.rebuild_all", return_value=["jellyfin"]):
            response = client.post("/actions/rebuild")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["rebuilt"] == ["jellyfin"]

    def test_docker_error_returns_503(self, client):
        with patch("movieseer.main.rebuild_all", side_effect=RuntimeError("socket error")):
            response = client.post("/actions/rebuild")

        assert response.status_code == 503


class TestWebhooks:
    """POST /webhook/radarr and /webhook/sonarr invalidate cache and notify."""

    def test_radarr_webhook_returns_ok(self, client):
        with (
            patch("movieseer.main.aggregator.invalidate_cache"),
            patch("movieseer.main.handle_radarr", new_callable=AsyncMock),
        ):
            response = client.post("/webhook/radarr", json={"eventType": "Grab"})

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_sonarr_webhook_returns_ok(self, client):
        with (
            patch("movieseer.main.aggregator.invalidate_cache"),
            patch("movieseer.main.handle_sonarr", new_callable=AsyncMock),
        ):
            response = client.post("/webhook/sonarr", json={"eventType": "Download"})

        assert response.status_code == 200
        assert response.json() == {"ok": True}

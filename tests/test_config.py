"""
Tests for config.py.

Verifies that all configuration values have sensible defaults when environment
variables are absent, and that numeric vars are returned as the correct type.
"""

import importlib
import os
import sys


def _reload_config(env_overrides: dict) -> object:
    """
    Reload the config module with a patched environment.

    Parameters
    ----------
    env_overrides : dict
        Environment variables to set before reloading. Any key set to ``None``
        will be removed from the environment.

    Returns
    -------
    object
        The freshly imported config module.
    """
    # Remove cached module so os.getenv calls re-evaluate.
    sys.modules.pop("movieseer.config", None)

    clean_env = {k: v for k, v in os.environ.items()}
    for key, val in env_overrides.items():
        if val is None:
            clean_env.pop(key, None)
        else:
            clean_env[key] = val

    original = os.environ.copy()
    os.environ.clear()
    os.environ.update(clean_env)

    try:
        import movieseer.config as config
        importlib.reload(config)
        return config
    finally:
        os.environ.clear()
        os.environ.update(original)
        sys.modules.pop("movieseer.config", None)


class TestDefaults:
    """Config defaults are applied when no env vars are set."""

    def test_jellyseerr_url_default(self):
        cfg = _reload_config({
            "JELLYSEERR_URL": None,
            "JELLYSEERR_API_KEY": None,
        })
        assert cfg.JELLYSEERR_URL == "http://jellyseerr:5055"

    def test_radarr_url_default(self):
        cfg = _reload_config({"RADARR_URL": None})
        assert cfg.RADARR_URL == "http://radarr:7878"

    def test_sonarr_url_default(self):
        cfg = _reload_config({"SONARR_URL": None})
        assert cfg.SONARR_URL == "http://sonarr:8989"

    def test_prowlarr_url_default(self):
        cfg = _reload_config({"PROWLARR_URL": None})
        assert cfg.PROWLARR_URL == "http://prowlarr:9696"

    def test_sabnzbd_url_default(self):
        cfg = _reload_config({"SABNZBD_URL": None})
        assert cfg.SABNZBD_URL == "http://sabnzbd:8080"

    def test_qbittorrent_url_default(self):
        cfg = _reload_config({"QBITTORRENT_URL": None})
        assert cfg.QBITTORRENT_URL == "http://gluetun:8080"

    def test_ntfy_url_default(self):
        cfg = _reload_config({"NTFY_URL": None})
        assert cfg.NTFY_URL == "http://ntfy:80"

    def test_ntfy_topic_default(self):
        cfg = _reload_config({"NTFY_TOPIC": None})
        assert cfg.NTFY_TOPIC == "movieseer"

    def test_cache_ttl_default_is_int(self):
        cfg = _reload_config({"CACHE_TTL": None})
        assert isinstance(cfg.CACHE_TTL, int)
        assert cfg.CACHE_TTL == 30

    def test_history_window_days_default_is_int(self):
        cfg = _reload_config({"HISTORY_WINDOW_DAYS": None})
        assert isinstance(cfg.HISTORY_WINDOW_DAYS, int)
        assert cfg.HISTORY_WINDOW_DAYS == 7


class TestOverrides:
    """Env var overrides are picked up correctly."""

    def test_jellyseerr_url_override(self):
        cfg = _reload_config({"JELLYSEERR_URL": "http://custom:1234"})
        assert cfg.JELLYSEERR_URL == "http://custom:1234"

    def test_cache_ttl_override(self):
        cfg = _reload_config({"CACHE_TTL": "60"})
        assert cfg.CACHE_TTL == 60
        assert isinstance(cfg.CACHE_TTL, int)

    def test_api_keys_default_to_empty_string(self):
        cfg = _reload_config({
            "JELLYSEERR_API_KEY": None,
            "RADARR_API_KEY": None,
            "SONARR_API_KEY": None,
        })
        assert cfg.JELLYSEERR_API_KEY == ""
        assert cfg.RADARR_API_KEY == ""
        assert cfg.SONARR_API_KEY == ""

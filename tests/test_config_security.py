import unittest
from pathlib import Path
from unittest.mock import patch

import backend


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


class QueueAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses.pop(0)


class ConfigSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_config_never_returns_service_secrets(self):
        config = await backend.get_config()
        forbidden = {"radarrKey", "sonarrKey", "plexToken", "tmdbKey"}
        self.assertTrue(forbidden.isdisjoint(config))
        self.assertEqual(bool(backend.RADARR_KEY), config["hasRadarrKey"])
        self.assertEqual(bool(backend.SONARR_KEY), config["hasSonarrKey"])
        self.assertEqual(bool(backend.PLEX_TOKEN), config["hasPlexToken"])
        self.assertEqual(bool(backend.TMDB_KEY), config["hasTmdbKey"])

    async def test_config_options_are_proxied_without_exposing_api_keys(self):
        client = QueueAsyncClient(
            [
                FakeResponse(200, [{"id": 4, "name": "HD-1080p"}]),
                FakeResponse(200, [{"path": "H:\\"}]),
                FakeResponse(200, [{"id": 5, "name": "HD-720p"}]),
                FakeResponse(200, [{"path": "I:\\TV"}]),
            ]
        )
        with patch.object(backend.httpx, "AsyncClient", return_value=client):
            result = await backend.get_config_options()

        self.assertEqual([{"id": 4, "name": "HD-1080p"}], result["radarrProfiles"])
        self.assertEqual(["H:\\"], result["radarrRoots"])
        self.assertEqual([{"id": 5, "name": "HD-720p"}], result["sonarrProfiles"])
        self.assertEqual(["I:\\TV"], result["sonarrRoots"])
        self.assertTrue(
            all("X-Api-Key" in kwargs["headers"] for _, kwargs in client.requests)
        )

    async def test_android_settings_use_safe_backend_options_proxy(self):
        source = (
            Path(__file__).parents[1]
            / "android/app/src/main/java/com/movieswipe/SettingsActivity.kt"
        ).read_text()
        self.assertIn("/api/config/options", source)
        self.assertNotIn('.addHeader("X-Api-Key"', source)
        self.assertNotIn('val radarrKey = config["radarrKey"]', source)
        self.assertNotIn('val sonarrKey = config["sonarrKey"]', source)


if __name__ == "__main__":
    unittest.main()

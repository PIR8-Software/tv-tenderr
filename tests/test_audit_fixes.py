import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import backend
from fastapi.testclient import TestClient


SYNTHETIC_TOKEN = "synthetic-test-token"
AUTH = {"Authorization": f"Bearer {SYNTHETIC_TOKEN}"}


class FakeResponse:
    def __init__(self, status_code, json_data=None, text="", content=b"", headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")


class QueueAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return self.responses.pop(0)

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return self.responses.pop(0)

    async def put(self, url, **kwargs):
        self.requests.append(("PUT", url, kwargs))
        return self.responses.pop(0)

    async def delete(self, url, **kwargs):
        self.requests.append(("DELETE", url, kwargs))
        return self.responses.pop(0)


class ExplodingAsyncClient:
    def __init__(self):
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        raise AssertionError(f"unauthorized request reached upstream GET {url}")

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        raise AssertionError(f"unauthorized request reached upstream POST {url}")

    async def put(self, url, **kwargs):
        self.requests.append(("PUT", url, kwargs))
        raise AssertionError(f"unauthorized request reached upstream PUT {url}")

    async def delete(self, url, **kwargs):
        self.requests.append(("DELETE", url, kwargs))
        raise AssertionError(f"unauthorized request reached upstream DELETE {url}")


def mutating_api_paths():
    paths = []
    for route in backend.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if not path.startswith("/api/"):
            continue
        for method in sorted(methods & {"POST", "PUT", "DELETE", "PATCH"}):
            concrete = path
            for token in ("{movie_id}", "{show_id}", "{tmdb_id}"):
                concrete = concrete.replace(token, "1")
            paths.append((method, concrete))
    return paths


class AuthBoundaryTests(unittest.TestCase):
    def setUp(self):
        self._prior = os.environ.get(backend.API_TOKEN_ENV)
        os.environ[backend.API_TOKEN_ENV] = SYNTHETIC_TOKEN
        self.client = TestClient(backend.app)
        self.upstream = ExplodingAsyncClient()
        self.patcher = patch.object(backend.httpx, "AsyncClient", return_value=self.upstream)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if self._prior is None:
            os.environ.pop(backend.API_TOKEN_ENV, None)
        else:
            os.environ[backend.API_TOKEN_ENV] = self._prior

    def test_health_is_public_and_leaks_nothing(self):
        response = self.client.get("/api/health")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"ok": True}, response.json())
        self.assertEqual([], self.upstream.requests)

    def test_unauthenticated_mutating_routes_do_not_touch_upstream(self):
        paths = mutating_api_paths()
        self.assertGreaterEqual(len(paths), 20)
        for method, path in paths:
            response = self.client.request(method, path, json={"title": "x"})
            self.assertEqual(401, response.status_code, path)
            self.assertEqual([], self.upstream.requests, path)

    def test_unauthenticated_sensitive_reads_are_rejected(self):
        for path in (
            "/api/movies",
            "/api/shows",
            "/api/history",
            "/api/shows/history",
            "/api/discover/history",
            "/api/config",
            "/api/config/options",
            "/api/poster/1",
            "/api/stats",
            "/api/calendar",
            "/api/providers",
        ):
            response = self.client.get(path)
            self.assertEqual(401, response.status_code, path)
            self.assertEqual([], self.upstream.requests, path)

    def test_invalid_token_is_rejected_before_upstream(self):
        response = self.client.post(
            "/api/movies/1/block",
            headers={"Authorization": "Bearer wrong-token"},
        )
        self.assertEqual(401, response.status_code)
        self.assertEqual([], self.upstream.requests)

    def test_missing_and_invalid_tokens_cannot_change_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            initial = "RADARR_URL='http://original.invalid'\n"
            env_path.write_text(initial, encoding="utf-8")
            with patch.object(backend, "ENV_FILE", env_path):
                for headers in ({}, {"Authorization": "Bearer wrong-token"}):
                    for route in ("/api/config", "/api/save-env"):
                        response = self.client.post(route, headers=headers, json={"radarrUrl": "http://attacker.invalid", "apiToken": "injected"})
                        self.assertEqual(401, response.status_code, route)
                        self.assertEqual(initial, env_path.read_text(encoding="utf-8"))
            self.assertEqual([], self.upstream.requests)

    def test_docs_are_not_public(self):
        for path in ("/openapi.json", "/docs", "/redoc"):
            response = self.client.get(path)
            self.assertIn(response.status_code, (401, 404), path)
            self.assertNotEqual(200, response.status_code)

    def test_remote_bootstrap_cannot_write_config(self):
        response = self.client.post("/api/save-env", json={"radarrUrl": "http://evil.example"})
        self.assertEqual(401, response.status_code)
        self.assertEqual([], self.upstream.requests)


class HistoryFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_block_requires_recoverable_metadata_before_file_delete(self):
        for action, identifier in ((backend.block_movie, "tmdbId"), (backend.block_show, "tvdbId")):
            for response in (FakeResponse(503, text="unavailable"), FakeResponse(200, {"title": "Missing ID", "images": []})):
                client = QueueAsyncClient([response])
                saved = []
                loader = "load_decisions" if action == backend.block_movie else "load_show_decisions"
                saver = "save_decisions" if action == backend.block_movie else "save_show_decisions"
                with (
                    patch.object(backend, loader, return_value={}),
                    patch.object(backend, saver, side_effect=lambda value: saved.append(value)),
                    patch.object(backend.httpx, "AsyncClient", return_value=client),
                ):
                    with self.assertRaises(backend.HTTPException) as caught:
                        await action(44)
                self.assertIn(caught.exception.status_code, (502, 503), identifier)
                self.assertEqual(["GET"], [request[0] for request in client.requests])
                self.assertEqual([], saved)

    async def test_unclean_preserves_history_when_episode_list_fails(self):
        decisions = {"44": {"action": "clean", "title": "Keep Me"}}
        client = QueueAsyncClient([FakeResponse(503, text="unavailable")])
        saved = []
        with (
            patch.object(backend, "load_show_decisions", return_value=decisions),
            patch.object(backend, "save_show_decisions", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            with self.assertRaises(backend.HTTPException) as caught:
                await backend.unclean_show(44)
        self.assertGreaterEqual(caught.exception.status_code, 400)
        self.assertEqual([], saved)
        self.assertEqual("clean", decisions["44"]["action"])

    async def test_unclean_preserves_history_when_put_fails(self):
        decisions = {"44": {"action": "clean"}}
        client = QueueAsyncClient(
            [
                FakeResponse(200, [{"id": 1, "monitored": False}]),
                FakeResponse(500, text="put failed"),
            ]
        )
        saved = []
        with (
            patch.object(backend, "load_show_decisions", return_value=decisions),
            patch.object(backend, "save_show_decisions", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            with self.assertRaises(backend.HTTPException):
                await backend.unclean_show(44)
        self.assertEqual([], saved)
        self.assertEqual("clean", decisions["44"]["action"])

    async def test_clean_does_not_record_success_when_a_delete_fails(self):
        decisions = {}
        client = QueueAsyncClient(
            [
                FakeResponse(200, {"title": "Show", "year": 2020, "images": []}),
                FakeResponse(200, [{"id": 9, "size": 10}]),
                FakeResponse(500, text="delete failed"),
            ]
        )
        saved = []
        with (
            patch.object(backend, "load_show_decisions", return_value=decisions),
            patch.object(backend, "save_show_decisions", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            with self.assertRaises(backend.HTTPException):
                await backend.clean_show(44)
        self.assertEqual([], saved)
        self.assertNotIn("44", decisions)


class PosterBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_absolute_poster_is_fetched_without_arr_key(self):
        client = QueueAsyncClient(
            [
                FakeResponse(200, {"images": [{"coverType": "poster", "remoteUrl": "https://image.tmdb.org/t/p/w500/abc.jpg"}]}),
                FakeResponse(200, content=b"img"),
            ]
        )
        with (
            patch.object(backend, "RADARR_KEY", "synthetic-radarr-key"),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            await backend.get_poster(7)
        poster_call = client.requests[1]
        self.assertEqual("https://image.tmdb.org/t/p/w500/abc.jpg", poster_call[1])
        self.assertNotIn("X-Api-Key", poster_call[2].get("headers", {}))
        self.assertNotIn("synthetic-radarr-key", json.dumps(poster_call[2]))

    async def test_relative_poster_keeps_arr_key_and_does_not_follow_redirects(self):
        client = QueueAsyncClient(
            [
                FakeResponse(200, {"images": [{"coverType": "poster", "url": "/MediaCover/7/poster.jpg"}]}),
                FakeResponse(200, content=b"img"),
            ]
        )
        with (
            patch.object(backend, "RADARR_URL", "http://radarr.test"),
            patch.object(backend, "RADARR_KEY", "synthetic-radarr-key"),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            await backend.get_poster(7)
        poster_call = client.requests[1]
        self.assertEqual("http://radarr.test/MediaCover/7/poster.jpg", poster_call[1])
        self.assertEqual("synthetic-radarr-key", poster_call[2]["headers"]["X-Api-Key"])
        self.assertFalse(poster_call[2].get("follow_redirects", False))

    async def test_unlisted_poster_host_is_rejected_without_a_fetch(self):
        client = QueueAsyncClient(
            [FakeResponse(200, {"images": [{"coverType": "poster", "remoteUrl": "https://evil.example/poster.jpg"}]})]
        )
        with patch.object(backend.httpx, "AsyncClient", return_value=client):
            with self.assertRaises(backend.HTTPException):
                await backend.get_poster(7)
        self.assertEqual(1, len(client.requests))


class SkipSemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_skip_preserves_existing_preference_and_does_not_call_arr(self):
        for action in ("keep", "super_keep", "block", "clean"):
            decisions = {"9": {"action": action, "title": "Stay"}}
            saved = []
            with (
                patch.object(backend, "load_decisions", return_value=decisions),
                patch.object(backend, "save_decisions", side_effect=lambda data: saved.append(dict(data))),
                patch.object(backend.httpx, "AsyncClient", side_effect=AssertionError("skip must not call upstream")),
            ):
                result = await backend.skip_movie(9)
            self.assertTrue(result["preserved"])
            self.assertEqual(action, decisions["9"]["action"])
            self.assertEqual([], saved)

    async def test_fresh_skip_is_temporary_and_not_an_exclusion(self):
        decisions = {}
        saved = []
        with (
            patch.object(backend, "load_decisions", return_value=decisions),
            patch.object(backend, "save_decisions", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", side_effect=AssertionError("skip must not call upstream")),
        ):
            result = await backend.skip_movie(9)
        self.assertEqual("skip", result["action"])
        self.assertFalse(result["preserved"])
        self.assertEqual("skip", saved[-1]["9"]["action"])
        self.assertNotIn("exclusion", saved[-1]["9"])
        self.assertTrue(backend.is_decision_active(saved[-1]["9"]))
        expired = {
            "action": "skip",
            "timestamp": (datetime.now() - timedelta(hours=backend.skip_revisit_hours() + 1)).isoformat(),
        }
        self.assertFalse(backend.is_decision_active(expired))

    def test_clean_stays_out_of_the_swipe_queue(self):
        self.assertTrue(backend.is_decision_active({"action": "clean", "timestamp": datetime.now().isoformat()}))


class StorageSafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_corrupt_store_is_not_replaced_with_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(backend.HTTPException) as caught:
                backend.load_json_store(path)
            self.assertEqual(503, caught.exception.status_code)
            with self.assertRaises(backend.HTTPException):
                backend.save_json_store(path, {})
            self.assertEqual("{", path.read_text(encoding="utf-8"))

    async def test_parallel_updates_do_not_drop_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decisions.json"
            backend.save_json_store(path, {})

            async def add(item_id):
                async with backend.decision_lock:
                    data = backend.load_json_store(path)
                    await asyncio.sleep(0.01)
                    data[str(item_id)] = {"action": "skip"}
                    backend.save_json_store(path, data)

            await asyncio.gather(*(add(i) for i in range(8)))
            stored = backend.load_json_store(path)
            self.assertEqual({str(i) for i in range(8)}, set(stored))


class ConfigPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_config_write_persists_quality_and_roots_without_leaking_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("TV_TENDERR_API_TOKEN=synthetic-test-token\nRADARR_KEY=keep-me\n", encoding="utf-8")
            prior = {
                "RADARR_URL": backend.RADARR_URL,
                "RADARR_QUALITY_ID": backend.RADARR_QUALITY_ID,
                "RADARR_ROOT_FOLDER": backend.RADARR_ROOT_FOLDER,
            }
            try:
                with patch.object(backend, "ENV_FILE", env_path), patch.dict(os.environ, {backend.API_TOKEN_ENV: 'synthetic-test-token'}):
                    result = await backend.update_config(
                        {
                            "radarrUrl": "http://radarr.test:7878",
                            "radarrQualityId": 6,
                            "radarrRootFolder": "Z:\\Movies",
                        }
                    )
                self.assertEqual({"ok": True}, result)
                values = backend.read_env_values(env_path)
                self.assertEqual("http://radarr.test:7878", values["RADARR_URL"])
                self.assertEqual("6", values["RADARR_QUALITY_ID"])
                self.assertEqual("Z:\\Movies", values["RADARR_ROOT_FOLDER"])
                self.assertEqual("keep-me", values["RADARR_KEY"])
                self.assertNotIn("synthetic-test-token", json.dumps(result))
                self.assertEqual("http://radarr.test:7878", backend.RADARR_URL)
                self.assertEqual(6, backend.RADARR_QUALITY_ID)
            finally:
                backend.RADARR_URL = prior["RADARR_URL"]
                backend.RADARR_QUALITY_ID = prior["RADARR_QUALITY_ID"]
                backend.RADARR_ROOT_FOLDER = prior["RADARR_ROOT_FOLDER"]

    async def test_config_rejects_non_http_urls_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("RADARR_URL=http://keep.test\n", encoding="utf-8")
            with patch.object(backend, "ENV_FILE", env_path), patch.dict(os.environ, {backend.API_TOKEN_ENV: 'synthetic-test-token'}):
                with self.assertRaises(backend.HTTPException):
                    await backend.update_config({"radarrUrl": "file:///etc/passwd"})
            self.assertEqual("RADARR_URL=http://keep.test\n", env_path.read_text(encoding="utf-8"))


class RestoreExclusionTests(unittest.IsolatedAsyncioTestCase):
    async def test_movie_restore_removes_exclusion_then_uses_configured_root(self):
        decisions = {"22": {"action": "block", "tmdbId": 12345}}
        client = QueueAsyncClient(
            [
                FakeResponse(200, [{"id": 5, "tmdbId": 12345}]),
                FakeResponse(200, {}),
                FakeResponse(200, [{"title": "Test Movie", "tmdbId": 12345, "images": []}]),
                FakeResponse(201, {"id": 66}),
            ]
        )
        saved = []
        with (
            patch.object(backend, "load_decisions", return_value=decisions),
            patch.object(backend, "save_decisions", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend, "RADARR_ROOT_FOLDER", "Z:\\Movies"),
            patch.object(backend, "RADARR_QUALITY_ID", 6),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            result = await backend.unblock_movie(22)
        self.assertEqual("unblock", result["action"])
        self.assertEqual({}, saved[-1])
        self.assertEqual(
            ["GET", "DELETE", "GET", "POST"],
            [request[0] for request in client.requests],
        )
        payload = client.requests[3][2]["json"]
        self.assertEqual("Z:\\Movies", payload["rootFolderPath"])
        self.assertEqual(6, payload["qualityProfileId"])

    async def test_movie_restore_preserves_history_when_exclusion_lookup_fails(self):
        decisions = {"22": {"action": "block", "tmdbId": 12345}}
        client = QueueAsyncClient([FakeResponse(503, text="no exclusions")])
        saved = []
        with (
            patch.object(backend, "load_decisions", return_value=decisions),
            patch.object(backend, "save_decisions", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            with self.assertRaises(backend.HTTPException):
                await backend.unblock_movie(22)
        self.assertEqual([], saved)
        self.assertEqual("block", decisions["22"]["action"])


class StatsRouteTests(unittest.IsolatedAsyncioTestCase):
    def test_only_one_stats_route_is_registered(self):
        matches = [route for route in backend.app.routes if getattr(route, "path", "") == "/api/stats"]
        self.assertEqual(1, len(matches))

    async def test_stats_shape_has_no_decision_dump(self):
        client = QueueAsyncClient([FakeResponse(200, []), FakeResponse(200, [])])
        with (
            patch.object(backend, "load_decisions", return_value={}),
            patch.object(backend, "load_show_decisions", return_value={}),
            patch.object(backend, "load_hidden", return_value={}),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            result = await backend.get_stats()
        self.assertIn("movies", result)
        self.assertIn("shows", result)
        self.assertIn("discover", result)
        self.assertNotIn("decisions", result)


class PlexHeaderTests(unittest.TestCase):
    def test_plex_token_is_not_placed_in_the_query_string(self):
        calls = []

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(200, text="<MediaContainer></MediaContainer>")

        with (
            patch.object(backend, "PLEX_TOKEN", "synthetic-plex-token"),
            patch.object(backend, "PLEX_URL", "http://plex.test"),
            patch.object(backend.httpx, "get", side_effect=fake_get),
        ):
            backend.get_plex_sections()
        url, kwargs = calls[0]
        self.assertNotIn("synthetic-plex-token", url)
        self.assertNotIn("X-Plex-Token", kwargs.get("params") or {})
        self.assertEqual("synthetic-plex-token", kwargs["headers"]["X-Plex-Token"])


class BindAndReleaseTests(unittest.TestCase):
    def test_bind_defaults_fail_closed_without_a_token(self):
        with patch.dict(os.environ, {"BACKEND_HOST": "", backend.API_TOKEN_ENV: ""}, clear=False):
            os.environ.pop("BACKEND_HOST", None)
            os.environ.pop(backend.API_TOKEN_ENV, None)
            self.assertEqual("127.0.0.1", backend.resolve_bind_host())

    def test_explicit_bind_is_honored(self):
        with patch.dict(os.environ, {"BACKEND_HOST": "100.64.0.2"}, clear=False):
            self.assertEqual("100.64.0.2", backend.resolve_bind_host())

    def test_release_script_refuses_a_dirty_tree_and_does_not_add_all(self):
        script = Path(__file__).parents[1].joinpath("release.sh").read_text()
        self.assertNotIn("git add -A", script)
        self.assertNotIn("git tag -f", script)
        self.assertNotIn("git push -f", script)
        self.assertIn("dirty", script)

    def test_startup_refuses_empty_store_when_legacy_data_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "current"
            legacy = Path(tmp) / "legacy"
            current.mkdir()
            legacy.mkdir()
            (legacy / "decisions.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(SystemExit):
                backend.assert_data_dir_safe(current, legacy)


class YearContractTests(unittest.TestCase):
    def test_history_year_accepts_int_and_numeric_string(self):
        self.assertEqual(2024, backend.history_year(2024))
        self.assertEqual(2024, backend.history_year("2024"))
        self.assertEqual(2024, backend.history_year("2024-05-01"))
        self.assertIsNone(backend.history_year(None))
        self.assertIsNone(backend.history_year(""))
        self.assertIsNone(backend.history_year("nope"))


class WebContractTests(unittest.TestCase):
    def test_web_defers_destructive_actions_and_escapes_titles(self):
        page = Path(__file__).parents[1].joinpath("web", "index.html").read_text(encoding="utf-8")
        self.assertIn("scheduleDestructive", page)
        self.assertIn("DESTRUCTIVE_UNDO_MS = 10000", page)
        self.assertIn("function escapeHtml", page)
        self.assertIn("function apiFetch", page)
        self.assertNotIn('<div class="card-title">${item.title}</div>', page)
        self.assertNotIn('value="${config.radarrKey', page)
        block = page.split("function singleBlock", 1)[1].split("function singleSkip", 1)[0]
        self.assertIn("scheduleLibraryBlock(item.id, type, item.title)", block)
        self.assertNotIn("actionBlock(", block)
        helper = page.split("function scheduleLibraryBlock", 1)[1].split("function scheduleDiscoverDislike", 1)[0]
        self.assertLess(helper.index("scheduleDestructive"), helper.index("() => actionBlock("))


class ClientSourceContractTests(unittest.TestCase):
    def test_android_secrets_are_not_backed_up_in_plaintext_fields(self):
        root = Path(__file__).parents[1]
        manifest = (root / "android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        settings = (root / "android/app/src/main/res/layout/activity_settings.xml").read_text(encoding="utf-8")
        self.assertIn('android:allowBackup="false"', manifest)
        self.assertNotIn('android:inputType="text"', settings)
        self.assertIn(
            "EncryptedSharedPreferences",
            (root / "android/app/src/main/java/com/movieswipe/SecretStore.kt").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()

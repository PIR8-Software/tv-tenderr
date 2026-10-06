import unittest
from unittest.mock import patch

import backend


class NoRequestAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def get(self, url, **kwargs):
        raise AssertionError(f"Unexpected GET {url}")


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
        self.requests.append(("GET", url, kwargs))
        return self.responses.pop(0)

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return self.responses.pop(0)

    async def delete(self, url, **kwargs):
        self.requests.append(("DELETE", url, kwargs))
        return self.responses.pop(0)

    async def put(self, url, **kwargs):
        self.requests.append(("PUT", url, kwargs))
        return self.responses.pop(0)


class DiscoverHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_history_uses_shared_history_item_id(self):
        hidden = {
            "12345": {
                "action": "added",
                "timestamp": "2026-08-20T10:00:00",
                "title": "Test Movie",
                "year": 2024,
                "type": "movie",
            }
        }

        with (
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(backend.httpx, "AsyncClient", return_value=NoRequestAsyncClient()),
        ):
            result = await backend.get_discover_history()

        item = result["history"][0]
        self.assertEqual(12345, item["movieId"])
        self.assertEqual(12345, item["tmdbId"])


class ShowHistoryActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_unblock_show_readds_series_before_removing_history(self):
        decisions = {
            "44": {
                "action": "block",
                "title": "Test Show",
                "tvdbId": 9876,
            }
        }
        lookup = {
            "title": "Test Show",
            "tvdbId": 9876,
            "images": [],
            "seasons": [],
        }
        client = QueueAsyncClient(
            [FakeResponse(200, []), FakeResponse(200, [lookup]), FakeResponse(201, {"id": 77})]
        )
        saved = []

        with (
            patch.object(backend, "load_show_decisions", return_value=decisions),
            patch.object(backend, "save_show_decisions", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            result = await backend.unblock_show(44)

        self.assertEqual("unblock", result["action"])
        self.assertEqual({}, saved[-1])
        self.assertEqual(
            [
                ("GET", f"{backend.SONARR_URL}/api/v3/importlistexclusion"),
                ("GET", f"{backend.SONARR_URL}/api/v3/series/lookup"),
                ("POST", f"{backend.SONARR_URL}/api/v3/series"),
            ],
            [(method, url) for method, url, _ in client.requests],
        )
        self.assertEqual(
            {"term": "tvdb:9876"},
            client.requests[1][2]["params"],
        )
        payload = client.requests[2][2]["json"]
        self.assertEqual(9876, payload["tvdbId"])
        self.assertEqual(backend.SONARR_ROOT_FOLDER, payload["rootFolderPath"])
        self.assertEqual(backend.SONARR_QUALITY_ID, payload["qualityProfileId"])

    async def test_unkeep_show_removes_regular_and_super_keep_decisions(self):
        for action in ("keep", "super_keep"):
            decisions = {"44": {"action": action}}
            saved = []
            with (
                patch.object(backend, "load_show_decisions", return_value=decisions),
                patch.object(backend, "save_show_decisions", side_effect=lambda data: saved.append(dict(data))),
            ):
                result = await backend.unkeep_show(44)
            self.assertEqual("unkeep", result["action"])
            self.assertEqual({}, saved[-1])

    async def test_unclean_show_remonitors_episodes_and_removes_history(self):
        decisions = {"44": {"action": "clean"}}
        client = QueueAsyncClient(
            [
                FakeResponse(200, [{"id": 1, "monitored": False}, {"id": 2, "monitored": True}]),
                FakeResponse(200, {}),
            ]
        )
        saved = []
        with (
            patch.object(backend, "load_show_decisions", return_value=decisions),
            patch.object(backend, "save_show_decisions", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            result = await backend.unclean_show(44)

        self.assertEqual(1, result["reMonitored"])
        self.assertEqual({}, saved[-1])
        self.assertEqual(["GET", "PUT"], [request[0] for request in client.requests])


class MovieHistoryActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_unkeep_movie_removes_regular_and_super_keep_decisions(self):
        for action in ("keep", "super_keep"):
            decisions = {"22": {"action": action}}
            saved = []
            with (
                patch.object(backend, "load_decisions", return_value=decisions),
                patch.object(backend, "save_decisions", side_effect=lambda data: saved.append(dict(data))),
            ):
                result = await backend.unkeep_movie(22)
            self.assertEqual("unkeep", result["action"])
            self.assertEqual({}, saved[-1])

    async def test_unblock_movie_readds_movie_before_removing_history(self):
        decisions = {"22": {"action": "block", "tmdbId": 12345}}
        lookup = {"title": "Test Movie", "tmdbId": 12345, "images": []}
        client = QueueAsyncClient(
            [FakeResponse(200, []), FakeResponse(200, [lookup]), FakeResponse(201, {"id": 66})]
        )
        saved = []
        with (
            patch.object(backend, "load_decisions", return_value=decisions),
            patch.object(backend, "save_decisions", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            result = await backend.unblock_movie(22)

        self.assertEqual("unblock", result["action"])
        self.assertEqual({}, saved[-1])
        self.assertEqual(["GET", "GET", "POST"], [request[0] for request in client.requests])


class DiscoverRemoveTests(unittest.IsolatedAsyncioTestCase):
    async def test_remove_added_movie_deletes_radarr_item_then_history(self):
        hidden = {"12345": {"action": "added", "type": "movie"}}
        client = QueueAsyncClient(
            [FakeResponse(200, [{"id": 9, "tmdbId": 12345}]), FakeResponse(204)]
        )
        saved = []
        with (
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(backend, "save_hidden", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            result = await backend.remove_movie_from_discover(12345)

        self.assertEqual({"ok": True}, result)
        self.assertEqual({}, saved[-1])
        self.assertEqual(["GET", "DELETE"], [request[0] for request in client.requests])

    async def test_remove_added_movie_preserves_history_when_radarr_delete_fails(self):
        hidden = {"12345": {"action": "added", "type": "movie"}}
        client = QueueAsyncClient(
            [FakeResponse(200, [{"id": 9, "tmdbId": 12345}]), FakeResponse(500, text="failed")]
        )
        saved = []
        with (
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(backend, "save_hidden", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            with self.assertRaises(backend.HTTPException):
                await backend.remove_movie_from_discover(12345)

        self.assertEqual([], saved)

    async def test_remove_added_show_deletes_sonarr_item_then_history(self):
        hidden = {"54321": {"action": "added", "type": "show"}}
        client = QueueAsyncClient(
            [
                FakeResponse(200, [{"tvdbId": 9876}]),
                FakeResponse(200, [{"id": 8, "tvdbId": 9876}]),
                FakeResponse(204),
            ]
        )
        saved = []
        with (
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(backend, "save_hidden", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            result = await backend.remove_show_from_discover(54321)

        self.assertEqual({"ok": True}, result)
        self.assertEqual({}, saved[-1])
        self.assertEqual(["GET", "GET", "DELETE"], [request[0] for request in client.requests])

    async def test_remove_added_show_preserves_history_when_sonarr_delete_fails(self):
        hidden = {"54321": {"action": "added", "type": "show"}}
        client = QueueAsyncClient(
            [
                FakeResponse(200, [{"tvdbId": 9876}]),
                FakeResponse(200, [{"id": 8, "tvdbId": 9876}]),
                FakeResponse(500, text="failed"),
            ]
        )
        saved = []
        with (
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(backend, "save_hidden", side_effect=lambda data: saved.append(dict(data))),
            patch.object(backend.httpx, "AsyncClient", return_value=client),
        ):
            with self.assertRaises(backend.HTTPException):
                await backend.remove_show_from_discover(54321)

        self.assertEqual([], saved)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

import backend


class FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


class FakeAsyncClient:
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


class DiscoverDislikeExclusionTests(unittest.IsolatedAsyncioTestCase):
    async def test_movie_dislike_records_history_when_radarr_exclusion_already_exists(
        self,
    ):
        client = FakeAsyncClient(
            [
                FakeResponse(400, text="Movie is already excluded"),
                FakeResponse(
                    200, [{"tmdbId": 12345, "movieTitle": "The Test Movie", "id": 77}]
                ),
            ]
        )
        saved = []
        body = {"title": "The Test Movie", "year": 2024, "type": "movies"}

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value={}),
            patch.object(
                backend, "save_hidden", side_effect=lambda data: saved.append(data)
            ),
        ):
            result = await backend.dislike_discover(12345, body)

        self.assertEqual({"ok": True}, result)
        self.assertEqual("dislike", saved[0]["12345"]["hideSource"])
        self.assertEqual("radarr", saved[0]["12345"]["exclusionSource"])
        self.assertEqual(77, saved[0]["12345"]["exclusionId"])
        self.assertEqual(
            [
                ("POST", f"{backend.RADARR_URL}/api/v3/exclusions"),
                ("GET", f"{backend.RADARR_URL}/api/v3/exclusions"),
            ],
            [(method, url) for method, url, _ in client.requests],
        )

    async def test_show_dislike_records_history_when_sonarr_exclusion_already_exists(
        self,
    ):
        client = FakeAsyncClient(
            [
                FakeResponse(
                    200, [{"tvdbId": 9876, "title": "Sonarr Canonical Title"}]
                ),
                FakeResponse(400, text="Series is already excluded"),
                FakeResponse(
                    200, [{"tvdbId": 9876, "title": "Sonarr Canonical Title", "id": 88}]
                ),
            ]
        )
        saved = []
        body = {"title": "The Test Show", "year": 2023, "type": "shows"}

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value={}),
            patch.object(
                backend, "save_hidden", side_effect=lambda data: saved.append(data)
            ),
        ):
            result = await backend.dislike_discover(54321, body)

        self.assertEqual({"ok": True}, result)
        self.assertEqual("dislike", saved[0]["54321"]["hideSource"])
        self.assertEqual("sonarr", saved[0]["54321"]["exclusionSource"])
        self.assertEqual(9876, saved[0]["54321"]["tvdbId"])
        self.assertEqual(88, saved[0]["54321"]["exclusionId"])
        self.assertEqual(
            [
                ("GET", f"{backend.SONARR_URL}/api/v3/series/lookup"),
                ("POST", f"{backend.SONARR_URL}/api/v3/importlistexclusion"),
                ("GET", f"{backend.SONARR_URL}/api/v3/importlistexclusion"),
            ],
            [(method, url) for method, url, _ in client.requests],
        )

    async def test_movie_dislike_adds_radarr_import_list_exclusion_and_preserves_history_metadata(
        self,
    ):
        client = FakeAsyncClient([FakeResponse(201, {"id": 7})])
        saved = []
        body = {
            "title": "The Test Movie",
            "year": 2024,
            "posterUrl": "https://image.test/poster.jpg",
            "type": "movies",
        }

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value={}),
            patch.object(
                backend, "save_hidden", side_effect=lambda data: saved.append(data)
            ),
        ):
            result = await backend.dislike_discover(12345, body)

        self.assertEqual({"ok": True}, result)
        self.assertEqual(
            [
                (
                    "POST",
                    f"{backend.RADARR_URL}/api/v3/exclusions",
                    {
                        "headers": {"X-Api-Key": backend.RADARR_KEY},
                        "json": {
                            "tmdbId": 12345,
                            "movieTitle": "The Test Movie",
                            "movieYear": 2024,
                        },
                        "timeout": 30,
                    },
                )
            ],
            client.requests,
        )
        decision = saved[0]["12345"]
        self.assertEqual("hidden", decision["action"])
        self.assertEqual("The Test Movie", decision["title"])
        self.assertEqual(2024, decision["year"])
        self.assertEqual("https://image.test/poster.jpg", decision["posterUrl"])
        self.assertEqual("movies", decision["type"])
        self.assertEqual("dislike", decision["hideSource"])
        self.assertEqual("radarr", decision["exclusionSource"])
        self.assertEqual(7, decision["exclusionId"])
        self.assertTrue(decision["timestamp"])

    async def test_show_dislike_resolves_tvdb_id_and_adds_sonarr_import_list_exclusion(
        self,
    ):
        client = FakeAsyncClient(
            [
                FakeResponse(
                    200, [{"tvdbId": 9876, "title": "Sonarr Canonical Title"}]
                ),
                FakeResponse(201, {"id": 8}),
            ]
        )
        saved = []
        body = {
            "title": "The Test Show",
            "year": 2023,
            "posterUrl": "https://image.test/show.jpg",
            "type": "shows",
        }

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value={}),
            patch.object(
                backend, "save_hidden", side_effect=lambda data: saved.append(data)
            ),
        ):
            result = await backend.dislike_discover(54321, body)

        self.assertEqual({"ok": True}, result)
        self.assertEqual(
            [
                (
                    "GET",
                    f"{backend.SONARR_URL}/api/v3/series/lookup",
                    {
                        "headers": {"X-Api-Key": backend.SONARR_KEY},
                        "params": {"term": "tmdb:54321"},
                        "timeout": 15,
                    },
                ),
                (
                    "POST",
                    f"{backend.SONARR_URL}/api/v3/importlistexclusion",
                    {
                        "headers": {"X-Api-Key": backend.SONARR_KEY},
                        "json": {"tvdbId": 9876, "title": "Sonarr Canonical Title"},
                        "timeout": 30,
                    },
                ),
            ],
            client.requests,
        )
        decision = saved[0]["54321"]
        self.assertEqual("hidden", decision["action"])
        self.assertEqual("The Test Show", decision["title"])
        self.assertEqual(2023, decision["year"])
        self.assertEqual("https://image.test/show.jpg", decision["posterUrl"])
        self.assertEqual("shows", decision["type"])
        self.assertEqual("sonarr", decision["exclusionSource"])
        self.assertEqual(8, decision["exclusionId"])
        self.assertEqual(9876, decision["tvdbId"])
        self.assertTrue(decision["timestamp"])

    async def test_skip_hide_records_metadata_without_contacting_radarr_or_sonarr(self):
        saved = []
        body = {
            "action": "hidden",
            "title": "Skipped Movie",
            "year": 2022,
            "posterUrl": "https://image.test/skipped.jpg",
            "type": "movies",
        }

        with (
            patch.object(
                backend.httpx,
                "AsyncClient",
                side_effect=AssertionError("skip must not call an Arr service"),
            ),
            patch.object(backend, "load_hidden", return_value={}),
            patch.object(
                backend, "save_hidden", side_effect=lambda data: saved.append(data)
            ),
        ):
            result = await backend.hide_discover(111, body)

        self.assertEqual({"ok": True}, result)
        self.assertEqual("hidden", saved[0]["111"]["action"])
        self.assertEqual("skip", saved[0]["111"]["hideSource"])
        self.assertEqual("Skipped Movie", saved[0]["111"]["title"])

    async def test_failed_import_list_exclusion_does_not_record_dislike(self):
        client = FakeAsyncClient([FakeResponse(500, text="service unavailable")])
        saved = []

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value={}),
            patch.object(
                backend, "save_hidden", side_effect=lambda data: saved.append(data)
            ),
            self.assertRaises(backend.HTTPException) as raised,
        ):
            await backend.dislike_discover(
                222,
                {"title": "Failed Movie", "year": 2020, "type": "movies"},
            )

        self.assertEqual(500, raised.exception.status_code)
        self.assertEqual([], saved)

    async def test_movie_show_again_deletes_stored_radarr_exclusion_before_local_unhide(
        self,
    ):
        client = FakeAsyncClient([FakeResponse(204)])
        hidden = {
            "12345": {
                "action": "hidden",
                "type": "movies",
                "exclusionSource": "radarr",
                "exclusionId": 7,
            }
        }
        saved = []

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(
                backend,
                "save_hidden",
                side_effect=lambda data: saved.append(data.copy()),
            ),
        ):
            result = await backend.unhide_discover(12345)

        self.assertEqual({"ok": True}, result)
        self.assertEqual(
            [
                (
                    "DELETE",
                    f"{backend.RADARR_URL}/api/v3/exclusions/7",
                    {"headers": {"X-Api-Key": backend.RADARR_KEY}, "timeout": 30},
                )
            ],
            client.requests,
        )
        self.assertEqual([{}], saved)

    async def test_show_show_again_deletes_stored_sonarr_exclusion_before_local_unhide(
        self,
    ):
        client = FakeAsyncClient([FakeResponse(204)])
        hidden = {
            "54321": {
                "action": "hidden",
                "type": "shows",
                "exclusionSource": "sonarr",
                "exclusionId": 8,
                "tvdbId": 9876,
            }
        }
        saved = []

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(
                backend,
                "save_hidden",
                side_effect=lambda data: saved.append(data.copy()),
            ),
        ):
            result = await backend.unhide_discover(54321)

        self.assertEqual({"ok": True}, result)
        self.assertEqual(
            [
                (
                    "DELETE",
                    f"{backend.SONARR_URL}/api/v3/importlistexclusion/8",
                    {"headers": {"X-Api-Key": backend.SONARR_KEY}, "timeout": 30},
                )
            ],
            client.requests,
        )
        self.assertEqual([{}], saved)

    async def test_movie_show_again_without_stored_id_lists_and_matches_only_tmdb_id(
        self,
    ):
        client = FakeAsyncClient(
            [
                FakeResponse(
                    200, [{"id": 70, "tmdbId": 99999}, {"id": 7, "tmdbId": 12345}]
                ),
                FakeResponse(204),
            ]
        )
        hidden = {
            "12345": {"action": "hidden", "type": "movies", "exclusionSource": "radarr"}
        }
        saved = []

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(
                backend,
                "save_hidden",
                side_effect=lambda data: saved.append(data.copy()),
            ),
        ):
            result = await backend.unhide_discover(12345)

        self.assertEqual({"ok": True}, result)
        self.assertEqual("GET", client.requests[0][0])
        self.assertEqual(
            f"{backend.RADARR_URL}/api/v3/exclusions", client.requests[0][1]
        )
        self.assertEqual(
            f"{backend.RADARR_URL}/api/v3/exclusions/7", client.requests[1][1]
        )
        self.assertNotIn("/70", client.requests[1][1])
        self.assertEqual([{}], saved)

    async def test_show_show_again_without_stored_id_lists_and_matches_only_tvdb_id(
        self,
    ):
        client = FakeAsyncClient(
            [
                FakeResponse(
                    200, [{"id": 80, "tvdbId": 1111}, {"id": 8, "tvdbId": 9876}]
                ),
                FakeResponse(204),
            ]
        )
        hidden = {
            "54321": {
                "action": "hidden",
                "type": "shows",
                "exclusionSource": "sonarr",
                "tvdbId": 9876,
            }
        }
        saved = []

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(
                backend,
                "save_hidden",
                side_effect=lambda data: saved.append(data.copy()),
            ),
        ):
            result = await backend.unhide_discover(54321)

        self.assertEqual({"ok": True}, result)
        self.assertEqual(
            f"{backend.SONARR_URL}/api/v3/importlistexclusion", client.requests[0][1]
        )
        self.assertEqual(
            f"{backend.SONARR_URL}/api/v3/importlistexclusion/8", client.requests[1][1]
        )
        self.assertEqual([{}], saved)

    async def test_show_show_again_without_tvdb_id_resolves_tmdb_then_matches_sonarr_exclusion(
        self,
    ):
        client = FakeAsyncClient(
            [
                FakeResponse(200, [{"tvdbId": 9876, "title": "Canonical"}]),
                FakeResponse(200, [{"id": 8, "tvdbId": 9876}]),
                FakeResponse(204),
            ]
        )
        hidden = {
            "54321": {"action": "hidden", "type": "shows", "exclusionSource": "sonarr"}
        }
        saved = []

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(
                backend,
                "save_hidden",
                side_effect=lambda data: saved.append(data.copy()),
            ),
        ):
            result = await backend.unhide_discover(54321)

        self.assertEqual({"ok": True}, result)
        self.assertEqual(
            f"{backend.SONARR_URL}/api/v3/series/lookup", client.requests[0][1]
        )
        self.assertEqual({"term": "tmdb:54321"}, client.requests[0][2]["params"])
        self.assertEqual(
            f"{backend.SONARR_URL}/api/v3/importlistexclusion", client.requests[1][1]
        )
        self.assertEqual(
            f"{backend.SONARR_URL}/api/v3/importlistexclusion/8", client.requests[2][1]
        )
        self.assertEqual([{}], saved)

    async def test_skip_show_again_unhides_without_contacting_arr_services(self):
        hidden = {
            "111": {
                "action": "hidden",
                "type": "movies",
                "hideSource": "skip",
            }
        }
        saved = []

        with (
            patch.object(
                backend.httpx,
                "AsyncClient",
                side_effect=AssertionError("skip must not call an Arr service"),
            ),
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(
                backend,
                "save_hidden",
                side_effect=lambda data: saved.append(data.copy()),
            ),
        ):
            result = await backend.unhide_discover(111)

        self.assertEqual({"ok": True}, result)
        self.assertEqual([{}], saved)

    async def test_missing_matching_exclusion_is_already_removed_and_unhides(self):
        client = FakeAsyncClient([FakeResponse(200, [{"id": 70, "tmdbId": 99999}])])
        hidden = {
            "12345": {"action": "hidden", "type": "movies", "exclusionSource": "radarr"}
        }
        saved = []

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(
                backend,
                "save_hidden",
                side_effect=lambda data: saved.append(data.copy()),
            ),
        ):
            result = await backend.unhide_discover(12345)

        self.assertEqual({"ok": True}, result)
        self.assertEqual(1, len(client.requests))
        self.assertEqual([{}], saved)

    async def test_remote_delete_failure_preserves_local_hidden_entry(self):
        client = FakeAsyncClient([FakeResponse(500, text="service unavailable")])
        hidden = {
            "12345": {
                "action": "hidden",
                "type": "movies",
                "exclusionSource": "radarr",
                "exclusionId": 7,
            }
        }
        saved = []

        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(backend, "load_hidden", return_value=hidden),
            patch.object(
                backend,
                "save_hidden",
                side_effect=lambda data: saved.append(data.copy()),
            ),
            self.assertRaises(backend.HTTPException) as raised,
        ):
            await backend.unhide_discover(12345)

        self.assertEqual(500, raised.exception.status_code)
        self.assertIn("12345", hidden)
        self.assertEqual([], saved)


if __name__ == "__main__":
    unittest.main()

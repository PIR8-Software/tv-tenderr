"""F3 regression tests: queue batch consumption on a shrinking eligible set.

The corrected client protocol fetches the HEAD of the remaining eligible queue
(skip=0) after every batch of confirmed decisions; decided cards leave the
eligible set, so a shrinking/shuffled set can never be offset past. These
tests consume more than one full batch for movies and shows and assert no
item is skipped or repeated. All synthetic; upstream transport mocked.
"""

import tempfile
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

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class QueueAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def _next(self):
        return self.responses.pop(0)

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return self._next()

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return self._next()


class QueuePaginationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

        async def no_cast(*args, **kwargs):
            return []

        self.patches = [
            patch.object(backend, "DECISIONS_FILE", self.dir / "decisions.json"),
            patch.object(
                backend, "SHOW_DECISIONS_FILE", self.dir / "show_decisions.json"
            ),
            patch.object(backend, "DATA_DIR", self.dir),
            # Scrub service credentials: no real Plex/TMDb requests in tests.
            patch.object(backend, "PLEX_TOKEN", ""),
            patch.object(backend, "TMDB_KEY", ""),
            patch.object(backend, "get_tmdb_cast", no_cast),
            patch.object(backend, "get_tmdb_cast_by_tvdb", no_cast),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def radarr_item(movie_id):
        return {
            "id": movie_id,
            "title": f"Movie {movie_id}",
            "year": 2020,
            "tmdbId": 1000 + movie_id,
            "genres": [],
        }

    @staticmethod
    def sonarr_item(show_id):
        return {
            "id": show_id,
            "title": f"Show {show_id}",
            "year": 2020,
            "genres": [],
        }

    async def consume_movies_with_decisions(self, total, batch):
        """Drive the corrected client protocol to exhaustion; return seen ids."""
        items = [self.radarr_item(i) for i in range(1, total + 1)]
        seen = []
        while True:
            client = QueueAsyncClient([FakeResponse(200, items)])
            with patch.object(backend.httpx, "AsyncClient", return_value=client):
                page = await backend.get_movies(skip=0, limit=batch)
            ids = [m["id"] for m in page["movies"]]
            if not ids:
                break
            for movie_id in ids:
                self.assertNotIn(movie_id, seen, f"movie {movie_id} repeated")
                seen.append(movie_id)
            # Confirm one decision per consumed card; each leaves the set.
            for movie_id in ids:
                await backend.skip_movie(movie_id)
            if len(seen) >= total:
                break
        return seen

    async def consume_shows_with_decisions(self, total, batch):
        items = [self.sonarr_item(i) for i in range(1, total + 1)]
        seen = []
        while True:
            client = QueueAsyncClient([FakeResponse(200, items)])
            with patch.object(backend.httpx, "AsyncClient", return_value=client):
                page = await backend.get_shows(skip=0, limit=batch)
            ids = [s["id"] for s in page["shows"]]
            if not ids:
                break
            for show_id in ids:
                self.assertNotIn(show_id, seen, f"show {show_id} repeated")
                seen.append(show_id)
            for show_id in ids:
                await backend.skip_show(show_id)
            if len(seen) >= total:
                break
        return seen

    async def test_movies_multi_batch_consumption_never_skips(self):
        seen = await self.consume_movies_with_decisions(total=25, batch=20)
        self.assertEqual(sorted(seen), list(range(1, 26)))

    async def test_shows_multi_batch_consumption_never_skips(self):
        seen = await self.consume_shows_with_decisions(total=45, batch=20)
        self.assertEqual(sorted(seen), list(range(1, 46)))

    async def test_decided_cards_do_not_reappear_in_next_head_fetch(self):
        items = [self.radarr_item(i) for i in range(1, 26)]
        client = QueueAsyncClient([FakeResponse(200, items)])
        with patch.object(backend.httpx, "AsyncClient", return_value=client):
            first = await backend.get_movies(skip=0, limit=20)
        for movie in first["movies"]:
            await backend.skip_movie(movie["id"])
        client = QueueAsyncClient([FakeResponse(200, items)])
        with patch.object(backend.httpx, "AsyncClient", return_value=client):
            second = await backend.get_movies(skip=0, limit=20)

        first_ids = {m["id"] for m in first["movies"]}
        second_ids = {m["id"] for m in second["movies"]}
        self.assertEqual(5, second["total"])
        self.assertEqual(5, len(second_ids))
        self.assertEqual(set(), first_ids & second_ids)
        self.assertEqual(first_ids | second_ids, set(range(1, 26)))


if __name__ == "__main__":
    unittest.main()

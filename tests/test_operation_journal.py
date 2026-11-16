"""F2 regression tests: durable operation-intent/recovery journal for destructive paths.

Every test uses disposable temp stores and mocked upstream transport only.
Media bytes deleted upstream are never claimed to be recoverable.
"""

import json
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


class RecordingAsyncClient:
    """Queue-backed fake client that snapshots the journal at each request."""

    def __init__(self, responses, journal_path=None):
        self.responses = list(responses)
        self.requests = []
        self.journal_at_delete = None
        self.journal_path = journal_path

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def _record(self, verb, url, kwargs):
        self.requests.append((verb, url, kwargs))
        if verb == "DELETE" and self.journal_path is not None:
            if self.journal_path.exists():
                self.journal_at_delete = json.loads(
                    self.journal_path.read_text(encoding="utf-8")
                )

    def _next(self):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url, **kwargs):
        self._record("GET", url, kwargs)
        return self._next()

    async def post(self, url, **kwargs):
        self._record("POST", url, kwargs)
        return self._next()

    async def put(self, url, **kwargs):
        self._record("PUT", url, kwargs)
        return self._next()

    async def delete(self, url, **kwargs):
        self._record("DELETE", url, kwargs)
        return self._next()


class OperationJournalTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.journal_path = self.dir / "operation_journal.json"
        self.decisions_path = self.dir / "decisions.json"
        self.show_decisions_path = self.dir / "show_decisions.json"
        self.patches = [
            patch.object(backend, "OPJOURNAL_FILE", self.journal_path),
            patch.object(backend, "DECISIONS_FILE", self.decisions_path),
            patch.object(backend, "SHOW_DECISIONS_FILE", self.show_decisions_path),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def journal(self):
        return backend.load_journal()

    def save_journal_raw(self, data):
        backend.save_json_store(self.journal_path, data)


class BlockMovieJournalTests(OperationJournalTestCase):
    movie = {
        "id": 7,
        "title": "Test Movie",
        "year": 2024,
        "tmdbId": 4242,
        "images": [],
    }

    async def test_journal_intent_is_durable_before_radarr_delete(self):
        client = RecordingAsyncClient(
            [FakeResponse(200, self.movie), FakeResponse(204)],
            journal_path=self.journal_path,
        )
        with patch.object(backend.httpx, "AsyncClient", return_value=client):
            result = await backend.block_movie(7)

        self.assertEqual({"ok": True, "action": "block"}, result)
        # The journal must already hold the intent record when the DELETE fires.
        at_delete = client.journal_at_delete
        self.assertIsNotNone(at_delete, "journal was not written before DELETE")
        entry = at_delete["block:movie:7"]
        self.assertIn(entry["phase"], ("intent", "deleting"))
        self.assertEqual(4242, entry["recovery"]["tmdbId"])
        self.assertEqual("Test Movie", entry["recovery"]["title"])

    async def test_post_delete_store_failure_leaves_recovery_record_and_retry_completes(
        self,
    ):
        client = RecordingAsyncClient(
            [FakeResponse(200, self.movie), FakeResponse(204)],
            journal_path=self.journal_path,
        )
        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(
                backend,
                "save_decisions",
                side_effect=OSError("synthetic disk-full"),
            ),
            self.assertRaises(OSError),
        ):
            await backend.block_movie(7)

        entry = self.journal()["block:movie:7"]
        self.assertIn("effect_done", entry["phase"])
        self.assertEqual(4242, entry["recovery"]["tmdbId"])

        # Retry after the item is gone upstream: must complete the local record
        # without re-issuing a destructive delete.
        retry_client = RecordingAsyncClient([], journal_path=self.journal_path)
        with patch.object(backend.httpx, "AsyncClient", return_value=retry_client):
            result = await backend.block_movie(7)

        self.assertEqual({"ok": True, "action": "block"}, result)
        self.assertEqual([], retry_client.requests)
        decisions = backend.load_decisions()
        self.assertEqual("block", decisions["7"]["action"])
        self.assertEqual(4242, decisions["7"]["tmdbId"])
        self.assertEqual("Test Movie", decisions["7"]["title"])

    async def test_network_uncertainty_is_recorded_and_reconciled_on_retry(self):
        client = RecordingAsyncClient(
            [FakeResponse(200, self.movie), OSError("synthetic connection reset")],
            journal_path=self.journal_path,
        )
        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            self.assertRaises(backend.HTTPException) as caught,
        ):
            await backend.block_movie(7)

        self.assertIn(caught.exception.status_code, (502, 503))
        detail = caught.exception.detail
        self.assertIn("unknown", detail.lower())
        self.assertNotIn("recover", detail.lower().replace("not recoverable", ""))
        entry = self.journal()["block:movie:7"]
        self.assertEqual("uncertain", entry["phase"])

        # Upstream confirms the item is gone: reconcile to the local record.
        retry_client = RecordingAsyncClient(
            [FakeResponse(404, None, "not found")], journal_path=self.journal_path
        )
        with patch.object(backend.httpx, "AsyncClient", return_value=retry_client):
            result = await backend.block_movie(7)

        self.assertEqual({"ok": True, "action": "block"}, result)
        self.assertEqual(["GET"], [request[0] for request in retry_client.requests])
        decisions = backend.load_decisions()
        self.assertEqual(4242, decisions["7"]["tmdbId"])

    async def test_uncertain_retry_with_item_still_present_deletes_again(self):
        self.save_journal_raw(
            {
                "block:movie:7": {
                    "operation": "block",
                    "kind": "movie",
                    "service": "radarr",
                    "phase": "uncertain",
                    "recovery": {
                        "title": "Test Movie",
                        "year": 2024,
                        "tmdbId": 4242,
                        "posterUrl": None,
                    },
                }
            }
        )
        client = RecordingAsyncClient(
            [FakeResponse(200, self.movie), FakeResponse(204)],
            journal_path=self.journal_path,
        )
        with patch.object(backend.httpx, "AsyncClient", return_value=client):
            result = await backend.block_movie(7)

        self.assertEqual({"ok": True, "action": "block"}, result)
        self.assertEqual(["GET", "DELETE"], [request[0] for request in client.requests])
        decisions = backend.load_decisions()
        self.assertEqual("block", decisions["7"]["action"])

    async def test_process_crash_window_before_delete_ack_is_reconciled(self):
        # A crash after the DELETE left the journal stuck in "deleting".
        self.save_journal_raw(
            {
                "block:movie:7": {
                    "operation": "block",
                    "kind": "movie",
                    "service": "radarr",
                    "phase": "deleting",
                    "recovery": {
                        "title": "Test Movie",
                        "year": 2024,
                        "tmdbId": 4242,
                        "posterUrl": None,
                    },
                }
            }
        )
        retry_client = RecordingAsyncClient(
            [FakeResponse(404, None, "not found")], journal_path=self.journal_path
        )
        with patch.object(backend.httpx, "AsyncClient", return_value=retry_client):
            result = await backend.block_movie(7)

        self.assertEqual({"ok": True, "action": "block"}, result)
        self.assertEqual([], [r for r in retry_client.requests if r[0] == "DELETE"])
        decisions = backend.load_decisions()
        self.assertEqual(4242, decisions["7"]["tmdbId"])

    async def test_definite_delete_rejection_is_not_recorded_as_done(self):
        client = RecordingAsyncClient(
            [
                FakeResponse(200, self.movie),
                FakeResponse(500, None, "synthetic upstream failure"),
            ],
            journal_path=self.journal_path,
        )
        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            self.assertRaises(backend.HTTPException),
        ):
            await backend.block_movie(7)

        entry = self.journal()["block:movie:7"]
        self.assertEqual("failed", entry["phase"])
        self.assertEqual({}, backend.load_decisions())


class BlockShowJournalTests(OperationJournalTestCase):
    show = {
        "id": 9,
        "title": "Test Show",
        "year": 2023,
        "tvdbId": 9876,
        "images": [],
    }

    async def test_show_journal_intent_then_recovery_on_store_failure(self):
        client = RecordingAsyncClient(
            [FakeResponse(200, self.show), FakeResponse(204)],
            journal_path=self.journal_path,
        )
        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(
                backend,
                "save_show_decisions",
                side_effect=OSError("synthetic disk-full"),
            ),
            self.assertRaises(OSError),
        ):
            await backend.block_show(9)

        self.assertIsNotNone(client.journal_at_delete)
        entry = client.journal_at_delete["block:show:9"]
        self.assertIn(entry["phase"], ("intent", "deleting"))
        self.assertEqual(9876, entry["recovery"]["tvdbId"])

        entry = self.journal()["block:show:9"]
        self.assertEqual("effect_done", entry["phase"])

        retry_client = RecordingAsyncClient([], journal_path=self.journal_path)
        with patch.object(backend.httpx, "AsyncClient", return_value=retry_client):
            result = await backend.block_show(9)

        self.assertEqual({"ok": True, "action": "block"}, result)
        self.assertEqual([], retry_client.requests)
        decisions = backend.load_show_decisions()
        self.assertEqual("block", decisions["9"]["action"])
        self.assertEqual(9876, decisions["9"]["tvdbId"])


class CleanShowJournalTests(OperationJournalTestCase):
    series = {
        "id": 9,
        "title": "Test Show",
        "year": 2023,
        "images": [],
    }

    async def test_clean_journal_intent_before_first_file_delete_and_retry_finishes(
        self,
    ):
        files = [{"id": 1, "size": 100}, {"id": 2, "size": 200}]
        client = RecordingAsyncClient(
            [
                FakeResponse(200, self.series),  # series info
                FakeResponse(200, files),  # episode files
                FakeResponse(500, None, "synthetic delete failure"),
            ],
            journal_path=self.journal_path,
        )
        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            self.assertRaises(backend.HTTPException),
        ):
            await backend.clean_show(9)

        at_delete = client.journal_at_delete
        self.assertIsNotNone(at_delete, "journal was not written before deletes")
        entry = at_delete["clean:show:9"]
        self.assertIn(entry["phase"], ("intent", "cleaning"))
        self.assertEqual("Test Show", entry["recovery"]["title"])

        entry = self.journal()["clean:show:9"]
        self.assertEqual("cleaning", entry["phase"])
        self.assertEqual(0, entry.get("filesDeleted", 0))

        # Retry resumes: remaining files deleted, episodes unmonitored,
        # series kept monitored, then the local record is written.
        episodes = [{"id": 5, "monitored": True}, {"id": 6, "monitored": False}]
        retry_client = RecordingAsyncClient(
            [
                FakeResponse(200, self.series),  # series info
                FakeResponse(200, [{"id": 2, "size": 200}]),  # remaining files
                FakeResponse(204),  # delete file 2
                FakeResponse(200, episodes),  # episodes to unmonitor
                FakeResponse(200),  # PUT episode 5
                FakeResponse(200, self.series),  # reload series
                FakeResponse(200),  # PUT series monitored
            ],
            journal_path=self.journal_path,
        )
        with patch.object(backend.httpx, "AsyncClient", return_value=retry_client):
            result = await backend.clean_show(9)

        self.assertEqual(1, result["deleted"])
        decisions = backend.load_show_decisions()
        self.assertEqual("clean", decisions["9"]["action"])
        self.assertEqual(1, decisions["9"]["deletedFiles"])
        entry = self.journal()["clean:show:9"]
        self.assertEqual("recorded", entry["phase"])

    async def test_clean_store_failure_after_effects_leaves_recovery_record(self):
        episodes = [{"id": 5, "monitored": True}]
        client = RecordingAsyncClient(
            [
                FakeResponse(200, self.series),  # series info
                FakeResponse(200, [{"id": 1, "size": 100}]),  # files
                FakeResponse(204),  # delete file
                FakeResponse(200, episodes),  # episodes
                FakeResponse(200),  # PUT episode
                FakeResponse(200, self.series),  # reload series
                FakeResponse(200),  # PUT series monitored
            ],
            journal_path=self.journal_path,
        )
        with (
            patch.object(backend.httpx, "AsyncClient", return_value=client),
            patch.object(
                backend,
                "save_show_decisions",
                side_effect=OSError("synthetic disk-full"),
            ),
            self.assertRaises(OSError),
        ):
            await backend.clean_show(9)

        entry = self.journal()["clean:show:9"]
        self.assertEqual("effect_done", entry["phase"])
        self.assertEqual(1, entry["recovery"]["deletedFiles"])

        retry_client = RecordingAsyncClient([], journal_path=self.journal_path)
        with patch.object(backend.httpx, "AsyncClient", return_value=retry_client):
            result = await backend.clean_show(9)

        self.assertEqual(1, result["deleted"])
        decisions = backend.load_show_decisions()
        self.assertEqual("clean", decisions["9"]["action"])
        self.assertEqual([], retry_client.requests)


if __name__ == "__main__":
    unittest.main()

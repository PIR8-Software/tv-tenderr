import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backend


class DiscoverIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_number_keeps_two_independent_histories(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            backend, "HIDDEN_FILE", Path(directory) / "hidden.json"
        ):
            await backend.hide_discover(42, {"type": "movies", "title": "Movie"})
            await backend.hide_discover(42, {"type": "shows", "title": "Show"})
            rows = backend.load_hidden()
            self.assertEqual({"movie:42", "show:42"}, set(rows))
            history = await backend.get_discover_history()
            self.assertEqual({"movie", "show"}, {r["type"] for r in history["history"]})
            await backend.unhide_discover(42, {"type": "movie"})
            self.assertEqual({"show:42"}, set(backend.load_hidden()))

    async def test_legacy_migration_is_lossless_and_does_not_guess_unknown_type(self):
        legacy = {
            "1": {"type": "movies", "exclusionId": 12},
            "2": {"type": "shows", "exclusionId": 13},
            "3": {"title": "Unknown"},
            "4": {"type": "movie", "exclusionId": 14},
            "movie:4": {"type": "movie", "exclusionId": 15},
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            backend, "HIDDEN_FILE", Path(directory) / "hidden.json"
        ):
            backend.save_json_store(backend.HIDDEN_FILE, legacy)
            rows = backend.load_hidden()
            self.assertEqual(5, len(rows))
            self.assertEqual(12, rows["movie:1"]["exclusionId"])
            self.assertEqual(13, rows["show:2"]["exclusionId"])
            self.assertEqual(legacy["3"], rows["3"])
            self.assertEqual(legacy["4"], rows["4"])
            backend.save_hidden(rows)
            self.assertEqual(rows, backend.load_hidden())
            with self.assertRaises(backend.HTTPException) as error:
                await backend.unhide_discover(4)
            self.assertEqual(409, error.exception.status_code)

    async def test_untyped_legacy_rows_keep_hiding_both_types(self):
        # An ambiguous legacy row cannot be attributed to one type; it must
        # keep filtering both Discover listings exactly as before the
        # migration, while remaining preserved in the store.
        legacy = {"3": {"title": "Unknown"}}
        with tempfile.TemporaryDirectory() as directory, patch.object(
            backend, "HIDDEN_FILE", Path(directory) / "hidden.json"
        ):
            backend.save_json_store(backend.HIDDEN_FILE, legacy)
            hidden = backend.load_hidden()
            self.assertIn("3", hidden)
            for media_type in ("movie", "show"):
                self.assertTrue(
                    backend.discover_key(3, media_type) in hidden or str(3) in hidden,
                    f"legacy row no longer filters {media_type} discover",
                )

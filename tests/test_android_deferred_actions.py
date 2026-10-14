import re
import unittest
from pathlib import Path

MAIN_ACTIVITY = (
    Path(__file__).parents[1]
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "com"
    / "movieswipe"
    / "MainActivity.kt"
)


class AndroidDeferredActionTests(unittest.TestCase):
    def test_undo_before_clean_timeout_does_not_call_unclean_endpoint(self):
        source = MAIN_ACTIVITY.read_text()
        match = re.search(
            r"Long press skip on shows = clean files(?P<body>.*?)pendingBlock = \{\s*api\.cleanShow",
            source,
            re.DOTALL,
        )
        if match is None:
            self.fail("Show clean deferred-action block not found")
        self.assertNotIn("api.uncleanShow", match.group("body"))


if __name__ == "__main__":
    unittest.main()

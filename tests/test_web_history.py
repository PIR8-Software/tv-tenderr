import unittest
from pathlib import Path


WEB_INDEX = Path(__file__).parents[1] / "web" / "index.html"


class WebHistoryTests(unittest.TestCase):
    def test_all_history_actions_have_wired_buttons_and_endpoints(self):
        html = WEB_INDEX.read_text()

        expected_fragments = (
            "/api/movies/${id}/unkeep",
            "/api/movies/${id}/unblock",
            "/api/shows/${id}/unkeep",
            "/api/shows/${id}/unblock",
            "/api/shows/${id}/unclean",
            "/api/discover/${tmdbId}/${endpoint}",
            "/api/discover/${tmdbId}/unhide",
            "clean: ['Re-monitor', () => unclean(item.movieId)]",
        )
        for fragment in expected_fragments:
            self.assertIn(fragment, html)

    def test_history_actions_do_not_report_success_on_http_errors(self):
        html = WEB_INDEX.read_text()
        self.assertIn("async function postHistoryAction(endpoint)", html)
        self.assertIn("if (!response.ok)", html)
        self.assertIn("throw new Error(`History action failed: ${response.status}`)", html)


if __name__ == "__main__":
    unittest.main()

"""Regression tests for release_preflight.sh.

These lock the exact mishap this preflight exists to prevent: publishing or
building from a stale base, or with a version that is not strictly newer than
the latest release / the version installed on the device. All checks run
against disposable local git repositories; nothing is cleaned up or deleted
by the script under test.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "release_preflight.sh"


def run(args, cwd, env=None):
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def git(repo, *args):
    return run(
        [
            "git",
            "-c",
            "user.name=preflight-test",
            "-c",
            "user.email=preflight@test.invalid",
            *args,
        ],
        cwd=repo,
    )


def preflight(repo, *extra):
    return run(
        ["bash", str(SCRIPT), "--no-fetch", "--skip-signing", *extra],
        cwd=repo,
    )


def version_args(planned, *extra):
    return (
        "--planned",
        planned,
        "--base",
        "main",
        "--latest-released",
        "1.4.0",
        *extra,
    )


class ReleasePreflightTests(unittest.TestCase):
    def setUp(self):
        if not SCRIPT.is_file():
            self.skipTest("release_preflight.sh not present in this source copy")
        self._tmp = tempfile.TemporaryDirectory(prefix="preflight-test-")
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        result = git(self.repo, "init", "-b", "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.repo / "app.txt").write_text("v1\n")
        git(self.repo, "add", "app.txt")
        git(self.repo, "commit", "-m", "initial")

    def test_clean_tree_and_newer_version_passes(self):
        result = preflight(self.repo, *version_args("1.4.1"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RESULT: PASS", result.stdout)

    def test_dirty_tracked_file_fails_without_cleanup(self):
        (self.repo / "app.txt").write_text("v1 - edited\n")
        result = preflight(self.repo, *version_args("1.4.1"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("dirty", result.stdout)
        # The script must report, never clean: the edit is still there.
        self.assertEqual((self.repo / "app.txt").read_text(), "v1 - edited\n")

    def test_untracked_file_counts_as_dirty(self):
        (self.repo / "stray_helper.py").write_text("print('stray')\n")
        result = preflight(self.repo, *version_args("1.4.1"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("stray_helper.py", result.stdout)
        self.assertTrue((self.repo / "stray_helper.py").is_file())

    def test_allow_dirty_downgrades_to_warn(self):
        (self.repo / "app.txt").write_text("v1 - edited\n")
        result = preflight(self.repo, *version_args("1.4.1", "--allow-dirty"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WARN", result.stdout)

    def test_planned_not_newer_than_latest_release_fails(self):
        for planned in ("1.4.0", "1.3.9"):
            with self.subTest(planned=planned):
                result = preflight(self.repo, *version_args(planned))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("NOT newer than latest release", result.stdout)

    def test_installed_device_version_gate(self):
        stale = preflight(self.repo, *version_args("1.4.1", "--installed", "1.4.1"))
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        self.assertIn("stale update", stale.stdout)
        older = preflight(self.repo, *version_args("1.4.1", "--installed", "1.4.0"))
        self.assertEqual(older.returncode, 0, older.stdout + older.stderr)

    def test_installed_version_code_gate(self):
        stale = preflight(
            self.repo, *version_args("1.4.1", "--installed-code", "10401")
        )
        self.assertEqual(stale.returncode, 1, stale.stdout + stale.stderr)
        self.assertIn("would reject the update", stale.stdout)
        older = preflight(
            self.repo, *version_args("1.4.1", "--installed-code", "10400")
        )
        self.assertEqual(older.returncode, 0, older.stdout + older.stderr)

    def test_behind_base_fails(self):
        result = git(self.repo, "checkout", "-b", "release-work")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = git(self.repo, "checkout", "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.repo / "app.txt").write_text("v2 on main\n")
        git(self.repo, "add", "app.txt")
        git(self.repo, "commit", "-m", "main moved")
        result = git(self.repo, "checkout", "release-work")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = preflight(self.repo, *version_args("1.4.1"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"1 commit\(s\) BEHIND main")

    def test_ahead_of_base_is_allowed_for_work_in_progress(self):
        result = git(self.repo, "checkout", "-b", "release-work")
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.repo / "app.txt").write_text("v2 work\n")
        git(self.repo, "add", "app.txt")
        git(self.repo, "commit", "-m", "work in progress")
        result = preflight(self.repo, *version_args("1.4.1"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"1 commit\(s\) ahead of main, 0 behind")

    def test_malformed_planned_version_is_rejected(self):
        result = preflight(self.repo, "--planned", "1.4", "--base", "main")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("numeric X.Y.Z", result.stdout + result.stderr)

    def test_version_code_computation_matches_bump_script_scheme(self):
        result = preflight(self.repo, *version_args("1.4.1"))
        match = re.search(r"computed planned versionCode=(\d+)", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        self.assertEqual(match.group(1), "10401")

    def test_signing_continuity_check_with_generated_keystore(self):
        if not shutil.which("keytool"):
            self.skipTest("keytool not available")
        keystore = Path(self._tmp.name) / "test.jks"
        gen = run(
            [
                "keytool",
                "-genkeypair",
                "-keystore",
                str(keystore),
                "-alias",
                "tv-tenderr",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "1",
                "-dname",
                "CN=preflight-test",
                "-storepass",
                "test-store-pass",
                "-keypass",
                "test-store-pass",
            ],
            cwd=self.repo,
        )
        self.assertEqual(gen.returncode, 0, gen.stderr)
        listing = run(
            [
                "keytool",
                "-list",
                "-v",
                "-keystore",
                str(keystore),
                "-alias",
                "tv-tenderr",
                "-storepass",
                "test-store-pass",
            ],
            cwd=self.repo,
        )
        fingerprint = ""
        for line in listing.stdout.splitlines():
            if "SHA256:" in line:
                fingerprint = (
                    line.split(":", 1)[1].replace(":", "").replace(" ", "").lower()
                )
                break
        self.assertTrue(fingerprint, listing.stdout)
        props = Path(self._tmp.name) / "gradle.properties"
        props.write_text("TV_TENDERR_KEYSTORE_PASSWORD=test-store-pass\n")
        env = os.environ.copy()
        env["TV_TENDERR_GRADLE_PROPERTIES"] = str(props)

        result = run(
            [
                "bash",
                str(SCRIPT),
                "--no-fetch",
                *version_args("1.4.1"),
                "--keystore",
                str(keystore),
                "--expected-signer",
                fingerprint,
            ],
            cwd=self.repo,
            env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("matches expected release signer", result.stdout)

        rotated = run(
            [
                "bash",
                str(SCRIPT),
                "--no-fetch",
                *version_args("1.4.1"),
                "--keystore",
                str(keystore),
                "--expected-signer",
                "0" * 64,
            ],
            cwd=self.repo,
            env=env,
        )
        self.assertEqual(rotated.returncode, 1, rotated.stdout + rotated.stderr)
        self.assertIn("fingerprint CHANGED", rotated.stdout)

    def test_default_expected_signer_is_the_shipped_release_signer(self):
        text = SCRIPT.read_text()
        match = re.search(r'EXPECTED_SIGNER_SHA256="([0-9a-f]{64})"', text)
        self.assertIsNotNone(match, "EXPECTED_SIGNER_SHA256 constant not found")
        self.assertEqual(
            match.group(1),
            "6acb6aa7f6ee5ee0aa135be5e2a0ea4938b13f3c4c587e0ffd9e7749301f7e07",
        )


if __name__ == "__main__":
    unittest.main()

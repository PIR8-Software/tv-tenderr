# Changelog

Notable changes to TV Tenderr. Full release history is in the GitHub releases.

## 1.4.1 — 2026-11-16

Six review findings (F1–F6) fixed and regression-tested. Verification on the
release baseline: backend 93 tests, Android 48 unit tests + lint + release
build, 4 browser fixture suites, and a signed-APK device smoke.

### Fixed

- **F1 (P1) — Discover movie/TV identity collision.** Hiding a movie and a show
  that shared the same numeric ID overwrote one history and hid both. Discover
  rows are now typed (`movie:<id>` / `show:<id>`) with a lossless lazy
  migration; ambiguous legacy rows are preserved and rejected with 409 instead
  of being guessed.
- **F2 (P1) — delete-before-persist loss.** An interruption between the
  Radarr/Sonarr delete and the local store write lost history rows. Destructive
  paths now journal their intent to `data/operation_journal.json` before any
  upstream delete and reconcile interrupted or uncertain attempts on retry.
- **F3 (P2) — shrinking-queue offset skip.** Deciding on a card while more
  items were loading shifted the queue and skipped unseen items. The queue now
  fetches the head of the remaining queue and reloads wait for in-flight
  decision writes.
- **F4 (P2) — mode/search change during an in-flight load.** Switching mode or
  search while a load was in flight could render stale results. Loads are now
  generation-tracked; stale responses are rejected and only the newest
  deferred request is dispatched.
- **F5 (P2) — invalid backend URL persisted/crash.** An invalid URL was saved
  to preferences and could crash the client. URLs are validated
  (HTTP(S)+host) before any preference write; the previous valid config is
  retained and invalid stored config is handled without crashing.
- **F6 (P2) — malformed 200 responses crash callback.** A 200 response with a
  malformed body (bad JSON, HTML, null, missing fields) crashed the success
  callback. Responses are now schema-validated with exactly one normal error
  callback.

### Limits

- The operation journal preserves recovery **metadata** only; media already
  deleted upstream remain unrecoverable (documented in SECURITY.md).
- Ambiguous legacy Discover rows require manual recovery (409 responses); the
  migration never guesses a missing type.
- Browser suites exercise synthetic/intercepted flows in real headless Chrome;
  they are not a certification of live-backend behavior or on-device remote /
  TalkBack behavior.

### Tooling

- `release_preflight.sh` + `tests/test_release_preflight.py`: read-only,
  fail-closed release gate (fetch + base freshness + dirty detection + version
  monotonicity vs latest release and installed device version + signing
  continuity). See RELEASE_CHECKLIST.md step 0.

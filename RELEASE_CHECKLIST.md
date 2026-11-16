# Release Checklist

The release process is manual by design: CI verifies source and tests but **never
publishes an APK**. This checklist is the release gate — the device smoke is the
only thing that sees runtime behavior.

## 0. Preflight (run before any build or publication)

`./release_preflight.sh` is the reusable, read-only gate that prevents the
known mishap of building or publishing from a stale base or with a version
that is not strictly newer than the latest release or the installed app. It
never cleans, resets, or deletes anything.

```bash
# Fetches origin/tags, verifies base freshness, detects dirty state,
# checks version monotonicity and signing continuity:
./release_preflight.sh --planned X.Y.Z --installed <device versionName>

# Read the device version first (read-only):
#   adb shell dumpsys package com.movieswipe | grep -E 'versionName|versionCode'
```

- [ ] `./release_preflight.sh --planned X.Y.Z --installed <on-device versionName>` passes
- [ ] The planned version is **strictly newer** than the latest GitHub release and the installed app
- [ ] The working tree is clean (the script fails on dirty state; commit or stash first — it never cleans for you)
- [ ] The keystore certificate fingerprint check passes (signing continuity — protects in-place updates)

## 1. Tag

- [ ] `main` is green: **CI** (`tests (3.10)`, `tests (3.12)`, `lint`) and **Release source checks** (`backend`, `android`)
- [ ] `./release.sh X.Y.Z` — refuses a dirty tree; bumps `versionName`/`versionCode` + web version, commits, tags `vX.Y.Z`, pushes
- [ ] The tag push auto-creates a **draft** release `TV Tenderr vX.Y.Z` with generated notes (it never touches a published release or its assets)

## 2. Build and sign the production APK

- [ ] `cd android && ./gradlew assembleRelease` with the real keystore credentials
- [ ] Confirm the built APK reports `X.Y.Z` (versionName) and the expected versionCode

## 3. Device smoke — the actual release gate

Install the signed APK on a physical phone. If dependencies or the toolchain
changed since the last release, give extra time to image loading and networking.

**Transport (okhttp)**
- [ ] Launch app → login/token flow succeeds against a configured server
- [ ] Movies, Shows, and Discover screens all load data

**Images (glide)**
- [ ] Posters and backdrops render on Movies / Shows / Discover cards and detail views
- [ ] History and Calendar thumbnails render

**Core interactions**
- [ ] Swipe right / left / down (keep / block / super keep) respond correctly
- [ ] Undo banner appears within the 10-second window and restores state
- [ ] Search and the filter dialog work (genres, year, rating)
- [ ] Calendar loads Radarr/Sonarr entries with monitoring status
- [ ] History loads; "Show Again" and undo actions work
- [ ] Settings load and save; Plex refresh works

**Robustness**
- [ ] Rotate on each main screen; background and relaunch the app
- [ ] No content renders under the status/navigation bars (edge-to-edge check)

**Web GUI**
- [ ] Login works; card and grid views render; one keep and one block end to end

## 4. Publish (manual — by design)

- [ ] Upload the verified APK to the draft release
- [ ] Record the APK SHA-256 checksum in the release notes
- [ ] Publish the release

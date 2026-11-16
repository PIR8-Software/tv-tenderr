#!/bin/bash
# Release preflight for tv-tenderr.
#
# Run this BEFORE any Android build/install or release publication:
#
#   ./release_preflight.sh --planned 1.4.1 --installed 1.4.0
#
# It prevents the known mishap of building/publishing from a stale base or
# with a version that is not newer than the latest release or the version
# already installed on the device. Every check is fail-closed and read-only:
# this script never cleans, resets, stashes, or deletes anything.
#
# Checks:
#   1. fetch origin + tags (skippable with --no-fetch)
#   2. base freshness: HEAD must not be behind or diverged from the base ref
#   3. dirty worktree detection (reported only, never cleaned)
#   4. version monotonicity: planned > latest GitHub release and > installed
#   5. signing continuity: release keystore cert fingerprint unchanged
#
# Options:
#   --planned X.Y.Z        planned release version (required, numeric X.Y.Z)
#   --installed X.Y.Z      version currently installed on the target device
#   --installed-code NNNNN versionCode currently installed on the device
#   --latest-released V    override latest released version (else GitHub/git)
#   --base REF             base ref to compare against (default: origin/main)
#   --repo OWNER/REPO      repo for the GitHub release lookup (default: from
#                          the origin remote URL)
#   --keystore PATH        release keystore (default: android/app/tv-tenderr-release.jks)
#   --expected-signer SHA  expected keystore cert SHA-256 fingerprint (default:
#                          the shipped release signer; override only on a
#                          deliberate, verified signing-key rotation)
#   --no-fetch             skip git fetch (offline/test use)
#   --allow-dirty          report a dirty worktree as WARN instead of FAIL
#   --skip-signing         skip the keystore continuity check
#
# Environment:
#   TV_TENDERR_GRADLE_PROPERTIES  file holding TV_TENDERR_KEYSTORE_PASSWORD
#                                 (default: ~/.gradle/gradle.properties)
#
# Exit status: 0 when every check passes, 1 otherwise.

set -u

PLANNED=""
INSTALLED=""
INSTALLED_CODE=""
LATEST=""
BASE="origin/main"
REPO=""
KEYSTORE="android/app/tv-tenderr-release.jks"
EXPECTED_SIGNER=""
DO_FETCH=1
ALLOW_DIRTY=0
SKIP_SIGNING=0

# Public SHA-256 fingerprint of the release signing certificate. This is NOT
# a secret: the certificate ships inside every published APK. Keeping it here
# makes an accidental keystore rotation fail the preflight instead of
# silently producing INSTALL_FAILED_UPDATE_INCOMPATIBLE builds.
EXPECTED_SIGNER_SHA256="6acb6aa7f6ee5ee0aa135be5e2a0ea4938b13f3c4c587e0ffd9e7749301f7e07"

FAILURES=0

pass() { echo "[PASS] $1"; }
warn() { echo "[WARN] $1"; }
fail() { echo "[FAIL] $1"; FAILURES=$((FAILURES + 1)); }

usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --planned) PLANNED="${2:?--planned needs a value}"; shift 2 ;;
    --installed) INSTALLED="${2:?--installed needs a value}"; shift 2 ;;
    --installed-code) INSTALLED_CODE="${2:?--installed-code needs a value}"; shift 2 ;;
    --latest-released) LATEST="${2:?--latest-released needs a value}"; shift 2 ;;
    --base) BASE="${2:?--base needs a value}"; shift 2 ;;
    --repo) REPO="${2:?--repo needs a value}"; shift 2 ;;
    --keystore) KEYSTORE="${2:?--keystore needs a value}"; shift 2 ;;
    --expected-signer) EXPECTED_SIGNER="${2:?--expected-signer needs a value}"; shift 2 ;;
    --no-fetch) DO_FETCH=0; shift ;;
    --allow-dirty) ALLOW_DIRTY=1; shift ;;
    --skip-signing) SKIP_SIGNING=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

echo "== tv-tenderr release preflight =="

if [ -z "$PLANNED" ]; then
  echo "Missing required --planned X.Y.Z" >&2
  usage
fi
if ! echo "$PLANNED" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "--planned must be numeric X.Y.Z (got: $PLANNED)" >&2
  usage
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  fail "git: not inside a git working tree"
  echo "== RESULT: FAIL ($FAILURES check(s) failed) =="
  exit 1
fi

# 1. fetch ---------------------------------------------------------------
if [ "$DO_FETCH" -eq 1 ]; then
  if git fetch origin --tags >/dev/null 2>&1; then
    pass "fetch: origin and tags fetched"
  else
    fail "fetch: 'git fetch origin --tags' failed"
  fi
else
  warn "fetch: skipped (--no-fetch)"
fi

# 2. base freshness ------------------------------------------------------
if git rev-parse --verify -q "$BASE" >/dev/null; then
  counts=$(git rev-list --left-right --count "$BASE"...HEAD)
  behind=$(echo "$counts" | cut -f1)
  ahead=$(echo "$counts" | cut -f2)
  if [ "$behind" -gt 0 ] && [ "$ahead" -gt 0 ]; then
    fail "base: HEAD diverged from $BASE ($behind behind, $ahead ahead) — reconcile before release"
  elif [ "$behind" -gt 0 ]; then
    fail "base: HEAD is $behind commit(s) BEHIND $BASE — stale base; update before building/releasing"
  else
    pass "base: HEAD is $ahead commit(s) ahead of $BASE, 0 behind"
  fi
else
  fail "base: ref '$BASE' not found (fetch failed or wrong --base)"
fi

# 3. dirty worktree ------------------------------------------------------
dirty=$(git status --porcelain)
if [ -n "$dirty" ]; then
  count=$(echo "$dirty" | wc -l)
  msg="worktree: dirty ($count path(s)) — commit or stash before release; nothing was cleaned"
  if [ "$ALLOW_DIRTY" -eq 1 ]; then
    warn "$msg"
  else
    fail "$msg"
    echo "$dirty" | sed 's/^/         /'
  fi
else
  pass "worktree: clean"
fi

# 4. version monotonicity ------------------------------------------------
version_gt() {
  # true when $1 > $2 (numeric dotted versions)
  [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$2" ]
}

to_code() {
  # same scheme as bump_version.sh: MAJOR*10000 + MINOR*100 + PATCH
  echo "$1" | awk -F. '{ print $1 * 10000 + $2 * 100 + $3 }'
}

if [ -z "$LATEST" ]; then
  if [ -z "$REPO" ]; then
    remote_url=$(git remote get-url origin 2>/dev/null || true)
    REPO=$(echo "$remote_url" | sed -E 's|.*github\.com[:/]||; s|\.git$||')
  fi
  if [ -n "$REPO" ] && command -v gh >/dev/null 2>&1; then
    LATEST=$(gh api "repos/$REPO/releases/latest" --jq '.tag_name' 2>/dev/null | sed 's/^v//' || true)
  fi
  if [ -z "$LATEST" ]; then
    LATEST=$(git tag -l 'v[0-9]*' | sort -V | tail -1 | sed 's/^v//')
  fi
fi

if [ -n "$LATEST" ]; then
  if version_gt "$PLANNED" "$LATEST"; then
    pass "version: planned $PLANNED is newer than latest release $LATEST"
  else
    fail "version: planned $PLANNED is NOT newer than latest release $LATEST"
  fi
else
  warn "version: no latest release found; monotonicity not checked"
fi

if [ -n "$INSTALLED" ]; then
  if version_gt "$PLANNED" "$INSTALLED"; then
    pass "installed: planned $PLANNED is newer than device version $INSTALLED"
  else
    fail "installed: planned $PLANNED is NOT newer than device version $INSTALLED — would build a stale update"
  fi
fi

planned_code=$(to_code "$PLANNED")
if [ -n "$INSTALLED_CODE" ]; then
  if [ "$planned_code" -gt "$INSTALLED_CODE" ]; then
    pass "installed-code: planned versionCode $planned_code > device versionCode $INSTALLED_CODE"
  else
    fail "installed-code: planned versionCode $planned_code <= device versionCode $INSTALLED_CODE — Android would reject the update"
  fi
else
  pass "installed-code: not provided (computed planned versionCode=$planned_code)"
fi

# 5. signing continuity --------------------------------------------------
if [ -z "$EXPECTED_SIGNER" ]; then
  EXPECTED_SIGNER="$EXPECTED_SIGNER_SHA256"
fi
if [ "$SKIP_SIGNING" -eq 1 ]; then
  warn "signing: skipped (--skip-signing)"
elif [ ! -f "$KEYSTORE" ]; then
  fail "signing: keystore '$KEYSTORE' not found"
else
  if ! command -v keytool >/dev/null 2>&1; then
    fail "signing: keytool not found (JDK required to verify keystore continuity)"
  else
    props="${TV_TENDERR_GRADLE_PROPERTIES:-${HOME}/.gradle/gradle.properties}"
    storepass=$(grep -m1 '^TV_TENDERR_KEYSTORE_PASSWORD=' "$props" 2>/dev/null | cut -d= -f2- | tr -d '\r\n')
    if [ -z "$storepass" ]; then
      fail "signing: TV_TENDERR_KEYSTORE_PASSWORD not readable from $props (continuity unverified)"
    else
      # Password travels via environment, never on the command line or output.
      export TV_TENDERR_PREFLIGHT_STOREPASS="$storepass"
      fp=$(keytool -list -v -keystore "$KEYSTORE" -alias tv-tenderr \
            -storepass:env TV_TENDERR_PREFLIGHT_STOREPASS 2>/dev/null \
          | grep -i 'SHA256:' | head -1 | cut -d: -f2- | tr -d ' :' | tr 'A-F' 'a-f')
      unset TV_TENDERR_PREFLIGHT_STOREPASS
      if [ -z "$fp" ]; then
        fail "signing: could not read certificate fingerprint from '$KEYSTORE'"
      elif [ "$fp" = "$EXPECTED_SIGNER" ]; then
        pass "signing: keystore cert fingerprint matches expected release signer"
      else
        fail "signing: keystore cert fingerprint CHANGED ($fp) — would break in-place updates"
      fi
    fi
  fi
fi

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "== RESULT: PASS =="
  exit 0
fi
echo "== RESULT: FAIL ($FAILURES check(s) failed) =="
exit 1

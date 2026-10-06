#!/bin/bash
# Usage: ./release.sh 1.3.0
# Refuses a dirty tree. Does not stage unrelated files, force tags, or force-push.

VERSION="${1:?Usage: ./release.sh X.Y.Z}"

set -e

if [ -n "$(git status --porcelain)" ]; then
  echo "Refusing release: working tree is dirty. Commit or stash first."
  exit 1
fi

echo "=== Releasing v$VERSION ==="

./bump_version.sh "$VERSION"

git add android/app/build.gradle.kts web/index.html
git commit -m "Release v$VERSION

Co-authored-by: Balthor <balthor@agentmail.to>"

git tag "v$VERSION"
git push origin main
git push origin "v$VERSION"

echo ""
echo "=== Done! ==="
echo "Source checks run in GitHub Actions. Publish the verified production APK manually at:"
echo "https://github.com/PIR8-Software/tv-tenderr/releases/tag/v$VERSION"

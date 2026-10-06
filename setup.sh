#!/bin/bash
# Prepare dependencies and a private template; never activate/restart a service.
set -euo pipefail
cd "$(dirname "$0")"
umask 077
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
if [ ! -e .env ]; then
  printf '%s\n' '# Configure locally; never commit credentials.' \
    'BACKEND_HOST=127.0.0.1' 'BACKEND_PORT=8899' \
    'TV_TENDERR_API_TOKEN=' 'RADARR_URL=http://localhost:7878' 'RADARR_KEY=' \
    'SONARR_URL=http://localhost:8989' 'SONARR_KEY=' \
    'PLEX_URL=http://localhost:32400' 'PLEX_TOKEN=' 'TMDB_KEY=' > .env
fi
mkdir -p data
printf '%s\n' 'Dependencies installed. Existing configuration and service template preserved.' \
  'Read SECURITY.md before configuring credentials or upgrading an existing server.' \
  'Choose a strong TV_TENDERR_API_TOKEN locally; keep BACKEND_HOST explicitly private.' \
  'Empty installations may instead use loopback web setup to choose their token.' \
  'Start manually: .venv/bin/python backend.py' \
  'Customize tv-tenderr.service for your user, checkout and venv before installing it.'

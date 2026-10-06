# TV Tenderr

A Tinder-style app for managing your Plex media library. Swipe through movies and TV shows to keep, block, or clean up your collection.

![Platform](https://img.shields.io/badge/Platform-Android%20%7C%20Web-blue)
![License](https://img.shields.io/badge/License-AGPL--3.0-blue)

## Features

- **Swipe gestures** — right to keep, left to block (deletes files, prevents re-addition), down for super keep
- **Cast display** — top 3 actors from TMDb on every movie, show, and discover card
- **Plex watched status** — see which movies/shows you've already watched in Plex
- **Trailer & IMDb links** — tap to watch trailers on YouTube or view on IMDb
- **Search & filter** — search by title, filter by genre, year range, and minimum rating
- **Swipe statistics** — see totals for kept, blocked, super kept, skipped across movies, shows, and discover
- **Calendar view** — upcoming releases from Radarr and Sonarr with monitoring/downloaded status
- **Plex integration** — refresh libraries from your phone
- **Radarr & Sonarr** — manage movies and TV shows
- **Discover** — find new content via TMDb; Dislike adds movies and shows to the matching Radarr/Sonarr Import List Exclusions, while Skip hides without excluding
- **Quality settings** — configure quality profiles and root folders
- **Undo protection** — 10-second window before destructive actions
- **History** — track all decisions; Show Again removes a Discover Import List Exclusion before restoring the item
- **Web GUI** — desktop interface with card and grid views, all features mirrored

## Security and upgrades

**1.3.4 requires an API token on configured servers.** Read [Security and upgrade notes](SECURITY.md) before updating. Set an explicit private `BACKEND_HOST`, use protected transport, run one backend worker, and connect each client with the existing token. Web login is session-scoped, not persistent across all tabs/browser restarts.

## Quick Start

```bash
git clone https://github.com/PIR8-Software/tv-tenderr.git
cd tv-tenderr
./setup.sh
# Edit .env with your credentials
.venv/bin/python backend.py
```

## Documentation

- **[User Guide](USER_GUIDE.md)** — complete usage instructions for app and web GUI
- **[Setup Guide](#quick-start)** — installation and configuration

## Screenshots

### Android App
![Movies](screenshots/android_movies.png)
![Shows](screenshots/android_shows.png)
![Discover](screenshots/android_discover.png)
![Calendar](screenshots/android_calendar.png)

### Web UI
![Web Movies](screenshots/web_movies.png)
![Web Calendar](screenshots/web_calendar.png)

### Features
- Card-based interface with swipe gestures
- Movies, Shows, and Discover modes
- Settings for all service connections

### Web GUI
- Dark theme matching Radarr/Sonarr aesthetic
- Card view (swipe) and Grid view (browse)
- Full feature parity with Android app

## Architecture

```
tv-tenderr/
├── backend.py          # FastAPI server
├── android/            # Android app (Kotlin)
├── web/                # Web GUI (HTML/CSS/JS)
├── data/               # Local data storage
├── .env.example        # Environment template
└── setup.sh            # Installation script
```

## API Endpoints

- `GET /api/movies` — list all movies
- `GET /api/shows` — list all shows
- `POST /api/movies/{id}/keep` — keep a movie
- `POST /api/movies/{id}/block` — block a movie (deletes files, adds import list exclusion — prevents re-addition from lists)
- `GET /api/discover/movies` — discover new movies
- `GET /api/discover/shows` — discover new shows
- `POST /api/discover/{tmdbId}/dislike` — hide a Discover item and add its Radarr/Sonarr Import List Exclusion
- `POST /api/discover/{tmdbId}/hide` — skip/hide a Discover item without adding an exclusion
- `POST /api/discover/{tmdbId}/unhide` — Show Again: remove its Import List Exclusion, then restore it to Discover
- `POST /api/plex/refresh` — refresh Plex libraries
- `GET /api/config` — get configuration
- `POST /api/config` — update configuration

## Requirements

- Python 3.10+
- Radarr instance with API key
- Sonarr instance with API key
- Plex server with token
- TMDb API key (free at themoviedb.org)

## License

[GNU Affero General Public License v3.0](LICENSE)

This software is free and open source under the AGPL-3.0 license. You are free to use, modify, and distribute it. If you run this software as a network service, you must provide the source code to your users.

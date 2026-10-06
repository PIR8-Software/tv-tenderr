"""TV Tenderr - Backend API
Connects to Radarr + Sonarr + Plex to serve movies/shows for the swipe interface.
"""
import asyncio
import hmac
import json
import os
import random
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv, dotenv_values
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# Load .env file if it exists. Tests patch ENV_FILE before any config write.
ENV_FILE = Path(__file__).parent / ".env"
load_dotenv(ENV_FILE, interpolate=False)

API_TOKEN_ENV = "TV_TENDERR_API_TOKEN"
LEGACY_DATA_DIR = Path("/home/roy/projects/movie-swipe/data")
POSTER_HOSTS = {"image.tmdb.org"}
PRESERVED_ACTIONS = {"keep", "super_keep", "block", "clean"}
LOOPBACK_HOSTS = {"127.0.0.1", "::1"}
decision_lock = asyncio.Lock()


def configured_api_token():
    return os.getenv(API_TOKEN_ENV, "").strip()


def resolve_bind_host():
    explicit = os.getenv("BACKEND_HOST", "").strip()
    if explicit:
        return explicit
    if configured_api_token():
        return "0.0.0.0"
    return "127.0.0.1"


def resolve_bind_port():
    raw = os.getenv("BACKEND_PORT", "8899").strip() or "8899"
    try:
        return int(raw)
    except ValueError:
        return 8899


def history_year(value):
    """Return a history year as an int, or None. Mixed string/int payloads are normalized, not rejected."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1800 <= value <= 2200 else None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        year = int(text)
        return year if 1800 <= year <= 2200 else None
    head = text[:4]
    if len(head) == 4 and head.isdigit() and not text[4:5].isdigit():
        year = int(head)
        return year if 1800 <= year <= 2200 else None
    return None


app = FastAPI(title="TV Tenderr", docs_url=None, redoc_url=None, openapi_url=None)

# Serve web UI
WEB_DIR = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

@app.get("/")
async def serve_ui():
    # Check if first run (no .env or missing config)
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists() or not RADARR_KEY or RADARR_KEY == "your_radarr_api_key":
        return FileResponse(str(WEB_DIR / "setup.html"))
    return FileResponse(str(WEB_DIR / "index.html"))

# Config - set these in .env or use env vars
RADARR_URL = os.getenv("RADARR_URL", "http://localhost:7878")
RADARR_KEY = os.getenv("RADARR_KEY", "")
SONARR_URL = os.getenv("SONARR_URL", "http://localhost:8989")
SONARR_KEY = os.getenv("SONARR_KEY", "")
PLEX_URL = os.getenv("PLEX_URL", "http://localhost:32400")
PLEX_TOKEN = os.getenv("PLEX_TOKEN", "")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def skip_revisit_hours():
    """Skip means decide later. The window is explicit and not a permanent exclusion."""
    raw = os.getenv("SKIP_REVISIT_HOURS", "24").strip() or "24"
    try:
        hours = int(raw)
    except ValueError:
        hours = 24
    return max(1, hours)


def is_decision_active(info):
    """Check if a decision is still active (not expired)."""
    action = info.get("action")
    if action in ("block", "super_keep", "clean"):
        return True
    if action == "keep":
        # Regular keeps expire after 6 months
        timestamp = info.get("timestamp")
        if timestamp:
            from dateutil.relativedelta import relativedelta
            decided = datetime.fromisoformat(timestamp)
            expires = decided + relativedelta(months=6)
            return datetime.now() < expires
        return True
    if action == "skip":
        timestamp = info.get("timestamp")
        if not timestamp:
            return False
        decided = datetime.fromisoformat(timestamp)
        return datetime.now() < decided + timedelta(hours=skip_revisit_hours())
    return False

DECISIONS_FILE = DATA_DIR / "decisions.json"
SHOW_DECISIONS_FILE = DATA_DIR / "show_decisions.json"

def load_json_store(path):
    """Load a decision file. A corrupt file fails closed and is never treated as empty."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Decision store unreadable: {path.name}") from exc
    if not text.strip():
        raise HTTPException(status_code=503, detail=f"Decision store corrupt: {path.name}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail=f"Decision store corrupt: {path.name}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=503, detail=f"Decision store corrupt: {path.name}")
    return data


def save_json_store(path, data):
    """Atomically replace a valid store. Refuse to overwrite a corrupt file."""
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Decision store must be an object")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        load_json_store(path)
    payload = json.dumps(data, indent=2)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def load_decisions():
    return load_json_store(DECISIONS_FILE)

def save_decisions(decisions):
    save_json_store(DECISIONS_FILE, decisions)

def load_show_decisions():
    return load_json_store(SHOW_DECISIONS_FILE)

def save_show_decisions(decisions):
    save_json_store(SHOW_DECISIONS_FILE, decisions)

def get_plex_sections():
    """Get Plex library sections to find the movies library."""
    if not PLEX_TOKEN:
        return None
    try:
        r = httpx.get(
            f"{PLEX_URL}/library/sections",
            headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/xml"},
            timeout=10,
        )
        r.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        for dir_elem in root.findall(".//Directory"):
            if dir_elem.get("type") == "movie":
                return dir_elem.get("key")
    except Exception as e:
        print(f"Plex error: {e}")
    return None

def get_plex_watched_titles(section_type="movie"):
    """Get set of watched titles (lowercase) from Plex."""
    if not PLEX_TOKEN:
        return set()
    try:
        # Get the section key for this type
        r = httpx.get(
            f"{PLEX_URL}/library/sections",
            headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/xml"},
            timeout=10,
        )
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        section_key = None
        for d in root.findall(".//Directory"):
            if d.get("type") == section_type:
                section_key = d.get("key")
                break
        if not section_key:
            return set()

        # Get all items with watched status
        r = httpx.get(
            f"{PLEX_URL}/library/sections/{section_key}/all",
            headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/xml"},
            params={"type": "1" if section_type == "movie" else "2"},
            timeout=60,
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        watched = set()
        for video in root.findall(".//Video"):
            view_count = int(video.get("viewCount", 0))
            if view_count > 0:
                title = video.get("title", "").lower().strip()
                year = video.get("year", "")
                watched.add(f"{title}|{year}")
        return watched
    except Exception as e:
        print(f"Plex watched error: {e}")
        return set()

def get_plex_watch_history(section_key):
    """Get watch history from Plex."""
    if not PLEX_TOKEN or not section_key:
        return {}
    try:
        r = httpx.get(
            f"{PLEX_URL}/library/sections/{section_key}/all",
            headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/xml"},
            params={"type": "1", "viewCount": ">>0"},
            timeout=30,
        )
        r.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        history = {}
        for video in root.findall(".//Video"):
            rating_key = video.get("ratingKey")
            view_count = int(video.get("viewCount", 0))
            last_viewed = video.get("lastViewedAt", "")
            history[rating_key] = {
                "viewCount": view_count,
                "lastViewedAt": last_viewed
            }
        return history
    except Exception as e:
        print(f"Plex history error: {e}")
        return {}

def get_poster_url(movie):
    """Get poster URL from Radarr images - prefer remote TMDB URL."""
    for img in movie.get("images", []):
        if img.get("coverType") == "poster":
            remote = img.get("remoteUrl")
            if remote:
                return remote
            return img.get("url")
    return None

async def get_tmdb_cast(client, tmdb_id, media_type="movie"):
    """Fetch top 3 actors from TMDb."""
    endpoint = "movie" if media_type == "movie" else "tv"
    try:
        r = await client.get(
            f"https://api.themoviedb.org/3/{endpoint}/{tmdb_id}/credits",
            params={"api_key": TMDB_KEY},
            timeout=8
        )
        if r.status_code == 200:
            cast = r.json().get("cast", [])[:3]
            return [c.get("name", "") for c in cast if c.get("name")]
    except:
        pass
    return []

async def get_tmdb_cast_by_tvdb(client, tvdb_id):
    """Fetch top 3 actors from TMDb using TVDB ID (for Sonarr shows)."""
    try:
        # First find the TMDb ID from TVDB ID
        r = await client.get(
            f"https://api.themoviedb.org/3/find/{tvdb_id}",
            params={"api_key": TMDB_KEY, "external_source": "tvdb_id"},
            timeout=8
        )
        if r.status_code == 200:
            tv_results = r.json().get("tv_results", [])
            if tv_results:
                tmdb_id = tv_results[0].get("id")
                if tmdb_id:
                    return await get_tmdb_cast(client, tmdb_id, "tv")
    except:
        pass
    return []

@app.get("/api/movies")
async def get_movies(skip: int = 0, limit: int = 50, genre: str = "", min_year: int = 0, max_year: int = 0, min_rating: float = 0, search: str = ""):
    """Get movies from Radarr with metadata."""
    decisions = load_decisions()
    watched = get_plex_watched_titles("movie")
    
    async with httpx.AsyncClient() as client:
        # Get all movies from Radarr
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie",
            headers={"X-Api-Key": RADARR_KEY},
            timeout=30
        )
        r.raise_for_status()
        radarr_movies = r.json()
    
    # Filter eligible movies
    eligible = []
    for m in radarr_movies:
        movie_id = str(m["id"])
        decision = decisions.get(movie_id, None)
        if decision and is_decision_active(decision):
            continue
        eligible.append(m)
    
    # Apply filters
    if genre:
        eligible = [m for m in eligible if genre.lower() in [g.lower() if isinstance(g, str) else g.get("name","").lower() for g in m.get("genres", [])]]
    if min_year:
        eligible = [m for m in eligible if m.get("year", 0) >= min_year]
    if max_year:
        eligible = [m for m in eligible if m.get("year", 0) <= max_year]
    if min_rating:
        eligible = [m for m in eligible if (m.get("ratings", {}).get("value", 0) or 0) >= min_rating]
    if search:
        search_lower = search.lower()
        eligible = [m for m in eligible if search_lower in m.get("title", "").lower()]

    random.shuffle(eligible)
    batch = eligible[skip:skip+limit]
    
    # Fetch cast only for the current batch
    async with httpx.AsyncClient() as client:
        import asyncio
        cast_tasks = [get_tmdb_cast(client, m.get("tmdbId"), "movie") for m in batch]
        cast_results = await asyncio.gather(*cast_tasks)
    
    movies = []
    for m, cast in zip(batch, cast_results):
        movie_id = str(m["id"])
        
        # Get file size if available
        size_gb = 0
        if m.get("sizeOnDisk"):
            size_gb = round(m["sizeOnDisk"] / (1024**3), 2)
        
        poster_url = get_poster_url(m)
        
        movies.append({
            "id": m["id"],
            "title": m["title"],
            "year": m.get("year"),
            "overview": m.get("overview", ""),
            "genres": [g if isinstance(g, str) else g["name"] for g in m.get("genres", [])],
            "rating": m.get("ratings", {}).get("value"),
            "runtime": m.get("runtime"),
            "sizeGB": size_gb,
            "posterUrl": poster_url,
            "hasFile": m.get("hasFile", False),
            "monitored": m.get("monitored", False),
            "qualityProfileId": m.get("qualityProfileId"),
            "status": m.get("status"),
            "cast": cast,
            "watched": f"{m['title'].lower().strip()}|{m.get('year', '')}" in watched,
            "imdbId": m.get("imdbId"),
            "trailerId": m.get("youTubeTrailerId"),
        })
    
    return {"movies": movies, "total": len(eligible)}

@app.post("/api/movies/{movie_id}/keep")
async def keep_movie(movie_id: int):
    """Mark a movie as keep - expires in 6 months."""
    decisions = load_decisions()
    
    movie_info = {}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie/{movie_id}",
            headers={"X-Api-Key": RADARR_KEY},
            timeout=15
        )
        if r.status_code == 200:
            m = r.json()
            movie_info = {
                "title": m.get("title"),
                "year": m.get("year"),
                "posterUrl": get_poster_url(m),
            }
    
    decisions[str(movie_id)] = {
        "action": "keep",
        "timestamp": datetime.now().isoformat(),
        **movie_info
    }
    save_decisions(decisions)
    return {"ok": True, "action": "keep"}


@app.post("/api/movies/{movie_id}/super_keep")
async def super_keep_movie(movie_id: int):
    """Mark a movie as super_keep - kept forever."""
    decisions = load_decisions()
    
    movie_info = {}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie/{movie_id}",
            headers={"X-Api-Key": RADARR_KEY},
            timeout=15
        )
        if r.status_code == 200:
            m = r.json()
            movie_info = {
                "title": m.get("title"),
                "year": m.get("year"),
                "posterUrl": get_poster_url(m),
            }
    
    decisions[str(movie_id)] = {
        "action": "super_keep",
        "timestamp": datetime.now().isoformat(),
        **movie_info
    }
    save_decisions(decisions)
    return {"ok": True, "action": "super_keep"}

@app.post("/api/movies/{movie_id}/block")
async def block_movie(movie_id: int):
    """Remove movie from Radarr and add to blocklist."""
    decisions = load_decisions()
    
    async with httpx.AsyncClient() as client:
        # Get movie details BEFORE deleting
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie/{movie_id}",
            headers={"X-Api-Key": RADARR_KEY},
            timeout=15
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail="Failed to get movie before block")
        m = r.json()
        if not m.get("tmdbId"):
            raise HTTPException(status_code=502, detail="Movie has no TMDb ID for restore; block cancelled")
        movie_info = {
            "title": m.get("title"),
            "year": m.get("year"),
            "tmdbId": m["tmdbId"],
            "posterUrl": get_poster_url(m),
        }
        
        # Delete from Radarr (deleteFiles=true removes the actual files)
        r = await client.delete(
            f"{RADARR_URL}/api/v3/movie/{movie_id}",
            headers={"X-Api-Key": RADARR_KEY},
            params={"deleteFiles": "true", "addImportListExclusion": "true"},
            timeout=30
        )
        if r.status_code not in (200, 204):
            raise HTTPException(status_code=r.status_code, detail=f"Radarr delete failed: {r.text}")
    
    decisions[str(movie_id)] = {
        "action": "block",
        "timestamp": datetime.now().isoformat(),
        **movie_info
    }
    save_decisions(decisions)
    return {"ok": True, "action": "block"}

@app.post("/api/movies/{movie_id}/skip")
async def skip_movie(movie_id: int):
    """Skip - decide later. Never overwrite an existing keep, block, or clean."""
    decisions = load_decisions()
    existing = decisions.get(str(movie_id))
    if existing and existing.get("action") in PRESERVED_ACTIONS:
        return {"ok": True, "action": existing.get("action"), "preserved": True}
    decisions[str(movie_id)] = {
        "action": "skip",
        "timestamp": datetime.now().isoformat(),
    }
    save_decisions(decisions)
    return {"ok": True, "action": "skip", "preserved": False}

@app.get("/api/stats")
async def get_stats():
    """Get swipe statistics."""
    movie_decisions = load_decisions()
    show_decisions = load_show_decisions()
    discover = load_hidden()
    
    movie_actions = {}
    for mid, info in movie_decisions.items():
        action = info.get("action", "unknown")
        movie_actions[action] = movie_actions.get(action, 0) + 1
    
    show_actions = {}
    for sid, info in show_decisions.items():
        action = info.get("action", "unknown")
        show_actions[action] = show_actions.get(action, 0) + 1
    
    discover_actions = {}
    for tid, info in discover.items():
        action = info.get("action", "unknown")
        discover_actions[action] = discover_actions.get(action, 0) + 1
    
    # Calculate disk space freed from blocked movies
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(
                f"{RADARR_URL}/api/v3/movie",
                headers={"X-Api-Key": RADARR_KEY},
                timeout=30
            )
            if r.status_code == 200:
                radarr_movies = r.json()
                total_movies = len(radarr_movies)
            else:
                total_movies = 0
        except:
            total_movies = 0
        
        try:
            r = await client.get(
                f"{SONARR_URL}/api/v3/series",
                headers={"X-Api-Key": SONARR_KEY},
                timeout=30
            )
            if r.status_code == 200:
                total_shows = len(r.json())
            else:
                total_shows = 0
        except:
            total_shows = 0
    
    return {
        "movies": {
            "total": total_movies,
            "kept": movie_actions.get("keep", 0),
            "superKept": movie_actions.get("super_keep", 0),
            "blocked": movie_actions.get("block", 0),
            "skipped": movie_actions.get("skip", 0),
            "undecided": total_movies - sum(movie_actions.values()),
        },
        "shows": {
            "total": total_shows,
            "kept": show_actions.get("keep", 0),
            "superKept": show_actions.get("super_keep", 0),
            "blocked": show_actions.get("block", 0),
            "skipped": show_actions.get("skip", 0),
            "undecided": total_shows - sum(show_actions.values()),
        },
        "discover": {
            "added": discover_actions.get("added", 0),
            "hidden": discover_actions.get("hidden", 0),
        }
    }

@app.get("/api/calendar")
async def get_calendar(days: int = 30):
    """Get upcoming releases from Radarr and Sonarr."""
    from datetime import datetime, timedelta
    
    start = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    
    items = []
    
    async with httpx.AsyncClient() as client:
        # Radarr calendar
        try:
            r = await client.get(
                f"{RADARR_URL}/api/v3/calendar",
                headers={"X-Api-Key": RADARR_KEY},
                params={"start": start, "end": end},
                timeout=30
            )
            if r.status_code == 200:
                for m in r.json():
                    release_date = m.get("digitalRelease") or m.get("physicalRelease") or m.get("inCinemas") or ""
                    items.append({
                        "type": "movie",
                        "title": m.get("title"),
                        "year": m.get("year"),
                        "releaseDate": release_date[:10] if release_date else "",
                        "status": m.get("status"),
                        "hasFile": m.get("hasFile", False),
                        "monitored": m.get("monitored", False),
                        "posterUrl": get_poster_url(m),
                        "tmdbId": m.get("tmdbId"),
                    })
        except:
            pass
        
        # Sonarr calendar
        try:
            r = await client.get(
                f"{SONARR_URL}/api/v3/calendar",
                headers={"X-Api-Key": SONARR_KEY},
                params={"start": start, "end": end, "includeSeries": "true"},
                timeout=30
            )
            if r.status_code == 200:
                for ep in r.json():
                    series = ep.get("series", {})
                    items.append({
                        "type": "show",
                        "title": series.get("title"),
                        "year": series.get("year"),
                        "episode": f"S{ep.get('seasonNumber',0):02d}E{ep.get('episodeNumber',0):02d}",
                        "episodeTitle": ep.get("title"),
                        "releaseDate": ep.get("airDate", ""),
                        "hasFile": ep.get("hasFile", False),
                        "monitored": ep.get("monitored", False),
                        "posterUrl": next((img.get("remoteUrl") or img.get("url") for img in series.get("images", []) if img.get("coverType") == "poster"), None),
                        "tmdbId": series.get("tvdbId"),
                    })
        except:
            pass
    
    items.sort(key=lambda x: x.get("releaseDate", ""))
    return {"calendar": items, "total": len(items)}

@app.get("/api/history")
async def get_history():
    """Get all decisions with movie details."""
    decisions = load_decisions()
    history = []
    
    # For decisions missing titles, look them up from Radarr
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie",
            headers={"X-Api-Key": RADARR_KEY},
            timeout=30
        )
        radarr_movies = {str(m["id"]): m for m in r.json()} if r.status_code == 200 else {}
    
    for mid, info in decisions.items():
        title = info.get("title")
        year = info.get("year")
        poster = info.get("posterUrl")
        
        # If no title stored, try to get it from Radarr
        if not title and mid in radarr_movies:
            m = radarr_movies[mid]
            title = m.get("title")
            year = m.get("year")
            poster = get_poster_url(m)
        
        history.append({
            "movieId": int(mid),
            "action": info.get("action"),
            "timestamp": info.get("timestamp"),
            "title": title,
            "year": history_year(year),
            "tmdbId": info.get("tmdbId"),
            "posterUrl": poster,
        })
    # Filter out skips
    history = [h for h in history if h.get("action") != "skip"]
    # Sort by timestamp, newest first
    history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"history": history}

@app.post("/api/movies/{movie_id}/unkeep")
async def unkeep_movie(movie_id: int):
    """Remove a keep decision - movie goes back to undecided."""
    decisions = load_decisions()
    mid = str(movie_id)
    if mid in decisions and decisions[mid].get("action") in ("keep", "super_keep"):
        del decisions[mid]
        save_decisions(decisions)
        return {"ok": True, "action": "unkeep"}
    raise HTTPException(status_code=404, detail="No keep decision found")

@app.post("/api/movies/{movie_id}/unblock")
async def unblock_movie(movie_id: int):
    """Re-add a blocked movie to Radarr using stored tmdbId."""
    decisions = load_decisions()
    mid = str(movie_id)
    
    if mid not in decisions or decisions[mid].get("action") != "block":
        raise HTTPException(status_code=404, detail="No block decision found")
    
    tmdb_id = decisions[mid].get("tmdbId")
    if not tmdb_id:
        raise HTTPException(status_code=400, detail="No tmdbId stored - cannot re-add")
    
    async with httpx.AsyncClient() as client:
        exclusions = await client.get(
            f"{RADARR_URL}/api/v3/exclusions",
            headers={"X-Api-Key": RADARR_KEY},
            timeout=30,
        )
        if exclusions.status_code != 200:
            raise HTTPException(status_code=exclusions.status_code, detail="Radarr exclusion lookup failed")
        match = next((item for item in exclusions.json() if str(item.get("tmdbId")) == str(tmdb_id)), None)
        if match:
            removed = await client.delete(
                f"{RADARR_URL}/api/v3/exclusions/{match['id']}",
                headers={"X-Api-Key": RADARR_KEY},
                timeout=30,
            )
            if removed.status_code not in (200, 202, 204, 404):
                raise HTTPException(status_code=removed.status_code, detail="Radarr exclusion removal failed")

        # Look up the movie on Radarr by tmdbId
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie/lookup",
            headers={"X-Api-Key": RADARR_KEY},
            params={"term": f"tmdb:{tmdb_id}"},
            timeout=15
        )
        if r.status_code != 200 or not r.json():
            raise HTTPException(status_code=404, detail="Movie not found on TMDB")
        
        movie_data = r.json()[0]
        
        # Add movie back to Radarr
        add_payload = {
            "title": movie_data["title"],
            "tmdbId": tmdb_id,
            "qualityProfileId": RADARR_QUALITY_ID,
            "rootFolderPath": RADARR_ROOT_FOLDER,
            "monitored": True,
            "addOptions": {"searchForMovie": False},
            "images": movie_data.get("images", []),
        }
        
        r = await client.post(
            f"{RADARR_URL}/api/v3/movie",
            headers={"X-Api-Key": RADARR_KEY},
            json=add_payload,
            timeout=30
        )
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=f"Radarr add failed: {r.text}")
    
    # Remove from decisions
    del decisions[mid]
    save_decisions(decisions)
    return {"ok": True, "action": "unblock", "title": movie_data["title"]}

@app.get("/api/blocklist")
async def get_blocklist():
    """Get current Radarr blocklist."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{RADARR_URL}/api/v3/blocklist",
            headers={"X-Api-Key": RADARR_KEY},
            timeout=30
        )
        r.raise_for_status()
        data = r.json()
    
    items = data.get("records", data) if isinstance(data, dict) else data
    return {"blocklist": items, "count": len(items)}

def poster_request(poster_path):
    """Attach the Arr key only to a relative Radarr media path. Never follow redirects with it."""
    if poster_path.startswith("/"):
        return {
            "url": f"{RADARR_URL}{poster_path}",
            "headers": {"X-Api-Key": RADARR_KEY},
        }
    parsed = urllib.parse.urlparse(poster_path)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in POSTER_HOSTS:
        raise HTTPException(status_code=400, detail="Poster URL host is not allowed")
    return {"url": poster_path, "headers": {}}


@app.get("/api/poster/{movie_id}")
async def get_poster(movie_id: int):
    """Proxy poster image from Radarr to avoid CORS issues."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie/{movie_id}",
            headers={"X-Api-Key": RADARR_KEY},
            timeout=15
        )
        r.raise_for_status()
        movie = r.json()
    
    poster_path = get_poster_url(movie)
    if not poster_path:
        raise HTTPException(status_code=404, detail="No poster")

    planned = poster_request(poster_path)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            planned["url"],
            headers=planned["headers"],
            timeout=15,
            follow_redirects=False,
        )
        if r.status_code in (301, 302, 303, 307, 308):
            raise HTTPException(status_code=502, detail="Poster redirect was not followed")
        r.raise_for_status()

    return Response(content=r.content, media_type="image/jpeg")

@app.get("/api/config")
async def get_config():
    """Get non-secret app configuration and credential status."""
    return {
        "radarrUrl": RADARR_URL,
        "sonarrUrl": SONARR_URL,
        "plexUrl": PLEX_URL,
        "hasRadarrKey": bool(RADARR_KEY),
        "hasSonarrKey": bool(SONARR_KEY),
        "hasPlexToken": bool(PLEX_TOKEN),
        "hasTmdbKey": bool(TMDB_KEY),
        "hasApiToken": bool(configured_api_token()),
        "radarrQualityId": RADARR_QUALITY_ID,
        "sonarrQualityId": SONARR_QUALITY_ID,
        "radarrRootFolder": RADARR_ROOT_FOLDER,
        "sonarrRootFolder": SONARR_ROOT_FOLDER,
    }


@app.get("/api/config/options")
async def get_config_options():
    """Proxy quality profiles and roots without exposing Arr API keys."""
    async with httpx.AsyncClient() as client:
        requests = (
            (f"{RADARR_URL}/api/v3/qualityprofile", RADARR_KEY),
            (f"{RADARR_URL}/api/v3/rootfolder", RADARR_KEY),
            (f"{SONARR_URL}/api/v3/qualityprofile", SONARR_KEY),
            (f"{SONARR_URL}/api/v3/rootfolder", SONARR_KEY),
        )
        responses = []
        for url, api_key in requests:
            response = await client.get(
                url,
                headers={"X-Api-Key": api_key},
                timeout=30,
            )
            responses.append(response.json() if response.status_code == 200 else [])

    radarr_profiles, radarr_roots, sonarr_profiles, sonarr_roots = responses
    return {
        "radarrProfiles": [
            {"id": item.get("id"), "name": item.get("name")}
            for item in radarr_profiles
        ],
        "radarrRoots": [item.get("path") for item in radarr_roots if item.get("path")],
        "sonarrProfiles": [
            {"id": item.get("id"), "name": item.get("name")}
            for item in sonarr_profiles
        ],
        "sonarrRoots": [item.get("path") for item in sonarr_roots if item.get("path")],
    }

@app.get("/api/latest-release")
async def get_latest_release():
    """Check GitHub for the latest release version."""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(
                "https://api.github.com/repos/PIR8-Software/tv-tenderr/releases/latest",
                headers={"Accept": "application/vnd.github.v3+json"},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                tag = data.get("tag_name", "").lstrip("v")
                return {
                    "version": tag,
                    "tagName": data.get("tag_name"),
                    "name": data.get("name"),
                    "body": data.get("body", ""),
                    "htmlUrl": data.get("html_url"),
                    "publishedAt": data.get("published_at"),
                    "downloadUrl": f"https://github.com/PIR8-Software/tv-tenderr/releases/latest/download/app-release.apk",
                }
            else:
                return {"error": f"GitHub API returned {r.status_code}"}
        except Exception as e:
            return {"error": str(e)}

@app.post("/api/config")
async def update_config(config: dict):
    """Update memory and atomically persist non-empty settings. Never mint a token."""
    if not configured_api_token() and not str(config.get("apiToken") or "").strip():
        raise HTTPException(status_code=400, detail="First-run setup requires a new API token")
    return persist_config(config)

# ==================== SONARR SHOW ENDPOINTS ====================

@app.get("/api/shows")
async def get_shows(skip: int = 0, limit: int = 50, genre: str = "", min_year: int = 0, max_year: int = 0, min_rating: float = 0, search: str = ""):
    """Get TV shows from Sonarr with metadata."""
    decisions = load_show_decisions()
    watched = get_plex_watched_titles("show")

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SONARR_URL}/api/v3/series",
            headers={"X-Api-Key": SONARR_KEY},
            timeout=30
        )
        r.raise_for_status()
        sonarr_shows = r.json()

    # Filter eligible shows
    eligible = []
    for s in sonarr_shows:
        show_id = str(s["id"])
        decision = decisions.get(show_id, None)
        if decision and is_decision_active(decision):
            continue
        eligible.append(s)

    # Apply filters
    if genre:
        eligible = [s for s in eligible if genre.lower() in [g.lower() if isinstance(g, str) else g.get("name","").lower() for g in s.get("genres", [])]]
    if min_year:
        eligible = [s for s in eligible if s.get("year", 0) >= min_year]
    if max_year:
        eligible = [s for s in eligible if s.get("year", 0) <= max_year]
    if min_rating:
        eligible = [s for s in eligible if (s.get("ratings", {}).get("value", 0) or 0) >= min_rating]
    if search:
        search_lower = search.lower()
        eligible = [s for s in eligible if search_lower in s.get("title", "").lower()]

    random.shuffle(eligible)
    batch = eligible[skip:skip+limit]

    # Fetch cast only for the current batch
    async with httpx.AsyncClient() as client:
        import asyncio
        cast_tasks = [get_tmdb_cast_by_tvdb(client, s.get("tvdbId")) for s in batch]
        cast_results = await asyncio.gather(*cast_tasks)

    shows = []
    for s, cast in zip(batch, cast_results):
        show_id = str(s["id"])

        # Calculate total size and episode count
        total_size = 0
        episode_count = 0
        for season in s.get("seasons", []):
            stats = season.get("statistics", {})
            total_size += stats.get("sizeOnDisk", 0)
            episode_count += stats.get("episodeFileCount", 0)

        size_gb = round(total_size / (1024**3), 2) if total_size else 0

        # Get poster URL
        poster_url = None
        for img in s.get("images", []):
            if img.get("coverType") == "poster":
                poster_url = img.get("remoteUrl") or img.get("url")
                break

        shows.append({
            "id": s["id"],
            "title": s["title"],
            "year": s.get("year"),
            "overview": s.get("overview", ""),
            "genres": s.get("genres", []),
            "rating": s.get("ratings", {}).get("value"),
            "seasonCount": len(s.get("seasons", [])),
            "episodeCount": episode_count,
            "sizeGB": size_gb,
            "posterUrl": poster_url,
            "status": s.get("status"),
            "monitored": s.get("monitored", False),
            "network": s.get("network"),
            "cast": cast,
            "watched": f"{s['title'].lower().strip()}|{s.get('year', '')}" in watched,
            "imdbId": s.get("imdbId"),
        })

    return {"shows": shows, "total": len(eligible)}


@app.post("/api/shows/{show_id}/keep")
async def keep_show(show_id: int):
    """Mark a show as keep - expires in 6 months."""
    decisions = load_show_decisions()

    show_info = {}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SONARR_URL}/api/v3/series/{show_id}",
            headers={"X-Api-Key": SONARR_KEY},
            timeout=15
        )
        if r.status_code == 200:
            s = r.json()
            poster_url = None
            for img in s.get("images", []):
                if img.get("coverType") == "poster":
                    poster_url = img.get("remoteUrl") or img.get("url")
                    break
            show_info = {
                "title": s.get("title"),
                "year": s.get("year"),
                "posterUrl": poster_url,
            }

    decisions[str(show_id)] = {
        "action": "keep",
        "timestamp": datetime.now().isoformat(),
        **show_info
    }
    save_show_decisions(decisions)
    return {"ok": True, "action": "keep"}


@app.post("/api/shows/{show_id}/super_keep")
async def super_keep_show(show_id: int):
    """Mark a show as super_keep - kept forever."""
    decisions = load_show_decisions()

    show_info = {}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SONARR_URL}/api/v3/series/{show_id}",
            headers={"X-Api-Key": SONARR_KEY},
            timeout=15
        )
        if r.status_code == 200:
            s = r.json()
            poster_url = None
            for img in s.get("images", []):
                if img.get("coverType") == "poster":
                    poster_url = img.get("remoteUrl") or img.get("url")
                    break
            show_info = {
                "title": s.get("title"),
                "year": s.get("year"),
                "posterUrl": poster_url,
            }

    decisions[str(show_id)] = {
        "action": "super_keep",
        "timestamp": datetime.now().isoformat(),
        **show_info
    }
    save_show_decisions(decisions)
    return {"ok": True, "action": "super_keep"}


@app.post("/api/shows/{show_id}/block")
async def block_show(show_id: int):
    """Remove show from Sonarr (delete files + blocklist)."""
    decisions = load_show_decisions()

    async with httpx.AsyncClient() as client:
        # Get show details BEFORE deleting
        r = await client.get(
            f"{SONARR_URL}/api/v3/series/{show_id}",
            headers={"X-Api-Key": SONARR_KEY},
            timeout=15
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail="Failed to get series before block")
        s = r.json()
        if not s.get("tvdbId"):
            raise HTTPException(status_code=502, detail="Show has no TVDb ID for restore; block cancelled")
        poster_url = None
        for img in s.get("images", []):
            if img.get("coverType") == "poster":
                poster_url = img.get("remoteUrl") or img.get("url")
                break
        show_info = {
            "title": s.get("title"),
            "year": s.get("year"),
            "tvdbId": s["tvdbId"],
            "posterUrl": poster_url,
        }

        # Delete from Sonarr
        r = await client.delete(
            f"{SONARR_URL}/api/v3/series/{show_id}",
            headers={"X-Api-Key": SONARR_KEY},
            params={"deleteFiles": "true", "addImportListExclusion": "true"},
            timeout=30
        )
        if r.status_code not in (200, 204):
            raise HTTPException(status_code=r.status_code, detail=f"Sonarr delete failed: {r.text}")

    decisions[str(show_id)] = {
        "action": "block",
        "timestamp": datetime.now().isoformat(),
        **show_info
    }
    save_show_decisions(decisions)
    return {"ok": True, "action": "block"}


@app.post("/api/shows/{show_id}/skip")
async def skip_show(show_id: int):
    """Skip a show - decide later. Never overwrite an existing preference."""
    decisions = load_show_decisions()
    existing = decisions.get(str(show_id))
    if existing and existing.get("action") in PRESERVED_ACTIONS:
        return {"ok": True, "action": existing.get("action"), "preserved": True}
    decisions[str(show_id)] = {
        "action": "skip",
        "timestamp": datetime.now().isoformat(),
    }
    save_show_decisions(decisions)
    return {"ok": True, "action": "skip", "preserved": False}


@app.post("/api/shows/{show_id}/unkeep")
async def unkeep_show(show_id: int):
    """Remove a keep/super_keep decision - show goes back to undecided."""
    decisions = load_show_decisions()
    sid = str(show_id)
    if sid in decisions and decisions[sid].get("action") in ("keep", "super_keep"):
        del decisions[sid]
        save_show_decisions(decisions)
        return {"ok": True, "action": "unkeep"}
    raise HTTPException(status_code=404, detail="No keep decision found")

@app.post("/api/shows/{show_id}/unblock")
async def unblock_show(show_id: int):
    """Re-add a blocked show to Sonarr, then remove its block decision."""
    decisions = load_show_decisions()
    sid = str(show_id)
    if sid not in decisions or decisions[sid].get("action") != "block":
        raise HTTPException(status_code=404, detail="No block decision found")

    tvdb_id = decisions[sid].get("tvdbId")
    if not tvdb_id:
        raise HTTPException(status_code=400, detail="No tvdbId stored - cannot re-add")

    async with httpx.AsyncClient() as client:
        exclusions = await client.get(
            f"{SONARR_URL}/api/v3/importlistexclusion",
            headers={"X-Api-Key": SONARR_KEY},
            timeout=30,
        )
        if exclusions.status_code != 200:
            raise HTTPException(status_code=exclusions.status_code, detail="Sonarr exclusion lookup failed")
        match = next((item for item in exclusions.json() if str(item.get("tvdbId")) == str(tvdb_id)), None)
        if match:
            removed = await client.delete(
                f"{SONARR_URL}/api/v3/importlistexclusion/{match['id']}",
                headers={"X-Api-Key": SONARR_KEY},
                timeout=30,
            )
            if removed.status_code not in (200, 202, 204, 404):
                raise HTTPException(status_code=removed.status_code, detail="Sonarr exclusion removal failed")

        r = await client.get(
            f"{SONARR_URL}/api/v3/series/lookup",
            headers={"X-Api-Key": SONARR_KEY},
            params={"term": f"tvdb:{tvdb_id}"},
            timeout=15,
        )
        if r.status_code != 200 or not r.json():
            raise HTTPException(status_code=404, detail="Show not found on TVDB")

        show_data = r.json()[0]
        add_payload = {
            "title": show_data["title"],
            "tvdbId": tvdb_id,
            "qualityProfileId": SONARR_QUALITY_ID,
            "rootFolderPath": SONARR_ROOT_FOLDER,
            "monitored": True,
            "addOptions": {"searchForMissingEpisodes": False},
            "images": show_data.get("images", []),
            "seasons": show_data.get("seasons", []),
        }
        r = await client.post(
            f"{SONARR_URL}/api/v3/series",
            headers={"X-Api-Key": SONARR_KEY},
            json=add_payload,
            timeout=30,
        )
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=f"Sonarr add failed: {r.text}")

    del decisions[sid]
    save_show_decisions(decisions)
    return {"ok": True, "action": "unblock", "title": show_data["title"]}

@app.post("/api/shows/{show_id}/clean")
async def clean_show(show_id: int):
    """Remove all episode files but keep show monitored for future episodes."""
    decisions = load_show_decisions()

    async with httpx.AsyncClient() as client:
        # Get show info before cleaning
        r = await client.get(
            f"{SONARR_URL}/api/v3/series/{show_id}",
            headers={"X-Api-Key": SONARR_KEY},
            timeout=15
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail="Failed to get series before clean")
        show_info = {}
        if r.status_code == 200:
            s = r.json()
            poster_url = None
            for img in s.get("images", []):
                if img.get("coverType") == "poster":
                    poster_url = img.get("remoteUrl") or img.get("url")
                    break
            show_info = {
                "title": s.get("title"),
                "year": s.get("year"),
                "posterUrl": poster_url,
            }

        # Get episode files
        r = await client.get(
            f"{SONARR_URL}/api/v3/episodefile",
            headers={"X-Api-Key": SONARR_KEY},
            params={"seriesId": show_id},
            timeout=30
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail="Failed to get episode files")

        files = r.json()
        deleted = 0
        total_size = 0
        for f in files:
            total_size += f.get("size", 0)
            dr = await client.delete(
                f"{SONARR_URL}/api/v3/episodefile/{f['id']}",
                headers={"X-Api-Key": SONARR_KEY},
                timeout=15
            )
            if dr.status_code not in (200, 204):
                raise HTTPException(status_code=dr.status_code, detail=f"Episode file delete failed after {deleted} deletes; retry clean to finish")
            deleted += 1

        # Unmonitor all episodes so they don't re-download
        er = await client.get(
            f"{SONARR_URL}/api/v3/episode",
            headers={"X-Api-Key": SONARR_KEY},
            params={"seriesId": show_id},
            timeout=30
        )
        if er.status_code != 200:
            raise HTTPException(status_code=er.status_code, detail="Failed to list episodes for clean")
        episodes = er.json()
        for ep in episodes:
            if ep.get("monitored"):
                ep["monitored"] = False
                put = await client.put(
                    f"{SONARR_URL}/api/v3/episode/{ep['id']}",
                    headers={"X-Api-Key": SONARR_KEY},
                    json=ep,
                    timeout=15
                )
                if put.status_code not in (200, 202):
                    raise HTTPException(status_code=put.status_code, detail="Failed to unmonitor episode")

        # Make sure show stays monitored (for future episodes)
        r = await client.get(
            f"{SONARR_URL}/api/v3/series/{show_id}",
            headers={"X-Api-Key": SONARR_KEY},
            timeout=15
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail="Failed to reload series after clean")
        show = r.json()
        show["monitored"] = True
        put = await client.put(
            f"{SONARR_URL}/api/v3/series/{show_id}",
            headers={"X-Api-Key": SONARR_KEY},
            json=show,
            timeout=15
        )
        if put.status_code not in (200, 202):
            raise HTTPException(status_code=put.status_code, detail="Failed to keep series monitored")

    # Log the clean action
    decisions[str(show_id)] = {
        "action": "clean",
        "timestamp": datetime.now().isoformat(),
        "deletedFiles": deleted,
        "freedGB": round(total_size / (1024**3), 2),
        **show_info
    }
    save_show_decisions(decisions)

    return {"ok": True, "deleted": deleted, "total": len(files), "freedGB": round(total_size / (1024**3), 2)}


@app.post("/api/shows/{show_id}/unclean")
async def unclean_show(show_id: int):
    """Re-monitor all episodes for a show (undo a clean)."""
    decisions = load_show_decisions()

    async with httpx.AsyncClient() as client:
        # Re-monitor all episodes
        er = await client.get(
            f"{SONARR_URL}/api/v3/episode",
            headers={"X-Api-Key": SONARR_KEY},
            params={"seriesId": show_id},
            timeout=30
        )
        if er.status_code != 200:
            raise HTTPException(status_code=er.status_code, detail="Failed to list episodes for re-monitor")
        re_monitored = 0
        episodes = er.json()
        for ep in episodes:
            if not ep.get("monitored"):
                ep["monitored"] = True
                put = await client.put(
                    f"{SONARR_URL}/api/v3/episode/{ep['id']}",
                    headers={"X-Api-Key": SONARR_KEY},
                    json=ep,
                    timeout=15
                )
                if put.status_code not in (200, 202):
                    raise HTTPException(status_code=put.status_code, detail="Failed to re-monitor episode")
                re_monitored += 1

    # Remove clean decision
    sid = str(show_id)
    if sid in decisions and decisions[sid].get("action") == "clean":
        del decisions[sid]
        save_show_decisions(decisions)

    return {"ok": True, "reMonitored": re_monitored}


@app.get("/api/shows/history")
async def get_show_history():
    """Get all show decisions with details."""
    decisions = load_show_decisions()
    history = []

    # Look up missing titles from Sonarr
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SONARR_URL}/api/v3/series",
            headers={"X-Api-Key": SONARR_KEY},
            timeout=30
        )
        sonarr_shows = {str(s["id"]): s for s in r.json()} if r.status_code == 200 else {}

    for sid, info in decisions.items():
        title = info.get("title")
        year = info.get("year")
        poster = info.get("posterUrl")

        if not title and sid in sonarr_shows:
            s = sonarr_shows[sid]
            title = s.get("title")
            year = s.get("year")
            for img in s.get("images", []):
                if img.get("coverType") == "poster":
                    poster = img.get("remoteUrl") or img.get("url")
                    break

        history.append({
            # History clients share one model for movies and shows. Keep showId
            # for API clarity, but also provide the common id field they use.
            "movieId": int(sid),
            "showId": int(sid),
            "action": info.get("action"),
            "timestamp": info.get("timestamp"),
            "title": title,
            "year": history_year(year),
            "posterUrl": poster,
            "deletedFiles": info.get("deletedFiles"),
            "freedGB": info.get("freedGB"),
        })

    # Filter out skips
    history = [h for h in history if h.get("action") != "skip"]
    history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"history": history}


@app.post("/api/plex/refresh")
async def plex_refresh():
    """Trigger Plex library refresh for all sections."""
    if not PLEX_TOKEN:
        raise HTTPException(status_code=400, detail="No Plex token configured")

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{PLEX_URL}/library/sections/all/refresh",
            headers={"X-Plex-Token": PLEX_TOKEN},
            timeout=15
        )

    return {"ok": True, "status": r.status_code}



def get_existing_movie_tmdb_ids():
    """Get TMDb IDs of all movies in Radarr."""
    try:
        import httpx as _httpx
        r = _httpx.get(f"{RADARR_URL}/api/v3/movie", headers={"X-Api-Key": RADARR_KEY}, timeout=30)
        if r.status_code == 200:
            return {str(m.get("tmdbId")) for m in r.json() if m.get("tmdbId")}
    except:
        pass
    return set()

def get_existing_show_titles():
    """Get normalized titles of all shows in Sonarr."""
    try:
        import httpx as _httpx
        r = _httpx.get(f"{SONARR_URL}/api/v3/series", headers={"X-Api-Key": SONARR_KEY}, timeout=30)
        if r.status_code == 200:
            titles = set()
            for s in r.json():
                title = s.get("title", "").lower().strip()
                year = s.get("year", "")
                titles.add(f"{title}|{year}")
            return titles
    except:
        pass
    return set()

# ==================== TMDB DISCOVER ENDPOINTS ====================

TMDB_KEY = os.getenv("TMDB_KEY", "")
RADARR_QUALITY_ID = int(os.getenv("RADARR_QUALITY_ID", "4"))
SONARR_QUALITY_ID = int(os.getenv("SONARR_QUALITY_ID", "4"))
RADARR_ROOT_FOLDER = os.getenv("RADARR_ROOT_FOLDER", "H:\\")
SONARR_ROOT_FOLDER = os.getenv("SONARR_ROOT_FOLDER", "I:\\TV")
HIDDEN_FILE = DATA_DIR / "hidden_discover.json"

def load_hidden():
    return load_json_store(HIDDEN_FILE)

def save_hidden(hidden):
    save_json_store(HIDDEN_FILE, hidden)

@app.get("/api/providers")
async def get_providers():
    """Get available streaming providers from TMDb."""
    async with httpx.AsyncClient() as client:
        movie_r = await client.get(
            f"https://api.themoviedb.org/3/watch/providers/movie?api_key={TMDB_KEY}&region=US&watch_region=US",
            timeout=15
        )
        tv_r = await client.get(
            f"https://api.themoviedb.org/3/watch/providers/tv?api_key={TMDB_KEY}&region=US&watch_region=US",
            timeout=15
        )

    movie_providers = []
    if movie_r.status_code == 200:
        for p in movie_r.json().get("results", []):
            movie_providers.append({
                "id": p["provider_id"],
                "name": p["provider_name"],
                "logo": f"https://image.tmdb.org/t/p/original{p['logo_path']}" if p.get("logo_path") else None,
            })

    tv_providers = []
    if tv_r.status_code == 200:
        for p in tv_r.json().get("results", []):
            tv_providers.append({
                "id": p["provider_id"],
                "name": p["provider_name"],
                "logo": f"https://image.tmdb.org/t/p/original{p['logo_path']}" if p.get("logo_path") else None,
            })

    return {"movie_providers": movie_providers, "tv_providers": tv_providers}


@app.get("/api/discover/movies")
async def discover_movies(page: int = 1, limit: int = 20, providers: str = "", sort_by: str = "popularity.desc"):
    """Discover movies from TMDb, optionally filtered by streaming providers."""
    hidden = load_hidden()
    existing_ids = get_existing_movie_tmdb_ids()

    movies = []
    tmdb_page = page
    max_attempts = 5  # Fetch up to 5 pages to fill the limit

    async with httpx.AsyncClient() as client:
        while len(movies) < limit and tmdb_page <= page + max_attempts:
            params = {
                "api_key": TMDB_KEY,
                "sort_by": sort_by,
                "watch_region": "US",
                "language": "en-US",
                "page": tmdb_page,
            }
            if providers:
                params["with_watch_providers"] = providers
                params["with_watch_monetization_types"] = "flatrate|free|ads"

            r = await client.get("https://api.themoviedb.org/3/discover/movie", params=params, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()

            for m in data.get("results", []):
                tmdb_id = m["id"]
                if str(tmdb_id) in hidden or str(tmdb_id) in existing_ids:
                    continue

                poster_url = f"https://image.tmdb.org/t/p/w500{m['poster_path']}" if m.get("poster_path") else None
                backdrop_url = f"https://image.tmdb.org/t/p/w780{m['backdrop_path']}" if m.get("backdrop_path") else None

                movies.append({
                    "tmdbId": tmdb_id,
                    "title": m["title"],
                    "year": m.get("release_date", "")[:4] or None,
                    "overview": m.get("overview", ""),
                    "rating": m.get("vote_average"),
                    "posterUrl": poster_url,
                    "backdropUrl": backdrop_url,
                    "cast": [],
                    "releaseDate": m.get("release_date"),
                })

                if len(movies) >= limit:
                    break

            tmdb_page += 1

        # Fetch cast for the final batch of discover movies
        final_movies = movies[:limit]
        import asyncio
        cast_tasks = [get_tmdb_cast(client, m["tmdbId"], "movie") for m in final_movies]
        cast_results = await asyncio.gather(*cast_tasks)
        for m, cast in zip(final_movies, cast_results):
            m["cast"] = cast

    return {"movies": final_movies, "total": 10000, "page": page}


@app.get("/api/discover/shows")
async def discover_shows(page: int = 1, limit: int = 20, providers: str = "", sort_by: str = "popularity.desc"):
    """Discover TV shows from TMDb, optionally filtered by streaming providers."""
    hidden = load_hidden()
    existing_titles = get_existing_show_titles()

    shows = []
    tmdb_page = page
    max_attempts = 5

    async with httpx.AsyncClient() as client:
        while len(shows) < limit and tmdb_page <= page + max_attempts:
            params = {
                "api_key": TMDB_KEY,
                "sort_by": sort_by,
                "watch_region": "US",
                "language": "en-US",
                "page": tmdb_page,
            }
            if providers:
                params["with_watch_providers"] = providers
                params["with_watch_monetization_types"] = "flatrate|free|ads"

            r = await client.get("https://api.themoviedb.org/3/discover/tv", params=params, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()

            for s in data.get("results", []):
                tmdb_id = s["id"]
                if str(tmdb_id) in hidden:
                    continue
                show_key = f"{s.get('name','').lower().strip()}|{s.get('first_air_date','')[:4]}"
                if show_key in existing_titles:
                    continue

                poster_url = f"https://image.tmdb.org/t/p/w500{s['poster_path']}" if s.get("poster_path") else None
                backdrop_url = f"https://image.tmdb.org/t/p/w780{s['backdrop_path']}" if s.get("backdrop_path") else None

                shows.append({
                    "tmdbId": tmdb_id,
                    "title": s["name"],
                    "year": s.get("first_air_date", "")[:4] or None,
                    "overview": s.get("overview", ""),
                    "rating": s.get("vote_average"),
                    "posterUrl": poster_url,
                    "backdropUrl": backdrop_url,
                    "cast": [],
                    "firstAirDate": s.get("first_air_date"),
                })

                if len(shows) >= limit:
                    break

            tmdb_page += 1

        # Fetch cast for the final batch of discover shows
        final_shows = shows[:limit]
        import asyncio
        cast_tasks = [get_tmdb_cast(client, s["tmdbId"], "tv") for s in final_shows]
        cast_results = await asyncio.gather(*cast_tasks)
        for s, cast in zip(final_shows, cast_results):
            s["cast"] = cast

    return {"shows": final_shows, "total": 10000, "page": page}


@app.post("/api/discover/{tmdb_id}/dislike")
async def dislike_discover(tmdb_id: int, body: dict = {}):
    """Hide a disliked discover item and prevent import lists from re-adding it."""
    media_type = body.get("type", "movie")
    title = body.get("title")
    year = body.get("year")
    exclusion_metadata = {}
    async with httpx.AsyncClient() as client:
        if media_type in ("movie", "movies"):
            r = await client.post(
                f"{RADARR_URL}/api/v3/exclusions",
                headers={"X-Api-Key": RADARR_KEY},
                json={"tmdbId": tmdb_id, "movieTitle": title, "movieYear": int(year or 0)},
                timeout=30,
            )
            exclusion_id = None
            if r.status_code in (200, 201):
                response_data = r.json() or {}
                if isinstance(response_data, dict):
                    exclusion_id = response_data.get("id")
            elif r.status_code == 400:
                original_error = r.text
                existing = await client.get(
                    f"{RADARR_URL}/api/v3/exclusions",
                    headers={"X-Api-Key": RADARR_KEY},
                    timeout=30,
                )
                match = None
                if existing.status_code == 200:
                    match = next((item for item in existing.json() if item.get("tmdbId") == tmdb_id), None)
                if not match:
                    raise HTTPException(status_code=400, detail=f"Radarr exclusion failed: {original_error}")
                exclusion_id = match.get("id")
            else:
                raise HTTPException(status_code=r.status_code, detail=f"Radarr exclusion failed: {r.text}")
            exclusion_metadata["exclusionSource"] = "radarr"
            if exclusion_id is not None:
                exclusion_metadata["exclusionId"] = exclusion_id
        elif media_type in ("show", "shows"):
            r = await client.get(
                f"{SONARR_URL}/api/v3/series/lookup",
                headers={"X-Api-Key": SONARR_KEY},
                params={"term": f"tmdb:{tmdb_id}"},
                timeout=15,
            )
            if r.status_code != 200 or not r.json():
                raise HTTPException(status_code=404, detail="Show not found")
            show = r.json()[0]
            r = await client.post(
                f"{SONARR_URL}/api/v3/importlistexclusion",
                headers={"X-Api-Key": SONARR_KEY},
                json={"tvdbId": show["tvdbId"], "title": show["title"]},
                timeout=30,
            )
            exclusion_id = None
            if r.status_code in (200, 201):
                response_data = r.json() or {}
                if isinstance(response_data, dict):
                    exclusion_id = response_data.get("id")
            elif r.status_code == 400:
                original_error = r.text
                existing = await client.get(
                    f"{SONARR_URL}/api/v3/importlistexclusion",
                    headers={"X-Api-Key": SONARR_KEY},
                    timeout=30,
                )
                match = None
                if existing.status_code == 200:
                    match = next((item for item in existing.json() if item.get("tvdbId") == show["tvdbId"]), None)
                if not match:
                    raise HTTPException(status_code=400, detail=f"Sonarr exclusion failed: {original_error}")
                exclusion_id = match.get("id")
            else:
                raise HTTPException(status_code=r.status_code, detail=f"Sonarr exclusion failed: {r.text}")
            exclusion_metadata.update({"exclusionSource": "sonarr", "tvdbId": show["tvdbId"]})
            if exclusion_id is not None:
                exclusion_metadata["exclusionId"] = exclusion_id
        else:
            raise HTTPException(status_code=400, detail="Unsupported discover type")

    hidden = load_hidden()
    hidden[str(tmdb_id)] = {
        "action": "hidden",
        "timestamp": datetime.now().isoformat(),
        "title": title,
        "year": history_year(year),
        "posterUrl": body.get("posterUrl"),
        "type": media_type,
        "hideSource": "dislike",
        **exclusion_metadata,
    }
    save_hidden(hidden)
    return {"ok": True}


@app.post("/api/discover/{tmdb_id}/hide")
async def hide_discover(tmdb_id: int, body: dict = {}):
    """Hide a discover item so it doesn't show again."""
    hidden = load_hidden()
    hidden[str(tmdb_id)] = {
        "action": body.get("action", "hidden"),
        "timestamp": datetime.now().isoformat(),
        "title": body.get("title"),
        "year": history_year(body.get("year")),
        "posterUrl": body.get("posterUrl"),
        "type": body.get("type", "movie"),
        "hideSource": "skip",
    }
    save_hidden(hidden)
    return {"ok": True}


@app.post("/api/discover/{tmdb_id}/add_movie")
async def add_movie_from_discover(tmdb_id: int):
    """Add a discovered movie to Radarr."""
    async with httpx.AsyncClient() as client:
        # Lookup movie in Radarr by tmdbId
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie/lookup",
            headers={"X-Api-Key": RADARR_KEY},
            params={"term": f"tmdb:{tmdb_id}"},
            timeout=15
        )
        if r.status_code != 200 or not r.json():
            raise HTTPException(status_code=404, detail="Movie not found")

        movie_data = r.json()[0]

        add_payload = {
            "title": movie_data["title"],
            "tmdbId": tmdb_id,
            "qualityProfileId": RADARR_QUALITY_ID,
            "rootFolderPath": RADARR_ROOT_FOLDER,
            "monitored": True,
            "addOptions": {"searchForMovie": True},
            "images": movie_data.get("images", []),
        }

        r = await client.post(
            f"{RADARR_URL}/api/v3/movie",
            headers={"X-Api-Key": RADARR_KEY},
            json=add_payload,
            timeout=30
        )
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=f"Radarr add failed: {r.text}")

    # Hide from discover
    hidden = load_hidden()
    hidden[str(tmdb_id)] = {
        "action": "added",
        "timestamp": datetime.now().isoformat(),
        "title": movie_data.get("title"),
        "year": movie_data.get("year"),
        "posterUrl": f"https://image.tmdb.org/t/p/w500{movie_data.get('images', [{}])[0].get('coverUrl', '').split('?')[0].replace('/MediaCover/', '')}" if movie_data.get("images") else None,
        "type": "movie",
    }
    save_hidden(hidden)

    return {"ok": True, "title": movie_data["title"]}


@app.post("/api/discover/{tmdb_id}/add_show")
async def add_show_from_discover(tmdb_id: int):
    """Add a discovered show to Sonarr."""
    async with httpx.AsyncClient() as client:
        # Lookup show by tmdbId
        r = await client.get(
            f"{SONARR_URL}/api/v3/series/lookup",
            headers={"X-Api-Key": SONARR_KEY},
            params={"term": f"tmdb:{tmdb_id}"},
            timeout=15
        )
        if r.status_code != 200 or not r.json():
            raise HTTPException(status_code=404, detail="Show not found")

        show_data = r.json()[0]

        add_payload = {
            "title": show_data["title"],
            "tmdbId": tmdb_id,
            "tvdbId": show_data.get("tvdbId"),
            "qualityProfileId": SONARR_QUALITY_ID,
            "rootFolderPath": SONARR_ROOT_FOLDER,
            "monitored": True,
            "addOptions": {"searchForMissingEpisodes": True},
            "images": show_data.get("images", []),
            "seasons": show_data.get("seasons", []),
        }

        r = await client.post(
            f"{SONARR_URL}/api/v3/series",
            headers={"X-Api-Key": SONARR_KEY},
            json=add_payload,
            timeout=30
        )
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=r.status_code, detail=f"Sonarr add failed: {r.text}")

    # Hide from discover
    hidden = load_hidden()
    hidden[str(tmdb_id)] = {
        "action": "added",
        "timestamp": datetime.now().isoformat(),
        "title": show_data.get("title"),
        "year": show_data.get("year"),
        "type": "show",
    }
    save_hidden(hidden)

    return {"ok": True, "title": show_data["title"]}


@app.get("/api/discover/history")
async def get_discover_history():
    """Get all discover actions (added, hidden)."""
    hidden = load_hidden()
    history = []

    async with httpx.AsyncClient() as client:
        for tmdb_id, info in hidden.items():
            title = info.get("title")
            year = info.get("year")
            poster = info.get("posterUrl")
            item_type = info.get("type", "movie")

            # Look up title from TMDb if missing
            if not title:
                try:
                    endpoint = "movie" if item_type == "movie" else "tv"
                    r = await client.get(
                        f"https://api.themoviedb.org/3/{endpoint}/{tmdb_id}?api_key={TMDB_KEY}",
                        timeout=10
                    )
                    if r.status_code == 200:
                        data = r.json()
                        title = data.get("title") or data.get("name")
                        year = (data.get("release_date") or data.get("first_air_date", ""))[:4] or None
                        poster_path = data.get("poster_path")
                        poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                except:
                    pass

            history.append({
                # Android uses the shared HistoryItem model for every section.
                "movieId": int(tmdb_id),
                "tmdbId": int(tmdb_id),
                "action": info.get("action", "hidden"),
                "timestamp": info.get("timestamp"),
                "title": title,
                "year": history_year(year),
                "posterUrl": poster,
                "type": item_type,
            })

    history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"history": history}


@app.post("/api/discover/{tmdb_id}/unhide")
async def unhide_discover(tmdb_id: int):
    """Remove a discover hide and its associated import-list exclusion."""
    hidden = load_hidden()
    mid = str(tmdb_id)
    info = hidden.get(mid)
    if not info:
        return {"ok": True}

    exclusion_source = info.get("exclusionSource")
    exclusion_id = info.get("exclusionId")
    if exclusion_source == "radarr" and exclusion_id is None:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{RADARR_URL}/api/v3/exclusions",
                headers={"X-Api-Key": RADARR_KEY},
                timeout=30,
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=f"Radarr exclusions lookup failed: {r.text}")
            match = next((item for item in r.json() if item.get("tmdbId") == tmdb_id), None)
            if match:
                r = await client.delete(
                    f"{RADARR_URL}/api/v3/exclusions/{match['id']}",
                    headers={"X-Api-Key": RADARR_KEY},
                    timeout=30,
                )
                if r.status_code not in (200, 202, 204, 404):
                    raise HTTPException(status_code=r.status_code, detail=f"Radarr exclusion removal failed: {r.text}")
    elif exclusion_source == "radarr":
        async with httpx.AsyncClient() as client:
            r = await client.delete(
                f"{RADARR_URL}/api/v3/exclusions/{exclusion_id}",
                headers={"X-Api-Key": RADARR_KEY},
                timeout=30,
            )
        if r.status_code not in (200, 202, 204, 404):
            raise HTTPException(status_code=r.status_code, detail=f"Radarr exclusion removal failed: {r.text}")
    elif exclusion_source == "sonarr" and exclusion_id is None:
        async with httpx.AsyncClient() as client:
            tvdb_id = info.get("tvdbId")
            if tvdb_id is None:
                r = await client.get(
                    f"{SONARR_URL}/api/v3/series/lookup",
                    headers={"X-Api-Key": SONARR_KEY},
                    params={"term": f"tmdb:{tmdb_id}"},
                    timeout=15,
                )
                if r.status_code != 200:
                    raise HTTPException(status_code=r.status_code, detail=f"Sonarr series lookup failed: {r.text}")
                lookup_results = r.json()
                tvdb_id = lookup_results[0].get("tvdbId") if lookup_results else None

            if tvdb_id is not None:
                r = await client.get(
                    f"{SONARR_URL}/api/v3/importlistexclusion",
                    headers={"X-Api-Key": SONARR_KEY},
                    timeout=30,
                )
                if r.status_code != 200:
                    raise HTTPException(status_code=r.status_code, detail=f"Sonarr exclusions lookup failed: {r.text}")
                match = next((item for item in r.json() if item.get("tvdbId") == tvdb_id), None)
                if match:
                    r = await client.delete(
                        f"{SONARR_URL}/api/v3/importlistexclusion/{match['id']}",
                        headers={"X-Api-Key": SONARR_KEY},
                        timeout=30,
                    )
                    if r.status_code not in (200, 202, 204, 404):
                        raise HTTPException(status_code=r.status_code, detail=f"Sonarr exclusion removal failed: {r.text}")
    elif exclusion_source == "sonarr" and exclusion_id is not None:
        async with httpx.AsyncClient() as client:
            r = await client.delete(
                f"{SONARR_URL}/api/v3/importlistexclusion/{exclusion_id}",
                headers={"X-Api-Key": SONARR_KEY},
                timeout=30,
            )
        if r.status_code not in (200, 202, 204, 404):
            raise HTTPException(status_code=r.status_code, detail=f"Sonarr exclusion removal failed: {r.text}")

    del hidden[mid]
    save_hidden(hidden)
    return {"ok": True}


@app.post("/api/discover/{tmdb_id}/remove_movie")
async def remove_movie_from_discover(tmdb_id: int):
    """Remove a movie that was added via discover from Radarr."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{RADARR_URL}/api/v3/movie",
            headers={"X-Api-Key": RADARR_KEY},
            timeout=30
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"Radarr lookup failed: {r.text}")

        movie = next((m for m in r.json() if m.get("tmdbId") == tmdb_id), None)
        if not movie:
            raise HTTPException(status_code=404, detail="Movie is no longer in Radarr")

        r = await client.delete(
            f"{RADARR_URL}/api/v3/movie/{movie['id']}",
            headers={"X-Api-Key": RADARR_KEY},
            params={"deleteFiles": "true"},
            timeout=15
        )
        if r.status_code not in (200, 202, 204):
            raise HTTPException(status_code=r.status_code, detail=f"Radarr delete failed: {r.text}")

    # Remove from hidden so it shows in discover again
    hidden = load_hidden()
    mid = str(tmdb_id)
    if mid in hidden:
        del hidden[mid]
        save_hidden(hidden)

    return {"ok": True}


@app.post("/api/discover/{tmdb_id}/remove_show")
async def remove_show_from_discover(tmdb_id: int):
    """Remove a show that was added via discover from Sonarr."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SONARR_URL}/api/v3/series/lookup",
            headers={"X-Api-Key": SONARR_KEY},
            params={"term": f"tmdb:{tmdb_id}"},
            timeout=15
        )
        if r.status_code != 200 or not r.json():
            raise HTTPException(status_code=404, detail="Show lookup failed")

        tvdb_id = r.json()[0].get("tvdbId")
        if not tvdb_id:
            raise HTTPException(status_code=400, detail="Show lookup has no tvdbId")

        r = await client.get(
            f"{SONARR_URL}/api/v3/series",
            headers={"X-Api-Key": SONARR_KEY},
            timeout=30
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"Sonarr lookup failed: {r.text}")

        show = next((s for s in r.json() if s.get("tvdbId") == tvdb_id), None)
        if not show:
            raise HTTPException(status_code=404, detail="Show is no longer in Sonarr")

        r = await client.delete(
            f"{SONARR_URL}/api/v3/series/{show['id']}",
            headers={"X-Api-Key": SONARR_KEY},
            params={"deleteFiles": "true"},
            timeout=15
        )
        if r.status_code not in (200, 202, 204):
            raise HTTPException(status_code=r.status_code, detail=f"Sonarr delete failed: {r.text}")

    # Remove from hidden
    hidden = load_hidden()
    mid = str(tmdb_id)
    if mid in hidden:
        del hidden[mid]
        save_hidden(hidden)

    return {"ok": True}


@app.post("/api/save-env")
async def save_env(config: dict):
    """Persist configuration. Same writer as /api/config; does not mint a token."""
    if not configured_api_token() and not str(config.get("apiToken") or "").strip():
        raise HTTPException(status_code=400, detail="First-run setup requires a new API token")
    return persist_config(config)


CONFIG_TO_ENV = {
    "radarrUrl": ("RADARR_URL", "url"),
    "radarrKey": ("RADARR_KEY", "secret"),
    "sonarrUrl": ("SONARR_URL", "url"),
    "sonarrKey": ("SONARR_KEY", "secret"),
    "plexUrl": ("PLEX_URL", "url"),
    "plexToken": ("PLEX_TOKEN", "secret"),
    "tmdbKey": ("TMDB_KEY", "secret"),
    "apiToken": ("TV_TENDERR_API_TOKEN", "secret"),
    "radarrQualityId": ("RADARR_QUALITY_ID", "int"),
    "sonarrQualityId": ("SONARR_QUALITY_ID", "int"),
    "radarrRootFolder": ("RADARR_ROOT_FOLDER", "text"),
    "sonarrRootFolder": ("SONARR_ROOT_FOLDER", "text"),
    "backendHost": ("BACKEND_HOST", "text"),
    "port": ("BACKEND_PORT", "int"),
}
ENV_KEY_ORDER = [
    "BACKEND_HOST",
    "BACKEND_PORT",
    "TV_TENDERR_API_TOKEN",
    "RADARR_URL",
    "RADARR_KEY",
    "SONARR_URL",
    "SONARR_KEY",
    "PLEX_URL",
    "PLEX_TOKEN",
    "TMDB_KEY",
    "RADARR_QUALITY_ID",
    "SONARR_QUALITY_ID",
    "RADARR_ROOT_FOLDER",
    "SONARR_ROOT_FOLDER",
]


def validate_service_url(url):
    parsed = urllib.parse.urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=400, detail="Service URL must be http or https with a host")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Service URL must not include credentials")
    return str(url)


def read_env_values(path):
    # Use the same parser on write/merge as startup; preserve quoted hashes,
    # backslashes and dollar expressions literally, without interpolation.
    return {key: value for key, value in dotenv_values(path, interpolate=False).items() if value is not None} if path.exists() else {}


def write_env_values(path, values):
    def quote(value):
        return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"

    lines = ["# TV Tenderr Configuration", ""]
    seen = set()
    for key in ENV_KEY_ORDER:
        if key in values:
            lines.append(f"{key}={quote(values[key])}")
            seen.add(key)
    for key, value in values.items():
        if key not in seen:
            lines.append(f"{key}={quote(value)}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write("\n".join(lines))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def apply_runtime_config(values):
    global RADARR_URL, RADARR_KEY, SONARR_URL, SONARR_KEY, PLEX_URL, PLEX_TOKEN, TMDB_KEY
    global RADARR_QUALITY_ID, SONARR_QUALITY_ID, RADARR_ROOT_FOLDER, SONARR_ROOT_FOLDER
    if values.get("RADARR_URL"):
        RADARR_URL = values["RADARR_URL"]
    if values.get("RADARR_KEY"):
        RADARR_KEY = values["RADARR_KEY"]
    if values.get("SONARR_URL"):
        SONARR_URL = values["SONARR_URL"]
    if values.get("SONARR_KEY"):
        SONARR_KEY = values["SONARR_KEY"]
    if values.get("PLEX_URL"):
        PLEX_URL = values["PLEX_URL"]
    if values.get("PLEX_TOKEN"):
        PLEX_TOKEN = values["PLEX_TOKEN"]
    if values.get("TMDB_KEY"):
        TMDB_KEY = values["TMDB_KEY"]
    if values.get("RADARR_QUALITY_ID"):
        RADARR_QUALITY_ID = int(values["RADARR_QUALITY_ID"])
    if values.get("SONARR_QUALITY_ID"):
        SONARR_QUALITY_ID = int(values["SONARR_QUALITY_ID"])
    if values.get("RADARR_ROOT_FOLDER"):
        RADARR_ROOT_FOLDER = values["RADARR_ROOT_FOLDER"]
    if values.get("SONARR_ROOT_FOLDER"):
        SONARR_ROOT_FOLDER = values["SONARR_ROOT_FOLDER"]
    if values.get("TV_TENDERR_API_TOKEN"):
        os.environ[API_TOKEN_ENV] = values["TV_TENDERR_API_TOKEN"]
    if values.get("BACKEND_HOST"):
        os.environ["BACKEND_HOST"] = values["BACKEND_HOST"]
    if values.get("BACKEND_PORT"):
        os.environ["BACKEND_PORT"] = values["BACKEND_PORT"]


def persist_config(config):
    """Merge a caller-supplied config into ENV_FILE. Blank secrets do not erase stored ones."""
    values = read_env_values(ENV_FILE)
    for field, (env_key, kind) in CONFIG_TO_ENV.items():
        if field not in config or config[field] is None:
            continue
        if kind == "secret":
            secret = str(config[field]).strip()
            if not secret:
                continue
            values[env_key] = secret
        elif kind == "url":
            url = str(config[field]).strip()
            if not url:
                continue
            values[env_key] = validate_service_url(url)
        elif kind == "int":
            try:
                number = int(config[field])
                if number <= 0:
                    raise ValueError()
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{field} must be a positive integer")
            values[env_key] = str(number)
        else:
            values[env_key] = str(config[field])
    if "BACKEND_HOST" not in values:
        values["BACKEND_HOST"] = resolve_bind_host()
    write_env_values(ENV_FILE, values)
    apply_runtime_config(values)
    return {"ok": True}


def _presented_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def token_is_valid(presented: str) -> bool:
    expected = configured_api_token()
    if not expected or not presented:
        return False
    return hmac.compare_digest(presented.encode('utf-8'), expected.encode('utf-8'))


def service_secrets_configured() -> bool:
    placeholders = {
        "",
        "your_radarr_api_key",
        "your_sonarr_api_key",
        "your_plex_token",
        "your_tmdb_api_key",
    }
    return any(value and value not in placeholders for value in (RADARR_KEY, SONARR_KEY, PLEX_TOKEN, TMDB_KEY))


def bootstrap_setup_allowed(client_host):
    if configured_api_token():
        return False
    if client_host not in LOOPBACK_HOSTS:
        return False
    return not service_secrets_configured()


def request_is_authorized(request: Request) -> bool:
    if token_is_valid(_presented_token(request)):
        return True
    if request.method == "POST" and request.url.path in {"/api/save-env", "/api/config"}:
        host = request.client.host if request.client else None
        return bootstrap_setup_allowed(host)
    return False


@app.middleware("http")
async def guard_api(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path != "/api/health":
        # The lock covers authorization as well as the complete handler's
        # read/await-upstream/modify/write transaction. Recheck inside the lock:
        # a queued bootstrap or old-token request must not survive a config change.
        async with decision_lock:
            if not request_is_authorized(request):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
            return await call_next(request)
    if path in {"/docs", "/redoc", "/openapi.json"} and not request_is_authorized(request):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
async def health():
    return {"ok": True}


def assert_data_dir_safe(current, legacy):
    if not legacy.exists():
        return
    try:
        if legacy.resolve() == current.resolve():
            return
    except OSError:
        return
    legacy_files = [path for path in legacy.glob("*.json") if path.is_file() and path.stat().st_size > 0]
    current_files = [path for path in current.glob("*.json") if path.is_file() and path.stat().st_size > 0]
    if legacy_files and not current_files:
        raise SystemExit(
            f"Refusing to boot: {current} has no decision store and an older store exists at {legacy}"
        )


if __name__ == "__main__":
    import uvicorn
    assert_data_dir_safe(DATA_DIR, LEGACY_DATA_DIR)
    bind_host = resolve_bind_host()
    bind_port = resolve_bind_port()
    print(f"TV Tenderr bind={bind_host}:{bind_port} auth_configured={bool(configured_api_token())}")
    uvicorn.run(app, host=bind_host, port=bind_port)

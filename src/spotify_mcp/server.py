import asyncio
import base64
import os
import logging
import sys
from enum import Enum
import json
from typing import List, Optional, Tuple
from datetime import datetime
from pathlib import Path

import mcp.types as types
from mcp.server import NotificationOptions, Server  # , stdio_server
import mcp.server.stdio
from pydantic import BaseModel, Field, AnyUrl
from spotipy import SpotifyException

from . import spotify_api
from .utils import normalize_redirect_uri


def setup_logger():
    class Logger:
        def info(self, message):
            print(f"[INFO] {message}", file=sys.stderr)

        def error(self, message):
            print(f"[ERROR] {message}", file=sys.stderr)

    return Logger()


logger = setup_logger()
# Normalize the redirect URI to meet Spotify's requirements
if spotify_api.REDIRECT_URI:
    spotify_api.REDIRECT_URI = normalize_redirect_uri(spotify_api.REDIRECT_URI)
spotify_client = spotify_api.Client(logger)

server = Server("spotify-mcp")

# Genre categories for PlaylistLibrarian
GENRE_CATEGORIES = {
    "🎸 Rock": ["rock", "metal", "punk", "grunge", "alternative", "indie rock", "hard rock"],
    "🎵 Pop": ["pop", "dance pop", "electropop", "synth-pop", "indie pop"],
    "🎤 Hip-Hop": ["hip hop", "rap", "trap", "southern hip hop", "gangster rap"],
    "🎧 Electronic": ["electronic", "edm", "house", "techno", "dubstep", "trance", "drum and bass"],
    "🎷 Jazz": ["jazz", "bebop", "swing", "smooth jazz", "jazz fusion"],
    "🎻 Classical": ["classical", "orchestra", "symphony", "baroque", "opera"],
    "🤠 Country": ["country", "americana", "folk", "bluegrass", "country rock"],
    "🎺 R&B": ["r&b", "soul", "funk", "neo soul", "motown"],
    "🌍 World": ["latin", "reggae", "afrobeat", "k-pop", "j-pop", "reggaeton", "bossa nova"],
    "😴 Chill": ["ambient", "lo-fi", "chill", "downtempo", "chillwave"],
}


# options =
class ToolModel(BaseModel):
    @classmethod
    def as_tool(cls):
        return types.Tool(
            name="Spotify" + cls.__name__,
            description=cls.__doc__,
            inputSchema=cls.model_json_schema()
        )


class Playback(ToolModel):
    """Manages the current playback with the following actions:
    - get: Get information about user's current track.
    - start: Starts playing new item or resumes current playback if called with no uri.
    - pause: Pauses current playback.
    - skip: Skips current track.
    """
    action: str = Field(description="Action to perform: 'get', 'start', 'pause' or 'skip'.")
    spotify_uri: Optional[str] = Field(default=None, description="Spotify uri of item to play for 'start' action. " +
                                                                 "If omitted, resumes current playback.")
    num_skips: Optional[int] = Field(default=1, description="Number of tracks to skip for `skip` action.")


class Queue(ToolModel):
    """Manage the playback queue - get the queue or add tracks."""
    action: str = Field(description="Action to perform: 'add' or 'get'.")
    track_id: Optional[str] = Field(default=None, description="Track ID to add to queue (required for add action)")


class GetInfo(ToolModel):
    """Get detailed information about a Spotify item (track, album, artist, or playlist)."""
    item_uri: str = Field(description="URI of the item to get information about. " +
                                      "If 'playlist' or 'album', returns its tracks. " +
                                      "If 'artist', returns albums and top tracks.")


class Search(ToolModel):
    """Search for tracks, albums, artists, or playlists on Spotify."""
    query: str = Field(description="query term")
    qtype: Optional[str] = Field(default="track",
                                 description="Type of items to search for (track, album, artist, playlist, " +
                                             "or comma-separated combination)")
    limit: Optional[int] = Field(default=10, description="Maximum number of items to return")


class Playlist(ToolModel):
    """Manage Spotify playlists.
    - get: Get a list of user's playlists.
    - get_tracks: Get tracks in a specific playlist.
    - add_tracks: Add tracks to a specific playlist.
    - remove_tracks: Remove tracks from a specific playlist.
    - change_details: Change details of a specific playlist.
    - create: Create a new playlist.
    """
    action: str = Field(
        description="Action to perform: 'get', 'get_tracks', 'add_tracks', 'remove_tracks', 'change_details', 'create'.")
    playlist_id: Optional[str] = Field(default=None, description="ID of the playlist to manage.")
    track_ids: Optional[List[str]] = Field(default=None, description="List of track IDs to add/remove.")
    name: Optional[str] = Field(default=None, description="Name for the playlist (required for create and change_details).")
    description: Optional[str] = Field(default=None, description="Description for the playlist.")
    public: Optional[bool] = Field(default=True, description="Whether the playlist should be public (for create action).")


class ArtistDeepDive(ToolModel):
    """Create a comprehensive playlist collection for any artist.
    Generates three playlists:
    - 'Best of [Artist]': Top 20 most popular tracks
    - '[Artist]: Deep Cuts': Hidden gems with low popularity scores
    - '[Artist]: Through the Years': Complete discography in chronological order
    """
    artist_name: str = Field(description="Name of the artist to analyze.")
    include_singles: Optional[bool] = Field(default=True, description="Include singles and EPs, not just albums.")
    deep_cuts_max_popularity: Optional[int] = Field(default=40, description="Maximum popularity score (0-100) for deep cuts. Lower = more obscure.")


class PlaylistLibrarian(ToolModel):
    """Auto-organize playlists by genre with emoji category prefixes.
    Analyzes tracks in each playlist, detects dominant genres, and optionally
    renames playlists with category prefixes like '🎸 Rock/My Playlist'.
    """
    dry_run: Optional[bool] = Field(default=True, description="If true, only show proposed changes without applying them.")
    category_style: Optional[str] = Field(default="emoji", description="Style for category prefix: 'emoji' (🎸 Rock/) or 'text' ([Rock])")


class MyTopMusic(ToolModel):
    """Get your personalized listening statistics and top music.
    Shows your most played tracks and artists for different time periods,
    with genre breakdown and optional playlist creation.
    """
    time_range: Optional[str] = Field(default="short_term", description="Time period: 'short_term' (4 weeks), 'medium_term' (6 months), or 'long_term' (all time)")
    top_count: Optional[int] = Field(default=10, description="Number of top items to return (max 50)")
    create_playlist: Optional[bool] = Field(default=False, description="Create a playlist from your top tracks")


class Discover(ToolModel):
    """Get personalized music recommendations based on an artist, track, or your listening history.
    Uses genre-matching and your top artists to find new music you'll like - without deprecated APIs.
    """
    seed_type: str = Field(description="Type of seed: 'artist', 'track', or 'listening_history'")
    seed_value: Optional[str] = Field(default=None, description="Artist name or track URI (required for 'artist' and 'track' seed types)")
    year_range: Optional[str] = Field(default="2015-2025", description="Year range for recommendations (e.g., '2020-2025')")
    limit: Optional[int] = Field(default=30, description="Number of recommendations to return (max 50)")
    create_playlist: Optional[bool] = Field(default=False, description="Create a playlist from recommendations")


class Library(ToolModel):
    """Manage user's Liked Songs library.
    - save: Save tracks to Liked Songs.
    - remove: Remove tracks from Liked Songs.
    - check: Check if tracks are in Liked Songs.
    """
    action: str = Field(description="Action to perform: 'save', 'remove', or 'check'.")
    track_ids: List[str] = Field(description="List of track IDs to save/remove/check.")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    return []


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    return []


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools."""
    logger.info("Listing available tools")
    tools = [
        Playback.as_tool(),
        Search.as_tool(),
        Queue.as_tool(),
        GetInfo.as_tool(),
        Playlist.as_tool(),
        Library.as_tool(),
        ArtistDeepDive.as_tool(),
        PlaylistLibrarian.as_tool(),
        MyTopMusic.as_tool(),
        Discover.as_tool(),
    ]
    logger.info(f"Available tools: {[tool.name for tool in tools]}")
    return tools


@server.call_tool()
async def handle_call_tool(
        name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""
    logger.info(f"Tool called: {name} with arguments: {arguments}")
    assert name[:7] == "Spotify", f"Unknown tool: {name}"
    try:
        match name[7:]:
            case "Playback":
                action = arguments.get("action")
                match action:
                    case "get":
                        logger.info("Attempting to get current track")
                        curr_track = spotify_client.get_current_track()
                        if curr_track:
                            logger.info(f"Current track retrieved: {curr_track.get('name', 'Unknown')}")
                            return [types.TextContent(
                                type="text",
                                text=json.dumps(curr_track, indent=2)
                            )]
                        logger.info("No track currently playing")
                        return [types.TextContent(
                            type="text",
                            text="No track playing."
                        )]
                    case "start":
                        logger.info(f"Starting playback with arguments: {arguments}")
                        spotify_client.start_playback(spotify_uri=arguments.get("spotify_uri"))
                        logger.info("Playback started successfully")
                        return [types.TextContent(
                            type="text",
                            text="Playback starting."
                        )]
                    case "pause":
                        logger.info("Attempting to pause playback")
                        spotify_client.pause_playback()
                        logger.info("Playback paused successfully")
                        return [types.TextContent(
                            type="text",
                            text="Playback paused."
                        )]
                    case "skip":
                        num_skips = int(arguments.get("num_skips", 1))
                        logger.info(f"Skipping {num_skips} tracks.")
                        spotify_client.skip_track(n=num_skips)
                        return [types.TextContent(
                            type="text",
                            text="Skipped to next track."
                        )]

            case "Search":
                logger.info(f"Performing search with arguments: {arguments}")
                search_results = spotify_client.search(
                    query=arguments.get("query", ""),
                    qtype=arguments.get("qtype", "track"),
                    limit=arguments.get("limit", 10)
                )
                logger.info("Search completed successfully.")
                return [types.TextContent(
                    type="text",
                    text=json.dumps(search_results, indent=2)
                )]

            case "Queue":
                logger.info(f"Queue operation with arguments: {arguments}")
                action = arguments.get("action")

                match action:
                    case "add":
                        track_id = arguments.get("track_id")
                        if not track_id:
                            logger.error("track_id is required for add to queue.")
                            return [types.TextContent(
                                type="text",
                                text="track_id is required for add action"
                            )]
                        spotify_client.add_to_queue(track_id)
                        return [types.TextContent(
                            type="text",
                            text=f"Track added to queue."
                        )]

                    case "get":
                        queue = spotify_client.get_queue()
                        return [types.TextContent(
                            type="text",
                            text=json.dumps(queue, indent=2)
                        )]

                    case _:
                        return [types.TextContent(
                            type="text",
                            text=f"Unknown queue action: {action}. Supported actions are: add, remove, and get."
                        )]

            case "GetInfo":
                logger.info(f"Getting item info with arguments: {arguments}")
                item_info = spotify_client.get_info(
                    item_uri=arguments.get("item_uri")
                )
                return [types.TextContent(
                    type="text",
                    text=json.dumps(item_info, indent=2)
                )]

            case "Playlist":
                logger.info(f"Playlist operation with arguments: {arguments}")
                action = arguments.get("action")
                match action:
                    case "get":
                        logger.info(f"Getting current user's playlists with arguments: {arguments}")
                        playlists = spotify_client.get_current_user_playlists()
                        return [types.TextContent(
                            type="text",
                            text=json.dumps(playlists, indent=2)
                        )]
                    case "get_tracks":
                        logger.info(f"Getting tracks in playlist with arguments: {arguments}")
                        if not arguments.get("playlist_id"):
                            logger.error("playlist_id is required for get_tracks action.")
                            return [types.TextContent(
                                type="text",
                                text="playlist_id is required for get_tracks action."
                            )]
                        tracks = spotify_client.get_playlist_tracks(arguments.get("playlist_id"))
                        return [types.TextContent(
                            type="text",
                            text=json.dumps(tracks, indent=2)
                        )]
                    case "add_tracks":
                        logger.info(f"Adding tracks to playlist with arguments: {arguments}")
                        track_ids = arguments.get("track_ids")
                        if isinstance(track_ids, str):
                            try:
                                track_ids = json.loads(track_ids)  # Convert JSON string to Python list
                            except json.JSONDecodeError:
                                logger.error("track_ids must be a list or a valid JSON array.")
                                return [types.TextContent(
                                    type="text",
                                    text="Error: track_ids must be a list or a valid JSON array."
                                )]

                        spotify_client.add_tracks_to_playlist(
                            playlist_id=arguments.get("playlist_id"),
                            track_ids=track_ids
                        )
                        return [types.TextContent(
                            type="text",
                            text="Tracks added to playlist."
                        )]
                    case "remove_tracks":
                        logger.info(f"Removing tracks from playlist with arguments: {arguments}")
                        track_ids = arguments.get("track_ids")
                        if isinstance(track_ids, str):
                            try:
                                track_ids = json.loads(track_ids)  # Convert JSON string to Python list
                            except json.JSONDecodeError:
                                logger.error("track_ids must be a list or a valid JSON array.")
                                return [types.TextContent(
                                    type="text",
                                    text="Error: track_ids must be a list or a valid JSON array."
                                )]

                        spotify_client.remove_tracks_from_playlist(
                            playlist_id=arguments.get("playlist_id"),
                            track_ids=track_ids
                        )
                        return [types.TextContent(
                            type="text",
                            text="Tracks removed from playlist."
                        )]

                    case "change_details":
                        logger.info(f"Changing playlist details with arguments: {arguments}")
                        if not arguments.get("playlist_id"):
                            logger.error("playlist_id is required for change_details action.")
                            return [types.TextContent(
                                type="text",
                                text="playlist_id is required for change_details action."
                            )]
                        if not arguments.get("name") and not arguments.get("description"):
                            logger.error("At least one of name, description or public is required.")
                            return [types.TextContent(
                                type="text",
                                text="At least one of name, description, public, or collaborative is required."
                            )]

                        spotify_client.change_playlist_details(
                            playlist_id=arguments.get("playlist_id"),
                            name=arguments.get("name"),
                            description=arguments.get("description")
                        )
                        return [types.TextContent(
                            type="text",
                            text="Playlist details changed."
                        )]

                    case "create":
                        logger.info(f"Creating playlist with arguments: {arguments}")
                        if not arguments.get("name"):
                            logger.error("name is required for create action.")
                            return [types.TextContent(
                                type="text",
                                text="name is required for create action."
                            )]
                        
                        playlist = spotify_client.create_playlist(
                            name=arguments.get("name"),
                            description=arguments.get("description"),
                            public=arguments.get("public", True)
                        )
                        return [types.TextContent(
                            type="text",
                            text=json.dumps(playlist, indent=2)
                        )]

                    case _:
                        return [types.TextContent(
                            type="text",
                            text=f"Unknown playlist action: {action}."
                                 "Supported actions are: get, get_tracks, add_tracks, remove_tracks, change_details, create."
                        )]

            case "Library":
                logger.info(f"Library operation with arguments: {arguments}")
                action = arguments.get("action")
                track_ids = arguments.get("track_ids", [])

                if isinstance(track_ids, str):
                    try:
                        track_ids = json.loads(track_ids)
                    except json.JSONDecodeError:
                        return [types.TextContent(
                            type="text",
                            text="Error: track_ids must be a list or a valid JSON array."
                        )]

                if not track_ids:
                    return [types.TextContent(
                        type="text",
                        text="Error: track_ids is required."
                    )]

                match action:
                    case "save":
                        spotify_client.save_tracks(track_ids)
                        return [types.TextContent(
                            type="text",
                            text=f"Saved {len(track_ids)} track(s) to Liked Songs."
                        )]
                    case "remove":
                        spotify_client.remove_saved_tracks(track_ids)
                        return [types.TextContent(
                            type="text",
                            text=f"Removed {len(track_ids)} track(s) from Liked Songs."
                        )]
                    case "check":
                        results = spotify_client.check_saved_tracks(track_ids)
                        check_results = [{"track_id": tid, "is_saved": saved} for tid, saved in zip(track_ids, results)]
                        return [types.TextContent(
                            type="text",
                            text=json.dumps(check_results, indent=2)
                        )]
                    case _:
                        return [types.TextContent(
                            type="text",
                            text=f"Unknown library action: {action}. Supported actions are: save, remove, check."
                        )]

            case "ArtistDeepDive":
                logger.info(f"ArtistDeepDive called with arguments: {arguments}")
                artist_name = arguments.get("artist_name")
                include_singles = arguments.get("include_singles", True)
                deep_cuts_threshold = arguments.get("deep_cuts_max_popularity", 40)

                # 1. Search for artist
                search_results = spotify_client.search(artist_name, qtype="artist", limit=1)
                if not search_results.get('artists'):
                    return [types.TextContent(type="text", text=f"Artist '{artist_name}' not found.")]

                artist = search_results['artists'][0]
                artist_id = artist['id']
                artist_display_name = artist['name']
                logger.info(f"Found artist: {artist_display_name} (ID: {artist_id})")

                # 2. Get all albums
                albums = spotify_client.get_artist_albums(artist_id, include_singles=include_singles)
                logger.info(f"Found {len(albums)} albums/singles for {artist_display_name}")

                # 3. Collect all tracks with metadata
                all_tracks = []
                for album in albums:
                    try:
                        tracks, release_date, album_type = spotify_client.get_album_tracks_full(album['id'])
                        for track in tracks:
                            full_track = spotify_client.get_track(track['id'])
                            all_tracks.append({
                                'id': track['id'],
                                'name': track['name'],
                                'popularity': full_track.get('popularity', 0),
                                'release_date': release_date,
                                'album_type': album_type,
                                'album_name': album['name']
                            })
                    except Exception as e:
                        logger.error(f"Error processing album {album.get('name')}: {str(e)}")
                        continue

                logger.info(f"Collected {len(all_tracks)} total tracks")

                # 4. Deduplicate by track name (keep highest popularity version)
                seen = {}
                for track in all_tracks:
                    key = track['name'].lower()
                    if key not in seen or track['popularity'] > seen[key]['popularity']:
                        seen[key] = track
                unique_tracks = list(seen.values())
                logger.info(f"After deduplication: {len(unique_tracks)} unique tracks")

                # 5. Create "Best of" playlist
                best_of_tracks = sorted(unique_tracks, key=lambda x: x['popularity'], reverse=True)[:20]
                best_of_ids = set(t['id'] for t in best_of_tracks)
                best_of_playlist = spotify_client.create_playlist(
                    name=f"Best of {artist_display_name}",
                    description=f"Top 20 most popular tracks by {artist_display_name}"
                )
                if best_of_tracks:
                    spotify_client.add_tracks_to_playlist(best_of_playlist['id'], [t['id'] for t in best_of_tracks])

                # 6. Create "Deep Cuts" playlist
                deep_cuts = [t for t in unique_tracks
                             if t['popularity'] < deep_cuts_threshold
                             and t['id'] not in best_of_ids
                             and t['album_type'] == 'album']
                deep_cuts = sorted(deep_cuts, key=lambda x: x['popularity'])[:25]
                deep_cuts_playlist = spotify_client.create_playlist(
                    name=f"{artist_display_name}: Deep Cuts",
                    description=f"Hidden gems and lesser-known tracks by {artist_display_name}"
                )
                if deep_cuts:
                    spotify_client.add_tracks_to_playlist(deep_cuts_playlist['id'], [t['id'] for t in deep_cuts])

                # 7. Create "Through the Years" playlist
                chronological = sorted(unique_tracks, key=lambda x: x['release_date'])
                chrono_playlist = spotify_client.create_playlist(
                    name=f"{artist_display_name}: Through the Years",
                    description=f"Complete discography of {artist_display_name} in chronological order"
                )
                if chronological:
                    track_ids = [t['id'] for t in chronological]
                    for i in range(0, len(track_ids), 100):
                        spotify_client.add_tracks_to_playlist(chrono_playlist['id'], track_ids[i:i+100])

                result = {
                    "artist": {"name": artist_display_name, "id": artist_id},
                    "playlists_created": [
                        {"name": best_of_playlist['name'], "id": best_of_playlist['id'], "track_count": len(best_of_tracks)},
                        {"name": deep_cuts_playlist['name'], "id": deep_cuts_playlist['id'], "track_count": len(deep_cuts)},
                        {"name": chrono_playlist['name'], "id": chrono_playlist['id'], "track_count": len(chronological)}
                    ],
                    "stats": {
                        "total_albums_analyzed": len(albums),
                        "total_tracks_analyzed": len(unique_tracks)
                    }
                }
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            case "PlaylistLibrarian":
                logger.info(f"PlaylistLibrarian called with arguments: {arguments}")
                dry_run = arguments.get("dry_run", True)
                style = arguments.get("category_style", "emoji")

                # 1. Get all user-owned playlists
                all_playlists = spotify_client.get_all_playlists()
                user_id = spotify_client.sp.current_user()['id']
                owned = [p for p in all_playlists if p['owner']['id'] == user_id]
                logger.info(f"Found {len(owned)} user-owned playlists")

                changes = []
                category_counts = {cat: 0 for cat in GENRE_CATEGORIES}
                skipped = 0

                for playlist in owned:
                    name = playlist['name']

                    # Skip if already categorized
                    if any(name.startswith(cat) for cat in GENRE_CATEGORIES):
                        skipped += 1
                        continue

                    # 2. Sample tracks from playlist
                    try:
                        tracks = spotify_client.get_playlist_tracks(playlist['id'])[:30]
                    except Exception as e:
                        logger.error(f"Error getting tracks for playlist '{name}': {str(e)}")
                        skipped += 1
                        continue

                    if not tracks:
                        skipped += 1
                        continue

                    track_ids = [t['id'] for t in tracks if t and t.get('id')]
                    if not track_ids:
                        skipped += 1
                        continue

                    # 3. Get artists and their genres
                    try:
                        artist_ids = spotify_client.get_artists_for_tracks(track_ids)
                        if not artist_ids:
                            skipped += 1
                            continue

                        artist_genres = spotify_client.get_artists_genres(artist_ids)
                    except Exception as e:
                        logger.error(f"Error getting genres for playlist '{name}': {str(e)}")
                        skipped += 1
                        continue

                    # 4. Score genres
                    all_genres = []
                    for genres in artist_genres.values():
                        all_genres.extend(genres)

                    best_category = None
                    best_score = 0
                    for category, keywords in GENRE_CATEGORIES.items():
                        score = sum(1 for g in all_genres if any(kw in g.lower() for kw in keywords))
                        if score > best_score:
                            best_score = score
                            best_category = category

                    if best_category and best_score > 0:
                        if style == "emoji":
                            new_name = f"{best_category}/{name}"
                        else:
                            text_cat = best_category.split()[1]
                            new_name = f"[{text_cat}] {name}"

                        changes.append({
                            "playlist_id": playlist['id'],
                            "original_name": name,
                            "new_name": new_name,
                            "detected_category": best_category,
                            "applied": not dry_run
                        })
                        category_counts[best_category] += 1

                        if not dry_run:
                            try:
                                spotify_client.change_playlist_details(playlist['id'], name=new_name)
                            except Exception as e:
                                logger.error(f"Error renaming playlist '{name}': {str(e)}")
                                changes[-1]["applied"] = False
                    else:
                        skipped += 1

                result = {
                    "playlists_analyzed": len(owned),
                    "playlists_categorized": len(changes),
                    "playlists_skipped": skipped,
                    "dry_run": dry_run,
                    "changes": changes,
                    "category_summary": {k: v for k, v in category_counts.items() if v > 0}
                }
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            case "MyTopMusic":
                logger.info(f"MyTopMusic called with arguments: {arguments}")
                time_range = arguments.get("time_range", "short_term")
                top_count = min(int(arguments.get("top_count", 10)), 50)
                create_playlist_flag = arguments.get("create_playlist", False)

                period_labels = {
                    "short_term": "Last 4 Weeks",
                    "medium_term": "Last 6 Months",
                    "long_term": "All Time"
                }

                if time_range not in period_labels:
                    return [types.TextContent(
                        type="text",
                        text=f"Invalid time_range: {time_range}. Must be 'short_term', 'medium_term', or 'long_term'."
                    )]

                # 1. Fetch data
                top_tracks = spotify_client.get_top_tracks(time_range, limit=50)
                top_artists = spotify_client.get_top_artists(time_range, limit=50)
                logger.info(f"Fetched {len(top_tracks)} top tracks, {len(top_artists)} top artists")

                # 2. Process top tracks
                top_tracks_display = []
                total_duration_ms = 0
                for i, track in enumerate(top_tracks[:top_count]):
                    total_duration_ms += track.get('duration_ms', 0)
                    top_tracks_display.append({
                        "rank": i + 1,
                        "name": track['name'],
                        "artist": track['artists'][0]['name'],
                        "id": track['id']
                    })

                # 3. Process top artists with genres
                top_artists_display = []
                all_genres = []
                for i, artist in enumerate(top_artists[:top_count]):
                    genres = artist.get('genres', [])
                    all_genres.extend(genres)
                    top_artists_display.append({
                        "rank": i + 1,
                        "name": artist['name'],
                        "genres": genres[:3]
                    })

                # 4. Calculate genre breakdown
                genre_counts = {}
                for genre in all_genres:
                    simple = genre.split()[0] if genre else "other"
                    genre_counts[simple] = genre_counts.get(simple, 0) + 1

                total_genres = sum(genre_counts.values()) or 1
                genre_breakdown = {
                    g: round(c / total_genres * 100)
                    for g, c in sorted(genre_counts.items(), key=lambda x: -x[1])[:5]
                }

                # 5. Stats
                stats = {
                    "top_tracks_analyzed": len(top_tracks),
                    "top_artists_analyzed": len(top_artists),
                    "estimated_top_tracks_duration_hours": round(total_duration_ms / 3600000, 1)
                }

                # 6. Optional playlist creation
                recap_playlist = None
                if create_playlist_flag and top_tracks:
                    month_year = datetime.now().strftime("%b %Y")
                    playlist = spotify_client.create_playlist(
                        name=f"My Top Tracks - {month_year}",
                        description=f"Your top tracks for {period_labels[time_range]}"
                    )
                    track_ids = [t['id'] for t in top_tracks[:top_count]]
                    spotify_client.add_tracks_to_playlist(playlist['id'], track_ids)
                    recap_playlist = {
                        "name": playlist['name'],
                        "id": playlist['id'],
                        "track_count": len(track_ids)
                    }

                result = {
                    "time_range": time_range,
                    "period_label": period_labels[time_range],
                    "top_tracks": top_tracks_display,
                    "top_artists": top_artists_display,
                    "genre_breakdown": genre_breakdown,
                    "stats": stats
                }
                if recap_playlist:
                    result["recap_playlist"] = recap_playlist

                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            case "Discover":
                logger.info(f"Discover called with arguments: {arguments}")
                seed_type = arguments.get("seed_type")
                seed_value = arguments.get("seed_value")
                year_range = arguments.get("year_range", "2015-2025")
                limit = min(arguments.get("limit", 30), 50)
                create_playlist_flag = arguments.get("create_playlist", False)

                # Validate inputs
                if seed_type not in ["artist", "track", "listening_history"]:
                    return [types.TextContent(
                        type="text",
                        text=f"Invalid seed_type: {seed_type}. Must be 'artist', 'track', or 'listening_history'."
                    )]

                if seed_type in ["artist", "track"] and not seed_value:
                    return [types.TextContent(
                        type="text",
                        text=f"seed_value is required for seed_type '{seed_type}'."
                    )]

                # Step 1: Get seed genres
                seed_genres = []
                seed_artist_name = None
                seed_popularity = 50  # Default middle-range

                if seed_type == "artist":
                    # Search for the artist
                    search_results = spotify_client.search(seed_value, qtype="artist", limit=1)
                    if not search_results.get('artists'):
                        return [types.TextContent(type="text", text=f"Artist '{seed_value}' not found.")]
                    artist = search_results['artists'][0]
                    artist_details = spotify_client.get_artist(artist['id'])
                    seed_genres = artist_details.get('genres', [])[:3]
                    seed_artist_name = artist['name']
                    logger.info(f"Seed artist: {seed_artist_name}, genres: {seed_genres}")

                elif seed_type == "track":
                    # Get track and its primary artist's genres
                    track_id = seed_value.split(':')[-1] if ':' in seed_value else seed_value
                    track = spotify_client.get_track(track_id)
                    seed_popularity = track.get('popularity', 50)
                    if track.get('artists'):
                        artist_id = track['artists'][0]['id']
                        artist_details = spotify_client.get_artist(artist_id)
                        seed_genres = artist_details.get('genres', [])[:3]
                        seed_artist_name = artist_details['name']
                    logger.info(f"Seed track by {seed_artist_name}, popularity: {seed_popularity}, genres: {seed_genres}")

                elif seed_type == "listening_history":
                    # Get genres from user's top artists
                    top_artists = spotify_client.get_top_artists(time_range="medium_term", limit=10)
                    genre_counts = {}
                    for artist in top_artists:
                        for genre in artist.get('genres', []):
                            genre_counts[genre] = genre_counts.get(genre, 0) + 1
                    # Get top 3 genres
                    seed_genres = sorted(genre_counts.keys(), key=lambda g: -genre_counts[g])[:3]
                    logger.info(f"Seed genres from listening history: {seed_genres}")

                if not seed_genres:
                    return [types.TextContent(
                        type="text",
                        text="Could not determine genres for recommendations. Try a different seed."
                    )]

                # Step 2: Get tracks to exclude (recent + saved)
                exclude_ids = set()
                try:
                    exclude_ids.update(spotify_client.get_recent_track_ids(limit=50))
                    exclude_ids.update(spotify_client.get_user_saved_track_ids(limit=100))
                except Exception as e:
                    logger.error(f"Error getting tracks to exclude: {str(e)}")

                # Step 3: Search for tracks by genre
                recommendations = []
                seen_track_ids = set()
                artist_track_counts = {}  # Track how many songs per artist

                for genre in seed_genres:
                    try:
                        tracks = spotify_client.search_by_genre(genre, year_range=year_range, limit=20)
                        for track in tracks:
                            track_id = track['id']
                            if track_id in seen_track_ids or track_id in exclude_ids:
                                continue

                            # Limit tracks per artist for diversity
                            artist_id = track['artists'][0]['id'] if track.get('artists') else None
                            if artist_id and artist_track_counts.get(artist_id, 0) >= 3:
                                continue

                            seen_track_ids.add(track_id)
                            if artist_id:
                                artist_track_counts[artist_id] = artist_track_counts.get(artist_id, 0) + 1

                            recommendations.append({
                                'id': track_id,
                                'name': track['name'],
                                'artist': track['artists'][0]['name'] if track.get('artists') else 'Unknown',
                                'artist_id': artist_id,
                                'popularity': track.get('popularity', 0),
                                'source_genre': genre
                            })
                    except Exception as e:
                        logger.error(f"Error searching genre '{genre}': {str(e)}")
                        continue

                # Step 4: Add top tracks from user's similar artists
                if seed_type in ["artist", "track"]:
                    try:
                        top_artists = spotify_client.get_top_artists(time_range="medium_term", limit=20)
                        matching_artists = []
                        for artist in top_artists:
                            artist_genres = set(artist.get('genres', []))
                            if artist_genres.intersection(seed_genres):
                                matching_artists.append(artist)

                        for artist in matching_artists[:5]:
                            try:
                                top_tracks = spotify_client.get_artist_top_tracks(artist['id'])
                                for track in top_tracks[:3]:
                                    track_id = track['id']
                                    if track_id in seen_track_ids or track_id in exclude_ids:
                                        continue
                                    seen_track_ids.add(track_id)
                                    recommendations.append({
                                        'id': track_id,
                                        'name': track['name'],
                                        'artist': artist['name'],
                                        'artist_id': artist['id'],
                                        'popularity': track.get('popularity', 0),
                                        'source_genre': 'top_artist_match'
                                    })
                            except Exception as e:
                                logger.error(f"Error getting top tracks for {artist['name']}: {str(e)}")
                                continue
                    except Exception as e:
                        logger.error(f"Error getting matching top artists: {str(e)}")

                # Step 5: Sort by popularity proximity to seed and diversify
                def score_track(t):
                    pop_diff = abs(t['popularity'] - seed_popularity)
                    return pop_diff

                recommendations.sort(key=score_track)
                recommendations = recommendations[:limit]

                logger.info(f"Generated {len(recommendations)} recommendations")

                # Step 6: Optional playlist creation
                discover_playlist = None
                if create_playlist_flag and recommendations:
                    playlist_name = f"Discover: {seed_artist_name or 'My Genres'}"
                    playlist = spotify_client.create_playlist(
                        name=playlist_name,
                        description=f"Recommendations based on {seed_type}: {seed_value or 'listening history'}"
                    )
                    track_ids = [t['id'] for t in recommendations]
                    spotify_client.add_tracks_to_playlist(playlist['id'], track_ids)
                    discover_playlist = {
                        "name": playlist['name'],
                        "id": playlist['id'],
                        "track_count": len(track_ids)
                    }

                result = {
                    "seed_type": seed_type,
                    "seed_value": seed_value or "listening_history",
                    "seed_genres": seed_genres,
                    "year_range": year_range,
                    "recommendations": [{
                        "name": t['name'],
                        "artist": t['artist'],
                        "id": t['id'],
                        "popularity": t['popularity']
                    } for t in recommendations],
                    "count": len(recommendations)
                }
                if discover_playlist:
                    result["playlist_created"] = discover_playlist

                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            case _:
                error_msg = f"Unknown tool: {name}"
                logger.error(error_msg)
                return [types.TextContent(
                    type="text",
                    text=error_msg
                )]
    except SpotifyException as se:
        error_msg = f"Spotify Client error occurred: {str(se)}"
        logger.error(error_msg)
        return [types.TextContent(
            type="text",
            text=f"An error occurred with the Spotify Client: {str(se)}"
        )]
    except Exception as e:
        error_msg = f"Unexpected error occurred: {str(e)}"
        logger.error(error_msg)
        return [types.TextContent(
            type="text",
            text=error_msg
        )]


async def main():
    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server error occurred: {str(e)}")
        raise

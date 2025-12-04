import logging
import os
from typing import Optional, Dict, List

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

from . import utils
from .remote_cache_handler import RemoteCacheHandler

load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
BACKEND_URL = os.getenv("SPOTIFY_BACKEND_URL")

# Normalize the redirect URI to meet Spotify's requirements
if REDIRECT_URI:
    REDIRECT_URI = utils.normalize_redirect_uri(REDIRECT_URI)

SCOPES = ["user-read-currently-playing", "user-read-playback-state", "user-read-currently-playing",  # spotify connect
          "app-remote-control", "streaming",  # playback
          "playlist-read-private", "playlist-read-collaborative", "playlist-modify-private", "playlist-modify-public",
          # playlists
          "user-read-playback-position", "user-top-read", "user-read-recently-played",  # listening history
          "user-library-modify", "user-library-read",  # library
          ]


class Client:
    def __init__(self, logger: logging.Logger):
        """Initialize Spotify client with necessary permissions"""
        self.logger = logger

        scope = "user-library-read,user-read-playback-state,user-modify-playback-state,user-read-currently-playing,playlist-read-private,playlist-read-collaborative,playlist-modify-private,playlist-modify-public"

        try:
            # Use remote cache handler if backend URL is configured, otherwise use local file cache
            if BACKEND_URL:
                self.logger.info(f"Using remote cache handler with backend: {BACKEND_URL}")
                cache_handler = RemoteCacheHandler(backend_url=BACKEND_URL)
            else:
                self.logger.info("Using local file cache handler")
                cache_handler = CacheFileHandler()

            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                scope=scope,
                client_id=CLIENT_ID,
                client_secret=CLIENT_SECRET,
                redirect_uri=REDIRECT_URI,
                cache_handler=cache_handler,
                open_browser=False))  # Don't open browser - we use web auth

            self.auth_manager: SpotifyOAuth = self.sp.auth_manager
            self.cache_handler = cache_handler
        except Exception as e:
            self.logger.error(f"Failed to initialize Spotify client: {str(e)}")
            raise

        self.username = None

    @utils.validate
    def set_username(self, device=None):
        self.username = self.sp.current_user()['display_name']

    @utils.validate
    def search(self, query: str, qtype: str = 'track', limit=10, device=None):
        """
        Searches based of query term.
        - query: query term
        - qtype: the types of items to return. One or more of 'artist', 'album',  'track', 'playlist'.
                 If multiple types are desired, pass in a comma separated string; e.g. 'track,album'
        - limit: max # items to return
        """
        if self.username is None:
            self.set_username()
        results = self.sp.search(q=query, limit=limit, type=qtype)
        if not results:
            raise ValueError("No search results found.")
        return utils.parse_search_results(results, qtype, self.username)

    def recommendations(self, artists: Optional[List] = None, tracks: Optional[List] = None, limit=20):
        # doesnt work
        recs = self.sp.recommendations(seed_artists=artists, seed_tracks=tracks, limit=limit)
        return recs

    def get_info(self, item_uri: str) -> dict:
        """
        Returns more info about item.
        - item_uri: uri. Looks like 'spotify:track:xxxxxx', 'spotify:album:xxxxxx', etc.
        """
        _, qtype, item_id = item_uri.split(":")
        match qtype:
            case 'track':
                return utils.parse_track(self.sp.track(item_id), detailed=True)
            case 'album':
                album_info = utils.parse_album(self.sp.album(item_id), detailed=True)
                return album_info
            case 'artist':
                artist_info = utils.parse_artist(self.sp.artist(item_id), detailed=True)
                albums = self.sp.artist_albums(item_id)
                top_tracks = self.sp.artist_top_tracks(item_id)['tracks']
                albums_and_tracks = {
                    'albums': albums,
                    'tracks': {'items': top_tracks}
                }
                parsed_info = utils.parse_search_results(albums_and_tracks, qtype="album,track")
                artist_info['top_tracks'] = parsed_info['tracks']
                artist_info['albums'] = parsed_info['albums']

                return artist_info
            case 'playlist':
                if self.username is None:
                    self.set_username()
                playlist = self.sp.playlist(item_id)
                self.logger.info(f"playlist info is {playlist}")
                playlist_info = utils.parse_playlist(playlist, self.username, detailed=True)

                return playlist_info

        raise ValueError(f"Unknown qtype {qtype}")

    def get_current_track(self) -> Optional[Dict]:
        """Get information about the currently playing track"""
        try:
            # current_playback vs current_user_playing_track?
            current = self.sp.current_user_playing_track()
            if not current:
                self.logger.info("No playback session found")
                return None
            if current.get('currently_playing_type') != 'track':
                self.logger.info("Current playback is not a track")
                return None

            track_info = utils.parse_track(current['item'])
            if 'is_playing' in current:
                track_info['is_playing'] = current['is_playing']

            self.logger.info(
                f"Current track: {track_info.get('name', 'Unknown')} by {track_info.get('artist', 'Unknown')}")
            return track_info
        except Exception as e:
            self.logger.error("Error getting current track info.")
            raise

    @utils.validate
    def start_playback(self, spotify_uri=None, device=None):
        """
        Starts spotify playback of uri. If spotify_uri is omitted, resumes current playback.
        - spotify_uri: ID of resource to play, or None. Typically looks like 'spotify:track:xxxxxx' or 'spotify:album:xxxxxx'.
        """
        try:
            self.logger.info(f"Starting playback for spotify_uri: {spotify_uri} on {device}")
            if not spotify_uri:
                if self.is_track_playing():
                    self.logger.info("No track_id provided and playback already active.")
                    return
                if not self.get_current_track():
                    raise ValueError("No track_id provided and no current playback to resume.")

            if spotify_uri is not None:
                if spotify_uri.startswith('spotify:track:'):
                    uris = [spotify_uri]
                    context_uri = None
                else:
                    uris = None
                    context_uri = spotify_uri
            else:
                uris = None
                context_uri = None

            device_id = device.get('id') if device else None

            self.logger.info(f"Starting playback of on {device}: context_uri={context_uri}, uris={uris}")
            result = self.sp.start_playback(uris=uris, context_uri=context_uri, device_id=device_id)
            self.logger.info(f"Playback result: {result}")
            return result
        except Exception as e:
            self.logger.error(f"Error starting playback: {str(e)}.")
            raise

    @utils.validate
    def pause_playback(self, device=None):
        """Pauses playback."""
        playback = self.sp.current_playback()
        if playback and playback.get('is_playing'):
            self.sp.pause_playback(device.get('id') if device else None)

    @utils.validate
    def add_to_queue(self, track_id: str, device=None):
        """
        Adds track to queue.
        - track_id: ID of track to play.
        """
        self.sp.add_to_queue(track_id, device.get('id') if device else None)

    @utils.validate
    def get_queue(self, device=None):
        """Returns the current queue of tracks."""
        queue_info = self.sp.queue()
        queue_info['currently_playing'] = self.get_current_track()

        queue_info['queue'] = [utils.parse_track(track) for track in queue_info.pop('queue')]

        return queue_info

    def get_liked_songs(self):
        # todo
        results = self.sp.current_user_saved_tracks()
        for idx, item in enumerate(results['items']):
            track = item['track']
            print(idx, track['artists'][0]['name'], " – ", track['name'])

    def is_track_playing(self) -> bool:
        """Returns if a track is actively playing."""
        curr_track = self.get_current_track()
        if not curr_track:
            return False
        if curr_track.get('is_playing'):
            return True
        return False

    def get_current_user_playlists(self, limit=50) -> List[Dict]:
        """
        Get current user's playlists.
        - limit: Max number of playlists to return.
        """
        playlists = self.sp.current_user_playlists()
        if not playlists:
            raise ValueError("No playlists found.")
        return [utils.parse_playlist(playlist, self.username) for playlist in playlists['items']]
    
    @utils.ensure_username
    def get_playlist_tracks(self, playlist_id: str, limit=50) -> List[Dict]:
        """
        Get tracks from a playlist.
        - playlist_id: ID of the playlist to get tracks from.
        - limit: Max number of tracks to return.
        """
        playlist = self.sp.playlist(playlist_id)
        if not playlist:
            raise ValueError("No playlist found.")
        return utils.parse_tracks(playlist['tracks']['items'])
    
    @utils.ensure_username
    def add_tracks_to_playlist(self, playlist_id: str, track_ids: List[str], position: Optional[int] = None):
        """
        Add tracks to a playlist.
        - playlist_id: ID of the playlist to modify.
        - track_ids: List of track IDs to add.
        - position: Position to insert the tracks at (optional).
        """
        if not playlist_id:
            raise ValueError("No playlist ID provided.")
        if not track_ids:
            raise ValueError("No track IDs provided.")
        
        try:
            response = self.sp.playlist_add_items(playlist_id, track_ids, position=position)
            self.logger.info(f"Response from adding tracks: {track_ids} to playlist {playlist_id}: {response}")
        except Exception as e:
            self.logger.error(f"Error adding tracks to playlist: {str(e)}")

    @utils.ensure_username
    def remove_tracks_from_playlist(self, playlist_id: str, track_ids: List[str]):
        """
        Remove tracks from a playlist.
        - playlist_id: ID of the playlist to modify.
        - track_ids: List of track IDs to remove.
        """
        if not playlist_id:
            raise ValueError("No playlist ID provided.")
        if not track_ids:
            raise ValueError("No track IDs provided.")
        
        try:
            response = self.sp.playlist_remove_all_occurrences_of_items(playlist_id, track_ids)
            self.logger.info(f"Response from removing tracks: {track_ids} from playlist {playlist_id}: {response}")
        except Exception as e:
            self.logger.error(f"Error removing tracks from playlist: {str(e)}")

    @utils.ensure_username
    def create_playlist(self, name: str, description: Optional[str] = None, public: bool = True):
        """
        Create a new playlist.
        - name: Name for the playlist.
        - description: Description for the playlist.
        - public: Whether the playlist should be public.
        """
        if not name:
            raise ValueError("Playlist name is required.")
        
        try:
            user = self.sp.current_user()
            user_id = user['id']
            
            playlist = self.sp.user_playlist_create(
                user=user_id,
                name=name,
                public=public,
                description=description
            )
            self.logger.info(f"Created playlist: {name} (ID: {playlist['id']})")
            return utils.parse_playlist(playlist, self.username, detailed=True)
        except Exception as e:
            self.logger.error(f"Error creating playlist: {str(e)}")
            raise

    @utils.ensure_username
    def change_playlist_details(self, playlist_id: str, name: Optional[str] = None, description: Optional[str] = None):
        """
        Change playlist details.
        - playlist_id: ID of the playlist to modify.
        - name: New name for the playlist.
        - public: Whether the playlist should be public.
        - description: New description for the playlist.
        """
        if not playlist_id:
            raise ValueError("No playlist ID provided.")
        
        try:
            response = self.sp.playlist_change_details(playlist_id, name=name, description=description)
            self.logger.info(f"Response from changing playlist details: {response}")
        except Exception as e:
            self.logger.error(f"Error changing playlist details: {str(e)}")
       
    def get_devices(self) -> dict:
        return self.sp.devices()['devices']

    def is_active_device(self):
        return any([device.get('is_active') for device in self.get_devices()])

    def _get_candidate_device(self):
        devices = self.get_devices()
        if not devices:
            raise ConnectionError("No active device. Is Spotify open?")
        for device in devices:
            if device.get('is_active'):
                return device
        self.logger.info(f"No active device, assigning {devices[0]['name']}.")
        return devices[0]

    def auth_ok(self) -> bool:
        try:
            token = self.cache_handler.get_cached_token()
            if token is None:
                self.logger.info("Auth check result: no token exists")
                return False
                
            is_expired = self.auth_manager.is_token_expired(token)
            self.logger.info(f"Auth check result: {'valid' if not is_expired else 'expired'}")
            return not is_expired  # Return True if token is NOT expired
        except Exception as e:
            self.logger.error(f"Error checking auth status: {str(e)}")
            return False  # Return False on error rather than raising

    def auth_refresh(self):
        self.auth_manager.validate_token(self.cache_handler.get_cached_token())

    def skip_track(self, n=1):
        # todo: Better error handling
        for _ in range(n):
            self.sp.next_track()

    def previous_track(self):
        self.sp.previous_track()

    def seek_to_position(self, position_ms):
        self.sp.seek_track(position_ms=position_ms)

    def set_volume(self, volume_percent):
        self.sp.volume(volume_percent)

    # --- Methods for advanced features ---

    def get_track(self, track_id: str) -> Dict:
        """Get full track details including popularity."""
        if track_id.startswith('spotify:track:'):
            track_id = track_id.split(':')[2]
        return self.sp.track(track_id)

    def get_artist_albums(self, artist_id: str, include_singles: bool = True, limit: int = 50) -> List[Dict]:
        """Get all albums for an artist with pagination."""
        album_type = 'album,single' if include_singles else 'album'
        all_albums = []
        offset = 0
        while True:
            results = self.sp.artist_albums(artist_id, album_type=album_type, limit=limit, offset=offset)
            all_albums.extend(results['items'])
            if not results['next']:
                break
            offset += limit
        return all_albums

    def get_album_tracks_full(self, album_id: str) -> tuple:
        """Get all tracks from an album with release date and album type."""
        album = self.sp.album(album_id)
        return album['tracks']['items'], album['release_date'], album['album_type']

    def get_artist_top_tracks(self, artist_id: str, country: str = 'US') -> List[Dict]:
        """Get artist's top tracks."""
        results = self.sp.artist_top_tracks(artist_id, country=country)
        return results['tracks']

    def get_all_playlists(self, limit: int = 50) -> List[Dict]:
        """Get all user playlists with pagination."""
        playlists = []
        offset = 0
        while True:
            results = self.sp.current_user_playlists(limit=limit, offset=offset)
            playlists.extend(results['items'])
            if not results['next']:
                break
            offset += limit
        return playlists

    def get_artists_for_tracks(self, track_ids: List[str]) -> List[str]:
        """Get unique artist IDs for multiple tracks (batch request)."""
        artist_ids = set()
        for i in range(0, len(track_ids), 50):
            batch = track_ids[i:i+50]
            tracks = self.sp.tracks(batch)['tracks']
            for t in tracks:
                if t and t.get('artists'):
                    artist_ids.add(t['artists'][0]['id'])
        return list(artist_ids)

    def get_artists_genres(self, artist_ids: List[str]) -> Dict[str, List[str]]:
        """Get genres for multiple artists (batch request)."""
        genres = {}
        for i in range(0, len(artist_ids), 50):
            batch = artist_ids[i:i+50]
            results = self.sp.artists(batch)['artists']
            for artist in results:
                if artist:
                    genres[artist['id']] = artist.get('genres', [])
        return genres

    def get_top_tracks(self, time_range: str = 'short_term', limit: int = 50) -> List[Dict]:
        """Get user's top tracks for time period."""
        results = self.sp.current_user_top_tracks(time_range=time_range, limit=limit)
        return results['items']

    def get_top_artists(self, time_range: str = 'short_term', limit: int = 50) -> List[Dict]:
        """Get user's top artists for time period."""
        results = self.sp.current_user_top_artists(time_range=time_range, limit=limit)
        return results['items']

    def get_recently_played(self, limit: int = 50) -> List[Dict]:
        """Get recently played tracks."""
        results = self.sp.current_user_recently_played(limit=limit)
        return results['items']

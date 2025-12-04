"""
Custom cache handler that fetches/stores Spotify tokens from a remote backend.
This allows the MCP to use tokens obtained via a web-based OAuth flow.
"""

import os
import logging
import requests
from spotipy.cache_handler import CacheHandler

logger = logging.getLogger(__name__)

BACKEND_URL = os.getenv("SPOTIFY_BACKEND_URL", "https://gentle-mesa-48529-28750f66374b.herokuapp.com")


class RemoteCacheHandler(CacheHandler):
    """
    A cache handler that stores and retrieves tokens from a remote backend API.
    This enables sharing OAuth tokens between web app and MCP.
    """

    def __init__(self, backend_url: str = None):
        self.backend_url = backend_url or BACKEND_URL
        self._cached_token = None

    def get_cached_token(self):
        """Fetch token from remote backend."""
        try:
            response = requests.get(
                f"{self.backend_url}/spotify/mcp-token",
                timeout=10
            )

            if response.status_code == 404:
                logger.info("No token cached in backend. User needs to authenticate via web.")
                return None

            if not response.ok:
                logger.error(f"Failed to fetch token from backend: {response.status_code}")
                return None

            token_info = response.json()
            self._cached_token = token_info
            logger.info("Successfully fetched token from backend")
            return token_info

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching token from backend: {e}")
            return None

    def save_token_to_cache(self, token_info):
        """Save token to remote backend."""
        try:
            response = requests.post(
                f"{self.backend_url}/spotify/mcp-token",
                json={
                    "access_token": token_info.get("access_token"),
                    "refresh_token": token_info.get("refresh_token"),
                    "expires_in": token_info.get("expires_in", 3600),
                },
                timeout=10
            )

            if response.ok:
                self._cached_token = token_info
                logger.info("Successfully saved token to backend")
            else:
                logger.error(f"Failed to save token to backend: {response.status_code}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Error saving token to backend: {e}")

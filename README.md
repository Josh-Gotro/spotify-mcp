# Spotify MCP for Claude Desktop

A Model Context Protocol (MCP) server that connects Claude Desktop with Spotify, allowing you to control playback, search for music, manage playlists, and more through natural conversation.

## Features

- Start, pause, and skip playback
- Search for tracks, albums, artists, and playlists
- Get detailed info about any Spotify item
- Manage the playback queue
- Create and manage playlists

## Prerequisites

- Windows 10/11
- [Claude Desktop](https://claude.ai/download) installed
- Spotify Premium account (required for playback controls)
- Spotify open and playing on a device

## Installation

### 1. Install uv (Python package manager)

Open PowerShell and run:

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

Close and reopen PowerShell, then verify:

```powershell
uv --version
```

### 2. Clone the repository

```powershell
git clone https://github.com/Josh-Gotro/spotify-mcp.git
cd spotify-mcp
```

### 3. Install dependencies

```powershell
uv sync
```

This will create a virtual environment and install all required packages.

## Configuration

### 1. Get your Spotify API credentials

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in and click **Create App**
3. Fill in the app details:
   - App name: Choose any name
   - Redirect URI: Add your callback URL (e.g., `https://your-domain.com/spotify/callback`)
4. Click **Settings** on your app to find your **Client ID** and **Client Secret**

### 2. Configure Claude Desktop

Open your Claude Desktop config file:

```
%APPDATA%\Claude\claude_desktop_config.json
```

Add the following configuration (create the file if it doesn't exist):

```json
{
  "mcpServers": {
    "spotify": {
      "command": "C:\\Users\\YOUR_USERNAME\\.local\\bin\\uv.exe",
      "args": [
        "--directory",
        "C:\\path\\to\\spotify-mcp",
        "run",
        "spotify-mcp"
      ],
      "env": {
        "SPOTIFY_CLIENT_ID": "your_client_id_here",
        "SPOTIFY_CLIENT_SECRET": "your_client_secret_here",
        "SPOTIFY_REDIRECT_URI": "your_redirect_uri_here",
        "SPOTIFY_BACKEND_URL": "your_backend_url_here"
      },
      "alwaysAllow": [
        "SpotifyPlayback",
        "SpotifySearch",
        "SpotifyQueue",
        "SpotifyGetInfo",
        "SpotifyPlaylist"
      ]
    }
  }
}
```

**Update these values:**

| Variable | Where to find it |
|----------|------------------|
| `YOUR_USERNAME` | Your Windows username |
| `C:\\path\\to\\spotify-mcp` | Path where you cloned the repo (use double backslashes) |
| `SPOTIFY_CLIENT_ID` | From your Spotify Developer Dashboard app settings |
| `SPOTIFY_CLIENT_SECRET` | From your Spotify Developer Dashboard app settings |
| `SPOTIFY_REDIRECT_URI` | The redirect URI you configured in your Spotify app |
| `SPOTIFY_BACKEND_URL` | Your backend server URL that handles token storage |

### 3. Authenticate with Spotify

Navigate to your authentication page and connect your Spotify account. This stores your authentication tokens in the backend database that the MCP server can access.

### 4. Restart Claude Desktop

1. Fully quit Claude Desktop (right-click the system tray icon → Quit)
2. Reopen Claude Desktop
3. Start a new chat

## Usage

Once configured, you can ask Claude things like:

- "What song is currently playing?"
- "Play some jazz music"
- "Search for songs by The Beatles"
- "Skip to the next track"
- "Add this song to my queue"
- "Show me my playlists"
- "Create a new playlist called 'Road Trip'"

## Available Tools

| Tool | Description |
|------|-------------|
| `SpotifyPlayback` | Get current track, start/pause/skip playback |
| `SpotifySearch` | Search for tracks, albums, artists, playlists |
| `SpotifyQueue` | View queue or add tracks to queue |
| `SpotifyGetInfo` | Get detailed info about any Spotify item |
| `SpotifyPlaylist` | List, create, and manage playlists |

## Troubleshooting

### "No active device" error

Make sure Spotify is open and actively playing (or recently played) on one of your devices.

### MCP not loading

1. Check that the paths in your config are correct
2. Verify uv is installed: `uv --version`
3. Check Claude Desktop logs at: `%APPDATA%\Claude\logs\mcp.log`

### Authentication issues

1. Re-authenticate via your authentication page
2. Verify token exists by checking your backend's token endpoint
3. Restart Claude Desktop after re-authenticating

### Token expired

Tokens expire after 1 hour. If you get auth errors, re-authenticate via your authentication page.

## Architecture

This fork uses a remote token storage system:

1. **Web Authentication**: OAuth flow stores tokens in a backend database
2. **Remote Cache Handler**: The MCP server fetches tokens from the backend instead of local files
3. **Shared Auth**: Multiple computers can share the same Spotify authentication

## Setting Up Your Own Backend

To use this MCP, you need a backend that provides these endpoints:

- `GET /spotify/mcp-token` - Returns stored tokens in spotipy format
- `POST /spotify/mcp-token` - Stores access_token, refresh_token, and expires_in
- `POST /spotify/token` - Exchanges authorization code for tokens

See the original [spotify-mcp](https://github.com/varunneal/spotify-mcp) project for a simpler local-only setup that doesn't require a backend.

## Credits

- Original project by [Varun Srivastava](https://github.com/varunneal/spotify-mcp)
- Built on [spotipy](https://github.com/spotipy-dev/spotipy) and the [Model Context Protocol](https://modelcontextprotocol.io/)

## License

MIT

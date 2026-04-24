# SkyRoom

SkyRoom is a soft pastel multiplayer room on Python.
It is a tiny social space with airy colors, glossy UI, floating clouds, little emotes, chat bubbles, local hosting, online browser flow, and a separate remote server mode for VPS deploys.

The vibe is simple:

- light
- clean
- a little dreamy
- a little mmm cute
- still real client-server code underneath

## What It Is

SkyRoom is built as a small 2D multiplayer social-space:

- desktop client on `pygame`
- authoritative game server on `asyncio`
- simple TCP JSON-line protocol
- local launcher with `Online` / `Offline`
- remote server variant for VPS
- external Cloudflare backend used only through HTTP endpoint calls

Players can:

- move with `WASD`
- click-to-walk
- turn toward the cursor
- glow
- handshake
- send short chat bubbles
- open right-click action menus in-game

## Current Mood Of The Project

This project is not trying to be a giant MMO or a heavy platform.
It is more like:

- a tiny shared room
- soft colors
- smooth little interactions
- fast local testing
- easy move from localhost to real hosting

The map is intentionally airy:

- pastel lakes
- glass gardens
- flower ribbons
- crystal towers
- cloud decks
- mint / pearl / halo style naming

## Main Parts

```text
oopServerClientProject/
|- client.py
|- server.py
|- launcher.py
|- README.md
|- servers.json
|- server_browser_state.json
|- skyroom/
|  |- config.py
|  |- models.py
|  |- protocol.py
|  |- world.py
|  |- server/
|  |  `- app.py
|  `- client/
|     |- app.py
|     |- launcher.py
|     |- network.py
|     |- endpoint.py
|     |- rendering.py
|     |- servers.py
|     |- debug.py
|     `- state.py
`- skyroom_remote_server/
   |- server.py
   |- app.py
   |- config.py
   |- endpoint.py
   |- protocol.py
   |- models.py
   |- world.py
   `- README.md
```

## How It Works

### Client

The client renders the world, sends player actions, receives snapshots and socket events, and keeps the whole thing smooth on screen.

Main things inside the client:

- login scene
- world scene
- chat input
- right-click action menu
- debug console on `Ctrl + D`
- online browser with health checks and endpoint list

### Game Server

The game server owns the world state:

- player positions
- collisions
- map obstacles
- glow timing
- handshake timing
- chat bubble timing

The client does not decide the truth of the room.
The server does.

### Remote Server

The remote server is the VPS/headless variant.
It keeps the same gameplay logic, exposes `/health` on a separate HTTP port, and can report itself to the external backend.

More details for that part live here:

- `skyroom_remote_server/README.md`

## Network Pieces

### TCP game connection

Gameplay uses a plain TCP socket with newline-delimited JSON.

Examples:

- `hello`
- `move`
- `click_move`
- `turn`
- `toggle_glow`
- `chat`
- `handshake`

Server responses include:

- `welcome`
- `snapshot`
- `system`
- event packets like `chat`, `glow`, `handshake`

### HTTP backend

The Python repo is only a client of the external backend.
It does not implement the backend inside this repo.

Current endpoint flow includes:

- `GET /servers`
- `POST /player-join`
- `POST /entry`

### Health checks

Health checks stay local and simple:

- game socket on `8765`
- `/health` HTTP on `8080`

The launcher uses `/health` to show status, ping, and online count for visible servers.

## Online / Offline Flow

### Offline

Offline is the cozy localhost mode.

When the app opens:

- local server starts in the background
- localhost appears at the top of the Online list
- it is marked delicately as `localhost`

When you open Offline:

- local server is used directly
- local client opens against `127.0.0.1`

### Online

Online mixes three sources cleanly:

1. localhost card pinned at the top
2. endpoint servers from `GET /servers`
3. locally saved servers from `servers.json`

Then visible servers get local `/health` checks for:

- online/offline state
- ping
- online count

`Refresh All` only refreshes the visible cards locally.
It does not fetch a new endpoint list.

## Files You May Notice

### `servers.json`

This is your saved server list.

It stores entries like:

- name
- host
- port

### `server_browser_state.json`

This is browser memory, not the actual server list.

It stores things like:

- which endpoint servers were already seen

This is used for the pastel yellow new-dot logic.

## In-Game Controls

### Main world

- `WASD` or arrows: move
- left click: click-to-walk
- `Enter`: chat
- `Q`: glow
- `E`: nearest handshake
- right click: action menu
- `Ctrl + D`: debug console

### Right-click menu

On empty space:

- `Chat`
- `Glow`

On another player:

- `Chat @nick`
- `Glow`
- `Handshake`

`Chat @nick` inserts a gentle tag prefix into the chat input.
`Handshake` walks toward that player and triggers the emote when close enough.

## Install

```bash
python -m pip install -r requirements.txt
```

## Run

### Launcher

```bash
python launcher.py
```

This is the nicest everyday entrypoint.

### Server

```bash
python server.py
```

### Client

```bash
python client.py
```

## Environment

The main local values are:

```env
SKYROOM_HOST=127.0.0.1
SKYROOM_PORT=8765
SKYROOM_HEALTH_PORT=8080
SKYROOM_SERVER_NAME=Local Skyroom
SKYROOM_ENDPOINT_BASE_URL=https://api.skyroom1337.workers.dev
```

You can override them before launch.

Example in PowerShell:

```powershell
$env:SKYROOM_HOST = "127.0.0.1"
$env:SKYROOM_PORT = "8765"
python server.py
```

## Debug Console

The debug console is meant to show real traffic, not fantasy logs.

It focuses on:

- `SOCKET`
- `ENDPOINT`
- `SERVER`
- `LOCALHOST`

It shows direction and payloads cleanly, while filtering movement spam.

## Design Notes

SkyRoom is intentionally not neutral gray software.
The code and visuals lean toward:

- pastel tones
- glossy edges
- soft highlights
- airy spacing
- little floating-room energy

So if something feels a bit mint, pearl, halo, blush, glass, ribbon, or lagoon coded:
yes, that is on purpose.

## Short Version

SkyRoom is a small multiplayer room with:

- pretty pastel visuals
- real client-server logic
- localhost-first flow
- online server browser
- VPS-ready remote server mode
- tiny social interactions instead of heavy systems

Soft outside, solid inside.

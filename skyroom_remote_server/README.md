# Skyroom Remote Server

Headless deployment package for running the Skyroom game server on a VPS or any other remote machine.

It does not depend on `pygame`.

## What it does

- runs the multiplayer TCP game server on port `8765`
- serves `GET /health` on a separate HTTP port `8080`
- sends `POST /check-up` to the external backend on startup
- sends `POST /check-up` again on a periodic timer
- keeps running even if the backend is unavailable

## Backend model

This package treats Cloudflare as an external backend service.

- `POST /check-up` announces the server
- `GET /health` stays local to the server and is used for UI, ping and manual checks
- backend failures must not stop the game server

## Files

- `server.py` - entry point
- `app.py` - async game server lifecycle
- `endpoint.py` - external `/check-up` client
- `config.py` - env-based configuration
- `models.py`, `world.py`, `protocol.py` - server core
- `.env.example` - example environment variables
- `requirements.txt` - no third-party runtime dependency

## Run

```bash
python server.py
```

Default ports:

- game TCP server: `8765`
- health HTTP server: `8080`

## Environment

- `SKYROOM_HOST`
- `SKYROOM_PORT`
- `SKYROOM_HEALTH_PORT`
- `SKYROOM_SERVER_NAME`
- `SKYROOM_PUBLIC_HOST`
- `SKYROOM_PUBLIC_PORT`
- `SKYROOM_ENDPOINT_BASE_URL`
- `SKYROOM_CHECKUP_INTERVAL`

Example:

```env
SKYROOM_HOST=0.0.0.0
SKYROOM_PORT=8765
SKYROOM_HEALTH_PORT=8080
SKYROOM_SERVER_NAME=My Skyroom Remote
SKYROOM_PUBLIC_HOST=203.0.113.20
SKYROOM_PUBLIC_PORT=8765
SKYROOM_ENDPOINT_BASE_URL=https://api.skyroom1337.workers.dev
SKYROOM_CHECKUP_INTERVAL=180
```

## /health

The health endpoint is served separately from the game port:

```text
http://<server_host>:8080/health
```

Example response:

```json
{
  "status": true,
  "server_name": "My Skyroom Remote",
  "server_host": "203.0.113.20",
  "server_port": 8765,
  "online": 3
}
```

## /check-up payload

When `SKYROOM_ENDPOINT_BASE_URL` is set, the remote server sends:

```json
{
  "server_name": "My Skyroom Remote",
  "server_host": "203.0.113.20",
  "server_port": 8765
}
```

The first request is sent on startup, then repeated every `SKYROOM_CHECKUP_INTERVAL` seconds.

## VPS deploy notes

Typical deployment flow:

1. Copy the `skyroom_remote_server` folder to the VPS.
2. Create a `.env` file from `.env.example`.
3. Set `SKYROOM_PUBLIC_HOST` to the public IP or domain of the VPS.
4. Open port `8765` for the game server.
5. Open port `8080` for local health checks if needed.
6. Run `python server.py` under your preferred process manager.

If the backend is down, `/check-up` errors are logged softly and the game server keeps running.

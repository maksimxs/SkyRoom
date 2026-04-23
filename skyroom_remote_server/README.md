# Skyroom Remote Server

This folder is a standalone headless deployment package for running the Skyroom server on a remote machine.

It does not depend on `pygame`.

## What it does

- Runs the multiplayer Skyroom server
- Responds to lightweight `ping` checks from the client
- Exposes `GET /health` on a separate HTTP port
- Calls the external endpoint `POST /check-up` on startup
- Can call `POST /check-up` again after successful player joins

## Important note about GitHub Pages

GitHub Pages is static hosting. It cannot directly accept live `POST` requests from a running server.

That means auto-registering new servers into a GitHub Pages server list requires an intermediate writable layer, for example:

- a small API service
- a webhook receiver
- a serverless function
- a GitHub Action trigger that updates JSON in the repo

This package is prepared for that future step via `SKYROOM_ENDPOINT_BASE_URL`.

## Files

- `server.py` - entry point
- `app.py` - async game server and lifecycle
- `endpoint.py` - `/check-up` integration
- `config.py` - env-based config
- `models.py`, `world.py`, `protocol.py` - server core
- `requirements.txt` - no third-party runtime dependency
- `.env.example` - example environment variables

## Run

```bash
python server.py
```

By default:

- game server: `8765`
- health endpoint: `8080`

## Environment

Core server settings:

- `SKYROOM_HOST`
- `SKYROOM_PORT`
- `SKYROOM_HEALTH_PORT`
- `SKYROOM_TICK_RATE`
- `SKYROOM_PLAYER_SPEED`

Remote endpoint settings:

- `SKYROOM_SERVER_NAME`
- `SKYROOM_PUBLIC_HOST`
- `SKYROOM_PUBLIC_PORT`
- `SKYROOM_ENDPOINT_BASE_URL`

## /health response

The health endpoint is now served on:

```text
http://<server_host>:8080/health
```

```json
{
  "status": true,
  "server_name": "My Skyroom Remote",
  "server_host": "203.0.113.20",
  "server_port": 8765,
  "online": 3
}
```

Backend or worker health-check URL example:

```text
http://213.108.4.34:8080/health
```

## /check-up payload

When `SKYROOM_ENDPOINT_BASE_URL` is set, the server sends JSON like:

```json
{
  "server_name": "My Skyroom Remote",
  "server_host": "203.0.113.20",
  "server_port": 8765
}
```

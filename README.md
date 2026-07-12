# Camzilla

Camzilla is a self-hosted camera viewer with pluggable object detection. Phase 1
is a single-camera, trusted-LAN-only vertical slice: WebRTC viewing via `go2rtc`,
browser-rendered detection metadata, and x86 CPU/CUDA development inference.
Supported Orange Pi/RKNN deployment, PTZ, alerts, recording, persistence,
multi-camera operation, and authentication begin in later phases.

## Prerequisites

- Docker Engine with Docker Compose v2 (validated with Compose v5)
- Node.js 24/npm for frontend checks
- Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/) for backend checks
- A current Chromium, Firefox, or Safari browser for WebRTC smoke tests

## Configuration and security

Copy `.env.example` to an ignored `.env` and set `CAMZILLA_CAMERA_RTSP_URL`.
Never commit it. `CAMZILLA_BIND_HOST` defaults to `127.0.0.1`; use `0.0.0.0`
only on a trusted LAN. Phase 1 has no authentication, so LAN exposure permits
any network peer to use the viewer. The `go2rtc` administrative API is internal
only, and camera URLs are not returned by the API.

Check configuration without printing values:

```sh
cd backend
uv run python -m app.cli
```

## Development

Start the live-reload stack (Vite HMR and FastAPI reload):

```sh
docker compose --env-file .env -f compose.yaml -f compose.dev.yaml up --build
```

Ordinary edits under `frontend/` and `backend/app/` synchronize without a
rebuild. Rebuild after Dockerfile, dependency/lockfile, native dependency, or
model-manifest changes. Target logs with `docker compose logs -f api`,
`frontend`, or `go2rtc`; stop with `docker compose down`.

## Production-like x86 startup

The base Compose file uses immutable images, non-root app images where supported,
health checks, restart policies, read-only filesystems where practical, and no
source mounts or reloaders:

```sh
docker compose --env-file .env up --build -d
docker compose ps
curl http://127.0.0.1:8000/health/ready
```

This validates x86 packaging and CPU/CUDA operation. Orange Pi/RKNN is a Phase 2
deliverable, not a supported Phase 1 production target.

## Checks

These commands are CI-safe and use no camera or secret:

```sh
(cd backend && uv run pytest && uv run ruff check .)
(cd frontend && npm install && npm run lint && npm run typecheck && npm test && npm run build)
docker compose config
```

Live-camera, CUDA, and eventual RKNN checks are opt-in hardware smoke tests;
they must skip cleanly when unavailable and must not retain frames. If the API
is healthy but video cannot connect, verify the camera configuration and local
network/firewall, then use the documented HLS/MJPEG diagnostic fallback once it
is enabled. Do not paste camera URLs or credentials into issues or logs.

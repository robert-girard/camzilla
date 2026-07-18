# Camzilla

Camzilla is a self-hosted camera viewer with pluggable object detection. Phase 1
is a single-camera, trusted-LAN-only vertical slice: WebRTC viewing via `go2rtc`,
browser-rendered detection metadata, and x86 CPU/CUDA development inference.
PTZ, alerts, persistence, multi-camera operation, and authentication are built
and validated locally on x86 first. Supported Orange Pi/RKNN deployment follows
authentication in Phase 4b.

## Prerequisites

- Docker Engine with Docker Compose v2 (validated with Compose v5)
- Node.js 24/npm for frontend checks
- Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/) for backend checks
- A current Chromium, Firefox, or Safari browser for WebRTC smoke tests

## Configuration and security

No `.env` is required for the synthetic fake development mode. To use a physical
camera, copy `.env.example` to an ignored `.env`, replace its neutral camera URL,
and never commit it. `CAMZILLA_BIND_HOST` defaults to `127.0.0.1`; use `0.0.0.0`
only on a trusted LAN. Phase 1 has no authentication, so LAN exposure permits any
network peer to use the viewer. The `go2rtc` administrative API is internal only,
and camera URLs are not returned by the API.

For real YOLO inference, choose `yolov8n`, `yolov8s`, `yolov8m`, `yolo11n`,
`yolo11s`, or `yolo11m`. Nano is fastest and medium is the most resource-heavy;
`yolov8n` remains the default. Download a recorded upstream artifact and verify
its checksum in one step, then select it in `.env`:

```sh
python3 scripts/download-model.py yolo11s
# .env
CAMZILLA_INFERENCE_BACKEND=ultralytics
CAMZILLA_MODEL_ID=yolo11s
```

The managed path is `/models/<model-id>.pt`; `CAMZILLA_MODEL_PATH` is available
only when an explicit verified path is needed. Use `uv sync --extra ultralytics`
for a host-side backend run. The Compose image includes that optional runtime.
Inference reads only the local
`CAMZILLA_INFERENCE_RESTREAM_URL` from `go2rtc`; it does not open another
physical-camera connection.

### Runtime inference selection

The camera page lists the model/target combinations verified by the API. CPU,
GPU, NPU, and TPU are stable target categories, but only installed,
checksum-verified artifacts with a healthy runtime can be selected. The local
x86 implementation supports all six managed weights on CPU and enables their
GPU choices only when CUDA is available. RKNN NPU is delivered in post-auth
Phase 4b; TPU remains unavailable until a concrete adapter is implemented.

Choose one available combination and use **Apply inference selection**. Video
remains independent while the candidate model loads and warms. Detection intake
pauses, stale results are cleared, and the old backend remains active if the
switch fails. A successful response updates health, diagnostics, and detection
metadata with the confirmed model and target. The choice is global and
runtime-only through Phase 2: restarting the API restores the `.env` default.
The browser never accepts a model path, remote URL, or arbitrary backend name.

The same allowlisted operation can be inspected or exercised locally through
the typed API without displaying paths or secrets:

```sh
curl --fail http://127.0.0.1:8000/api/v1/inference
curl --fail --request PUT \
  --header 'content-type: application/json' \
  --data '{"capability_id":"ultralytics:yolo11s:cpu"}' \
  http://127.0.0.1:8000/api/v1/inference/selection
```

If a model is reported as not installed, run
`python3 scripts/download-model.py <model-id>` on the host and restart the API
so startup re-verifies the manifest checksum. An unavailable GPU indicates that
the server has not verified a CUDA device/runtime; Camzilla does not silently
downgrade a browser-requested GPU switch to CPU.

### Optional PTZ controls

PTZ is disabled by default. The API and browser controls remain unavailable
until `CAMZILLA_PTZ_ENABLED=true`, the ONVIF host, port, profile, username, and
password are configured in the ignored `.env`, and
`CAMZILLA_PTZ_VERIFIED=true` records that this exact camera/profile combination
has already passed an attended movement check. Credentials stay server-side.

Every button press sends one server-bounded timed `ContinuousMove` command at a
conservative fixed speed and duration. Camzilla does not send `Stop`, because
the first verified camera does not implement it. The server rejects commands
outside its speed/duration limits and throttles overlapping or rapid presses.

Before setting the verification flag for a physical camera, perform this
attended checklist:

1. Ensure someone can see the camera, its wiring, and the full movement area;
   remove obstructions and stop any unattended PTZ scripts.
2. Confirm the configured ONVIF profile belongs to the intended camera without
   displaying or logging credentials.
3. Send exactly one 1-second movement at speed 0.1 in a safe direction, then
   wait at least two seconds and inspect the result.
4. If needed, send one short opposite-direction command to restore the view.
   Do not loop commands and do not use the unsupported `Stop` action.
5. Set `CAMZILLA_PTZ_VERIFIED=true` only after the attended check succeeds.
   Set it back to `false` whenever the camera, profile, or mounting changes.

To run the optional real-model contract check, download the verified weight
listed in `models/manifest.yaml` and use a redistributable fixture image:

```sh
cd backend
CAMZILLA_ULTRALYTICS_MODEL_PATH=../models/yolo11s.pt \
CAMZILLA_ULTRALYTICS_FIXTURE_PATH=/path/to/public-fixture.jpg \
uv run --extra ultralytics pytest tests/test_ultralytics_contract.py
```

With the Compose stack and real camera already running, an explicit local-only
smoke check reads one in-memory frame from the **local go2rtc restream** and
retains nothing:

```sh
cd backend
CAMZILLA_HARDWARE_SMOKE=1 \
CAMZILLA_INFERENCE_RESTREAM_URL=rtsp://127.0.0.1:8554/front-door \
uv run --extra ultralytics pytest tests/test_live_camera_smoke.py
```

Check synthetic-development configuration, or explicitly require the physical
camera variables, without printing values:

```sh
cd backend
uv run python -m app.cli
uv run --env-file ../.env python -m app.cli --camera
```

## Development

Start the live-reload stack (Vite HMR and FastAPI reload):

```sh
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

This clean-clone command starts synthetic frames and deterministic fake person
detections. If `.env` exists, Compose loads the configured camera and inference
settings automatically. Ordinary edits under `frontend/` and `backend/app/`
synchronize without a rebuild. Rebuild after a Dockerfile, dependency/lockfile,
native dependency, or model-manifest change. Target one service with, for example,
`docker compose -f compose.yaml -f compose.dev.yaml logs -f api` (or `frontend`
or `go2rtc`). Stop with:

```sh
docker compose -f compose.yaml -f compose.dev.yaml down
```

## Production-like x86 startup

The base Compose file uses immutable images, non-root app images where supported,
health checks, restart policies, read-only filesystems where practical, and no
source mounts or reloaders:

```sh
docker compose --env-file .env up --build -d
docker compose ps
curl http://127.0.0.1:8000/health/ready
```

This validates the local-first x86 packaging and CPU/CUDA operation used through
Phase 4. Orange Pi/RKNN is a post-auth Phase 4b deliverable, not a currently
supported production target.

## Checks

These commands are CI-safe and use no camera or secret:

```sh
(cd backend && uv run mypy app && uv run pytest && uv run ruff check .)
(cd frontend && npm ci && npm run lint && npm run typecheck && npm test && npm run build)
(cd frontend && npx playwright install chromium && npm run test:e2e)
docker compose config
docker compose -f compose.yaml -f compose.dev.yaml up --build -d --wait
curl --fail http://127.0.0.1:8000/health/ready
curl --fail http://127.0.0.1:5173/
docker compose -f compose.yaml -f compose.dev.yaml down
```

Live-camera, CUDA, and eventual RKNN checks are opt-in hardware smoke tests;
they must skip cleanly when unavailable and must not retain frames. If the API
is healthy but WebRTC cannot connect, verify the camera configuration and local
network/firewall, then use the page’s **Open HLS diagnostic fallback** link.
That link proxies only the diagnostic stream through the API; it never exposes
the `go2rtc` administrative endpoint or camera URL. Do not paste camera URLs or
credentials into issues or logs.

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
metadata with the confirmed model and target. The choice is global and is
persisted with the Phase 3 configuration; the `.env` model remains the safe
bootstrap fallback when no compatible persisted choice can be restored.
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

### Detection categories

Each installed model exposes a versioned class catalog. The configuration panel
uses that catalog for searchable per-camera and per-alert-rule selectors;
`coco:person` is the safe default. Display labels such as `person` and numeric
model class indices are not persisted as cross-model identity. Use semantic IDs
for environment defaults, for example:

```sh
CAMZILLA_ALLOWED_CLASSES=coco:person,coco:car
CAMZILLA_ALERT_CLASSES=coco:person
```

A camera filters detection publication, overlays, category metrics, retained
event media, and alert evaluation to its saved allowlist. Alert-rule targets
must be a subset of that camera's selection. Before applying a model change,
the UI previews any semantic IDs missing from the target catalog and names the
affected cameras and rules. Camzilla does not silently remove, broaden, rename,
or substitute a category.

The typed category endpoints are:

```sh
curl --fail http://127.0.0.1:8000/api/v1/cameras/front-door/categories
curl --fail http://127.0.0.1:8000/api/v1/inference/compatibility/ultralytics:yolo11s:cpu
```

Saving categories requires the exact returned catalog revision and current
configuration version. The deterministic `fake-multi-v1` development model
provides person, car, and dog fixtures so the full selection and conflict flow
can be tested without a camera or ML runtime. Historical events retain both
semantic IDs and their catalog revision; if a catalog is no longer installed,
the UI displays the stable ID instead of guessing a replacement label.

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

### Alert delivery safety

The Phase 2 person rule is enabled by default but uses the `dry-run` notifier,
so qualifying detections exercise debounce, snapshot rendering, and status
accounting without making an external request. Inspect its redacted state at
`http://127.0.0.1:8000/api/v1/alerts/status`. Snapshots exist only in the
bounded delivery queue and are released after evaluation; Phase 2 does not
write them to disk.

Real Discord delivery requires all three settings in the ignored `.env`:

```sh
CAMZILLA_NOTIFIER=discord
CAMZILLA_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/REPLACE/REPLACE
CAMZILLA_DISCORD_DELIVERY_CONFIRMED=true
```

Without a valid HTTPS Discord webhook and the explicit confirmation flag, the
API safely falls back to dry-run and reports why without returning the URL.
Discord requests use bounded timeouts, retries, and rate-limit backoff. Do not
paste webhook URLs into logs, tests, issues, or browser fields.

The API reconnects the local inference restream with bounded exponential
backoff and keeps consuming after an isolated inference failure. Stream-down
alerts fire once on transition and then no more than
`CAMZILLA_STREAM_DOWN_REPEAT_SECONDS`; recovery is reported once. The page's
**Alerts and reliability** panel polls the redacted health state so camera,
inference, and notifier degradation/recovery remain visible.

### Persistent configuration and history

Production Compose stores SQLite metadata in the `camzilla_data` volume and
media in the separate `camzilla_media` volume. Startup applies versioned
Alembic migrations before accepting requests. The database stores camera and
notifier secret references such as environment-variable names, never plaintext
credentials, webhook URLs, authenticated stream URLs, snapshots, or clips.
Keep the SQLite database and WAL on local storage, not NFS/SMB.

The global configuration has an optimistic version. A stale rule edit receives
HTTP 409 instead of overwriting a newer change. The active inference selection,
camera capability results, rule settings, and event metadata survive container
restart. Inspect migration state without exposing configuration values:

```sh
docker compose exec api alembic current
docker compose exec api alembic check
```

SQLite is the supported single-node store. A PostgreSQL repository becomes
appropriate only for multiple application instances, a shared/remote database,
or measured sustained write contention; changing the URL alone is not yet a
supported migration procedure.

Media persistence is enabled in production Compose and disabled in the
camera-free host test default. Detection events save an annotated JPEG and use
a bounded in-memory pre-roll ring to produce a configurable 5–30 second MP4.
`CAMZILLA_CLIP_PRE_ROLL_SECONDS` is part of that total duration. The history
table exposes snapshots and inline clip playback; deleting an event also
deletes its media. Manual recording uses **Start recording** / **Stop
recording** on the camera card and the same encoder and retention policy.

`CAMZILLA_MEDIA_QUOTA_BYTES` is a hard local quota. After each atomic media
write, Camzilla removes oldest media first and clears the corresponding
database references. An oversized write, full/unavailable filesystem, or
encoder failure is redacted and counted in health without terminating
inference or notification processing. Never copy the media volume into CI
artifacts; it may contain private camera imagery.

Additional camera definitions may be persisted with environment secret
references, and the UI renders each camera's independent runtime state. The
current physical runtime still starts one configured stream. Multi-camera
inference runs through a shared, size-one-per-camera round-robin scheduler: a
busy source can replace only its own stale frame and cannot starve a quieter
camera. Version-2 detection messages and metrics carry the camera ID, WebSocket clients
subscribe to the displayed camera, alert rules route by camera, and clip
pre-roll buffers remain camera-local. Deterministic two-source integration
coverage validates this path; a real second-camera smoke still waits for
hardware/configuration.

The configuration panel exports a versioned JSON backup and validates a local
JSON file before enabling restore. Exports contain camera/rule settings, the
active capability ID, category catalog revisions, and semantic category IDs,
but exclude secret values, secret references, transient
capability probes, events, and media. Restore uses the current optimistic
configuration version, preserves existing external-secret bindings, and gives
new cameras derived `env:` references that must be configured separately.
If a backup selects a different inference capability, Camzilla serializes model
warm-up and the configuration commit: a stale version never starts the switch,
and a failed warm-up leaves both the saved configuration and last healthy
runtime unchanged. An unloadable saved model at startup activates and persists
the configured bootstrap fallback while readiness reports a redacted degraded
state.
Current exports use backup schema version 2. Person-only version 1 backups are
migrated to semantic IDs and the active model's known catalog revision during
validation; incompatible or unknown catalogs are rejected rather than guessed.

The equivalent export and validation endpoints are
`GET /api/v1/backup` and `POST /api/v1/backup/validate`. Use the UI for restore
so validation and the current version are applied together. Even secret-free
exports reveal camera names and security rules; store them privately and do
not attach them to public issues or CI artifacts.

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

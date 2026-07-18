# Design Doc: Home Security Camera AI Alert System

## Document Role

This document records Camzilla's current technical direction: deployment targets, component boundaries, data flow, concurrency, technology choices, and cross-cutting constraints. Consult the [PRD](PRD-home-security-ai-alerts.md) for product intent, the [implementation plan](implementation-plan.md) for phase tasks/status and acceptance criteria, and the [first-camera notes](../cam_info/README.md) for device-specific facts. Update this document when a durable architecture decision changes; use an ADR for decisions whose alternatives and consequences need independent history.

## 1. Deployment Targets

- **Local-first application target (Phases 1–4):** x86, used for development and production-like operation while viewer, alerting, persistence, advanced configuration, and authentication mature. Inference runs on CPU or CUDA via standard Ultralytics.
- **Post-auth edge target (Phase 4b):** Orange Pi 5 (RK3588, Mali G610 GPU, ~6 TOPS NPU). The already-authenticated product migrates here and inference runs via RKNN on the NPU.
- **Design constraint:** the system should also be deployable on plain x86/CPU or Nvidia/CUDA setups for anyone without an Orange Pi — this is a first-class supported path, not just a dev convenience. This is why the inference backend is abstracted (see §3.3).
- **Future accelerator target:** TPU is a reserved capability category, not a selected implementation. A concrete hardware family, runtime, model format, and validation target must be accepted before a TPU adapter is advertised as available.

## 2. Tech Stack Summary

| Layer | Choice | Notes |
|---|---|---|
| Backend / API | **FastAPI** | Python-native, async, pairs naturally with Ultralytics/RKNN, auto-generated OpenAPI schema |
| Python package management | **uv** | |
| Frontend | **React**; Zustand only where justified | Prefer local/query state first; add a shared client store for genuinely cross-cutting UI state |
| Service/process model | **Compose service isolation + dedicated inference worker** | Explicit runtime startup; bounded latest-frame queue; no loaded-runtime `fork` assumption |
| Inference (post-auth edge) | **RKNN** (RK3588 NPU) | Phase 4b |
| Inference (local x86 / CPU / GPU) | **Ultralytics** (CPU or CUDA) | Phases 1–4 |
| Inference selection | **Capability API + transactional worker switch** | Phase 1b; only verified backend/model/target combinations are selectable |
| Video bridging (browser) | **WebRTC through `go2rtc`** | HLS/MJPEG is a diagnostic fallback; see §4 |
| Detection metadata | **Versioned backend WebSocket** | Timestamped normalized boxes rendered over video in the browser |
| Detection model | **YOLOv8/YOLO11 n/s/m in development; YOLOv8n default** | Orange Pi production selection remains measurement-driven; see §6 |
| Relational persistence | **SQLite + SQLAlchemy 2 + Alembic** | Phase 3; local single-node metadata/config/events, with a PostgreSQL migration path |
| Media persistence | **Filesystem with database references** | Snapshots/clips stay out of database blobs; retention owns lifecycle |
| Local orchestration | **Docker Compose development override/watch** | Vite HMR and FastAPI reload without ordinary source rebuilds |
| CI | **GitHub Actions** | Tests/checks/builds first; deployment pipelines deferred |

## 3. Core Architecture: Three Pluggable Abstractions

The system is built around three interfaces so that no single vendor, protocol, or hardware target is hard-baked into the core logic.

### 3.1 Camera Abstraction
- Base interface: stream access (connect, get frames/stream URL).
- Optional capability interfaces, implemented only where supported: PTZ control, IR/light toggle, ONVIF Profile G edge storage (recording control + playback).
- First implementation: ONVIF/RTSP.
- Capabilities are considered usable only after operation-level verification. The first camera advertises PTZ but requires short timed `ContinuousMove` calls because `Stop` and `GetStatus` are not implemented.

### 3.2 Notifier Abstraction
- Interface accepts a generic alert payload: required text + optional list of attachments (MIME type + data/reference).
- First implementation: Discord webhook.
- Future adapters (email, SMS, push) just need to handle the same payload shape, degrading gracefully if they don't support attachments.

### 3.3 Inference Backend Abstraction
- Lifecycle: load/warm up, detect, report health/identity, and close.
- Detection output: normalized bounding boxes, class, confidence, source dimensions, capture/result timestamps, and timing/backend/model metadata.
- Implementations: RKNN backend (Orange Pi NPU), Ultralytics CPU/CUDA backend (dev machine, generic x86/GPU deployments), and a future TPU adapter only after its concrete runtime is chosen and validated.
- Build and contract-test a deterministic fake before wiring real detection, then require every backend to pass the same contract suite.
- Each backend publishes a capability matrix of stable backend, model, target, and model-artifact IDs plus compatibility, availability, health, and redacted unavailability reasons. CPU, GPU, NPU, and TPU are target categories; the category alone never proves a usable runtime.
- Phase 1b switching is serialized and transactional. Intake pauses while a candidate worker loads and warms, the active reference changes only after success, stale queued/results are cleared, and the previous healthy worker is retained or restored on failure. Environment configuration remains the restart default until Phase 3 persists the shared selection.
- The browser may request only allowlisted capability IDs. It cannot supply model paths, remote URLs, runtime arguments, credentials, or arbitrary backend names.
- Each model artifact may publish a versioned object-detection class catalog. Phase 3b stores selections by verified semantic ID, maps them to model-native class IDs inside the adapter, and treats a changed or missing mapping as a configuration conflict rather than guessing from numeric indices or display labels.

### 3.4 Stream Fan-out and Application Boundary

- `go2rtc` owns one authenticated upstream RTSP connection to the physical camera and exposes internal restreams to the browser and frame sampler.
- FastAPI owns public application contracts, sanitized stream descriptors, health, and detection WebSockets. Camera URLs and `go2rtc` administrative APIs are never browser-facing.
- Viewer frames run at the available stream rate. The inference restream decoder is drained continuously while the sampler submits only the newest frame at its configured rate; decoder-discarded and queue-superseded frames are counted as drops so slow inference cannot increase latency invisibly.

## 4. Video Streaming to Browser

RTSP isn't natively playable in browsers, so a bridge is needed between the camera's RTSP stream and something browsers can render.

| Option | Latency | Complexity | Notes |
|---|---|---|---|
| **HLS** | Several seconds | Low | Chunks video over HTTP, plays via native `<video>` tag + minor JS. Fine for casual viewing, not ideal for real-time PTZ feedback. |
| **WebRTC** | Sub-second | Higher | Real-time, needed for responsive PTZ control. Requires signaling + STUN/TURN. |

**Decision:** use `go2rtc` for RTSP→WebRTC instead of building signaling/media bridging. Its administrative API remains internal and its configuration is generated from runtime secrets. HLS/MJPEG is retained only as a diagnostic fallback.

Detection boxes are not burned into the video. FastAPI sends versioned results over WebSocket; the React page renders them on a separate canvas/SVG overlay. Messages include normalized coordinates, source dimensions, sequence and capture/result timestamps. The client handles resizing/letterboxing, expires stale results, and reports result age. MVP synchronization is best-effort and must be measured rather than assumed.

## 5. Process Model & Concurrency

- FastAPI async tasks handle API/WebSocket I/O and orchestration; CPU/NPU-bound decode and inference must not block the event loop.
- Use an explicitly started inference service/worker with one loaded backend and a bounded input queue. Do not fork after loading CUDA or RKNN state, and do not assume a model copy per camera will scale on constrained hardware.
- Phase 1 begins with one camera and one inference worker. Multi-camera work adds a measured scheduler or configurable worker pool only after memory, decode, throughput, and fairness measurements.
- The frame sampler submits at a configured target rate. It must keep draining the source between samples rather than sleeping between decoder reads, because decoder-internal buffering would otherwise bypass latest-frame-wins semantics. A size-one or small bounded queue exposes processed, dropped, failed, and latency metrics.
- Service/process shutdown must close streams and runtimes explicitly. RKNN initialization/shutdown behavior is validated on the Orange Pi rather than inferred from x86 behavior.
- Runtime model/target changes use the same explicit lifecycle. A switch lock prevents concurrent workers from racing; video stays independent, while detection readiness reports the transition and resumes only after the new identity is confirmed.
- Alert evaluation is isolated from inference and notification I/O. Qualifying results enter a size-one bounded delivery queue after debounce; the queued frame is copied, annotated in memory, and released after delivery. Notifier timeout/retry/rate-limit failures update redacted status without terminating inference. Pre-auth Discord delivery requires both valid external secret configuration and an explicit confirmation flag; otherwise the rule runs through the dry-run adapter.
- Phase 3 multi-camera groundwork keeps a size-one latest-frame slot per camera and selects ready cameras round-robin through the shared inference worker. A high-rate source may replace only its own pending frame, so it cannot create an unbounded backlog or starve a quieter source. The default remains one worker until measured memory/throughput justifies a configurable pool.

## 6. Detection Model Notes

- **Development models:** Ultralytics YOLOv8 and YOLO11 detection weights in nano, small, and medium sizes are supported for the Phase 1 CPU/CUDA vertical slice; YOLOv8n remains the default.
  - Each managed weight has a pinned upstream URL and SHA-256 provenance record and is selected by model ID without changing application contracts.
  - Making all six weights available for development supports comparison but is not an Orange Pi deployment decision.
  - YOLOv8 currently has the more established RKNN tooling path for this project; Phase 4b benchmarks candidate generation, size, and input resolution before selecting the NPU artifact.
- **Selection rule:** choose model size and input resolution from measured accuracy, FPS, latency, memory, and thermal behavior on both development and target hardware. The initial 5–10 inference FPS goal does not require the viewer to run at the same rate.
- **Operator selection:** Phase 1b exposes only installed and compatible combinations. Ultralytics CPU is the baseline; CUDA, RKNN NPU, and future TPU choices become enabled only after runtime and model-artifact health checks pass.
- **Detection categories:** Phase 3b optionally exposes the active artifact's class catalog for per-camera and per-alert-rule multi-selection. These are object-detection classes with bounding boxes, not image-classification categories. Filtering and alert evaluation use stable semantic IDs, while adapters own model-native index mapping.
- **Package/parcel detection:** COCO pretraining does not include a generic "package" class. Plan is to fine-tune a nano/small YOLO model using a labeled dataset (Ultralytics' package segmentation dataset, and/or a Roboflow community dataset) — no adequate pretrained package-specific model found on Hugging Face at time of research. Training workflow is a separate task to scope later.
- **Detection type:** standard object detection (bounding boxes + class + confidence), not segmentation — sufficient for zone/overlap-based alert logic (e.g. person+parcel proximity) at lower compute cost than pixel-mask segmentation.
- **Licensing:** Ultralytics is accepted under AGPL-3.0 for the MVP. The repository must add the compatible project license and attribution before adding the dependency. Record license/source/checksum provenance independently for code, weights, datasets, calibration inputs, and generated RKNN artifacts.

## 7. Model Loading / NPU Memory Behavior (background)

The RK3588 NPU doesn't hold model weights persistently on-chip — it has small internal caches/buffers only. The RKNN runtime loads the compiled model into system RAM, and the NPU driver DMAs weights/activations from RAM into the NPU as it processes each layer. This means system RAM (and its bandwidth) is a real factor in NPU inference performance, not just raw NPU TOPS.

## 8. Discovery Spikes

- **Deferred to implementation Phase 5:** confirm whether the physical camera supports ONVIF **Profile G** (recording control + SD card playback) vs. only Profile S, and whether that access can coexist with its existing vendor application.
- Query and measure both known ONVIF media profiles. The main stream is known to be 2304x1296 H.264; determine whether `PROFILE_001` is a more efficient inference source while keeping the main stream for viewing.
- Validate the chosen `go2rtc` release/configuration with the physical H.264/PCMU stream, supported browsers, internal-only API restrictions, reconnection, and one-upstream fan-out.

## 9. Development, Deployment, Security, and CI

- Shared Compose service definitions describe the production-like topology. A development override/watch configuration syncs source into containers, runs Vite HMR and FastAPI/Uvicorn reload, and rebuilds only for dependency/container changes. Production uses immutable images, no source mounts/reloaders, health checks, and explicit restart policy.
- Phase 1 creates a root `README.md` as the developer/operator entry point. It documents live-reload development, production-like x86 operation, configuration/security, tests, health, troubleshooting, and that supported Orange Pi/RKNN deployment begins only in post-auth Phase 4b.
- Pre-auth phases bind application endpoints to loopback by default; trusted-LAN exposure is explicit. `go2rtc` administration remains internal. Authenticated RTSP URLs and secrets are redacted from logs, errors, health, metrics, browser payloads, and CI artifacts.
- GitHub Actions runs backend lint/type/tests, frontend lint/type/tests/build, deterministic Playwright flows, secret/privacy checks, Compose validation, and amd64 builds. Physical camera, CUDA, and RKNN tests are opt-in or later self-hosted jobs and skip cleanly when hardware is absent.
- Real captures, recordings, home-derived calibration images, generated credential-bearing configuration, databases, and large model artifacts are never committed. CI uses synthetic or explicitly redistributable fixtures.

### 9.1 Persistence Direction

- Phase 3 stores cameras, verified capabilities, alert rules, event metadata, configuration versions, and secret references in SQLite on local x86-host storage through SQLAlchemy 2 and Alembic migrations. Phase 4b migrates and validates that state on local Orange Pi storage after authentication is complete.
- Snapshots and clips are filesystem objects with database metadata/references. Retention coordinates deletion of both; media is not stored as database blobs.
- Plaintext credentials and authenticated camera/notifier URLs are not persisted. Database rows refer to environment/external secret identifiers.
- Keep transaction and repository boundaries portable to PostgreSQL. PostgreSQL becomes appropriate for multiple application instances, a remote/shared database, or sustained concurrent-write pressure; it is not required for the initial single-node deployment.
- Do not place SQLite database/WAL files on a network filesystem. Backup/restore and disk-full behavior require integration tests before persistence is considered complete.

## 10. Implementation Sequence

The [implementation plan](implementation-plan.md) is authoritative for task status and exit criteria:

1. **Phase 1:** Compose development workflow, one-camera WebRTC viewer, fake then Ultralytics backend, timestamped WebSocket detections, browser bounding-box overlay, tests, and GitHub Actions.
2. **Phase 1b:** capability-driven model and CPU/GPU/NPU/TPU target selection UI, with transactional switching and unsupported-target explanations.
3. **Phase 2:** local x86 Tripwire completion with bounded PTZ, Discord snapshot alerts, reconnect/health behavior, and sustained CPU/CUDA operation.
4. **Phase 3:** persistence/history, zones/schedules, clips/retention, configuration/versioning, and multi-camera groundwork—all before auth.
5. **Phase 3b (optional stretch):** model-provided detection-category selection per camera and alert rule, with cross-model compatibility handling.
6. **Phase 4:** Keycloak, backend authorization, role boundaries, WebSocket/media protection, and concurrent-edit handling.
7. **Phase 4b:** authenticated migration to Orange Pi, RKNN parity and NPU selection, ARM64 packaging, hardware validation, and rollback.

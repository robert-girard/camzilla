# Camzilla Implementation Plan

Status: Phase 3 in progress; Phase 2 implementation complete with attended PTZ and live Discord checks explicitly deferred (Phase 1b GitHub Actions confirmation remains pending)
Last updated: 2026-07-17
Primary product source: [PRD](PRD-home-security-ai-alerts.md)

## Document Role and References

This is the executable roadmap and status tracker. Consult the [PRD](PRD-home-security-ai-alerts.md) for product requirements, the [design document](design-doc-home-security-ai-alerts.md) for current architecture, and the [first-camera notes](../cam_info/README.md) for device-specific behavior. Update this file during implementation; update the PRD or design in the same change when an accepted implementation decision alters product scope or durable architecture.

## How to use this plan

- `[ ]` not started, `[~]` in progress, `[x]` complete, `[!]` blocked.
- Update task state in the same change that produces or verifies the work.
- A phase is complete only when all required tasks and exit criteria are complete. Tasks explicitly marked optional do not block completion.
- Add discoveries beneath the phase they affect. Put cross-cutting decisions in the decision log and meaningful design changes in ADRs.
- Phase 1 is complete. Phase 1b is the next intended `/goal`; do not pull PTZ, alerts, recording, persistence, or authentication into it.
- Mark work `[~]` when it begins and `[x]` only after implementation and validation. Use `[!]` with an unblock condition for genuine blockers.
- Split partially completed compound tasks instead of marking them complete. Preserve completed tasks and commit status updates with their implementation/tests.
- Update `Last updated` whenever task state, phase scope, decisions, or exit criteria materially change.

## Confirmed decisions

- Phase 1 is a single-camera live viewer with pluggable inference and browser-rendered detection boxes. PTZ and Discord alerts begin in Phase 2.
- Per the 2026-07-17 local-first direction, Orange Pi image production, RKNN conversion/runtime work, data migration, and device deployment are deferred to post-auth Phase 4b and do not block Phases 1 through 4.
- Browser video uses `go2rtc` WebRTC. Detection metadata travels separately over a backend WebSocket and is rendered on a canvas overlay. HLS/MJPEG is diagnostic fallback only.
- Docker Compose is used for development and deployment. Development uses Vite HMR, FastAPI reload, source sync/bind mounts, and dependency-triggered rebuilds.
- GitHub Actions provides CI for tests, checks, and builds. Deployment automation is deferred.
- The development MVP uses Ultralytics and supports the COCO detection weights for YOLOv8 and YOLO11 in nano, small, and medium sizes under AGPL-3.0; YOLOv8n remains the low-cost default. Keep inference pluggable to preserve a future replacement/enterprise-license path. Orange Pi/RKNN model selection remains a Phase 4b benchmark decision.
- Phase 1b adds a browser UI and API for selecting a compatible model and inference target. The server is authoritative for the capability matrix: CPU, GPU, NPU, and TPU are stable target categories, but only installed, verified, healthy backend/model combinations are selectable. Phase 1b makes Ultralytics CPU and available CUDA GPU combinations operational; RKNN NPU becomes selectable when Phase 4b installs it, and TPU remains unavailable until a concrete TPU runtime and adapter are accepted.
- Phase 1b selections are single-user, global runtime state initialized from environment defaults and reset on application restart. Phase 3 persists the selection with the rest of global configuration; the unauthenticated Phase 1b UI remains loopback-by-default/trusted-LAN-only.
- Phase 3b is an optional stretch phase for selecting model-provided object-detection categories beyond `person`. Category choices come from a versioned model class catalog, use stable semantic IDs across backends where equivalence is verified, and must not be confused with a separate image-classification model.
- No authentication is present until Phase 4. Before then, services bind to loopback by default; LAN access is explicit and documented as trusted-network-only.
- Phase 1 creates a root `README.md` as the developer/operator entry point, covering development live reload, production-like x86 usage, configuration, security, tests, health, troubleshooting, and the post-auth Phase 4b boundary for Orange Pi/RKNN support.
- Persistent relational state uses SQLite on local storage with SQLAlchemy 2 and Alembic. Media remains in filesystem storage, credentials remain in environment/external secrets, and PostgreSQL is a later migration path for multi-instance or write-heavy deployments rather than an initial dependency.
- Per user direction on 2026-07-17, implementation proceeds through Phase 3b while live Discord delivery testing is deferred until an attended session. Deterministic fake-notifier coverage and dry-run production smoke are required before advancing. Physical PTZ movement also remains deferred because no explicit camera-movement approval was given; the browser/API path is covered against a fake ONVIF service meanwhile.

## Review of the PRD and preliminary design

The PRD's Tripwire success criteria are broader than the requested first implementation slice. This plan treats Phase 1 as a technical vertical slice, Phase 1b as operator-selectable inference configuration, and Phase 2 as completion of Tripwire; the PRD now records that mapping explicitly.

The preliminary design was reconciled with these corrections and additions:

1. **Process model:** do not fork after loading inference runtimes. CUDA and RKNN runtime state may not be fork-safe, and one loaded model per camera wastes memory. Use a dedicated inference service/worker with bounded input and explicit lifecycle. Add a configurable worker pool only after measurement.
2. **Camera fan-out:** avoid separate upstream RTSP connections for every consumer. Let `go2rtc` connect to the camera once and expose local restreams for WebRTC and inference.
3. **Backpressure:** live video and inference have different rates. Keep native-rate viewing, sample inference at a configurable target, and drop superseded frames rather than accumulating latency.
4. **Overlay synchronization:** WebRTC does not carry detection metadata from the inference service. Define frame/result timestamps, normalized coordinates, a result TTL, and client handling for letterboxing/resizing. MVP synchronization is best-effort and must expose measurable age.
5. **NPU packaging:** RKNN conversion tooling and the ARM64 runtime belong in separate build/runtime concerns. Do not install x86 conversion tooling in the Orange Pi runtime image.
6. **Capabilities:** an advertised ONVIF endpoint is not proof that every operation works. Capability discovery must represent verified operations; this camera accepts timed `ContinuousMove` but does not implement `Stop` or `GetStatus`.
7. **Security before auth:** a trusted-LAN assumption is not a security boundary. Keep the `go2rtc` API internal, redact URLs, default to loopback, and make unauthenticated LAN exposure deliberate.
8. **Model language:** Phase 1 performs object detection, which already returns class labels and bounding boxes. A separate image-classification model is not needed.
9. **Resolution and profiles:** the known main stream is 2304x1296 H.264. Discover `PROFILE_001` resolution/bitrate early; a lower-resolution substream may be preferable for inference while the main stream remains the viewer source.
10. **Licensing/provenance:** record licenses and checksums for Ultralytics code, model weights, datasets, and generated artifacts. Do not assume a public repository alone satisfies all obligations.

## Target architecture

```text
Physical camera
  | one authenticated RTSP connection
  v
go2rtc (internal API only)
  |-- WebRTC ------------------------------> React video element
  |                                           + canvas overlay
  `-- local RTSP --------------------------> frame sampler
                                              | bounded latest-frame queue
                                              v
                                       InferenceBackend
                                       | dev: Ultralytics CPU/CUDA
                                       ` edge: RKNN (Phase 4b)
                                              |
                                              v
FastAPI REST/health <--- application state --- WebSocket detections
  |
  `-- later: PTZ, alert evaluation, notifier, event storage
```

The API owns public contracts and application orchestration. `go2rtc` and inference implementation details remain behind internal boundaries. Detection results use a backend-neutral schema so recorded fixtures and fake adapters can drive all CI tests.

## Proposed repository shape

```text
backend/                 FastAPI app, domain contracts, adapters, tests
frontend/                React/Vite app and tests
infra/go2rtc/            sanitized static config/template; no credentials
models/                  manifests/checksums only; large artifacts ignored
tests/fixtures/          synthetic or explicitly redistributable media
.github/workflows/       GitHub Actions CI
compose.yaml             production-like service definitions
compose.dev.yaml         source sync, HMR/reload, development ports
doc/adr/                 durable architecture decisions
```

## Phase 1 — Live detection vertical slice (first `/goal`)

### Outcome

On the x86 development machine, the user can start the development stack, open one browser page, view the live camera over WebRTC, and see fresh `person` detections with class/confidence boxes. The same application contracts are ready for the RKNN backend, but Orange Pi optimization and operational alerting are not Phase 1 requirements.

### Scope exclusions

No PTZ UI, Discord notification, event history, recording, persistent configuration, parcel model, multi-camera UI, Keycloak, or Internet exposure.

### Tasks

#### Decisions and foundation

- [x] Add AGPL-3.0 project license, Ultralytics attribution, and a third-party/model provenance document.
- [x] Record ADRs for video delivery, detection metadata, inference contract, and trusted-LAN/no-auth posture.
- [x] Scaffold `backend`, `frontend`, `infra`, an in-memory deterministic synthetic frame source, and model-manifest directories.
- [x] Define supported tool versions: Python, `uv`, Node/npm, Docker Engine/Compose, and browser baseline.
- [x] Create `.env.example` values with safe placeholders; ignore local overrides, generated `go2rtc` configuration, models, databases, captures, and test artifacts.
- [x] Add a validation command that accepts no-camera synthetic development, can require physical-camera configuration explicitly, validates managed model presence, and reports missing variables by name without displaying values.

#### Development and Compose workflow

- [x] Define the shared Compose topology for frontend, API/inference, and `go2rtc`.
- [x] Add a development override/profile: frontend source sync plus Vite HMR; backend source sync plus FastAPI/Uvicorn reload; stable `go2rtc` unless its config changes.
- [x] Rebuild only when lockfiles, Dockerfiles, native dependencies, or model manifests change; ordinary backend/frontend source changes reload in the running development containers.
- [x] Document clean-clone one-command startup, physical-camera opt-in, targeted service logs, rebuild conditions, tests, and teardown.
- [x] Define production-like Compose behavior with immutable images, non-root users where supported, read-only mounts where practical, health checks, restart policies, and no reloaders/source mounts.
- [x] Create the root `README.md` with a dev quick start (`docker compose` watch, Vite HMR, FastAPI reload), production-like x86 startup, prerequisites, configuration/secrets, ports and trusted-LAN/no-auth warning, test commands, health checks, troubleshooting, shutdown, and CI-safe versus hardware smoke-test guidance.
- [x] State clearly in the root README that production-like Compose validates local x86 CPU/CUDA operation through Phase 4, while supported Orange Pi/RKNN deployment is delivered and documented in post-auth Phase 4b.

#### Camera and streaming

- [x] Define the minimal camera source contract without exposing raw credentials to API responses or logs.
- [x] Query both ONVIF profiles and record sanitized codec/resolution/FPS/bitrate capabilities; select the 2304x1296 main profile for the viewer and shared Phase 1 upstream, with inference resizing from the local restream to avoid a second camera connection.
- [x] Configure `go2rtc` from runtime secrets so it owns one upstream RTSP connection; a redacted physical-camera run reported exactly one producer while WebRTC, inference, and HLS consumers were active.
- [x] Restrict the `go2rtc` administrative/API surface to the internal Compose network and allow only required paths/modules.
- [x] Implement a backend-issued/sanitized stream descriptor for the frontend; never send the camera RTSP URL to the browser.
- [x] Add WebRTC connection/loading/error/retry states and a documented, allowlisted HLS diagnostic fallback proxy; cover the failure/fallback flow deterministically in a browser.

#### Inference and detection transport

- [x] Define `InferenceBackend` lifecycle and detection contracts: load/warm-up, detect, health, close, backend/model metadata, normalized box, class, confidence, source dimensions, timestamps, and timing metrics.
- [x] Implement a fake deterministic backend first to validate orchestration and UI independent of ML/hardware.
- [x] Implement Ultralytics YOLOv8n CPU inference; select CUDA automatically only when configured and available, with an explicit reported fallback.
- [x] Allow verified YOLOv8 and YOLO11 detection weights in nano, small, and medium sizes to be selected for development CPU/CUDA inference; keep YOLOv8n as the default.
- [x] Limit MVP classes to `person` by default while keeping filters configurable.
- [x] Implement preprocessing with preserved aspect ratio and tested reverse coordinate mapping.
- [x] Add configurable sampling and a size-one/bounded latest-frame queue; measure dropped, processed, and failed frames.
- [x] Continuously drain the local RTSP decoder while sampling at the configured inference rate so buffered frames cannot make fresh metadata describe old video; cover the decoder-backlog regression and live browser recovery.
- [x] Consume the local `go2rtc` restream rather than opening a second physical-camera session; validate real Ultralytics inference from that restream with one go2rtc producer.
- [x] Publish versioned detection messages over WebSocket with heartbeat, reconnect behavior, monotonic sequence, capture/result timestamps, and result age.
- [x] Expose redacted health/readiness information for camera/source, bridge, inference backend/model/device/fallback, WebSocket clients, FPS, latency, processed/dropped/failed frames, and degraded source state.

#### Frontend

- [x] Build a responsive single-camera page with accessible loading, connected, degraded, and disconnected states.
- [x] Render WebRTC video with a separate non-interactive SVG overlay.
- [x] Correctly transform normalized boxes through video scaling, letterboxing, resize, fullscreen, and device-pixel-ratio changes by sharing the source view box and fullscreen container; cover resize/fullscreen in Chromium.
- [x] Show class and confidence, backend/model identity, inference FPS/latency, result age, and connection health in a compact diagnostics panel.
- [x] Expire stale detections on an independent clock and visually distinguish degraded/stale metadata from video state.
- [x] Keep server access in a typed API layer and React-local state; Zustand is not justified for the Phase 1 page.

#### Backend tests

- [x] Unit-test inference contract validation, class/confidence filtering, coordinate transforms, queue/drop behavior, timestamp age, redaction, configuration/model validation, and CUDA selection/fallback.
- [x] Contract-test the fake backend in CI, retain an opt-in public-fixture person-detection contract for Ultralytics, and run the common load/detect/health contract over all six managed weights without committing fixtures or weights.
- [x] Integration-test the synthetic stream through sampling, fake inference, versioned WebSocket delivery, and readiness without a physical camera.
- [x] Test source/bridge loss redaction, inference exceptions, slow inference/drop behavior, browser WebSocket reconnect, and clean pipeline/application shutdown.
- [x] Add opt-in live-camera smoke tests that skip clearly when credentials/network are unavailable and never retain frames.

#### Frontend and end-to-end tests

- [x] Unit-test overlay geometry and stale-result expiry with Vitest; validate reconnect, diagnostics, fullscreen, fallback, and accessibility-critical interactions in the real-browser suite.
- [x] Mock REST/WebSocket/WebRTC boundaries for deterministic component tests.
- [x] Add Playwright flows for initial load, simulated detections, resize/fullscreen geometry, stale expiry, metadata disconnect/recovery, and video failure/fallback.
- [x] Run Playwright against deterministic local media/fakes in CI; physical-camera browser validation remains an explicit local smoke test.

#### GitHub Actions CI

- [x] Add least-privilege workflow permissions, concurrency cancellation, dependency caching, and pinned action major versions.
- [x] Run backend format/lint/type/unit/integration jobs on GitHub-hosted Linux without camera secrets.
- [x] Run frontend lint/type/unit/build jobs and Playwright with retained traces only on failure.
- [x] Run secret scanning plus repository checks that reject captures, local configuration, authenticated RTSP URLs, and unapproved large model binaries.
- [x] Validate Compose configuration and build the amd64 development/production images; defer publishing/deployment.
- [x] Start and probe the clean no-camera development stack in CI so image/override and runtime-startup regressions fail the workflow.
- [x] Make required CI checks and exact local equivalents explicit in the root README.

### Exit criteria

- [x] A clean clone can start the no-camera dev stack with documented prerequisites and live reload works without rebuilding for ordinary Python/React edits.
- [x] The physical camera streams to a supported browser with no camera URL or credential visible in browser payloads/logs.
- [x] `person` boxes remain correctly placed during resize/fullscreen and disappear when older than the configured TTL.
- [x] The pipeline remains responsive under slower-than-source inference because old frames are dropped.
- [x] CPU inference works on x86; CUDA selection/fallback is reported accurately when applicable.
- [x] Automated backend, frontend, integration, Playwright, build, and security checks pass in GitHub Actions.
- [x] Manual smoke results record browser, timestamp-based pipeline latency, view FPS, inference FPS, CPU/GPU utilization, and known limitations without retaining private media.

### Phase 1 validation evidence

- 2026-07-17: A live-demo overlay mismatch exposed decoder-internal RTSP backlog: a 15 FPS source was read only at the 5 FPS inference cadence, so old frames could receive fresh capture timestamps and the latest-frame queue reported zero drops. The corrected source continuously drains with `grab`, retrieves only the newest frame at the configured cadence, and includes decoder discards in dropped-frame metrics. A deterministic 25-to-5 FPS regression test proved intermediate frames were discarded; the full backend suite passed with 35 tests and 8 expected opt-in skips. In the physical-camera stack, 46 superseded frames were dropped over a five-second sample with zero failures; the existing Chromium window recovered through backend reload, remained connected through fullscreen, and a temporary visual check showed the current detection box aligned. No camera or browser artifact was retained.
- 2026-07-17: GitHub Actions [CI run #2](https://github.com/robert-girard/camzilla/actions/runs/29624848742) passed on commit `1777fa8`: backend format/lint/type/unit/integration checks, frontend lint/type/unit/build/Playwright checks, and the security/Compose configuration, image-build, and clean no-camera startup smoke job all completed successfully.
- 2026-07-17: A redacted physical-camera smoke in Headless Chromium 150 connected WebRTC at 2304x1296 and measured 13.2 displayed FPS over 3 seconds. Browser network requests exposed only `/api/v1/stream` and `/api/v1/webrtc`; metadata remained connected through fullscreen. The HLS diagnostic proxy returned HTTP 200, and the internal bridge reported one producer with three active consumers.
- 2026-07-17: During the physical CPU smoke, YOLOv8n reported about 4.7 inference FPS, 20-26 ms recent inference, zero failures, a 26 ms sampler-capture-to-result interval, and a result observed by the browser at 148 ms old. The API container used about 130% of one CPU core and 545 MiB, go2rtc about 0.8%/17 MiB, and the development frontend about 0.2%/254 MiB at the sampled instant. CUDA was unavailable and the explicit CPU fallback was correct. No frames, recordings, URLs, credentials, or browser artifacts were retained. True scene-to-display latency was not measurable without placing a synchronized time source in the private scene; timestamp metrics begin after decode.
- 2026-07-17: A redacted ONVIF discovery run measured `PROFILE_000` as H.264 2304x1296 at 15 FPS/1536 kbps and `PROFILE_001` as H.264 640x360 at 15 FPS/512 kbps; both returned an RTSP URI. Phase 1 uses the main profile for the single go2rtc upstream and lets inference resize from the shared local restream.
- 2026-07-17: A no-`.env` development Compose build started API, stable go2rtc, and Vite services on loopback. Synthetic fake inference reported ready at about 5 FPS with no failures, browser metadata connected with a visible `person` overlay, and missing video showed the proxied fallback. Touching backend and frontend sources kept the same containers, triggered Uvicorn reload and Vite HMR, and the browser reconnected metadata successfully. This run also exposed and fixed an inherited frontend build/image tag that had produced `npm: not found` before validation.
- 2026-07-17: Backend CI-equivalent checks passed with 34 tests plus 8 intentional hardware/model skips; frontend lint, typecheck, 3 Vitest tests, production build, and 5 deterministic Chromium flows passed. The browser flows cover connected diagnostics, source-coordinate overlay, resize/fullscreen, independent stale expiry, metadata recovery, and video failure/fallback. The CPU image reports the lock-aligned Torch 2.13.0, torchvision 0.28.0, and Ultralytics 8.4.92 versions, and its dependency layer remains cached across application-source-only rebuilds.
- 2026-07-17: All six managed development weights (`yolov8n`, `yolov8s`, `yolov8m`, `yolo11n`, `yolo11s`, and `yolo11m`) matched the SHA-256 values recorded from the official Ultralytics v8.4.0 assets release and passed the shared CPU load, warm-up, synthetic-frame detect, identity, and health contract. Weight binaries remained ignored and were not committed.
- 2026-07-12: The production-style amd64 API image loaded the checksum-verified YOLOv8n weight on CPU and detected `person` (top confidence 0.87) from a public, temporary fixture; neither weight nor fixture was committed. In the no-camera synthetic pipeline it reported 5.0 inference FPS, 31.0 ms most-recent inference, zero failures, and zero dropped frames. The backend records CPU fallback when CUDA is unavailable.
- 2026-07-12: The no-camera Compose stack ran with deterministic fake frames. Chromium verified connected detection metadata, an SVG `person` overlay, diagnostics, and the degraded WebRTC state. The real-camera work that remained at that point was completed by the 2026-07-17 smoke evidence above.

## Phase 1b — Model and inference target selection UI (pre-auth)

### Outcome

From the single-camera page, the operator can inspect the active model and inference target and safely switch to any backend/model combination the server reports as available. Phase 1b delivers functional selection among the six managed YOLO development weights on CPU and on CUDA GPU when present. The same capability-driven UI represents NPU and TPU targets without claiming unsupported hardware: RKNN NPU becomes available through post-auth Phase 4b, while TPU requires a separately accepted runtime and adapter.

### Scope exclusions

No RKNN conversion/runtime implementation, TPU adapter, PTZ, alerts, persistence, recording, multi-camera orchestration, authentication, arbitrary model upload, remote model URL, or browser-supplied filesystem path. A Phase 1b selection is global runtime state and returns to the environment-configured default after application restart.

### Tasks

#### Selection contracts and lifecycle

- [x] Define a backend-neutral inference capability contract containing stable backend, model, and target IDs; target category (`cpu`, `gpu`, `npu`, or `tpu`); compatibility; availability; unavailability reason; active state; and backend/model metadata.
- [x] Expose typed endpoints to read capabilities and the active selection and to request a supported selection; reject unknown, unavailable, unhealthy, or incompatible combinations without accepting arbitrary paths, URLs, or secret-bearing values.
- [x] Enumerate all six managed YOLO development weights for Ultralytics CPU and for CUDA GPU only when CUDA is verified available; report a redacted, actionable reason for every unavailable GPU, NPU, or TPU option.
- [x] Serialize concurrent selection requests and implement a transactional worker switch: stop intake, initialize and warm the candidate, atomically publish it only on success, close the previous backend after the swap, and retain or restore the previous healthy backend on failure.
- [x] Reset bounded queues and detection sequence state across a successful switch so results from the previous model/target cannot be presented as current; keep video available and report an explicit switching/degraded state.
- [x] Keep environment variables as restart defaults and store the selected combination only in memory until Phase 3 persistence is implemented.
- [x] Update health, readiness, diagnostics, and detection metadata immediately after a successful switch with the active backend, target, model, device, fallback, and transition status.

#### Frontend

- [x] Add accessible model and inference-target controls to the single-camera page, showing CPU, GPU, NPU, and TPU categories, the active combination, loading/switching state, and clear reasons for unavailable or incompatible choices.
- [x] Require an explicit apply action, preserve the displayed active selection until the server confirms the swap, and show recoverable failure feedback when warm-up or switching fails.
- [x] Keep the overlay and diagnostics coherent during switching: expire old detections, reconnect metadata when required, and display the confirmed backend/model/target identity returned by the server.
- [x] Explain in the UI that the selection is global and runtime-only through Phase 2 and that unavailable hardware requires its corresponding backend/runtime rather than a browser setting.

#### Tests, documentation, and integration gates

- [x] Unit-test capability/compatibility validation, stable IDs, unavailable reasons, concurrent request serialization, transition state, queue/result reset, successful cleanup, failed warm-up rollback, and redaction.
- [x] Integration-test CPU model switching through the running pipeline and deterministic fake capability fixtures for CPU, GPU, NPU, and TPU; keep CUDA/RKNN/TPU hardware tests opt-in with clear skip semantics.
- [x] Add Playwright flows for a successful model/CPU switch, capability-gated GPU/NPU/TPU choices, switching state, failed-switch rollback, diagnostics identity, stale-overlay expiry, and metadata recovery.
- [x] Update the root README with selection behavior, supported combinations, runtime-only semantics, restart defaults, expected interruption, unavailable-target troubleshooting, and hardware-dependent validation commands.
- [x] Extend CI to run the selection contract, integration, frontend, and deterministic Playwright tests without requiring model binaries or accelerator hardware.
- [ ] **Phase 4b follow-up (does not block Phase 1b):** register verified RKNN model artifacts in this capability contract and make NPU choices selectable without changing the Phase 1b API or UI contract.

### Exit criteria

- [x] The browser can switch among installed, checksum-verified managed YOLO weights on CPU, and the active model identity in health and detection messages matches the confirmed selection.
- [x] CUDA GPU is selectable only when verified available; CPU remains usable when CUDA is absent or a GPU switch fails.
- [x] CPU, GPU, NPU, and TPU are represented consistently, with unsupported combinations disabled and explained rather than accepted and silently downgraded.
- [x] A failed or racing switch cannot leave two active workers, leak a loaded runtime, expose a secret/path, or replace the last healthy backend.
- [x] Video remains available during a switch, stale detections are cleared, and metadata/diagnostics recover with the newly confirmed identity.
- [~] Backend, frontend, integration, Playwright, build, and security checks pass in hardware-independent CI; accelerator-specific checks have documented opt-in results and skip behavior. Local CI equivalents pass; GitHub Actions confirmation is pending.

### Phase 1b validation evidence

- 2026-07-17: The running no-camera Ultralytics stack reported all six checksum-verified managed weights as CPU-available and switched transactionally through `yolov8n`, `yolov8s`, `yolov8m`, `yolo11n`, `yolo11s`, and `yolo11m`; each response and health check confirmed CPU identity and ready transition state. After the final switch, synthetic inference resumed near 4.9 FPS with 61 processed frames and zero failures. CUDA was unavailable and all GPU combinations remained disabled with a redacted reason; NPU and TPU placeholders were disabled with their planned-runtime explanations.
- 2026-07-17: Real Chromium against the running API displayed all target categories and six CPU weights, switched explicitly from YOLO11m to YOLOv8n, cleared the old result, and recovered diagnostics/metadata with the confirmed CPU identity. Deterministic browser coverage passed eight flows, including switching state, failed warm-up rollback, unavailable hardware, stale expiry, metadata recovery, fullscreen, and video fallback. No camera media or browser artifact was retained.
- 2026-07-17: Local CI equivalents passed with 44 backend tests plus 8 expected opt-in skips, backend format/lint/type checks, 3 frontend unit tests, frontend lint/type/build, 8 Playwright flows, security scanning, Compose configuration, production image builds, and a clean no-camera production-stack readiness smoke.

## Phase 2 — Complete Tripwire locally on x86 (pre-auth)

### Outcome

The local x86 deployment becomes a reliable trusted-LAN Tripwire: the first camera offers safe timed PTZ controls and produces debounced Discord person alerts with redacted snapshots using Ultralytics CPU or available CUDA inference. Orange Pi packaging and RKNN are deliberately excluded until after authentication and the more advanced local features are complete.

### Tasks

#### PTZ

- [x] Model PTZ as an optional verified capability, not merely an advertised ONVIF service.
- [x] Implement bounded timed `ContinuousMove` commands using server-enforced speed/duration limits; never rely on unsupported `Stop`.
- [x] Add keyboard/touch-accessible PTZ controls with press throttling, request state, and failure feedback.
- [x] Unit-test command bounds/direction mapping and integration-test against a fake ONVIF service.
- [x] Add a manual physical-camera PTZ checklist that avoids repeated/unattended movement.

#### Alerts and reliability

- [x] Define alert rule, event, attachment, and notifier contracts; begin with one camera, `person`, confidence threshold, and debounce.
- [x] Implement an async Discord webhook adapter with timeout, retry/backoff, rate-limit handling, and secret redaction.
- [x] Capture a bounded in-memory snapshot at trigger time, annotate a copy, and avoid persistence unless explicitly enabled.
- [x] Add reconnect/backoff and state transitions for camera, restream, inference, and notifier failures.
- [x] Add stream-down notification policy with state-based suppression to prevent alert storms.
- [x] Provide a dry-run notifier and require explicit confirmation/configuration before sending real alerts.
- [x] Test debounce boundaries, duplicate suppression, attachment limits, retry policy, reconnect, secret redaction, and notifier failure isolation.
- [x] Add Playwright coverage for PTZ states, alert rule display/dry-run, degraded health, and recovery.
- [x] Run a sustained production-like x86 smoke through service restart using CPU and available CUDA, recording latency, throughput, memory, and recovery behavior without retaining private media.

### Exit criteria

- [x] The production-like x86 stack survives service restart and sustains the agreed CPU/CUDA performance envelope without unbounded latency or queues.
- [x] The Phase 1b selector applies supported Ultralytics CPU/CUDA combinations while NPU and TPU remain explicitly unavailable.
- [~] Browser PTZ performs short bounded moves without requiring `Stop`; deterministic browser/fake-ONVIF coverage passes, but attended physical movement awaits explicit approval.
- [~] A qualifying detection emits at most one Discord alert per debounce window with an annotated snapshot, and dry-run mode emits none externally; deterministic coverage passes, but the user deferred a real webhook smoke.
- [x] Automated tests pass; camera/CUDA-only checks have documented results and skip semantics.

### Phase 2 validation evidence

- 2026-07-17: PTZ contract, bounds, direction mapping, server throttle, and the timed `ContinuousMove`-only ONVIF adapter passed focused backend tests against a fake service. Frontend lint/type/build, unit tests, and eleven deterministic Playwright flows passed, including PTZ acceptance, operation-verification gating, and redacted failure recovery. Physical movement remains an explicit attended smoke test and was not performed during unattended development.
- 2026-07-17: The alert and reliability suite passed 65 backend tests plus 8 expected opt-in skips and thirteen Playwright flows. Deterministic adapters covered exact debounce boundaries, bounded annotated attachments, Discord timeout/retry/rate-limit behavior, explicit delivery confirmation, source reconnect, inference/notifier failure isolation, stream-down suppression, and visible degraded/recovered UI states. Per user direction, no real Discord webhook request was sent; live alert delivery remains deferred until an attended session.
- 2026-07-17: A production-image, no-camera, dry-run soak used checksum-verified YOLO11s on CPU. Before restart it processed 572 frames at 4.99 FPS with sampled inference latency of 41–51 ms, zero failed/dropped frames, and approximately 399–418 MiB API memory. After an API-container restart it returned ready, reloaded the same identity, and processed another 243 frames at 5.00 FPS with 68 ms sampled latency, zero failures/drops, and approximately 394 MiB memory. Frontend and bridge remained healthy. CUDA was unavailable, so all six GPU choices stayed disabled with the expected reason. The isolated stack was removed and retained no media.

## Phase 3 — Operability, history, and multi-camera groundwork (pre-auth)

### Outcome

The system becomes convenient for daily personal use before authentication is introduced: persistent alert history, editable global configuration, zones/schedules, clips, retention, and a measured path to multiple cameras.

### Tasks

- [x] Implement SQLite persistence through SQLAlchemy 2 with Alembic migrations for the single-node deployment; keep media outside database rows and avoid SQLite database files on network filesystems.
- [x] Persist cameras, capability results, the active inference backend/model/target selection, alert rules, events, and secret references—never plaintext secrets or authenticated URLs.
- [x] Keep the persistence/domain boundary compatible with a later PostgreSQL adapter and document the operational conditions that justify migration (multiple app instances, shared/remote database, or sustained write contention).
- [x] Add alert-history API/UI with pagination, filtering, sorting, snapshot/clip access, and deletion.
- [x] Add editable confidence, debounce, time schedules, and normalized polygon zones with validation and preview.
- [x] Add pre-roll ring buffering and configurable 5–30 second alert clips with storage quotas and oldest-first retention.
- [x] Add manual recording only after retention and disk-full behavior are tested.
- [x] Generalize orchestration/UI to multiple cameras while sharing or pooling inference workers based on measured memory/throughput.
- [x] Add optimistic config versioning before multiple authenticated editors exist, so Phase 4 does not retrofit it.
- [ ] Add backup/export with secrets excluded by default and explicit restore validation.
- [ ] Unit/integration-test migrations, rules, zones, schedules, retention, disk-full handling, multi-camera fairness, and backup/restore.
- [x] Add Playwright coverage for history filters, rule editing conflicts/validation, zone drawing, clip playback, and multi-camera degraded states.

### Phase 3 validation evidence

- 2026-07-17: The initial migration, repository, runtime integration, history/config APIs, and selection rollback passed 75 backend tests plus 8 expected opt-in skips. Sixteen deterministic Playwright flows passed, including history filtering/deletion, optimistic conflict handling, schedule/rule editing, normalized zone drawing/preview, and client validation. Schema and API responses contain secret references or redacted capability state only, never secret values or authenticated URLs.
- 2026-07-17: Media storage, quota retention, pre-roll/post-roll sessions, manual-recording gating, database-reference cleanup, and redacted disk failure behavior passed 83 backend tests plus 8 expected opt-in skips, including a real OpenCV MP4 encode on the development runtime. Seventeen Playwright flows passed with inline clip playback and manual start/stop controls. Tests used synthetic bytes/frames under temporary roots and retained no media.
- 2026-07-17: Multi-camera persistence/API validation and the bounded round-robin scheduler passed 86 backend tests plus 8 expected opt-in skips. Flooding two simulated sources retained only one latest frame per camera and serviced the quieter source after the busy source's single turn. Eighteen Playwright flows passed, including distinct synthetic/degraded camera cards with only the operational camera exposing recording controls. Real second-camera testing remains hardware-dependent.
- [ ] Extend GitHub Actions with migration checks and schema/API compatibility checks; deployment remains manual.

### Exit criteria

- [ ] Personal daily-use configuration and history survive restart and migration.
- [ ] Retention prevents unbounded storage and behaves safely when storage is unavailable/full.
- [x] Multiple simulated cameras cannot starve one another; real second-camera testing waits for hardware/configuration.
- [ ] No export, API, log, or UI surface exposes stored secrets.

## Phase 3b — Detection category selection (optional stretch goal, pre-auth)

This stretch phase is optional and does not block Phase 4. Here, “category” means an object-detection class exposed by the selected model, not a separate image-classification model.

### Outcome

The operator can choose one or more detection categories beyond `person`—for example, model-provided vehicle or animal classes—for each camera and alert rule. The UI derives its choices from the active model's verified class catalog, persists them as shared configuration, and never offers a category the selected model cannot produce.

### Scope exclusions

No new model training, arbitrary label creation, semantic remapping guessed from display text, parcel support without a verified parcel-capable model, relational event logic, or multi-camera subject correlation. Phase 3b selects from classes already declared by an installed model artifact.

### Tasks

- [ ] Extend model/backend capabilities with a versioned class catalog containing stable semantic IDs, model-native class IDs, display labels, and optional descriptions; do not persist model-specific numeric indices as the cross-model identity.
- [ ] Add persisted, versioned per-camera detection-category allowlists and per-alert-rule target categories, retaining `person` as the safe default for existing configurations.
- [ ] Expose typed APIs that return categories for the active model/target combination and validate saved selections against that exact capability revision.
- [ ] Apply the per-camera allowlist consistently to detection publication, overlays, metrics, snapshots/clips, and alert evaluation; an alert rule may reference only categories enabled for its camera.
- [ ] Add accessible searchable multi-select controls with select-all/clear actions, category descriptions, active counts, validation, and a preview using deterministic detections.
- [ ] Reconcile category selections during a Phase 1b model/backend switch by stable semantic ID. Require explicit resolution when the new model lacks a selected category; never silently broaden, drop, or substitute alert targets.
- [ ] Show model changes that would invalidate camera or alert-rule categories before applying the switch, including affected cameras/rules and the available compatible choices.
- [ ] Record the active category catalog revision and selected semantic IDs in events so historical results remain interpretable after model changes.
- [ ] Unit/integration-test catalog validation, semantic-ID mapping, defaults, multi-select filtering, persistence/migration, invalidation conflicts, alert isolation, and models with different class catalogs.
- [ ] Add Playwright coverage for selecting non-person categories, filtering overlays, configuring multi-category alert rules, persistence across restart, and resolving a model-switch incompatibility.
- [ ] Update backup/export, README configuration guidance, and schema/API compatibility checks for class catalogs and selected categories.

### Exit criteria

- [ ] The UI lists only categories declared by the active model and can persist one or more non-`person` categories per camera and alert rule.
- [ ] Detection overlays, event records, and alerts consistently honor the selected semantic categories while `person` remains the migration/default behavior.
- [ ] Switching to a model with a different class catalog cannot silently remove, rename, or reinterpret an existing selection.
- [ ] Multiple cameras may use different supported category selections without leaking detections or alert rules across cameras.
- [ ] Backend, migration, frontend, Playwright, backup/export, and compatibility checks pass with deterministic models that expose different class catalogs.

## Phase 4 — Keycloak authentication and concurrent administration

### Outcome

All browser/API access is authenticated through Keycloak, authorization is enforced server-side, and shared configuration is protected from lost updates.

### Tasks

- [ ] Confirm issuer, realm, client, redirect/logout URLs, LAN DNS/TLS, role mapping, and outage behavior with the actual Keycloak deployment.
- [ ] Use Authorization Code with PKCE for the SPA; do not put client secrets in frontend code.
- [ ] Validate JWT signature, issuer, audience, expiry, and roles in FastAPI using cached JWKS with safe refresh/failure behavior.
- [ ] Authorize REST, detection WebSocket, media-signaling proxy, snapshots, clips, PTZ, configuration, and health detail server-side.
- [ ] Define viewer/operator/admin permissions; keep sensitive health/configuration admin-only.
- [ ] Enforce optimistic locking/version checks and provide a usable frontend conflict-resolution flow.
- [ ] Add secure headers, narrow CORS/origin checks, session/logout handling, and audit events for security-sensitive actions.
- [ ] Unit/integration-test token validation failures, role boundaries, JWKS rotation/outage, WebSocket expiry, and concurrent edits.
- [ ] Add Playwright tests using a disposable Keycloak realm for login, logout, expiry, unauthorized access, role behavior, and edit conflicts.
- [ ] Keep CI credentials synthetic and ephemeral; never connect GitHub Actions to the personal Keycloak instance.

### Exit criteria

- [ ] Anonymous users cannot reach video, detections, PTZ, media, configuration, or detailed health through any direct service route.
- [ ] Role enforcement and concurrent-edit protection pass backend and browser tests.
- [ ] Keycloak outage/rotation behavior fails safely and recovery is documented.

## Phase 4b — Authenticated Orange Pi and RKNN deployment

### Outcome

After the local x86 product, persistence, and authentication flows are stable, the authenticated system is deployed to the Orange Pi with RKNN NPU inference. Existing cameras, configuration, history, media, permissions, alerts, and optional Phase 3b category selections migrate without weakening security or changing application contracts.

### Entry conditions

- Phase 4 authentication and server-side authorization exit criteria are complete.
- Phase 3 persistence, backup/restore, retention, and disk-full behavior are complete on x86.
- Phase 3b is optional; if implemented, its category catalog and selections must also pass RKNN compatibility and migration tests.

### Tasks

#### RKNN backend and packaging

- [ ] Inventory Orange Pi OS/kernel, NPU driver/runtime, Python, Docker/Compose, storage, thermals, and architecture without collecting device identifiers.
- [ ] Pin a compatible RKNN toolkit/runtime/driver matrix and document the x86 model-conversion environment separately from the ARM64 runtime.
- [ ] Export and quantize the selected YOLO model with a redistributable calibration dataset; record source, license, checksum, input shape, conversion settings, and class catalog.
- [ ] Implement the RKNN backend behind the Phase 1 contract with explicit initialization and shutdown; do not rely on forked runtime state.
- [ ] Register each verified RKNN model artifact and its NPU compatibility in the Phase 1b capability API so the existing selector can activate it without frontend special cases.
- [ ] Add golden-image parity tests between Ultralytics and RKNN with documented numerical, coordinate, class-catalog, and detection tolerances.
- [ ] Produce architecture-specific or multi-architecture production images without installing x86 conversion tooling in the ARM64 runtime or emulating NPU tests in GitHub-hosted CI.
- [ ] Benchmark FPS, end-to-end latency, memory, NPU utilization, CPU decode, temperature, and sustained operation; choose model generation/size and input resolution from evidence.
- [ ] Add an opt-in or self-hosted Orange Pi hardware test path; keep GitHub-hosted CI hardware-independent.

#### Authenticated migration and operations

- [ ] Document and test backup, transfer, restore, schema migration, media validation, and rollback from the authenticated x86 deployment to local Orange Pi storage without copying plaintext secrets or generated credential-bearing configuration.
- [ ] Provide a production Compose deployment for ARM64/RKNN with immutable images, explicit health checks, restart policy, bounded resource settings, no source mounts/reloaders, and no directly exposed `go2rtc` administration.
- [ ] Validate Keycloak login, JWT/JWKS behavior, role enforcement, WebSocket/media authorization, PTZ, alerts, history, clips, configuration, and detailed-health restrictions on the Orange Pi deployment.
- [ ] Validate reboot recovery, camera/restream/inference/notifier reconnection, database/media consistency, retention, disk-full handling, and safe failure when the NPU runtime is unavailable.
- [ ] Document an operator migration checklist and a tested rollback to the last healthy authenticated x86 deployment.
- [ ] Update the root README with supported Orange Pi prerequisites, image/runtime selection, deployment, migration, backup, rollback, health, performance/thermal limits, troubleshooting, and hardware smoke commands.

### Exit criteria

- [ ] The authenticated Orange Pi stack survives reboot/restart and sustained operation within the agreed performance, memory, storage, and thermal envelope.
- [ ] RKNN and Ultralytics satisfy the same inference contract and acceptable parity thresholds, including class identities and normalized coordinates.
- [ ] The Phase 1b selector reports and applies supported RKNN NPU model combinations while keeping incompatible artifacts unavailable with an actionable reason.
- [ ] Existing persisted configuration, history, media references, rules, permissions, and implemented category selections migrate and restore successfully, with a tested x86 rollback path.
- [ ] Anonymous access remains blocked across every direct service route, and authenticated browser/API behavior matches the Phase 4 authorization contract.
- [ ] Automated tests pass; Orange Pi/NPU-only checks have documented results, opt-in execution, and clear skip semantics.

## Phase 5 and deferred work

- [ ] False-positive feedback and threshold-tuning workflow.
- [ ] ONVIF Profile G discovery and edge-storage integration only after verified hardware tests.
- [ ] Native ONVIF event discovery as an optional signal, never a dependency for YOLO detection.
- [ ] Parcel dataset selection, labeling, training, evaluation, licensing, and model delivery.
- [ ] Person-plus-parcel relational rules, dwell time, disappearance/theft logic, and line crossing.
- [ ] Multi-camera subject correlation and advanced dashboard visualizations.
- [ ] Additional notifiers and external storage backends.
- [ ] Select a concrete TPU hardware family and runtime, then implement and contract-test its inference adapter and model-artifact pipeline; register it with the Phase 1b capability API only after hardware validation.
- [ ] Image publishing, signed artifacts/SBOMs, automated rollout/rollback, and release automation beyond the documented Phase 4b manual deployment.

## Security hygiene completed during planning

- [x] Confirmed the ignored local `.env` is not present in reachable local Git history.
- [x] Confirmed the example environment file contains no credential values.
- [x] Replaced the tracked camera IP/MAC and helper defaults with environment-driven configuration in the current working tree.
- [x] Verified the physical ONVIF and RTSP services were reachable and an authenticated H.264 pipeline processed the stream without printing credentials.
- [x] Commit the sanitized current state locally.
- [x] Push the sanitized current state to GitHub.
- [ ] Decide whether to rewrite old public history after reviewing the risk and coordination cost; do not force-push without explicit approval.

## Open decisions and discovery gates

- [ ] Choose the repository copyright holder/notice for the AGPL-3.0 license.
- [ ] Confirm dev machine OS, CPU/GPU/CUDA availability, RAM, and expected browsers.
- [ ] Confirm Orange Pi OS image, NPU driver/runtime state, RAM, storage, and whether it is available during Phase 4b.
- [ ] Choose the intended TPU hardware/runtime (for example, an Edge TPU/TFLite-class target) before planning adapter implementation; `tpu` remains an unavailable capability category until then.
- [x] Measure `PROFILE_001` and decide whether inference uses the substream or a downscaled main-stream restream.
- [ ] Set numeric Phase 1 targets after the first baseline: acceptable view latency, detection age, inference FPS, and CPU/GPU usage.
- [ ] Decide later whether snapshots/events may be retained by default; use memory-only behavior through Phase 2.

## Git-history exposure assessment

The historical values are a private LAN address, device MAC, camera model/service layout, and unauthenticated URI shape. The LAN address is not Internet-routable, the MAC is normally useful only on the local network, and the audit found no committed `.env` or obvious assigned credential values. This is low-severity information disclosure, not a credential compromise. Risk rises if camera ports were forwarded publicly, camera credentials were reused elsewhere, or captured media was ever committed.

History can be rewritten with `git-filter-repo --replace-text` in a fresh mirror clone followed by a coordinated force-push. That changes commit hashes and requires other clones to be replaced or carefully cleaned. Forks, existing clones, cached commit views, and pull-request references may retain old content; GitHub Support generally reserves cache/reference cleanup for genuinely sensitive data. Because these identifiers are low sensitivity and current content is sanitized, rewriting is optional rather than urgent. If chosen, take a mirror backup, freeze pushes, enumerate all refs/PRs/forks, verify replacements locally, force-push, and have every collaborator re-clone.

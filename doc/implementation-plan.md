# Camzilla Implementation Plan

Status: Phase 1 in progress
Last updated: 2026-07-12
Primary product source: [PRD](PRD-home-security-ai-alerts.md)

## Document Role and References

This is the executable roadmap and status tracker. Consult the [PRD](PRD-home-security-ai-alerts.md) for product requirements, the [design document](design-doc-home-security-ai-alerts.md) for current architecture, and the [first-camera notes](../cam_info/README.md) for device-specific behavior. Update this file during implementation; update the PRD or design in the same change when an accepted implementation decision alters product scope or durable architecture.

## How to use this plan

- `[ ]` not started, `[~]` in progress, `[x]` complete, `[!]` blocked.
- Update task state in the same change that produces or verifies the work.
- A phase is complete only when all required tasks and exit criteria are complete. Tasks explicitly marked optional do not block completion.
- Add discoveries beneath the phase they affect. Put cross-cutting decisions in the decision log and meaningful design changes in ADRs.
- Phase 1 is the intended first `/goal`. Do not pull PTZ, alerts, recording, or authentication into it.
- Mark work `[~]` when it begins and `[x]` only after implementation and validation. Use `[!]` with an unblock condition for genuine blockers.
- Split partially completed compound tasks instead of marking them complete. Preserve completed tasks and commit status updates with their implementation/tests.
- Update `Last updated` whenever task state, phase scope, decisions, or exit criteria materially change.

## Confirmed decisions

- Phase 1 is a single-camera live viewer with pluggable inference and browser-rendered detection boxes. PTZ and Discord alerts begin in Phase 2.
- Browser video uses `go2rtc` WebRTC. Detection metadata travels separately over a backend WebSocket and is rendered on a canvas overlay. HLS/MJPEG is diagnostic fallback only.
- Docker Compose is used for development and deployment. Development uses Vite HMR, FastAPI reload, source sync/bind mounts, and dependency-triggered rebuilds.
- GitHub Actions provides CI for tests, checks, and builds. Deployment automation is deferred.
- The MVP uses Ultralytics and YOLOv8 under AGPL-3.0. Add the project license and third-party notices before introducing the dependency. Keep inference pluggable to preserve a future replacement/enterprise-license path.
- No authentication is present until Phase 4. Before then, services bind to loopback by default; LAN access is explicit and documented as trusted-network-only.
- Phase 1 creates a root `README.md` as the developer/operator entry point, covering development live reload, production-like x86 usage, configuration, security, tests, health, troubleshooting, and the Phase 2 boundary for Orange Pi/RKNN support.
- Persistent relational state uses SQLite on local storage with SQLAlchemy 2 and Alembic. Media remains in filesystem storage, credentials remain in environment/external secrets, and PostgreSQL is a later migration path for multi-instance or write-heavy deployments rather than an initial dependency.

## Review of the PRD and preliminary design

The PRD's Tripwire success criteria are broader than the requested first implementation slice. This plan treats Phase 1 as a technical vertical slice and Phase 2 as completion of Tripwire; the PRD now records that mapping explicitly.

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
                                       ` prod: RKNN (Phase 2)
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
- [~] Scaffold `backend`, `frontend`, `infra`, deterministic fixtures, and model-manifest directories. (Core directories and model manifest are present; deterministic fixture is pending.)
- [x] Define supported tool versions: Python, `uv`, Node/npm, Docker Engine/Compose, and browser baseline.
- [x] Create `.env.example` values with safe placeholders; ignore local overrides, generated `go2rtc` configuration, models, databases, captures, and test artifacts.
- [~] Add a validation command that reports missing configuration by variable name without displaying values.

#### Development and Compose workflow

- [x] Define the shared Compose topology for frontend, API/inference, and `go2rtc`.
- [x] Add a development override/profile: frontend source sync plus Vite HMR; backend source sync plus FastAPI/Uvicorn reload; stable `go2rtc` unless its config changes.
- [ ] Rebuild only when lockfiles, Dockerfiles, native dependencies, or model manifests change.
- [ ] Document one-command startup, targeted service logs, rebuild, test, and teardown.
- [x] Define production-like Compose behavior with immutable images, non-root users where supported, read-only mounts where practical, health checks, restart policies, and no reloaders/source mounts.
- [x] Create the root `README.md` with a dev quick start (`docker compose` watch, Vite HMR, FastAPI reload), production-like x86 startup, prerequisites, configuration/secrets, ports and trusted-LAN/no-auth warning, test commands, health checks, troubleshooting, shutdown, and CI-safe versus hardware smoke-test guidance.
- [x] State clearly in the root README that Phase 1 production-like Compose validates packaging and CPU/CUDA operation, while supported Orange Pi/RKNN deployment is delivered and documented in Phase 2.

#### Camera and streaming

- [x] Define the minimal camera source contract without exposing raw credentials to API responses or logs.
- [ ] Query both ONVIF profiles and record sanitized codec/resolution/bitrate capabilities; select viewer and inference profiles based on measurements.
- [~] Configure `go2rtc` from runtime secrets so it owns one upstream RTSP connection. (Runtime-secret configuration is present; physical-camera smoke validation remains.)
- [x] Restrict the `go2rtc` administrative/API surface to the internal Compose network and allow only required paths/modules.
- [x] Implement a backend-issued/sanitized stream descriptor for the frontend; never send the camera RTSP URL to the browser.
- [~] Add WebRTC connection/loading/error/retry states and a documented HLS/MJPEG diagnostic fallback. (WHEP loading/error states are present; fallback endpoint and physical smoke are pending.)

#### Inference and detection transport

- [x] Define `InferenceBackend` lifecycle and detection contracts: load/warm-up, detect, health, close, backend/model metadata, normalized box, class, confidence, source dimensions, timestamps, and timing metrics.
- [x] Implement a fake deterministic backend first to validate orchestration and UI independent of ML/hardware.
- [x] Implement Ultralytics YOLOv8n CPU inference; select CUDA automatically only when configured and available, with an explicit reported fallback.
- [x] Limit MVP classes to `person` by default while keeping filters configurable.
- [x] Implement preprocessing with preserved aspect ratio and tested reverse coordinate mapping.
- [x] Add configurable sampling and a size-one/bounded latest-frame queue; measure dropped, processed, and failed frames.
- [~] Consume a local `go2rtc` restream rather than opening a second physical-camera session where supported. (Local-restream adapter is present; physical-camera smoke validation remains.)
- [x] Publish versioned detection messages over WebSocket with heartbeat, reconnect behavior, monotonic sequence, capture/result timestamps, and result age.
- [~] Expose redacted health/readiness information for camera, bridge, inference backend/model, WebSocket clients, FPS, and latency. (Backend and pipeline counters are present; camera/bridge and rate/latency readiness are pending.)

#### Frontend

- [~] Build a responsive single-camera page with accessible loading, connected, degraded, and disconnected states.
- [~] Render WebRTC video with a separate non-interactive canvas/SVG overlay.
- [~] Correctly transform normalized boxes through video scaling, letterboxing, resize, fullscreen, and device-pixel-ratio changes. (SVG source-coordinate mapping is implemented; browser resize/fullscreen coverage is pending.)
- [~] Show class and confidence, backend/model identity, inference FPS/latency, and connection health in a compact diagnostics panel.
- [~] Expire stale detections and visually distinguish degraded metadata from a live video stream.
- [ ] Keep server state in an API/query layer; introduce Zustand only for shared client state that React-local state cannot reasonably own.

#### Backend tests

- [ ] Unit-test inference contract validation, class filtering, confidence filtering, coordinate transforms, queue/drop behavior, timestamp age, redaction, and configuration validation.
- [ ] Contract-test fake and Ultralytics backends with the same redistributable images and tolerance-based expected detections.
- [ ] Integration-test the recorded/synthetic stream through sampling, fake inference, and WebSocket delivery without a physical camera.
- [ ] Test camera/bridge loss, inference exception, slow inference, WebSocket reconnect, and clean shutdown.
- [ ] Add opt-in live-camera smoke tests that skip clearly when credentials/network are unavailable and never retain frames.

#### Frontend and end-to-end tests

- [~] Unit-test overlay geometry, stale-result expiry, reconnect state, diagnostics, and accessibility-critical interactions with Vitest/React Testing Library. (Geometry and expiry are covered; component accessibility/reconnect tests remain.)
- [x] Mock REST/WebSocket/WebRTC boundaries for deterministic component tests.
- [~] Add Playwright flows for initial load, simulated detections, resize/fullscreen geometry, metadata disconnect/recovery, and video failure. (Initial/detection/resize flows are covered; recovery and explicit video-failure flow remain.)
- [x] Run Playwright against deterministic local media/fakes in CI; physical-camera browser validation remains an explicit local smoke test.

#### GitHub Actions CI

- [x] Add least-privilege workflow permissions, concurrency cancellation, dependency caching, and pinned action major versions.
- [x] Run backend format/lint/type/unit/integration jobs on GitHub-hosted Linux without camera secrets.
- [x] Run frontend lint/type/unit/build jobs and Playwright with retained traces only on failure.
- [x] Run secret scanning plus repository checks that reject captures, local configuration, authenticated RTSP URLs, and unapproved large model binaries.
- [x] Validate Compose configuration and build the amd64 development/production images; defer publishing/deployment.
- [~] Make required CI checks and local equivalents explicit in contributor documentation. (README lists checks; CI workflow additions are pending README command reconciliation.)

### Exit criteria

- [ ] A clean clone can start the dev stack with documented prerequisites and live reload works without rebuilding for ordinary Python/React edits.
- [ ] The physical camera streams to a supported browser with no camera URL or credential visible in browser payloads/logs.
- [ ] `person` boxes remain correctly placed during resize/fullscreen and disappear when older than the configured TTL.
- [ ] The pipeline remains responsive under slower-than-source inference because old frames are dropped.
- [ ] CPU inference works on x86; CUDA selection/fallback is reported accurately when applicable.
- [ ] Automated backend, frontend, integration, Playwright, build, and security checks pass in GitHub Actions.
- [ ] Manual smoke results record browser, end-to-end latency, view FPS, inference FPS, CPU/GPU utilization, and known limitations without retaining private media.

### Phase 1 validation evidence

- 2026-07-12: The production-style amd64 API image loaded the checksum-verified YOLOv8n weight on CPU and detected `person` (top confidence 0.87) from a public, temporary fixture; neither weight nor fixture was committed. The backend records CPU fallback when CUDA is unavailable.
- 2026-07-12: The no-camera Compose stack ran with deterministic fake frames. Chromium verified connected detection metadata, an SVG `person` overlay, diagnostics, and the degraded WebRTC state. Real-camera latency/FPS and browser/WebRTC success remain explicit smoke work.

## Phase 2 — Complete Tripwire and deploy to the Orange Pi (pre-auth)

### Outcome

The first camera runs reliably on the Orange Pi using RKNN, offers safe timed PTZ controls, and produces debounced Discord person alerts with redacted snapshots. This completes the practical Tripwire tier while remaining trusted-LAN-only.

### Tasks

#### RKNN deployment

- [ ] Inventory Orange Pi OS/kernel, NPU driver/runtime, Python, Docker/Compose, storage, thermals, and architecture without collecting device identifiers.
- [ ] Pin a compatible RKNN toolkit/runtime/driver matrix and document the model conversion environment separately from the ARM64 runtime.
- [ ] Export and quantize the selected YOLO model with a redistributable calibration dataset; record source, license, checksum, input shape, and conversion settings.
- [ ] Implement the RKNN backend behind the Phase 1 contract with explicit initialization and shutdown; do not rely on forked runtime state.
- [ ] Add golden-image parity tests between Ultralytics and RKNN with documented numerical/detection tolerances.
- [ ] Produce multi-architecture Compose images or architecture-specific inference targets without emulating NPU tests in CI.
- [ ] Benchmark FPS, end-to-end latency, memory, NPU utilization, CPU decode, temperature, and sustained operation; choose nano/small and input size from evidence.
- [ ] Add an opt-in/self-hosted hardware test path; keep GitHub-hosted CI hardware-independent.

#### PTZ

- [ ] Model PTZ as an optional verified capability, not merely an advertised ONVIF service.
- [ ] Implement bounded timed `ContinuousMove` commands using server-enforced speed/duration limits; never rely on unsupported `Stop`.
- [ ] Add keyboard/touch-accessible PTZ controls with press throttling, request state, and failure feedback.
- [ ] Unit-test command bounds/direction mapping and integration-test against a fake ONVIF service.
- [ ] Add a manual physical-camera PTZ checklist that avoids repeated/unattended movement.

#### Alerts and reliability

- [ ] Define alert rule, event, attachment, and notifier contracts; begin with one camera, `person`, confidence threshold, and debounce.
- [ ] Implement an async Discord webhook adapter with timeout, retry/backoff, rate-limit handling, and secret redaction.
- [ ] Capture a bounded in-memory snapshot at trigger time, annotate a copy, and avoid persistence unless explicitly enabled.
- [ ] Add reconnect/backoff and state transitions for camera, restream, inference, and notifier failures.
- [ ] Add stream-down notification policy with state-based suppression to prevent alert storms.
- [ ] Provide a dry-run notifier and require explicit confirmation/configuration before sending real alerts.
- [ ] Test debounce boundaries, duplicate suppression, attachment limits, retry policy, reconnect, secret redaction, and notifier failure isolation.
- [ ] Add Playwright coverage for PTZ states, alert rule display/dry-run, degraded health, and recovery.

### Exit criteria

- [ ] Orange Pi runs the stack through reboot/restart and sustains the agreed performance/thermal envelope.
- [ ] RKNN and development backends satisfy the same contract and acceptable parity thresholds.
- [ ] Browser PTZ performs short bounded moves without requiring `Stop`.
- [ ] A qualifying detection emits at most one Discord alert per debounce window with an annotated snapshot, and dry-run mode emits none.
- [ ] Automated tests pass; hardware-only checks have documented results and skip semantics.

## Phase 3 — Operability, history, and multi-camera groundwork (pre-auth)

### Outcome

The system becomes convenient for daily personal use before authentication is introduced: persistent alert history, editable global configuration, zones/schedules, clips, retention, and a measured path to multiple cameras.

### Tasks

- [ ] Implement SQLite persistence through SQLAlchemy 2 with Alembic migrations for the single-node deployment; keep media outside database rows and avoid SQLite database files on network filesystems.
- [ ] Persist cameras, capability results, alert rules, events, and secret references—never plaintext secrets or authenticated URLs.
- [ ] Keep the persistence/domain boundary compatible with a later PostgreSQL adapter and document the operational conditions that justify migration (multiple app instances, shared/remote database, or sustained write contention).
- [ ] Add alert-history API/UI with pagination, filtering, sorting, snapshot/clip access, and deletion.
- [ ] Add editable confidence, debounce, time schedules, and normalized polygon zones with validation and preview.
- [ ] Add pre-roll ring buffering and configurable 5–30 second alert clips with storage quotas and oldest-first retention.
- [ ] Add manual recording only after retention and disk-full behavior are tested.
- [ ] Generalize orchestration/UI to multiple cameras while sharing or pooling inference workers based on measured memory/throughput.
- [ ] Add optimistic config versioning before multiple authenticated editors exist, so Phase 4 does not retrofit it.
- [ ] Add backup/export with secrets excluded by default and explicit restore validation.
- [ ] Unit/integration-test migrations, rules, zones, schedules, retention, disk-full handling, multi-camera fairness, and backup/restore.
- [ ] Add Playwright coverage for history filters, rule editing conflicts/validation, zone drawing, clip playback, and multi-camera degraded states.
- [ ] Extend GitHub Actions with migration checks and schema/API compatibility checks; deployment remains manual.

### Exit criteria

- [ ] Personal daily-use configuration and history survive restart and migration.
- [ ] Retention prevents unbounded storage and behaves safely when storage is unavailable/full.
- [ ] Multiple simulated cameras cannot starve one another; real second-camera testing waits for hardware/configuration.
- [ ] No export, API, log, or UI surface exposes stored secrets.

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

## Phase 5 and deferred work

- [ ] False-positive feedback and threshold-tuning workflow.
- [ ] ONVIF Profile G discovery and edge-storage integration only after verified hardware tests.
- [ ] Native ONVIF event discovery as an optional signal, never a dependency for YOLO detection.
- [ ] Parcel dataset selection, labeling, training, evaluation, licensing, and model delivery.
- [ ] Person-plus-parcel relational rules, dwell time, disappearance/theft logic, and line crossing.
- [ ] Multi-camera subject correlation and advanced dashboard visualizations.
- [ ] Additional notifiers and external storage backends.
- [ ] Image publishing, signed artifacts/SBOMs, Orange Pi deployment workflow, rollback, and release automation.

## Security hygiene completed during planning

- [x] Confirmed the ignored local `.env` is not present in reachable local Git history.
- [x] Confirmed the example environment file contains no credential values.
- [x] Replaced the tracked camera IP/MAC and helper defaults with environment-driven configuration in the current working tree.
- [x] Verified the physical ONVIF and RTSP services were reachable and an authenticated H.264 pipeline processed the stream without printing credentials.
- [x] Commit the sanitized current state locally.
- [ ] Push the sanitized current state to GitHub.
- [ ] Decide whether to rewrite old public history after reviewing the risk and coordination cost; do not force-push without explicit approval.

## Open decisions and discovery gates

- [ ] Choose the repository copyright holder/notice for the AGPL-3.0 license.
- [ ] Confirm dev machine OS, CPU/GPU/CUDA availability, RAM, and expected browsers.
- [ ] Confirm Orange Pi OS image, NPU driver/runtime state, RAM, storage, and whether it is available during Phase 2.
- [ ] Measure `PROFILE_001` and decide whether inference uses the substream or a downscaled main-stream restream.
- [ ] Set numeric Phase 1 targets after the first baseline: acceptable view latency, detection age, inference FPS, and CPU/GPU usage.
- [ ] Decide later whether snapshots/events may be retained by default; use memory-only behavior through Phase 2.

## Git-history exposure assessment

The historical values are a private LAN address, device MAC, camera model/service layout, and unauthenticated URI shape. The LAN address is not Internet-routable, the MAC is normally useful only on the local network, and the audit found no committed `.env` or obvious assigned credential values. This is low-severity information disclosure, not a credential compromise. Risk rises if camera ports were forwarded publicly, camera credentials were reused elsewhere, or captured media was ever committed.

History can be rewritten with `git-filter-repo --replace-text` in a fresh mirror clone followed by a coordinated force-push. That changes commit hashes and requires other clones to be replaced or carefully cleaned. Forks, existing clones, cached commit views, and pull-request references may retain old content; GitHub Support generally reserves cache/reference cleanup for genuinely sensitive data. Because these identifiers are low sensitivity and current content is sanitized, rewriting is optional rather than urgent. If chosen, take a mirror backup, freeze pushes, enumerate all refs/PRs/forks, verify replacements locally, force-push, and have every collaborator re-clone.

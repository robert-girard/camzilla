# Camzilla Implementation Plan

Status: Phase 1 complete (x86 development scope; Orange Pi deployment deferred to Phase 2)
Last updated: 2026-07-17
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
- Per the 2026-07-17 development-only direction, Orange Pi image production, RKNN conversion/runtime work, and device deployment remain deferred to Phase 2 and do not block Phase 1.
- Browser video uses `go2rtc` WebRTC. Detection metadata travels separately over a backend WebSocket and is rendered on a canvas overlay. HLS/MJPEG is diagnostic fallback only.
- Docker Compose is used for development and deployment. Development uses Vite HMR, FastAPI reload, source sync/bind mounts, and dependency-triggered rebuilds.
- GitHub Actions provides CI for tests, checks, and builds. Deployment automation is deferred.
- The development MVP uses Ultralytics and supports the COCO detection weights for YOLOv8 and YOLO11 in nano, small, and medium sizes under AGPL-3.0; YOLOv8n remains the low-cost default. Keep inference pluggable to preserve a future replacement/enterprise-license path. Orange Pi/RKNN model selection remains a Phase 2 benchmark decision.
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
- [x] State clearly in the root README that Phase 1 production-like Compose validates packaging and CPU/CUDA operation, while supported Orange Pi/RKNN deployment is delivered and documented in Phase 2.

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

- 2026-07-17: GitHub Actions [CI run #2](https://github.com/robert-girard/camzilla/actions/runs/29624848742) passed on commit `1777fa8`: backend format/lint/type/unit/integration checks, frontend lint/type/unit/build/Playwright checks, and the security/Compose configuration, image-build, and clean no-camera startup smoke job all completed successfully.
- 2026-07-17: A redacted physical-camera smoke in Headless Chromium 150 connected WebRTC at 2304x1296 and measured 13.2 displayed FPS over 3 seconds. Browser network requests exposed only `/api/v1/stream` and `/api/v1/webrtc`; metadata remained connected through fullscreen. The HLS diagnostic proxy returned HTTP 200, and the internal bridge reported one producer with three active consumers.
- 2026-07-17: During the physical CPU smoke, YOLOv8n reported about 4.7 inference FPS, 20-26 ms recent inference, zero failures, a 26 ms sampler-capture-to-result interval, and a result observed by the browser at 148 ms old. The API container used about 130% of one CPU core and 545 MiB, go2rtc about 0.8%/17 MiB, and the development frontend about 0.2%/254 MiB at the sampled instant. CUDA was unavailable and the explicit CPU fallback was correct. No frames, recordings, URLs, credentials, or browser artifacts were retained. True scene-to-display latency was not measurable without placing a synchronized time source in the private scene; timestamp metrics begin after decode.
- 2026-07-17: A redacted ONVIF discovery run measured `PROFILE_000` as H.264 2304x1296 at 15 FPS/1536 kbps and `PROFILE_001` as H.264 640x360 at 15 FPS/512 kbps; both returned an RTSP URI. Phase 1 uses the main profile for the single go2rtc upstream and lets inference resize from the shared local restream.
- 2026-07-17: A no-`.env` development Compose build started API, stable go2rtc, and Vite services on loopback. Synthetic fake inference reported ready at about 5 FPS with no failures, browser metadata connected with a visible `person` overlay, and missing video showed the proxied fallback. Touching backend and frontend sources kept the same containers, triggered Uvicorn reload and Vite HMR, and the browser reconnected metadata successfully. This run also exposed and fixed an inherited frontend build/image tag that had produced `npm: not found` before validation.
- 2026-07-17: Backend CI-equivalent checks passed with 34 tests plus 8 intentional hardware/model skips; frontend lint, typecheck, 3 Vitest tests, production build, and 5 deterministic Chromium flows passed. The browser flows cover connected diagnostics, source-coordinate overlay, resize/fullscreen, independent stale expiry, metadata recovery, and video failure/fallback. The CPU image reports the lock-aligned Torch 2.13.0, torchvision 0.28.0, and Ultralytics 8.4.92 versions, and its dependency layer remains cached across application-source-only rebuilds.
- 2026-07-17: All six managed development weights (`yolov8n`, `yolov8s`, `yolov8m`, `yolo11n`, `yolo11s`, and `yolo11m`) matched the SHA-256 values recorded from the official Ultralytics v8.4.0 assets release and passed the shared CPU load, warm-up, synthetic-frame detect, identity, and health contract. Weight binaries remained ignored and were not committed.
- 2026-07-12: The production-style amd64 API image loaded the checksum-verified YOLOv8n weight on CPU and detected `person` (top confidence 0.87) from a public, temporary fixture; neither weight nor fixture was committed. In the no-camera synthetic pipeline it reported 5.0 inference FPS, 31.0 ms most-recent inference, zero failures, and zero dropped frames. The backend records CPU fallback when CUDA is unavailable.
- 2026-07-12: The no-camera Compose stack ran with deterministic fake frames. Chromium verified connected detection metadata, an SVG `person` overlay, diagnostics, and the degraded WebRTC state. The real-camera work that remained at that point was completed by the 2026-07-17 smoke evidence above.

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

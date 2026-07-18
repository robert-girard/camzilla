# PRD: Home Security Camera AI Alert System

## Document Role

This PRD defines product intent, scope, release tiers, and product-level success criteria. The [design document](design-doc-home-security-ai-alerts.md) describes the current technical architecture, the [implementation plan](implementation-plan.md) controls phase sequencing and task status, and the [first-camera notes](../cam_info/README.md) contain device-specific facts. Update this document when accepted decisions change user-visible behavior or release scope; do not use it for task tracking.

## 1. Overview

A self-hosted system that connects to home security cameras (starting with an ONVIF/RTSP camera), runs on-device object detection (YOLO) on an Orange Pi 5's NPU, and sends configurable alerts (starting with Discord) when specified objects or object combinations are detected — e.g. "person + parcel" for package delivery notifications.

The system is designed around pluggable abstractions (cameras, notifiers, inference backends) so it isn't locked into any single camera protocol, alert destination, or compute target.

## 2. Goals

- Reliable, low-latency, on-premises object detection from home camera feeds.
- Configurable, class-combination-aware alerting (not just single-object triggers).
- Rich alerts: text + snapshot/video attachments delivered to Discord (and other notifiers later).
- Live viewing and recorded playback of camera feeds.
- Architecture that supports multiple cameras, multiple camera *types*, multiple notifier types, and operator-selectable inference backends/targets (CPU, GPU, NPU, and future TPU) without rearchitecting later.
- Runs on constrained edge hardware (Orange Pi 5, RK3588 NPU) but is not hard-locked to it — CPU/CUDA deployment should also be viable.

## 3. Non-Goals (for now)

- Per-user settings/personalization (single shared configuration model).
- Full authentication/authorization (deferred until Keycloak is available).
- Multi-camera event correlation (tracking one subject across multiple camera views).
- Reliance on camera-native (e.g. CloudEdge/SD card) motion detection or recording.

## 4. Release Tiers

To keep scope honest and incremental, features are grouped into four tiers:

| Tier | Name | Description |
|---|---|---|
| 1 | **Tripwire** (MVP) | One camera, live view with detection boxes, PTZ, RKNN edge inference, basic debounced Discord snapshot alerts, no auth. |
| 2 | **Stakeout** | Multi-camera support, alert history dashboard, configurable zones/schedules, snapshot/clip attachments, retention, and persistent global configuration. |
| 3 | **Command Center** | Keycloak auth, role enforcement, concurrent-edit safety, protected media/control paths, config backup/export, and false-positive feedback. |
| 4 | **Skynet** (pie-in-the-sky) | Multi-camera correlation, ONVIF Profile G edge-storage integration, advanced dashboard visualizations (timelines, sunbursts), dwell-time/theft detection. |

Implementation phases are intentionally smaller than release tiers. [Implementation Phase 1](implementation-plan.md#phase-1--live-detection-vertical-slice-first-goal) establishes live WebRTC viewing and development-machine detection. [Phase 1b](implementation-plan.md#phase-1b--model-and-inference-target-selection-ui-pre-auth) adds capability-driven model and inference-target selection. [Phase 2](implementation-plan.md#phase-2--complete-tripwire-and-deploy-to-the-orange-pi-pre-auth) adds RKNN, PTZ, Discord alerts, and reliability to complete Tripwire. [Phase 3](implementation-plan.md#phase-3--operability-history-and-multi-camera-groundwork-pre-auth) builds Stakeout capabilities; optional [Phase 3b](implementation-plan.md#phase-3b--detection-category-selection-optional-stretch-goal-pre-auth) adds model-provided detection-category selection before [Phase 4](implementation-plan.md#phase-4--keycloak-authentication-and-concurrent-administration) introduces Keycloak.

## 5. Core Abstractions

These are foundational design decisions that should be in place from the start, even before all features behind them are built:

1. **Camera abstraction** — a base interface (stream access) plus optional capability interfaces cameras may or may not support: PTZ control, IR/light toggle, ONVIF Profile G edge storage (recording control + playback). First implementation: ONVIF/RTSP.
2. **Notifier abstraction** — a generic interface accepting an alert payload (see §6.4) so new notification channels (email, SMS, push) can be added as adapters. First implementation: Discord webhook.
3. **Inference backend abstraction** — a generic "run detection on a frame" interface with swappable backends: RKNN (Orange Pi NPU), standard Ultralytics CPU/CUDA (x86 dev machine, GPU deployments), and future TPU adapters after a concrete target is selected and validated. The server exposes verified backend/model/target capabilities so the UI never treats an advertised but unusable combination as selectable.

## 6. Feature Set

### 6.1 Authentication & Multi-User Config
- **Tier 3.** Login via Keycloak (SSO).
- Configuration is global/shared (no per-user settings), since cameras and alerts are shared infrastructure.
- Concurrent-edit protection needed (e.g. optimistic locking / config version check) to prevent two logged-in users from clobbering each other's changes.
- **Tier 1:** no auth at all (local network only, temporary).

### 6.2 Camera Management
- Add/configure one or more cameras (Tier 1: one camera; Tier 2: multiple).
- Each camera stores its own config: connection details (e.g. RTSP URL, credentials), and which capabilities it supports.
- Built on the camera abstraction (§5) so future camera types/protocols beyond ONVIF/RTSP can be added without breaking existing cameras.
- Optional per-camera capabilities, exposed only if supported by that camera:
  - PTZ control
  - IR / light toggle
  - ONVIF Profile G edge storage (recording control + SD card playback) — **Tier 4**, pending a discovery spike to confirm the specific camera hardware actually supports Profile G (many consumer cameras, including ones paired with apps like CloudEdge, only support Profile S/streaming and keep SD recording proprietary).

### 6.3 Detection & Alerts
- Detection runs via the pluggable inference backend (§5) against each active camera stream.
- A single global operator control selects the model and inference target from combinations the server verifies as installed, compatible, and healthy. CPU, GPU, NPU, and TPU are stable UI categories; unavailable targets remain visible with a reason and cannot be silently downgraded.
- Selection is runtime-only and initialized from deployment defaults until Tier 2 persistence is delivered. Phase 1b enables CPU and available CUDA GPU choices; Phase 2 enables verified RKNN NPU choices. TPU requires a separately scoped hardware/runtime adapter.
- **Phase 3b stretch:** each active model exposes a verified object-detection class catalog, and the operator may select one or more available categories per camera and alert rule. `person` remains the default; unsupported categories cannot be invented or silently remapped when the model changes.
- **Alert definitions:**
  - Composed of one or more target object classes (e.g. "person", "parcel").
  - Assignable to one or more cameras.
  - Configurable debounce/timeout window (e.g. 5/10/15 min) to avoid duplicate alerts for a continuing event.
  - Configurable confidence threshold per alert.
  - Optional zone restriction (region of interest in frame) to reduce false positives outside areas of interest.
  - Optional time-of-day scheduling (e.g. only armed overnight).
  - Optional relational logic (e.g. person + parcel bounding-box overlap/proximity) rather than simple single-class detection.
- **Stretch/future alert logic (Tier 4):**
  - Line-crossing / directional detection (e.g. "approaching" vs. "passing").
  - Dwell-time / disappearance detection (e.g. package present, then gone with no person nearby — theft alert).
  - Multi-camera correlation (same subject tracked across camera views).

### 6.4 Notifications
- Built on the notifier abstraction (§5); Discord webhook is the first implementation.
- **Alert payload model:**
  - Required text component (human-readable message).
  - Optional list of attachments, each described by MIME type + data/reference, so each notifier adapter can decide what it supports (e.g. Discord can embed image/video; SMS might fall back to text-only or a link).
- Attachments:
  - **Tier 1/2:** snapshot image.
  - **Tier 2:** configurable 5–30 second video clip.
  - Consider pre-roll buffering (capturing a few seconds *before* the trigger, not just after).

### 6.5 Live View & Recording
- **Live view:** on-demand viewing of a given camera's current stream from the browser.
- **Recorded history:** playback of past footage, retained per a configurable policy.
- **Recording triggers:**
  - Automatic recording tied to alerts (using the alert's configured clip duration).
  - Manual start/stop recording from the camera page.
  - Scheduled recording windows.
- **Retention policy** (to be refined during implementation as storage patterns become clear):
  - Storage backend and quota per camera (local disk vs. network share).
  - Behavior at quota limit (oldest-first deletion vs. alert/notify admin).
  - Possibly different retention windows for alert-triggered clips vs. manual/scheduled recordings.
  - SD-card-based storage (via ONVIF Profile G) as a *possible* secondary option — **Tier 4, contingent on discovery spike.**

### 6.6 Alert History Dashboard
- **Tier 2:** simple sortable/filterable table of past alerts, with downloadable snapshots/clips.
- **Tier 4:** richer visualizations (timeline view, alert-type breakdowns/sunbursts, etc.).
- **Tier 3:** false-positive feedback mechanism (mark an alert as wrong) to support future threshold tuning.

### 6.7 System Health & Reliability
- Auto-reconnect on camera/stream disconnect.
- Configurable stream-down alerting (e.g. alert once immediately, then repeat at a configurable interval such as hourly, rather than spamming continuously).

### 6.8 Configuration Management
- **Tier 2:** config backup/export so camera and alert setup isn't lost if the Orange Pi has issues. Exports exclude secrets by default.
- Persistent configuration and event metadata must support schema migrations and backup/restore. Media is retained separately from relational metadata, and credentials remain external to persisted application state.

## 7. Open Questions / Discovery Items

- Does the specific camera hardware support ONVIF Profile G (recording control + SD card playback), or only Profile S (streaming)? Needs a hands-on discovery spike.
- If Profile G *is* supported, can it be used concurrently with the camera's existing CloudEdge app/account, or is camera access exclusive to one client at a time?
- Can the camera's native motion detection/analytics be accessed via ONVIF Events, or is it fully proprietary to CloudEdge? (Current assumption: treat it as inaccessible/irrelevant — the system will use its own YOLO-based detection instead of relying on camera-native motion triggers.)

## 8. Model / Detection Notes (background, informs design doc)

- Ultralytics YOLOv8 and YOLO11 COCO detection weights in nano, small, and medium sizes are selectable for development CPU/CUDA inference. YOLOv8n remains the default because it has the lowest development compute cost. RKNN parity and the supported production model are selected from Orange Pi measurements in implementation Phase 2; development availability does not imply NPU suitability.
- The selection UI is capability-driven rather than a promise that every model runs on every target. It may show CPU, GPU, NPU, and TPU categories, but it enables only verified backend/model artifacts and gives an explicit reason for unavailable combinations.
- Phase 3b category selection refers to object-detection classes emitted with boxes and confidence values, not a separate image-classification model. Cross-model selections use verified semantic IDs rather than assuming equal numeric class indices or similar labels are equivalent.
- Camzilla will use Ultralytics under AGPL-3.0 for the MVP. Code, weights, datasets, and generated model artifacts require recorded license provenance and checksums.
- COCO-pretrained models cover "person" well but have no generic "package/box" class — a fine-tuned model (e.g. via Ultralytics' package segmentation dataset or Roboflow community datasets) will be needed for parcel detection.
- Target performance envelope: near-real-time (5–10 fps acceptable) across multiple camera streams on the Orange Pi 5's NPU (~6 TOPS).

## 9. Success Criteria

### First Implementation Slice (Implementation Phase 1)

- One physical camera works in an in-browser WebRTC viewer on the x86 development machine.
- A selectable YOLOv8/YOLO11 nano, small, or medium weight detects `person` through a pluggable inference backend and sends timestamped, backend-neutral detection metadata; YOLOv8n is the default.
- Class/confidence bounding boxes render correctly over the live video, including resize/fullscreen handling and stale-result expiry.
- CPU inference works; CUDA is selected only when configured and available, with an explicit fallback.
- Backend, frontend, integration, Playwright, build, and security checks run in GitHub Actions without physical-camera access or secrets.
- No PTZ, Discord alert, persistence, recording, multi-camera UI, or authentication is required for this first slice.

### Inference Selection Slice (Implementation Phase 1b)

- The single-camera page displays the active model, backend, and CPU/GPU/NPU/TPU target category and can apply any combination the server reports as available.
- All six managed YOLO development weights can be selected for CPU inference; CUDA GPU choices are enabled only when CUDA is verified available.
- NPU and TPU choices are capability-gated: RKNN becomes selectable after Phase 2 hardware work, while TPU remains unavailable until a concrete adapter and model pipeline are validated.
- Switching is transactional: a failed load or warm-up retains the last healthy inference backend, stale detections are cleared, and the confirmed identity is reflected in health and detection metadata.
- The unauthenticated selection is global, runtime-only, loopback-by-default, and does not accept arbitrary model uploads, URLs, or filesystem paths.

### MVP Release (Tripwire; Implementation Phases 1, 1b, and 2)

- Live view of the camera stream works in-browser.
- PTZ control works from the browser.
- Basic object detection (person, at minimum) runs and can trigger a Discord alert with a snapshot.
- Detection runs against the same pluggable inference contract on Ultralytics CPU/CUDA and RKNN.
- Camera, streaming, inference, and notifier failures reconnect or fail safely without unbounded queues or alert storms.
- No authentication required (temporary, pending Keycloak).

### Detection Category Selection Stretch (Implementation Phase 3b)

- The active model's verified class catalog drives per-camera and per-alert-rule multi-select controls, allowing supported categories beyond `person`.
- Overlay publication, events, snapshots/clips, and alert evaluation consistently honor the saved category selections.
- Model/backend changes preserve categories only through verified stable semantic IDs and require explicit resolution for unsupported selections.
- Category selections persist, migrate, export, and restore without exposing secrets or losing the model/catalog revision needed to interpret historical events.

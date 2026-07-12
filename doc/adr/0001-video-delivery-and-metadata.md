# ADR 0001: WebRTC video and separate detection metadata

## Status

Accepted — 2026-07-11.

## Decision

`go2rtc` converts the camera's single upstream RTSP connection to WebRTC for
the browser. FastAPI publishes versioned, timestamped normalized detections on
a separate WebSocket. The browser draws those detections in a non-interactive
overlay; they are never burned into video.

## Consequences

The browser retains native-rate viewing while inference can sample and drop old
frames independently. Overlay synchronization is best-effort, so clients must
show result age and expire stale data. HLS/MJPEG remain diagnostic fallbacks.

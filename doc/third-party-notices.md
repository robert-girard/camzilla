# Third-party and model provenance

Camzilla is distributed under AGPL-3.0-or-later. Phase 1 is designed to use the
[Ultralytics](https://github.com/ultralytics/ultralytics) package and YOLOv8n
weights under the Ultralytics AGPL-3.0 license path. Before enabling the
Ultralytics backend, record the exact package version and SHA-256 of the
downloaded weights in `models/manifest.yaml`; do not commit the weights.

The deterministic fake backend is used by default in development and CI and has
no model or dataset dependency. Test fixtures must be synthetic or explicitly
redistributable and must never be derived from a private camera.

`go2rtc` is used as the RTSP/WebRTC bridge. Its image version is pinned in the
Compose configuration and its upstream license/provenance must be retained when
shipping a distribution image.

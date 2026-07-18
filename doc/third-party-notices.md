# Third-party and model provenance

Camzilla is distributed under AGPL-3.0-or-later. Phase 1 is designed to use the
[Ultralytics](https://github.com/ultralytics/ultralytics) package and the
recorded YOLOv8/YOLO11 detection weights under the Ultralytics AGPL-3.0 license
path. Phase 1 supports nano, small, and medium weights for each generation.
Before enabling the Ultralytics backend, verify the exact artifact SHA-256
against `models/manifest.yaml`; do not commit the weights.

The deterministic fake backend is used by default in development and CI and has
no model or dataset dependency. Test fixtures must be synthetic or explicitly
redistributable and must never be derived from a private camera.

`go2rtc` is used as the RTSP/WebRTC bridge. Its image version is pinned in the
Compose configuration and its upstream license/provenance must be retained when
shipping a distribution image.

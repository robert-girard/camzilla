# BCXAXA Camera Notes

## Document Role

This file records sanitized, device-specific observations for Camzilla's first camera. Use it when implementing or diagnosing ONVIF discovery, RTSP intake, media profiles/codecs, GStreamer pipelines, PTZ, or opt-in hardware smoke tests. It is not a general camera contract and the physical device must never be required by CI.

See the [PRD](../doc/PRD-home-security-ai-alerts.md) for product requirements, the [design document](../doc/design-doc-home-security-ai-alerts.md) for how this camera fits the streaming/inference architecture, and the [implementation plan](../doc/implementation-plan.md) for scheduled camera work and acceptance criteria. Keep real addresses, credentials, captures, and household details in ignored local configuration—not this public document.

## Device

- Camera: BCXAXA IP camera
- LAN host: stored in `.env` as `CAMERA_HOST`
- ONVIF username: stored in `.env` as `ONVIF_USER`
- ONVIF password: stored in `.env` as `ONVIF_PASSWORD`

The camera initially looked closed from a normal port scan, but after ONVIF was enabled it exposed ONVIF on TCP port `8000` and RTSP on TCP port `8554`.

## ONVIF Endpoints

The device advertises these ONVIF service addresses:

- Device: `http://${CAMERA_HOST}:${ONVIF_PORT}/onvif/device_service`
- Media: `http://${CAMERA_HOST}:${ONVIF_PORT}/onvif/Media`
- PTZ: `http://${CAMERA_HOST}:${ONVIF_PORT}/onvif/PTZ`
- Imaging: `http://${CAMERA_HOST}:${ONVIF_PORT}/onvif/Imaging`
- DeviceIO: `http://${CAMERA_HOST}:${ONVIF_PORT}/onvif/DeviceIO`
- Analytics: `http://${CAMERA_HOST}:${ONVIF_PORT}/onvif/Analytics`
- Recording: `http://${CAMERA_HOST}:${ONVIF_PORT}/onvif/Recording`
- Search: `http://${CAMERA_HOST}:${ONVIF_PORT}/onvif/SearchRecording`
- Replay: `http://${CAMERA_HOST}:${ONVIF_PORT}/onvif/Replay`

The helper script `onvif_stream.py` queries the ONVIF media service for profiles and the stream URI:

```bash
./onvif_stream.py
```

Known profiles:

- `PROFILE_000`: H.264, 2304x1296, 15 FPS, 1536 kbps
- `PROFILE_001`: H.264, 640x360, 15 FPS, 512 kbps

Both profiles returned an RTSP URI in the sanitized 2026-07-17 discovery run.
Phase 1 selects `PROFILE_000` for the viewer and the single shared go2rtc
upstream. Inference consumes that same local restream and resizes internally;
using `PROFILE_001` for inference would otherwise require a second upstream
camera session or reduce viewer quality. Revisit this tradeoff only if measured
decode cost justifies changing the fan-out design.

The first profile returned this sanitized RTSP URL shape:

```text
rtsp://${CAMERA_HOST}:${RTSP_PORT}${RTSP_PATH}
```

RTSP requires authentication, so most tools should use:

```text
rtsp://${ONVIF_USER}:${ONVIF_PASSWORD}@${CAMERA_HOST}:${RTSP_PORT}${RTSP_PATH}
```

## RTSP Stream

The RTSP server responds to standard RTSP methods:

- `OPTIONS`
- `DESCRIBE`
- `SETUP`
- `PLAY`
- `PAUSE`
- `TEARDOWN`

Observed server string:

```text
Server: rtsp_demo
```

The stream carries:

- Video: H.264 over RTP
- Audio: PCMU over RTP, 8000 Hz

GStreamer confirmed video RTP caps like:

```text
application/x-rtp, media=video, encoding-name=H264, payload=96
```

and audio RTP caps like:

```text
application/x-rtp, media=audio, encoding-name=PCMU, clock-rate=8000
```

## PTZ

The camera advertises a PTZ ONVIF service and returned PTZ nodes/configurations.

Observed nodes/configs:

- `NODE_000`
- `NODE_001`
- `PTZ_000`
- `PTZ_001`

Advertised PTZ spaces include:

- Absolute pan/tilt position
- Absolute zoom position
- Relative pan/tilt translation
- Relative zoom translation
- Continuous pan/tilt velocity
- Continuous zoom velocity
- Pan/tilt speed
- Zoom speed

The service accepted a short `ContinuousMove` command:

```text
ContinuousMove right 0.2 for PT1S -> HTTP 200
```

But these actions returned `Action Not Implemented`:

- `GetStatus`
- `Stop`

Because `Stop` is not implemented, PTZ movement should use short timed `ContinuousMove` commands with a timeout instead of relying on a separate stop call.

Use `ptz_control.py`:

```bash
./ptz_control.py left
./ptz_control.py right
./ptz_control.py up
./ptz_control.py down
./ptz_control.py in
./ptz_control.py out
```

Optional speed/time:

```bash
./ptz_control.py right --speed 0.1 --seconds 1
```

## Toolchains Used

### Network and Service Probing

Tools used:

- `ping` to confirm the camera was reachable.
- `arp` / `ip neigh` to inspect the local MAC address.
- `nc` to check whether TCP ports were open.
- `curl` to test HTTP/ONVIF endpoints.
- Small Python scripts using `requests` for SOAP/ONVIF calls.

Important ports:

- `8000/tcp`: ONVIF HTTP SOAP services.
- `8554/tcp`: RTSP stream.

### ONVIF SOAP

The Python helpers manually build ONVIF SOAP requests with WS-Security UsernameToken digest authentication.

Authentication includes:

- Username
- Password digest
- Nonce
- UTC creation timestamp

This avoided needing a full ONVIF Python package. The local environment did not initially have `onvif` or `zeep` installed, but `requests` was available and was enough for these calls.

### GStreamer

GStreamer is the main working local media toolchain.

Because this shell inherited some VS Code Snap-related environment variables, `gst-launch-1.0` initially tried to load incompatible Snap libraries and failed with a `libpthread` symbol error. The scripts run GStreamer with a clean environment:

```bash
env -i HOME="$HOME" USER="$USER" DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" XDG_RUNTIME_DIR="$XDG_RUNTIME_DIR" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin ...
```

That makes `/usr/bin/gst-launch-1.0` use the system GStreamer libraries.

### VLC

VLC should play the RTSP URL directly:

```text
rtsp://${ONVIF_USER}:${ONVIF_PASSWORD}@${CAMERA_HOST}:${RTSP_PORT}${RTSP_PATH}
```

VLC did not play the raw `stream.h264` recording reliably because that file was only an elementary H.264 stream, not a media container with timestamps and metadata.

## Processing and Packaging Pipelines

### Live RTSP Intake

The camera sends H.264 video inside RTP packets over RTSP:

```text
Camera -> RTSP -> RTP/H.264 packets
```

GStreamer receives that with:

```text
rtspsrc
```

Then dynamic pads are filtered so only the video stream is used:

```text
src. ! application/x-rtp,media=video,encoding-name=H264
```

### Depayloading

RTP is a packet transport. Before saving or decoding, the H.264 payload must be removed from RTP packets:

```text
rtph264depay
```

This converts:

```text
RTP/H.264 packets -> H.264 stream
```

### Raw H.264 Recording

The first raw recording pipeline was:

```text
rtspsrc -> rtph264depay -> filesink
```

That produced `stream.h264`.

This proves video capture works, but the output is not a normal playable container. It lacks the wrapping, timestamps, and metadata that players expect from files like MKV, MP4, AVI, or MOV.

Raw mode is still available:

```bash
./record_camera.sh "rtsp://${ONVIF_USER}:${ONVIF_PASSWORD}@${CAMERA_HOST}:${RTSP_PORT}${RTSP_PATH}" stream.h264 30 raw
```

### Why `h264parse` Matters

`h264parse` is a GStreamer parser for H.264. It normalizes the H.264 stream for downstream elements.

It handles details such as:

- Frame/access-unit alignment.
- SPS/PPS codec parameter handling.
- Stream format conversion, such as byte-stream vs AVC.
- Parsed caps negotiation for muxers.

Without `h264parse`, this failed:

```text
rtspsrc -> rtph264depay -> matroskamux -> filesink
```

The error was:

```text
streaming stopped, reason not-negotiated
```

That means the depayloader and muxer could not agree on the exact H.264 format/caps. Installing `gstreamer1.0-plugins-bad` added `h264parse`, and MKV packaging started working.

Verified parser:

```text
Plugin: videoparsersbad
Element: h264parse
Package: GStreamer Bad Plugins
```

### Efficient MKV Recording

Current preferred recording pipeline:

```text
rtspsrc -> rtph264depay -> h264parse -> matroskamux -> filesink
```

In command form:

```bash
gst-launch-1.0 -e \
  rtspsrc name=src location="rtsp://${ONVIF_USER}:${ONVIF_PASSWORD}@${CAMERA_HOST}:${RTSP_PORT}${RTSP_PATH}" protocols=tcp latency=200 \
  src. ! 'application/x-rtp,media=video,encoding-name=H264' ! \
  rtph264depay ! h264parse config-interval=-1 ! matroskamux ! filesink location=camera.mkv
```

This packages the camera's original H.264 into Matroska without decoding and re-encoding. It is much more efficient than AVI/MJPEG.

The `record_camera.sh` default now records MKV:

```bash
./record_camera.sh
```

Default output:

```text
camera.mkv
```

Custom duration/output:

```bash
./record_camera.sh "rtsp://${ONVIF_USER}:${ONVIF_PASSWORD}@${CAMERA_HOST}:${RTSP_PORT}${RTSP_PATH}" front-door.mkv 60
```

### AVI/MJPEG Fallback

Before `h264parse` was installed, AVI/MJPEG was used as a VLC-friendly fallback:

```text
rtspsrc -> rtph264depay -> avdec_h264 -> videoconvert -> jpegenc -> avimux -> filesink
```

This decodes the camera's H.264 and re-encodes each frame as JPEG inside AVI.

Pros:

- Easy for VLC to play.
- Does not require `h264parse`.

Cons:

- Larger files.
- More CPU.
- Lower efficiency than copying the original H.264 stream.

AVI fallback is still available:

```bash
./record_camera.sh "rtsp://${ONVIF_USER}:${ONVIF_PASSWORD}@${CAMERA_HOST}:${RTSP_PORT}${RTSP_PATH}" camera.avi 30 avi
```

## Files in This Workspace

- `onvif_stream.py`: Queries ONVIF media profiles and prints the RTSP URI.
- `ptz_control.py`: Sends short timed ONVIF PTZ `ContinuousMove` commands.
- `record_camera.sh`: Records the RTSP stream. Defaults to MKV/H.264 packaging.
- `view_camera.sh`: Attempts live viewing through GStreamer.
- `snapshot.jpg`: Verified JPEG snapshot from the stream, `2304x1296`.
- `stream.h264`: Raw H.264 elementary stream recording.
- `camera.mkv`: Matroska/H.264 recording.
- `camera.avi`: AVI/MJPEG fallback recording.

## Recommended Current Commands

Discover stream URI:

```bash
./onvif_stream.py
```

Record 30 seconds to MKV:

```bash
./record_camera.sh
```

Record 60 seconds to a named MKV:

```bash
./record_camera.sh "rtsp://${ONVIF_USER}:${ONVIF_PASSWORD}@${CAMERA_HOST}:${RTSP_PORT}${RTSP_PATH}" camera-60s.mkv 60
```

Move PTZ right briefly:

```bash
./ptz_control.py right --speed 0.1 --seconds 1
```

Open directly in VLC:

```bash
vlc "rtsp://${ONVIF_USER}:${ONVIF_PASSWORD}@${CAMERA_HOST}:${RTSP_PORT}${RTSP_PATH}"
```

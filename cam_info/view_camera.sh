#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
env_file="$script_dir/.env"

if [[ -f "$env_file" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    export "$key=$value"
  done < "$env_file"
fi

if [[ $# -gt 0 ]]; then
  uri="$1"
else
  : "${CAMERA_HOST:?Set CAMERA_HOST in .env or pass an RTSP URI as the first argument}"
  : "${ONVIF_USER:?Set ONVIF_USER in .env or pass an RTSP URI as the first argument}"
  : "${ONVIF_PASSWORD:?Set ONVIF_PASSWORD in .env or pass an RTSP URI as the first argument}"
  uri="rtsp://${ONVIF_USER}:${ONVIF_PASSWORD}@${CAMERA_HOST}:${RTSP_PORT:-8554}${RTSP_PATH:-/Streaming/Channels/101}"
fi

env -i \
  HOME="$HOME" \
  USER="${USER:-robert}" \
  DISPLAY="${DISPLAY:-}" \
  XAUTHORITY="${XAUTHORITY:-}" \
  XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  /usr/bin/gst-launch-1.0 \
    rtspsrc name=src location="$uri" protocols=tcp latency=200 \
    src. ! 'application/x-rtp,media=video,encoding-name=H264' ! \
    rtph264depay ! avdec_h264 ! videoconvert ! autovideosink

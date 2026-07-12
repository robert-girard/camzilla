#!/usr/bin/env bash
set -euo pipefail

# Check tracked content only: ignored local camera data may exist for opt-in
# hardware work but must never enter a commit or CI artifact.
tracked="$(git ls-files)"

if printf '%s\n' "$tracked" | rg -v '(^|/)\.env\.example$' | rg -q '(^|/)\.env($|\.)'; then
  echo 'tracked local environment file detected' >&2
  exit 1
fi

if printf '%s\n' "$tracked" | rg -q '\.(avi|mkv|jpg|jpeg|png|h264)$'; then
  echo 'tracked capture or image detected' >&2
  exit 1
fi

if printf '%s\n' "$tracked" | rg -q '(^|/)models/.*\.(pt|onnx|rknn)$'; then
  echo 'tracked model binary detected' >&2
  exit 1
fi

# Permit variable-based examples (rtsp://${USER}:${PASSWORD}@...), but reject
# a literal user:password authority component anywhere in tracked text.
auth_pattern='rtsp://'
auth_pattern+='[^[:space:]$@]+:[^[:space:]@]+@'
if git grep -nE "$auth_pattern" -- ':!cam_info/.env.example'; then
  echo 'authenticated RTSP URL detected' >&2
  exit 1
fi

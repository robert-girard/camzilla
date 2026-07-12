"""Opt-in smoke check for the local go2rtc restream; never writes a frame."""

import importlib.util
import os

import pytest


@pytest.mark.skipif(
    os.getenv("CAMZILLA_HARDWARE_SMOKE") != "1",
    reason="set CAMZILLA_HARDWARE_SMOKE=1 to probe the local restream",
)
def test_local_restream_yields_an_in_memory_frame() -> None:
    if importlib.util.find_spec("cv2") is None:
        pytest.skip("OpenCV is only installed with the Ultralytics runtime extra")
    import cv2

    restream_url = os.getenv("CAMZILLA_INFERENCE_RESTREAM_URL")
    if not restream_url:
        pytest.skip("CAMZILLA_INFERENCE_RESTREAM_URL is not configured")
    capture = cv2.VideoCapture(restream_url)
    try:
        if not capture.isOpened():
            pytest.skip("local restream is unavailable")
        ok, frame = capture.read()
        if not ok or frame is None:
            pytest.skip("local restream returned no frame")
        assert frame.size > 0
    finally:
        capture.release()

from fastapi.testclient import TestClient

from app.main import app


def test_stream_descriptor_is_sanitized() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/stream")
    assert response.status_code == 200
    assert response.json() == {
        "camera_name": "front-door",
        "webrtc_path": "/webrtc/front-door",
        "diagnostic_fallback": "hls",
    }
    assert "rtsp" not in response.text.lower()


def test_readiness_does_not_return_camera_url() -> None:
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert "camera_rtsp_url" not in response.text

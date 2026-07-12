from fastapi.testclient import TestClient

from app.main import app


def test_stream_descriptor_is_sanitized() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/stream")
    assert response.status_code == 200
    assert response.json() == {
        "camera_name": "front-door",
        "webrtc_path": "/api/v1/webrtc",
        "diagnostic_fallback": "hls",
    }
    assert "rtsp" not in response.text.lower()


def test_readiness_does_not_return_camera_url() -> None:
    with TestClient(app) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert "camera_rtsp_url" not in response.text


def test_fake_pipeline_delivers_versioned_detection_over_websocket() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/detections") as websocket:
            message = websocket.receive_json()
    assert message["version"] == "v1"
    assert message["sequence"] >= 0
    assert message["detections"][0]["class_name"] == "person"


def test_whep_proxy_uses_internal_bridge_and_returns_only_sdp(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        status_code = 200
        content = b"v=0\r\n"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, content, headers):
            calls.append((url, content, headers))
            return FakeResponse()

    monkeypatch.setattr("app.main.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    with TestClient(app) as client:
        response = client.post("/api/v1/webrtc", content=b"v=0\r\n")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/sdp"
    assert calls[0][0] == "http://go2rtc:1984/api/webrtc?src=front-door"

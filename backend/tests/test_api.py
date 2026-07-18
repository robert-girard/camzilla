import httpx
from fastapi.testclient import TestClient

from app.contracts import PtzCapabilityResponse
from app.main import app
from app.ptz import PtzService


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
    assert response.json()["camera"] == {"configured": False, "state": "not_configured"}
    assert response.json()["bridge"] == {"state": "synthetic"}
    assert response.json()["inference"]["fallback_reason"] is None


def test_fake_pipeline_delivers_versioned_detection_over_websocket() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/detections") as websocket:
            message = websocket.receive_json()
    assert message["version"] == "v1"
    assert message["sequence"] >= 0
    assert message["detections"][0]["class_name"] == "person"
    assert message["target"] == "cpu"
    assert message["device"] == "synthetic"


def test_inference_capabilities_are_typed_and_paths_are_redacted() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/inference")
    assert response.status_code == 200
    payload = response.json()
    assert payload["active"]["capability_id"] == "fake:fake-person-v1:cpu"
    assert payload["runtime_only"] is True
    assert {item["target"] for item in payload["capabilities"]} == {
        "cpu",
        "gpu",
        "npu",
        "tpu",
    }
    assert "/models" not in response.text
    assert ".pt" not in response.text


def test_inference_selection_rejects_unknown_and_unavailable_ids() -> None:
    with TestClient(app) as client:
        missing = client.put(
            "/api/v1/inference/selection", json={"capability_id": "fake:missing:cpu"}
        )
        unavailable = client.put(
            "/api/v1/inference/selection",
            json={"capability_id": "rknn:unconfigured:npu"},
        )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "inference capability not found"}
    assert unavailable.status_code == 409
    assert unavailable.json() == {"detail": "inference capability is unavailable"}


def test_ptz_capability_is_unavailable_until_operation_verified() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/cameras/front-door/capabilities/ptz")
        move = client.post(
            "/api/v1/cameras/front-door/ptz",
            json={"direction": "left", "speed": 0.2, "duration_seconds": 0.5},
        )
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["supports_stop"] is False
    assert move.status_code == 409
    assert move.json() == {"detail": "PTZ is unavailable"}


def test_ptz_endpoint_uses_bounded_request_and_redacts_adapter_failure() -> None:
    class BrokenController:
        async def continuous_move(self, _request):
            raise RuntimeError("private ONVIF endpoint and credentials")

    capability = PtzCapabilityResponse(
        camera_name="front-door",
        available=True,
        verified=True,
        supports_continuous_move=True,
    )
    with TestClient(app) as client:
        app.state.ptz = PtzService(capability, BrokenController())
        response = client.post(
            "/api/v1/cameras/front-door/ptz",
            json={"direction": "up", "speed": 0.2, "duration_seconds": 0.5},
        )
        unbounded = client.post(
            "/api/v1/cameras/front-door/ptz",
            json={"direction": "up", "speed": 1, "duration_seconds": 10},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "PTZ command failed"}
    assert "private ONVIF" not in response.text
    assert unbounded.status_code == 422


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


def test_hls_diagnostic_rewrites_internal_playlist_paths(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200
        content = b"#EXTM3U\nhls/playlist.m3u8?id=abc\n"
        headers = {"content-type": "application/vnd.apple.mpegurl"}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return FakeResponse()

    monkeypatch.setattr("app.main.httpx.AsyncClient", lambda **_kwargs: FakeClient())
    with TestClient(app) as client:
        response = client.get("/api/v1/diagnostics/hls/stream.m3u8")
    assert response.status_code == 200
    assert "/api/v1/diagnostics/hls/playlist.m3u8?id=abc" in response.text


def test_bridge_connection_failure_returns_a_sanitized_error(monkeypatch) -> None:
    class BrokenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            request = httpx.Request("POST", "http://go2rtc:1984/api/webrtc")
            raise httpx.ConnectError("private camera source details", request=request)

    monkeypatch.setattr("app.main.httpx.AsyncClient", lambda **_kwargs: BrokenClient())
    with TestClient(app) as client:
        response = client.post("/api/v1/webrtc", content=b"v=0\r\n")
    assert response.status_code == 503
    assert response.json() == {"detail": "video bridge unavailable"}
    assert "private camera source details" not in response.text


def test_hls_diagnostic_rejects_unapproved_bridge_paths() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/diagnostics/hls/admin/config")
    assert response.status_code == 404


def test_readiness_reports_a_redacted_source_failure() -> None:
    with TestClient(app) as client:
        app.state.pipeline.source_error = "RuntimeError"
        response = client.get("/health/ready")
    assert response.json()["status"] == "degraded"
    assert response.json()["bridge"] == {"state": "error"}
    assert "rtsp" not in response.text.lower()

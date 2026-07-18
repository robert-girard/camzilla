from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
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
    assert message["detections"][0]["semantic_id"] == "coco:person"
    assert message["detections"][0]["native_class_id"] == 0
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


def test_category_catalog_selection_and_model_switch_conflict_are_explicit() -> None:
    multi_id = "fake:fake-multi-v1:cpu"
    person_id = "fake:fake-person-v1:cpu"
    with TestClient(app) as client:
        switched = client.put("/api/v1/inference/selection", json={"capability_id": multi_id})
        initial = client.get("/api/v1/cameras/front-door/categories")
        changed = client.put(
            "/api/v1/cameras/front-door/categories",
            json={
                "expected_config_version": initial.json()["config_version"],
                "catalog_revision": "coco-person-car-dog-v1",
                "category_ids": ["coco:person", "coco:car"],
            },
        )
        configuration = client.get("/api/v1/config").json()
        rule = client.put(
            "/api/v1/alert-rules/person-detected",
            json={
                "expected_config_version": configuration["version"],
                "confidence_threshold": 0.6,
                "debounce_seconds": 300,
                "target_categories": ["coco:person", "coco:car"],
            },
        )
        compatibility = client.get(f"/api/v1/inference/compatibility/{person_id}")
        blocked = client.put("/api/v1/inference/selection", json={"capability_id": person_id})
        active = client.get("/api/v1/inference")

    assert switched.status_code == 200
    assert [item["semantic_id"] for item in initial.json()["catalog"]["categories"]] == [
        "coco:person",
        "coco:car",
        "coco:dog",
    ]
    assert changed.status_code == 200
    assert changed.json()["selected_category_ids"] == ["coco:person", "coco:car"]
    assert rule.status_code == 200
    assert compatibility.json() == {
        "capability_id": person_id,
        "catalog_revision": "coco-person-v1",
        "compatible": False,
        "retained_category_ids": ["coco:person"],
        "missing_category_ids": ["coco:car"],
        "affected_camera_ids": ["front-door"],
        "affected_rule_ids": ["person-detected"],
        "available_category_ids": ["coco:person"],
    }
    assert blocked.status_code == 409
    assert "invalidate categories" in blocked.json()["detail"]
    assert active.json()["active"]["capability_id"] == multi_id


def test_category_update_validates_revision_ids_rules_and_version() -> None:
    with TestClient(app) as client:
        current = client.get("/api/v1/cameras/front-door/categories").json()
        stale_revision = client.put(
            "/api/v1/cameras/front-door/categories",
            json={
                "expected_config_version": current["config_version"],
                "catalog_revision": "removed-catalog-v1",
                "category_ids": ["coco:person"],
            },
        )
        unknown = client.put(
            "/api/v1/cameras/front-door/categories",
            json={
                "expected_config_version": current["config_version"],
                "catalog_revision": current["catalog"]["revision"],
                "category_ids": ["custom:parcel"],
            },
        )
        empty = client.put(
            "/api/v1/cameras/front-door/categories",
            json={
                "expected_config_version": current["config_version"],
                "catalog_revision": current["catalog"]["revision"],
                "category_ids": [],
            },
        )
    assert stale_revision.status_code == 409
    assert unknown.status_code == 422
    assert empty.status_code == 422


def test_cameras_persist_independent_category_allowlists() -> None:
    with TestClient(app) as client:
        client.put(
            "/api/v1/inference/selection",
            json={"capability_id": "fake:fake-multi-v1:cpu"},
        )
        version = client.get("/api/v1/config").json()["version"]
        created = client.post(
            "/api/v1/cameras",
            json={
                "expected_config_version": version,
                "id": "side-door",
                "name": "Side door",
                "stream_secret_ref": "env:CAMZILLA_SIDE_DOOR_RTSP_URL",
            },
        )
        changed = client.put(
            "/api/v1/cameras/side-door/categories",
            json={
                "expected_config_version": created.json()["version"],
                "catalog_revision": "coco-person-car-dog-v1",
                "category_ids": ["coco:person", "coco:dog"],
            },
        )
        front = client.get("/api/v1/cameras/front-door/categories")

    assert changed.status_code == 200
    assert changed.json()["selected_category_ids"] == ["coco:person", "coco:dog"]
    assert front.json()["selected_category_ids"] == ["coco:person"]


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


def test_alert_status_defaults_to_external_delivery_safe_dry_run() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/alerts/status")
    assert response.status_code == 200
    assert response.json()["requested_notifier"] == "dry-run"
    assert response.json()["effective_notifier"] == "dry-run"
    assert response.json()["external_delivery_configured"] is False
    assert "webhook" not in response.text.lower()


def test_persisted_configuration_updates_optimistically_without_secret_values() -> None:
    with TestClient(app) as client:
        current = client.get("/api/v1/config")
        version = current.json()["version"]
        update = {
            "expected_config_version": version,
            "confidence_threshold": 0.72,
            "debounce_seconds": 60,
            "schedule_start": "22:00",
            "schedule_end": "06:00",
            "zone": {"points": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.5, "y": 0.9}]},
            "target_categories": ["coco:person"],
        }
        changed = client.put("/api/v1/alert-rules/person-detected", json=update)
        conflict = client.put("/api/v1/alert-rules/person-detected", json=update)
    assert current.status_code == 200
    assert "secret_ref" not in current.text
    assert "rtsp://" not in current.text
    assert "discord.com/api/webhooks" not in current.text
    assert changed.status_code == 200
    assert changed.json()["version"] == version + 1
    assert changed.json()["alert_rules"][0]["confidence_threshold"] == 0.72
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "configuration version conflict"}


def test_additional_camera_persists_only_a_secret_reference() -> None:
    with TestClient(app) as client:
        version = client.get("/api/v1/config").json()["version"]
        payload = {
            "expected_config_version": version,
            "id": "side-door",
            "name": "Side door",
            "stream_secret_ref": "env:CAMZILLA_SIDE_DOOR_RTSP_URL",
        }
        created = client.post("/api/v1/cameras", json=payload)
        duplicate = client.post(
            "/api/v1/cameras", json={**payload, "expected_config_version": version + 1}
        )
        unsafe = client.post(
            "/api/v1/cameras",
            json={
                **payload,
                "expected_config_version": version + 1,
                "id": "unsafe",
                "stream_secret_ref": "literal-secret-value",
            },
        )
    assert created.status_code == 201
    assert {item["id"] for item in created.json()["cameras"]} == {"front-door", "side-door"}
    side_door = next(item for item in created.json()["cameras"] if item["id"] == "side-door")
    assert side_door["capabilities"]["runtime_state"] == "pending"
    assert "CAMZILLA_SIDE_DOOR_RTSP_URL" not in created.text
    assert "rtsp://" not in created.text
    assert duplicate.status_code == 409
    assert unsafe.status_code == 422


def test_backup_export_validation_and_optimistic_restore_are_secret_free() -> None:
    with TestClient(app) as client:
        exported = client.get("/api/v1/backup")
        document = exported.json()
        version = client.get("/api/v1/config").json()["version"]
        validation = client.post("/api/v1/backup/validate", json={"document": document})
        invalid = client.post(
            "/api/v1/backup/validate",
            json={"document": {**document, "schema_version": "private-invalid-value"}},
        )
        document["alert_rules"][0]["confidence_threshold"] = 0.77
        restored = client.put(
            "/api/v1/backup",
            json={"expected_config_version": version, "document": document},
        )
        conflict = client.put(
            "/api/v1/backup",
            json={"expected_config_version": version, "document": document},
        )
    assert exported.status_code == 200
    assert exported.json()["secrets_included"] is False
    assert exported.json()["schema_version"] == "2"
    assert "secret_ref" not in exported.text.lower()
    assert "CAMZILLA_CAMERA_RTSP_URL" not in exported.text
    assert validation.json() == {"valid": True, "errors": []}
    assert invalid.json()["valid"] is False
    assert "private-invalid-value" not in invalid.text
    assert restored.status_code == 200
    assert restored.json()["alert_rules"][0]["confidence_threshold"] == 0.77
    assert conflict.status_code == 409


def test_rule_update_rejects_invalid_zone_schedule_and_disabled_category() -> None:
    with TestClient(app) as client:
        version = client.get("/api/v1/config").json()["version"]
        invalid_zone = client.put(
            "/api/v1/alert-rules/person-detected",
            json={
                "expected_config_version": version,
                "confidence_threshold": 0.6,
                "debounce_seconds": 60,
                "zone": {
                    "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}, {"x": 0.3, "y": 0.3}]
                },
                "target_categories": ["coco:person"],
            },
        )
        partial_schedule = client.put(
            "/api/v1/alert-rules/person-detected",
            json={
                "expected_config_version": version,
                "confidence_threshold": 0.6,
                "debounce_seconds": 60,
                "schedule_start": "22:00",
                "target_categories": ["coco:person"],
            },
        )
        disabled_category = client.put(
            "/api/v1/alert-rules/person-detected",
            json={
                "expected_config_version": version,
                "confidence_threshold": 0.6,
                "debounce_seconds": 60,
                "target_categories": ["car"],
            },
        )
    assert invalid_zone.status_code == 422
    assert partial_schedule.status_code == 422
    assert disabled_category.status_code == 422


def test_event_history_paginates_filters_sorts_and_deletes() -> None:
    with TestClient(app) as client:
        repository = app.state.repository
        baseline = client.get("/api/v1/events?event_type=detection").json()["total"]
        now = datetime.now(UTC)
        event_ids = [str(uuid4()) for _ in range(3)]
        repository.record_event(
            event_id=event_ids[0],
            camera_id="front-door",
            rule_id="person-detected",
            event_type="detection",
            triggered_at=now - timedelta(minutes=2),
            categories=["coco:person"],
        )
        repository.record_event(
            event_id=event_ids[1],
            camera_id="front-door",
            rule_id=None,
            event_type="stream-down",
            triggered_at=now - timedelta(minutes=1),
            categories=["stream-down"],
        )
        repository.record_event(
            event_id=event_ids[2],
            camera_id="front-door",
            rule_id="person-detected",
            event_type="detection",
            triggered_at=now,
            categories=["coco:person"],
        )
        page = client.get("/api/v1/events?page=1&page_size=1&event_type=detection&sort=desc")
        category = client.get("/api/v1/events?category=stream-down")
        removed = client.delete(f"/api/v1/events/{event_ids[2]}")
        missing = client.delete(f"/api/v1/events/{event_ids[2]}")
    assert page.status_code == 200
    assert page.json()["total"] == baseline + 2
    assert page.json()["pages"] == baseline + 2
    assert page.json()["items"][0]["id"] == event_ids[2]
    assert category.json()["total"] == 1
    assert category.json()["items"][0]["event_type"] == "stream-down"
    assert removed.status_code == 204
    assert missing.status_code == 404


def test_media_and_manual_recording_are_gated_when_storage_is_disabled() -> None:
    event_id = uuid4()
    with TestClient(app) as client:
        start = client.post("/api/v1/cameras/front-door/recordings")
        snapshot = client.get(f"/api/v1/events/{event_id}/snapshot")
        stop = client.delete(f"/api/v1/recordings/{event_id}")
        health = client.get("/health/ready")
    assert start.status_code == 409
    assert start.json() == {"detail": "media recording is disabled"}
    assert snapshot.status_code == 404
    assert stop.status_code == 404
    assert health.json()["media"] == {
        "enabled": False,
        "failures": 0,
        "recording_sessions": 0,
    }


def test_enabled_media_serves_deletes_and_gates_manual_recording(monkeypatch, tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        media_enabled=True,
        media_root=str(tmp_path / "media"),
        media_quota_bytes=1024 * 1024,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'camzilla.db'}",
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    event_id = str(uuid4())
    with TestClient(app) as client:
        store = app.state.media_store
        stored = store.save_snapshot("front-door", event_id, b"jpeg fixture")
        app.state.repository.record_event(
            event_id=event_id,
            camera_id="front-door",
            rule_id="person-detected",
            event_type="detection",
            triggered_at=datetime.now(UTC),
            categories=["coco:person"],
            snapshot_path=stored.path,
        )
        snapshot = client.get(f"/api/v1/events/{event_id}/snapshot")
        started = client.post("/api/v1/cameras/front-door/recordings")
        duplicate = client.post("/api/v1/cameras/front-door/recordings")
        stopped = client.delete(f"/api/v1/recordings/{started.json()['id']}")
        removed = client.delete(f"/api/v1/events/{event_id}")
        missing = client.get(f"/api/v1/events/{event_id}/snapshot")
    assert snapshot.status_code == 200
    assert snapshot.content == b"jpeg fixture"
    assert snapshot.headers["content-type"].startswith("image/jpeg")
    assert started.status_code == 201 and started.json()["status"] == "recording"
    assert duplicate.status_code == 409
    assert stopped.status_code == 200 and stopped.json()["status"] == "processing"
    assert removed.status_code == 204
    assert missing.status_code == 404
    assert not (tmp_path / "media" / "front-door" / f"{event_id}.jpg").exists()


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

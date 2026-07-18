from app.contracts import Detection
from app.main import app


def test_openapi_keeps_phase_three_contracts_and_excludes_secret_configuration() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    required = {
        "/api/v1/config",
        "/api/v1/cameras",
        "/api/v1/alert-rules/{rule_id}",
        "/api/v1/events",
        "/api/v1/events/{event_id}/{kind}",
        "/api/v1/backup",
        "/api/v1/backup/validate",
        "/api/v1/inference",
        "/api/v1/inference/compatibility/{capability_id}",
        "/api/v1/cameras/{camera_id}/categories",
    }
    assert required <= set(paths)
    serialized = str(schema).lower()
    assert "discord_webhook_url" not in serialized
    assert "onvif_password" not in serialized
    assert "camera_rtsp_url" not in serialized
    assert "database_url" not in serialized
    detection = Detection.model_json_schema()["properties"]
    assert {"semantic_id", "native_class_id", "class_name"} <= set(detection)
    backup = schema["components"]["schemas"]["BackupDocument"]["properties"]
    assert backup["schema_version"]["const"] == "2"

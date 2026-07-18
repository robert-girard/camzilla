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
    }
    assert required <= set(paths)
    serialized = str(schema).lower()
    assert "discord_webhook_url" not in serialized
    assert "onvif_password" not in serialized
    assert "camera_rtsp_url" not in serialized
    assert "database_url" not in serialized

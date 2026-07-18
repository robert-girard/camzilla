from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from app.persistence import (
    AlertRuleRecord,
    CameraRecord,
    ConfigurationConflictError,
    Database,
    EventRecord,
    Repository,
)


@pytest.fixture
def repository(tmp_path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'camzilla.db'}")
    database.migrate()
    repo = Repository(database)
    repo.seed("front-door", "fake:fake-person-v1:cpu")
    yield repo
    database.close()


def test_migration_creates_expected_schema_and_secret_references(repository) -> None:
    tables = set(inspect(repository.database.engine).get_table_names())
    assert {"alembic_version", "config_state", "cameras", "alert_rules", "events"} <= tables
    with repository.database.session() as session:
        camera = session.scalar(select(CameraRecord))
        rule = session.scalar(select(AlertRuleRecord))
    assert camera is not None
    assert camera.stream_secret_ref == "env:CAMZILLA_CAMERA_RTSP_URL"
    assert "://" not in camera.stream_secret_ref
    assert camera.allowed_categories == ["coco:person"]
    assert rule is not None and rule.target_categories == ["coco:person"]


def test_semantic_category_migration_preserves_legacy_person_state(tmp_path) -> None:
    database_path = tmp_path / "legacy.db"
    url = f"sqlite+pysqlite:///{database_path}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0001_phase3_state")
    database = Database(url)
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO config_state "
                "(id, version, active_capability_id, notifier_secret_ref) VALUES "
                "(1, 1, 'fake:fake-person-v1:cpu', 'env:CAMZILLA_DISCORD_WEBHOOK_URL')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO cameras "
                "(id, name, enabled, stream_secret_ref, capabilities, allowed_categories, "
                "catalog_revision, version) VALUES "
                "('front-door', 'front-door', 1, 'env:CAMZILLA_CAMERA_RTSP_URL', '{}', "
                "'[\"person\"]', 'person-v1', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO alert_rules "
                "(id, camera_id, enabled, target_categories, confidence_threshold, "
                "debounce_seconds, version) VALUES "
                "('person-detected', 'front-door', 1, '[\"person\"]', 0.6, 300, 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO events "
                "(id, camera_id, rule_id, event_type, triggered_at, categories) VALUES "
                "('11111111-1111-4111-8111-111111111111', 'front-door', "
                "'person-detected', 'detection', '2026-07-17T12:00:00Z', '[\"person\"]')"
            )
        )
    command.upgrade(config, "head")
    with database.engine.connect() as connection:
        camera = connection.execute(
            text("SELECT allowed_categories, catalog_revision FROM cameras")
        ).one()
        rule_categories = connection.execute(
            text("SELECT target_categories FROM alert_rules")
        ).scalar_one()
        event = connection.execute(text("SELECT categories, catalog_revision FROM events")).one()
    database.close()

    assert camera == ('["coco:person"]', "coco-person-v1")
    assert rule_categories == '["coco:person"]'
    assert event == ('["coco:person"]', "coco-person-v1")


def test_active_selection_and_optimistic_rule_update_survive_sessions(repository) -> None:
    assert repository.active_capability_id() == "fake:fake-person-v1:cpu"
    repository.set_active_capability("ultralytics:yolo11s:cpu", "coco80-v1")
    version = repository.configuration_version()
    next_version = repository.update_rule(
        "person-detected",
        expected_config_version=version,
        confidence_threshold=0.75,
        debounce_seconds=60,
        schedule_start="22:00",
        schedule_end="06:00",
        zone=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]],
        target_categories=["coco:person"],
    )

    assert repository.active_capability_id() == "ultralytics:yolo11s:cpu"
    assert next_version == version + 1
    with pytest.raises(ConfigurationConflictError):
        repository.update_rule(
            "person-detected",
            expected_config_version=version,
            confidence_threshold=0.5,
            debounce_seconds=30,
            schedule_start=None,
            schedule_end=None,
            zone=None,
            target_categories=["coco:person"],
        )


def test_verified_capability_results_persist_without_adapter_configuration(repository) -> None:
    repository.set_camera_capabilities(
        "front-door",
        {
            "ptz": {"available": False, "unavailable_reason": "PTZ is not enabled"},
            "inference": [{"id": "fake:fake-person-v1:cpu", "available": True}],
        },
    )
    configuration = repository.configuration()
    capabilities = configuration.cameras[0].capabilities
    assert capabilities["ptz"] == {
        "available": False,
        "unavailable_reason": "PTZ is not enabled",
    }
    assert "password" not in str(capabilities).lower()
    assert "://" not in str(capabilities)


def test_event_metadata_persists_without_media_blobs(repository) -> None:
    event_id = str(uuid4())
    repository.record_event(
        event_id=event_id,
        camera_id="front-door",
        rule_id="person-detected",
        event_type="detection",
        triggered_at=datetime.now(UTC),
        categories=["coco:person"],
        catalog_revision="coco-person-v1",
        snapshot_path="front-door/example.jpg",
    )
    with repository.database.session() as session:
        event = session.get(EventRecord, event_id)
    assert event is not None
    assert event.categories == ["coco:person"]
    assert event.catalog_revision == "coco-person-v1"
    assert event.snapshot_path == "front-door/example.jpg"
    columns = {item["name"] for item in inspect(repository.database.engine).get_columns("events")}
    assert "data" not in columns
    assert "blob" not in columns

    repository.update_event_media(event_id, clip_path="front-door/example.mp4")
    assert repository.event_media_path(event_id, "clip") == "front-door/example.mp4"
    repository.clear_media_paths(("front-door/example.jpg",))
    assert repository.event_media_path(event_id, "snapshot") is None
    assert repository.event_media_path(event_id, "clip") == "front-door/example.mp4"

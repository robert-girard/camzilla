from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select

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
    assert camera.allowed_categories == ["person"]
    assert rule is not None and rule.target_categories == ["person"]


def test_active_selection_and_optimistic_rule_update_survive_sessions(repository) -> None:
    assert repository.active_capability_id() == "fake:fake-person-v1:cpu"
    repository.set_active_capability("ultralytics:yolo11s:cpu")
    version = repository.configuration_version()
    next_version = repository.update_rule(
        "person-detected",
        expected_config_version=version,
        confidence_threshold=0.75,
        debounce_seconds=60,
        schedule_start="22:00",
        schedule_end="06:00",
        zone=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]],
        target_categories=["person"],
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
            target_categories=["person"],
        )


def test_event_metadata_persists_without_media_blobs(repository) -> None:
    event_id = str(uuid4())
    repository.record_event(
        event_id=event_id,
        camera_id="front-door",
        rule_id="person-detected",
        event_type="detection",
        triggered_at=datetime.now(UTC),
        categories=["person"],
        snapshot_path="front-door/example.jpg",
    )
    with repository.database.session() as session:
        event = session.get(EventRecord, event_id)
    assert event is not None
    assert event.categories == ["person"]
    assert event.snapshot_path == "front-door/example.jpg"
    columns = {item["name"] for item in inspect(repository.database.engine).get_columns("events")}
    assert "data" not in columns
    assert "blob" not in columns

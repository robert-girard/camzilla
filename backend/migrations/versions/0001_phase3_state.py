"""Create Phase 3 configuration and event tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase3_state"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active_capability_id", sa.String(length=160), nullable=False),
        sa.Column("notifier_secret_ref", sa.String(length=160), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "cameras",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("stream_secret_ref", sa.String(length=160), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("allowed_categories", sa.JSON(), nullable=False),
        sa.Column("catalog_revision", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("camera_id", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("target_categories", sa.JSON(), nullable=False),
        sa.Column("confidence_threshold", sa.Float(), nullable=False),
        sa.Column("debounce_seconds", sa.Float(), nullable=False),
        sa.Column("schedule_start", sa.String(length=5), nullable=True),
        sa.Column("schedule_end", sa.String(length=5), nullable=True),
        sa.Column("zone", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_rules_camera_id", "alert_rules", ["camera_id"])
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=80), nullable=False),
        sa.Column("rule_id", sa.String(length=80), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("snapshot_path", sa.String(length=240), nullable=True),
        sa.Column("clip_path", sa.String(length=240), nullable=True),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"]),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_camera_id", "events", ["camera_id"])
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_rule_id", "events", ["rule_id"])
    op.create_index("ix_events_triggered_at", "events", ["triggered_at"])


def downgrade() -> None:
    op.drop_index("ix_events_triggered_at", table_name="events")
    op.drop_index("ix_events_rule_id", table_name="events")
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_index("ix_events_camera_id", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_alert_rules_camera_id", table_name="alert_rules")
    op.drop_table("alert_rules")
    op.drop_table("cameras")
    op.drop_table("config_state")

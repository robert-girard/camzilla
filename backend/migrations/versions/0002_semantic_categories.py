"""Migrate legacy person selections to stable semantic IDs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_semantic_categories"
down_revision: str | None = "0001_phase3_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "catalog_revision",
            sa.String(length=120),
            nullable=False,
            server_default="legacy-v1",
        ),
    )
    op.execute(
        "UPDATE cameras SET allowed_categories = '[\"coco:person\"]', "
        "catalog_revision = 'coco-person-v1' "
        "WHERE json_array_length(allowed_categories) = 1 "
        "AND json_extract(allowed_categories, '$[0]') = 'person'"
    )
    op.execute(
        "UPDATE alert_rules SET target_categories = '[\"coco:person\"]' "
        "WHERE json_array_length(target_categories) = 1 "
        "AND json_extract(target_categories, '$[0]') = 'person'"
    )
    op.execute(
        "UPDATE events SET categories = '[\"coco:person\"]' "
        "WHERE json_array_length(categories) = 1 "
        "AND json_extract(categories, '$[0]') = 'person'"
    )
    op.execute(
        "UPDATE events SET catalog_revision = 'coco-person-v1' "
        "WHERE json_array_length(categories) = 1 "
        "AND json_extract(categories, '$[0]') = 'coco:person'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE cameras SET allowed_categories = '[\"person\"]', "
        "catalog_revision = 'person-v1' "
        "WHERE json_array_length(allowed_categories) = 1 "
        "AND json_extract(allowed_categories, '$[0]') = 'coco:person'"
    )
    op.execute(
        "UPDATE alert_rules SET target_categories = '[\"person\"]' "
        "WHERE json_array_length(target_categories) = 1 "
        "AND json_extract(target_categories, '$[0]') = 'coco:person'"
    )
    op.execute(
        "UPDATE events SET categories = '[\"person\"]' "
        "WHERE json_array_length(categories) = 1 "
        "AND json_extract(categories, '$[0]') = 'coco:person'"
    )
    op.drop_column("events", "catalog_revision")

"""Remove obsolete standalone training capacity settings.

Training I and II are modeled as catalog requirements and offerings. Their
standalone settings were unused by the database planning loader.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0005"
down_revision = "20261010_0004"
branch_labels = None
depends_on = None


def upgrade():
    settings = sa.table("engine_settings", sa.column("key", sa.String()))
    op.execute(settings.delete().where(settings.c.key.in_([
        "training_1_capacity", "training_2_capacity",
    ])))


def downgrade():
    settings = sa.table(
        "engine_settings",
        sa.column("key", sa.String()), sa.column("value", sa.JSON()),
        sa.column("description", sa.Text()),
        sa.column("unverified_assumption", sa.Boolean()),
    )
    op.bulk_insert(settings, [
        {"key": "training_1_capacity", "value": 5,
         "description": "Training I period capacity", "unverified_assumption": False},
        {"key": "training_2_capacity", "value": 5,
         "description": "Training II period capacity", "unverified_assumption": False},
    ])

"""Create the frozen initial academic-planning persistence schema."""

from alembic import op

from academic_planner.database.migration_snapshots.v20261009_0001 import Base


revision = "20261009_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())

"""Add supporting source references to student requirements."""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0009"
down_revision = "20261011_0008"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("student_requirements")
    }
    if "source_reference" not in columns:
        op.add_column(
            "student_requirements",
            sa.Column("source_reference", sa.String(500), nullable=True),
        )


def downgrade():
    op.drop_column("student_requirements", "source_reference")

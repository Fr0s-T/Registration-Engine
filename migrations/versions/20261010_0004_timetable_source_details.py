"""Preserve timetable source and section details."""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0004"
down_revision = "20261010_0003"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    offering_columns = {column["name"] for column in inspector.get_columns("offerings")}
    section_columns = {column["name"] for column in inspector.get_columns("sections")}
    if "source_document_id" not in offering_columns:
        op.add_column("offerings", sa.Column("source_document_id", sa.Integer(), nullable=True))
    if "instructor" not in section_columns:
        op.add_column("sections", sa.Column("instructor", sa.String(255), nullable=True))
    if "notes" not in section_columns:
        op.add_column("sections", sa.Column("notes", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("sections") as batch:
        batch.drop_column("notes")
        batch.drop_column("instructor")
    with op.batch_alter_table("offerings") as batch:
        batch.drop_column("source_document_id")

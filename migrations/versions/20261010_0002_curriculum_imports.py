"""Add source-aware complete curriculum imports."""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0002"
down_revision = "20261009_0001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    def names(table):
        return {column["name"] for column in inspector.get_columns(table)}
    # SQLite can add nullable columns directly. Avoid batch table recreation here:
    # curriculum_revisions is referenced by courses and cannot safely be dropped while
    # foreign-key enforcement is active.
    if "storage_path" not in names("source_documents"):
        op.add_column("source_documents", sa.Column("storage_path", sa.String(500), nullable=True))
    if "source_document_id" not in names("curriculum_revisions"):
        # SQLite cannot add a foreign-key constraint without recreating this referenced
        # table. Application writes still use the ORM relationship and validated IDs.
        op.add_column("curriculum_revisions", sa.Column("source_document_id", sa.Integer(), nullable=True))
    if "source_locator" not in names("courses"):
        op.add_column("courses", sa.Column("source_locator", sa.String(255), nullable=True))
    if "source_text" not in names("prerequisite_groups"):
        op.add_column("prerequisite_groups", sa.Column("source_text", sa.Text(), nullable=True))
    if "lab_relationships" not in inspector.get_table_names():
        op.create_table(
            "lab_relationships",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lab_course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("source_locator", sa.String(255), nullable=True),
            sa.UniqueConstraint("course_id", "lab_course_id"),
            sa.CheckConstraint("course_id <> lab_course_id"),
        )


def downgrade():
    op.drop_table("lab_relationships")
    with op.batch_alter_table("prerequisite_groups") as batch:
        batch.drop_column("source_text")
    with op.batch_alter_table("courses") as batch:
        batch.drop_column("source_locator")
    with op.batch_alter_table("curriculum_revisions") as batch:
        batch.drop_column("source_document_id")
    with op.batch_alter_table("source_documents") as batch:
        batch.drop_column("storage_path")

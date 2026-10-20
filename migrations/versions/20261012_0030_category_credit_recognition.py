"""Persist auditable legacy-to-contract category recognition.

Revision ID: 20261012_0030
Revises: 20261012_0029
"""
import sqlalchemy as sa
from alembic import op


revision = "20261012_0030"
down_revision = "20261012_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "course_requirement_group_recognitions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "course_requirement_group_recognitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_course_id", sa.Integer(), nullable=False),
        sa.Column("requirement_group_id", sa.Integer(), nullable=False),
        sa.Column("recognition_scope", sa.String(30), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("provenance", sa.String(40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_group_id"], ["requirement_groups.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_course_id", "requirement_group_id"),
        sa.CheckConstraint("recognition_scope = 'CATEGORY_CREDIT'"),
    )


def downgrade() -> None:
    op.drop_table("course_requirement_group_recognitions")

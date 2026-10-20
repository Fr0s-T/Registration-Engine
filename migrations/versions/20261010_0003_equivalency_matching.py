"""Persist deterministic equivalency matching decisions."""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0003"
down_revision = "20261010_0002"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "equivalency_matches" not in inspector.get_table_names():
        op.create_table(
            "equivalency_matches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("old_course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("new_course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("equivalency_id", sa.Integer(), sa.ForeignKey("equivalencies.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("method", sa.String(40), nullable=False),
            sa.Column("review_reasons", sa.JSON(), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("verified_by", sa.String(100), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("old_course_id", "new_course_id"),
            sa.CheckConstraint("old_course_id <> new_course_id"),
            sa.CheckConstraint("status IN ('AUTO_MATCHED','NEEDS_REVIEW','HUMAN_VERIFIED','REJECTED')"),
        )


def downgrade():
    op.drop_table("equivalency_matches")

"""Add student-specific optional graduation-credit approvals."""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0008"
down_revision = "20261010_0007"
branch_labels = None
depends_on = None


def upgrade():
    if "student_optional_credit_approvals" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "student_optional_credit_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(),
                  sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.Integer(),
                  sa.ForeignKey("courses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("course_code_snapshot", sa.String(40), nullable=False),
        sa.Column("credit_category", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="UNVERIFIED"),
        sa.Column("authority", sa.String(120), nullable=True),
        sa.Column("source_reference", sa.String(500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("academic_period", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("student_id", "course_id", "credit_category"),
        sa.CheckConstraint("status IN ('UNVERIFIED','APPROVED','REJECTED')"),
    )


def downgrade():
    op.drop_table("student_optional_credit_approvals")

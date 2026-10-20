"""Align persisted student requirements with catalog credit-band roles."""
from alembic import op

revision = "20261011_0012"
down_revision = "20261011_0011"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DELETE FROM student_requirements
        WHERE course_id IN (
            SELECT id FROM courses WHERE graduation_role <> 'MANDATORY'
        )
    """)


def downgrade():
    # Deleted student-specific rows cannot be reconstructed authoritatively.
    pass

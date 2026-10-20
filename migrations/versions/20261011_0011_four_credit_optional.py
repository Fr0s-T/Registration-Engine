"""Treat four-ECTS catalog courses as optional."""
from alembic import op

revision = "20261011_0011"
down_revision = "20261011_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE courses
        SET graduation_role = 'OPTIONAL',
            graduation_role_basis = 'USER_CONFIRMED_CREDIT_BAND_RULE'
        WHERE ects = 4 AND is_fyp = 0
    """)
    op.execute("""
        DELETE FROM degree_requirements
        WHERE course_id IN (
            SELECT id FROM courses WHERE ects = 4 AND is_fyp = 0
        )
    """)


def downgrade():
    op.execute("""
        UPDATE courses
        SET graduation_role = 'NEEDS_REVIEW',
            graduation_role_basis = 'USER_CONFIRMED_CREDIT_BAND_RULE'
        WHERE ects = 4 AND is_fyp = 0
    """)

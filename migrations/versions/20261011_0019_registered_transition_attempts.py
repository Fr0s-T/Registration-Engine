"""Distinguish confirmed transition registrations from generic pending work."""
from alembic import op

revision = "20261011_0019"
down_revision = "20261011_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE student_attempts
        SET status = 'REGISTERED'
        WHERE source_value = 'PENDING'
          AND source_term = 'FALL2026'
    """)


def downgrade():
    op.execute("""
        UPDATE student_attempts
        SET status = 'IN_PROGRESS'
        WHERE source_value = 'PENDING'
          AND source_term = 'FALL2026'
    """)

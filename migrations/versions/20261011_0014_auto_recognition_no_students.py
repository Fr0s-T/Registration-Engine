"""Accept high-confidence auto matches and remove persisted student data."""
from alembic import op

revision = "20261011_0014"
down_revision = "20261011_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE equivalencies
        SET recognizes_history = 1,
            notes = 'Automatically accepted high-confidence historical equivalency; an administrator may unverify or replace it.'
        WHERE verification_status = 'AUTO_MATCHED'
    """)
    # Student inputs are request-scoped. Catalog, timetable, and equivalency
    # administration remain persistent, but identity and transcript data do not.
    op.execute("DELETE FROM students")


def downgrade():
    op.execute("""
        UPDATE equivalencies
        SET recognizes_history = 0,
            notes = 'Structural match only; not official university approval.'
        WHERE verification_status = 'AUTO_MATCHED'
    """)
    # Deleted student records cannot be reconstructed safely.

"""Remove the obsolete identity-scoped graduation-pathway patch.

Revision ID: 20261012_0032
Revises: 20261012_0031
"""
import sqlalchemy as sa
from alembic import op


revision = "20261012_0032"
down_revision = "20261012_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if "student_requirements" in sa.inspect(connection).get_table_names():
        connection.execute(sa.text("""
            DELETE FROM student_requirements
            WHERE authority = 'IUL_APPROVED_GRADUATION_PATHWAY'
        """))


def downgrade() -> None:
    pass

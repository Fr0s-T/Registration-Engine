"""Authorize offered OLD Year-5 equivalents for prospective registration.

Revision ID: 20261011_0020
Revises: 20261011_0019
"""
from alembic import op

revision = "20261011_0020"
down_revision = "20261011_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE equivalencies
        SET prospective_registration_allowed = 1
        WHERE id IN (
            SELECT e.id
            FROM equivalencies e
            JOIN courses source ON source.id = e.source_course_id
            JOIN courses target ON target.id = e.target_course_id
            WHERE (source.code = 'ELBC901' AND target.code = 'CCE640')
               OR (source.code = 'ELCC916' AND target.code = 'CCE651')
        )
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE equivalencies
        SET prospective_registration_allowed = NULL
        WHERE id IN (
            SELECT e.id
            FROM equivalencies e
            JOIN courses source ON source.id = e.source_course_id
            JOIN courses target ON target.id = e.target_course_id
            WHERE (source.code = 'ELBC901' AND target.code = 'CCE640')
               OR (source.code = 'ELCC916' AND target.code = 'CCE651')
        )
    """)

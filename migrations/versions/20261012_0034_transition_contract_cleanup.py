"""Remove redundant student requirements and authorize verified OLD replacements.

Revision ID: 20261012_0034
Revises: 20261012_0033
"""
import sqlalchemy as sa
from alembic import op


revision = "20261012_0034"
down_revision = "20261012_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("""
        DELETE FROM student_requirements
        WHERE authority IN (
            'IUL_APPROVED_GRADUATION_PATHWAY', 'SUPPLIED_CONTRACT_SHEET'
        )
    """))
    connection.execute(sa.text("""
        UPDATE equivalencies
        SET prospective_registration_allowed = 1
        WHERE verification_status IN (
            'AUTO_MATCHED', 'HUMAN_VERIFIED', 'OFFICIALLY_DOCUMENTED', 'VERIFIED'
        )
          AND source_course_id IN (
              SELECT course.id FROM courses course
              JOIN curriculum_revisions revision
                ON revision.id = course.curriculum_id
              WHERE revision.version = 'OLD' AND revision.active = 1
          )
          AND target_course_id IN (
              SELECT course.id FROM courses course
              JOIN curriculum_revisions revision
                ON revision.id = course.curriculum_id
              WHERE revision.version = 'NEW' AND revision.active = 1
          )
    """))


def downgrade() -> None:
    pass

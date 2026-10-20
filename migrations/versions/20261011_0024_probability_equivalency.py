"""Recognize completed OLD probability and statistics as NEW STA222.

Revision ID: 20261011_0024
Revises: 20261011_0023
"""
import sqlalchemy as sa
from alembic import op

revision = "20261011_0024"
down_revision = "20261011_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text("""
        INSERT OR IGNORE INTO equivalencies
            (source_course_id, target_course_id, recognizes_history,
             prospective_registration_allowed, verification_status,
             provenance, notes)
        SELECT source.id, target.id, 1, NULL, 'HUMAN_VERIFIED',
               'USER_CONFIRMED_POLICY',
               'User confirmed OLD ELCM318 Probability & Statistics satisfies '
               || 'NEW STA222 Probability and Statistics for Engineers. Historical '
               || 'earned ECTS remain 5; the NEW course is not scheduled again.'
        FROM courses source
        JOIN curriculum_revisions source_revision
          ON source_revision.id = source.curriculum_id
        JOIN courses target ON target.code = 'STA222'
        JOIN curriculum_revisions target_revision
          ON target_revision.id = target.curriculum_id
        WHERE source.code = 'ELCM318'
          AND source_revision.version = 'OLD' AND source_revision.active = 1
          AND target_revision.version = 'NEW' AND target_revision.active = 1
    """))


def downgrade() -> None:
    op.execute("""
        DELETE FROM equivalencies
        WHERE provenance = 'USER_CONFIRMED_POLICY'
          AND source_course_id IN (
              SELECT c.id FROM courses c
              JOIN curriculum_revisions r ON r.id = c.curriculum_id
              WHERE c.code = 'ELCM318' AND r.version = 'OLD'
          )
          AND target_course_id IN (
              SELECT c.id FROM courses c
              JOIN curriculum_revisions r ON r.id = c.curriculum_id
              WHERE c.code = 'STA222' AND r.version = 'NEW'
          )
    """)

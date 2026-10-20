"""Recognize completed OLD Microwaves as the current NEW requirement."""
import sqlalchemy as sa
from alembic import op

revision = "20261011_0018"
down_revision = "20261011_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("""
        INSERT OR IGNORE INTO equivalencies
            (source_course_id, target_course_id, recognizes_history,
             prospective_registration_allowed, verification_status,
             provenance, notes)
        SELECT source.id, target.id, 1, NULL, 'HUMAN_VERIFIED',
               'SOURCE_REVIEW',
               'ELCC722 Microwaves satisfies CCE541; historical 3 ECTS are preserved.'
        FROM courses source
        JOIN curriculum_revisions source_revision
          ON source_revision.id = source.curriculum_id
        JOIN courses target ON target.code = 'CCE541'
        JOIN curriculum_revisions target_revision
          ON target_revision.id = target.curriculum_id
        WHERE source.code = 'ELCC722'
          AND source_revision.version = 'OLD' AND source_revision.active = 1
          AND target_revision.version = 'NEW' AND target_revision.active = 1
    """))


def downgrade():
    op.execute("""
        DELETE FROM equivalencies
        WHERE provenance = 'SOURCE_REVIEW'
          AND notes = 'ELCC722 Microwaves satisfies CCE541; historical 3 ECTS are preserved.'
    """)

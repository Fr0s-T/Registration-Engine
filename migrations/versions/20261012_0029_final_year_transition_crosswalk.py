"""Complete configured final-year rollout substitutions.

Revision ID: 20261012_0029
Revises: 20261012_0028
"""
import sqlalchemy as sa
from alembic import op


revision = "20261012_0029"
down_revision = "20261012_0028"
branch_labels = None
depends_on = None


PAIRS = (
    ("ELBC901", "CCE640"),
    ("ELCC914", "CCE653"),
    ("ELCC916", "CCE651"),
    ("ELCC919", "CCE655"),
    ("ELCC923", "CCE652"),
)


def upgrade() -> None:
    connection = op.get_bind()
    for source_code, target_code in PAIRS:
        connection.execute(sa.text("""
            INSERT INTO equivalencies
                (source_course_id, target_course_id, recognizes_history,
                 prospective_registration_allowed, verification_status,
                 provenance, notes)
            SELECT source.id, target.id, 1, 1, 'HUMAN_VERIFIED',
                   'CURATED_TRANSITION_CATALOGUE',
                   'Configured equal-credit OLD Year-5 rollout substitution.'
            FROM courses source
            JOIN curriculum_revisions sr ON sr.id = source.curriculum_id
            JOIN courses target ON target.code = :target_code
            JOIN curriculum_revisions tr ON tr.id = target.curriculum_id
            WHERE source.code = :source_code
              AND sr.version = 'OLD' AND sr.active = 1
              AND tr.version = 'NEW' AND tr.active = 1
              AND NOT EXISTS (
                  SELECT 1 FROM equivalencies e
                  WHERE e.source_course_id = source.id
                    AND e.target_course_id = target.id
              )
        """), {"source_code": source_code, "target_code": target_code})
        connection.execute(sa.text("""
            UPDATE equivalencies
            SET prospective_registration_allowed = 1,
                verification_status = 'HUMAN_VERIFIED'
            WHERE source_course_id IN (
                SELECT c.id FROM courses c JOIN curriculum_revisions r
                  ON r.id = c.curriculum_id
                WHERE c.code = :source_code AND r.version = 'OLD' AND r.active = 1
            )
              AND target_course_id IN (
                SELECT c.id FROM courses c JOIN curriculum_revisions r
                  ON r.id = c.curriculum_id
                WHERE c.code = :target_code AND r.version = 'NEW' AND r.active = 1
            )
        """), {"source_code": source_code, "target_code": target_code})


def downgrade() -> None:
    connection = op.get_bind()
    for source_code, target_code in PAIRS:
        connection.execute(sa.text("""
            UPDATE equivalencies
            SET prospective_registration_allowed = NULL
            WHERE source_course_id IN (
                SELECT c.id FROM courses c JOIN curriculum_revisions r
                  ON r.id = c.curriculum_id
                WHERE c.code = :source_code AND r.version = 'OLD'
            )
              AND target_course_id IN (
                SELECT c.id FROM courses c JOIN curriculum_revisions r
                  ON r.id = c.curriculum_id
                WHERE c.code = :target_code AND r.version = 'NEW'
            )
        """), {"source_code": source_code, "target_code": target_code})

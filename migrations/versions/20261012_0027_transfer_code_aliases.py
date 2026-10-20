"""Resolve transferred ethics and religion course codes.

Revision ID: 20261012_0027
Revises: 20261012_0026
"""
import sqlalchemy as sa
from alembic import op


revision = "20261012_0027"
down_revision = "20261012_0026"
branch_labels = None
depends_on = None


ALIASES = (
    (
        "REL312", "GER312",
        "Transferred Culture, Moral, Religion: exact title and 2-ECTS match.",
    ),
    (
        "DRH320", "GER333",
        "Transferred Ethics of the Profession: Professional Ethics, 2 ECTS.",
    ),
)


def upgrade() -> None:
    connection = op.get_bind()
    for source_code, target_code, notes in ALIASES:
        connection.execute(sa.text("""
            INSERT OR REPLACE INTO transcript_code_mappings
                (id, source_code, target_course_id, mapping_kind,
                 verification_status, provenance, notes)
            SELECT existing.id, :source_code, target.id, 'COURSE_ALIAS',
                   'HUMAN_VERIFIED', 'SOURCE_REVIEW', :notes
            FROM courses target
            JOIN curriculum_revisions revision
              ON revision.id = target.curriculum_id
            LEFT JOIN transcript_code_mappings existing
              ON existing.source_code = :source_code
            WHERE target.code = :target_code
              AND revision.version = 'NEW'
              AND revision.active = 1
        """), {
            "source_code": source_code,
            "target_code": target_code,
            "notes": notes,
        })


def downgrade() -> None:
    op.execute("""
        DELETE FROM transcript_code_mappings
        WHERE source_code IN ('REL312', 'DRH320')
          AND provenance = 'SOURCE_REVIEW'
    """)

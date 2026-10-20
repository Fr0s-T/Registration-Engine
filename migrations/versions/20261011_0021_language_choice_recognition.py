"""Model GER221/GER222 as the English/French track choice.

Revision ID: 20261011_0021
Revises: 20261011_0020
"""
from alembic import op

revision = "20261011_0021"
down_revision = "20261011_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The source curriculum contains one slash-delimited 4-credit choice:
    # GER221 (English) or GER222 (French), not two courses worth 8 credits.
    op.execute("""
        UPDATE courses
        SET academic_track_policy = 'TRACK_SPECIFIC',
            permitted_student_tracks = '["EN"]',
            notes = COALESCE(notes || ' ', '') ||
                'English alternative in the GER221/GER222 language-track choice.'
        WHERE code = 'GER221' AND curriculum_id IN (
            SELECT id FROM curriculum_revisions WHERE version = 'NEW'
        )
    """)
    op.execute("""
        UPDATE courses
        SET academic_track_policy = 'TRACK_SPECIFIC',
            permitted_student_tracks = '["FR"]',
            notes = COALESCE(notes || ' ', '') ||
                'French alternative in the GER221/GER222 language-track choice.'
        WHERE code = 'GER222' AND curriculum_id IN (
            SELECT id FROM curriculum_revisions WHERE version = 'NEW'
        )
    """)
    # Both historical English components are valid evidence for the English
    # alternative. Their separate source identities preserve all earned credit,
    # while the modern requirement is satisfied only once.
    op.execute("""
        INSERT OR IGNORE INTO transcript_code_mappings
            (source_code, target_course_id, mapping_kind, verification_status,
             provenance, notes)
        SELECT source_code, c.id, 'COURSE_ALIAS', 'HUMAN_VERIFIED',
               'SOURCE_REVIEW',
               'Historical English transcript component recognized against the English GER221 alternative.'
        FROM (SELECT 'ENG221' AS source_code UNION ALL SELECT 'ENG222') source
        JOIN courses c ON c.code = 'GER221'
        JOIN curriculum_revisions r ON r.id = c.curriculum_id AND r.version = 'NEW'
    """)


def downgrade() -> None:
    op.execute("DELETE FROM transcript_code_mappings WHERE source_code IN ('ENG221','ENG222')")
    op.execute("""
        UPDATE courses
        SET academic_track_policy = 'SHARED', permitted_student_tracks = '["EN","FR"]'
        WHERE code IN ('GER221','GER222') AND curriculum_id IN (
            SELECT id FROM curriculum_revisions WHERE version = 'NEW'
        )
    """)

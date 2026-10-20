"""Enforce mandatory training and exclude known non-degree catalog courses.

Revision ID: 20261012_0026
Revises: 20261011_0025
"""
from alembic import op


revision = "20261012_0026"
down_revision = "20261011_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Recompute roles from the policy instead of preserving classifications
    # produced before training was recognized as an unconditional requirement.
    op.execute("""
        UPDATE courses
        SET graduation_role = CASE
            WHEN code IN (
                SELECT source_code FROM transcript_code_mappings
                WHERE mapping_kind = 'NON_DEGREE'
            ) THEN 'NEEDS_REVIEW'
            WHEN is_fyp = 1 OR course_type = 'TRAINING' OR ects >= 5
                THEN 'MANDATORY'
            WHEN ects BETWEEN 1 AND 4 THEN 'OPTIONAL'
            ELSE 'NEEDS_REVIEW'
        END,
        graduation_role_basis = 'IUL_300_ECTS_CREDIT_BAND_RULE'
    """)

    # Training is mandatory even when it is below five ECTS.  Existing 5+ and
    # FYP requirements are already present from the earlier migrations/imports.
    op.execute("""
        INSERT OR IGNORE INTO degree_requirements
            (curriculum_id, course_id, language_track, requirement_type)
        SELECT course.curriculum_id, course.id, NULL, 'TRAINING'
        FROM courses course
        JOIN curriculum_revisions revision
          ON revision.id = course.curriculum_id
        WHERE revision.active = 1
          AND course.course_type = 'TRAINING'
          AND course.graduation_role = 'MANDATORY'
    """)

    # A known non-degree course must never survive as a curriculum requirement.
    op.execute("""
        DELETE FROM degree_requirements
        WHERE course_id IN (
            SELECT course.id
            FROM courses course
            JOIN transcript_code_mappings mapping
              ON mapping.source_code = course.code
            WHERE mapping.mapping_kind = 'NON_DEGREE'
        )
    """)
    op.execute("""
        DELETE FROM student_requirements
        WHERE course_id IN (
            SELECT course.id
            FROM courses course
            JOIN transcript_code_mappings mapping
              ON mapping.source_code = course.code
            WHERE mapping.mapping_kind = 'NON_DEGREE'
        )
    """)


def downgrade() -> None:
    # The old classification incorrectly treated sub-five-ECTS training as
    # optional; restoring it is safe, but deleted invalid requirements are not.
    op.execute("""
        UPDATE courses
        SET graduation_role = 'OPTIONAL'
        WHERE course_type = 'TRAINING' AND ects BETWEEN 1 AND 4
    """)
    op.execute("""
        DELETE FROM degree_requirements
        WHERE requirement_type = 'TRAINING'
          AND course_id IN (
              SELECT id FROM courses WHERE ects BETWEEN 1 AND 4
          )
    """)

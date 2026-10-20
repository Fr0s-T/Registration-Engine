"""Confirm transition equivalencies and final-two-semester load policy.

Revision ID: 20261011_0022
Revises: 20261011_0021
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "20261011_0022"
down_revision = "20261011_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    pairs = (
        (
            "ELCC820", "CCE563",
            "Confirmed OLD Network Administration Under Unix to NEW Linux & Windows Networks Administration correspondence.",
        ),
        (
            "ELCC1017", "CCE556",
            "Confirmed OLD Mobile Development & Cloud Computing to NEW Mobile Applications Development correspondence; historical ECTS remain unchanged.",
        ),
    )
    for source_code, target_code, notes in pairs:
        connection.execute(sa.text("""
            INSERT OR IGNORE INTO equivalencies
                (source_course_id, target_course_id, recognizes_history,
                 prospective_registration_allowed, verification_status,
                 provenance, notes)
            SELECT source.id, target.id, 1, NULL, 'HUMAN_VERIFIED',
                   'USER_CONFIRMED_POLICY', :notes
            FROM courses source
            JOIN curriculum_revisions source_revision
              ON source_revision.id = source.curriculum_id
            JOIN courses target ON target.code = :target_code
            JOIN curriculum_revisions target_revision
              ON target_revision.id = target.curriculum_id
            WHERE source.code = :source_code
              AND source_revision.version = 'OLD' AND source_revision.active = 1
              AND target_revision.version = 'NEW' AND target_revision.active = 1
        """), {
            "source_code": source_code,
            "target_code": target_code,
            "notes": notes,
        })
    settings = (
        (
            "allow_final_two_semester_graduation_load", True,
            "Allow up to 36 ECTS in the final two regular semesters only when it improves graduation",
        ),
        (
            "final_two_semester_graduation_capacity", 36,
            "IUL final-two-semester graduation capacity",
        ),
    )
    for key, value, description in settings:
        connection.execute(sa.text("""
            INSERT OR IGNORE INTO engine_settings
                (key, value, description, unverified_assumption)
            VALUES (:key, :value, :description, 0)
        """), {
            "key": key,
            "value": json.dumps(value),
            "description": description,
        })


def downgrade() -> None:
    op.execute("""
        DELETE FROM equivalencies
        WHERE provenance = 'USER_CONFIRMED_POLICY'
          AND (
            (source_course_id IN (SELECT id FROM courses WHERE code = 'ELCC820')
             AND target_course_id IN (SELECT id FROM courses WHERE code = 'CCE563'))
            OR
            (source_course_id IN (SELECT id FROM courses WHERE code = 'ELCC1017')
             AND target_course_id IN (SELECT id FROM courses WHERE code = 'CCE556'))
          )
    """)
    op.execute("""
        DELETE FROM engine_settings
        WHERE key IN (
            'allow_final_two_semester_graduation_load',
            'final_two_semester_graduation_capacity'
        )
    """)

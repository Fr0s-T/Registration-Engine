"""Make transition-catalogue coverage exhaustive and durable.

Revision ID: 20261011_0025
Revises: 20261011_0024
"""
import sqlalchemy as sa
from alembic import op

from academic_planner.matching.catalogue import IUL_OLD_TO_NEW_EQUIVALENCIES

revision = "20261011_0025"
down_revision = "20261011_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if "transition_course_dispositions" not in sa.inspect(connection).get_table_names():
        op.create_table(
            "transition_course_dispositions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "old_course_id", sa.Integer(),
                sa.ForeignKey("courses.id", ondelete="CASCADE"),
                nullable=False, unique=True,
            ),
            sa.Column("disposition", sa.String(40), nullable=False),
            sa.Column(
                "verification_status", sa.String(30), nullable=False,
                server_default="CATALOGUE_REVIEWED",
            ),
            sa.Column(
                "provenance", sa.String(40), nullable=False,
                server_default="CURATED_TRANSITION_CATALOGUE",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "disposition IN ('LEGACY_CREDIT_ONLY','PATHWAY_SPECIFIC')"
            ),
        )

    for old_code, new_code in IUL_OLD_TO_NEW_EQUIVALENCIES:
        connection.execute(sa.text("""
            INSERT OR IGNORE INTO equivalencies
                (source_course_id, target_course_id, recognizes_history,
                 prospective_registration_allowed, verification_status,
                 provenance, notes)
            SELECT source.id, target.id, 1, NULL, 'HUMAN_VERIFIED',
                   'CURATED_TRANSITION_CATALOGUE',
                   'Code-based IUL OLD-to-NEW historical crosswalk. Historical '
                   || 'earned ECTS are preserved; prospective registration is unset.'
            FROM courses source
            JOIN curriculum_revisions source_revision
              ON source_revision.id = source.curriculum_id
            JOIN courses target ON target.code = :new_code
            JOIN curriculum_revisions target_revision
              ON target_revision.id = target.curriculum_id
            WHERE source.code = :old_code
              AND source_revision.version = 'OLD' AND source_revision.active = 1
              AND target_revision.version = 'NEW' AND target_revision.active = 1
        """), {"old_code": old_code, "new_code": new_code})

    connection.execute(sa.text("""
        DELETE FROM transition_course_dispositions
        WHERE old_course_id IN (SELECT source_course_id FROM equivalencies)
    """))
    connection.execute(sa.text("""
        INSERT OR IGNORE INTO transition_course_dispositions
            (old_course_id, disposition, verification_status, provenance, notes)
        SELECT course.id,
               CASE WHEN course.is_fyp = 1
                    THEN 'PATHWAY_SPECIFIC' ELSE 'LEGACY_CREDIT_ONLY' END,
               'CATALOGUE_REVIEWED', 'CURATED_TRANSITION_CATALOGUE',
               CASE WHEN course.is_fyp = 1
                    THEN 'Handled by the registered FYP pathway policy; no direct NEW course substitution is applied.'
                    ELSE 'No direct NEW mapping exists in the curated crosswalk. Earned source ECTS remain valid without satisfying another course.'
               END
        FROM courses course
        JOIN curriculum_revisions revision
          ON revision.id = course.curriculum_id
        WHERE revision.version = 'OLD' AND revision.active = 1
          AND NOT EXISTS (
              SELECT 1 FROM equivalencies equivalency
              WHERE equivalency.source_course_id = course.id
          )
    """))


def downgrade() -> None:
    op.execute("""
        DELETE FROM equivalencies
        WHERE provenance = 'CURATED_TRANSITION_CATALOGUE'
    """)
    op.drop_table("transition_course_dispositions")

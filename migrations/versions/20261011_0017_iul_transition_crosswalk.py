"""Persist source-reviewed IUL transcript aliases and approved equivalencies."""
import sqlalchemy as sa
from alembic import op

revision = "20261011_0017"
down_revision = "20261011_0016"
branch_labels = None
depends_on = None


def upgrade():
    if "transcript_code_mappings" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "transcript_code_mappings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_code", sa.String(40), nullable=False, unique=True),
            sa.Column(
                "target_course_id", sa.Integer(),
                sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=True,
            ),
            sa.Column("mapping_kind", sa.String(30), nullable=False),
            sa.Column(
                "verification_status", sa.String(30), nullable=False,
                server_default="HUMAN_VERIFIED",
            ),
            sa.Column(
                "provenance", sa.String(40), nullable=False,
                server_default="SOURCE_REVIEW",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.CheckConstraint("mapping_kind IN ('COURSE_ALIAS','NON_DEGREE')"),
            sa.CheckConstraint(
                "(mapping_kind = 'COURSE_ALIAS' AND target_course_id IS NOT NULL) OR "
                "(mapping_kind = 'NON_DEGREE' AND target_course_id IS NULL)"
            ),
        )
    connection = op.get_bind()
    target_ids = dict(connection.execute(sa.text("""
        SELECT c.code, MAX(c.id)
        FROM courses c
        JOIN curriculum_revisions r ON r.id = c.curriculum_id
        WHERE r.active = 1 AND c.code IN ('GER224', 'GER350', 'CCE471')
        GROUP BY c.code
    """)).all())
    mappings = (
        ("SOC221", "GER224", "Same-title 2-ECTS Civic Engagement source review."),
        ("SHM350", "GER350", "Work Ready Now transition alias; historical earned ECTS are preserved."),
        ("ELCC608", "CCE471", "Training I transition alias approved from supplied material."),
    )
    for source_code, target_code, notes in mappings:
        target_id = target_ids.get(target_code)
        if target_id is not None:
            connection.execute(sa.text("""
                INSERT OR IGNORE INTO transcript_code_mappings
                    (source_code, target_course_id, mapping_kind,
                     verification_status, provenance, notes)
                VALUES (:source_code, :target_id, 'COURSE_ALIAS',
                        'HUMAN_VERIFIED', 'SOURCE_REVIEW', :notes)
            """), {"source_code": source_code, "target_id": target_id, "notes": notes})
    connection.execute(sa.text("""
        INSERT OR IGNORE INTO transcript_code_mappings
            (source_code, target_course_id, mapping_kind,
             verification_status, provenance, notes)
        VALUES ('ENG108', NULL, 'NON_DEGREE', 'HUMAN_VERIFIED',
                'TRANSCRIPT_POLICY',
                'Transcript marks the course as excluded from GPA and degree credit.')
    """))

    approved_pairs = (
        ("ELBC403", "CCE341"),
        ("ELCC524", "CCE440"),
        ("ELCC619", "CCE442"),
        ("ELCM312", "CSC333"),
        ("ELCC631", "CCE432"),
    )
    for source_code, target_code in approved_pairs:
        connection.execute(sa.text("""
            INSERT OR IGNORE INTO equivalencies
                (source_course_id, target_course_id, recognizes_history,
                 prospective_registration_allowed, verification_status,
                 provenance, notes)
            SELECT source.id, target.id, 1, NULL, 'HUMAN_VERIFIED',
                   'SOURCE_REVIEW',
                   'Approved transition correspondence; historical earned ECTS are preserved.'
            FROM courses source
            JOIN curriculum_revisions source_revision
              ON source_revision.id = source.curriculum_id
            JOIN courses target ON target.code = :target_code
            JOIN curriculum_revisions target_revision
              ON target_revision.id = target.curriculum_id
            WHERE source.code = :source_code
              AND source_revision.version = 'OLD' AND source_revision.active = 1
              AND target_revision.version = 'NEW' AND target_revision.active = 1
        """), {"source_code": source_code, "target_code": target_code})


def downgrade():
    op.execute("""
        DELETE FROM equivalencies
        WHERE provenance = 'SOURCE_REVIEW'
          AND notes = 'Approved transition correspondence; historical earned ECTS are preserved.'
    """)
    op.drop_table("transcript_code_mappings")

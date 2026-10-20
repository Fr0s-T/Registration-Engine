"""Separate governing curriculum from mixed course availability.

Revision ID: 20261012_0033
Revises: 20261012_0032
"""
import sqlalchemy as sa
from alembic import op


revision = "20261012_0033"
down_revision = "20261012_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    student_columns = {
        column["name"] for column in inspector.get_columns("students")
    }
    if "governing_curriculum_version" not in student_columns:
        op.add_column("students", sa.Column(
            "governing_curriculum_version", sa.String(10), nullable=False,
            server_default="OLD",
        ))
        connection.execute(sa.text("""
            UPDATE students
            SET governing_curriculum_version = CASE
                WHEN curriculum_mode = 'NEW' THEN 'NEW'
                ELSE 'OLD'
            END
        """))
    connection.execute(sa.text("""
        UPDATE students
        SET degree_contract_id = NULL
        WHERE governing_curriculum_version = 'OLD'
    """))
    if "curriculum_mode" in student_columns:
        op.drop_column("students", "curriculum_mode")
    if "graduation_pathway_courses" in tables:
        op.drop_table("graduation_pathway_courses")
    if "graduation_pathway_templates" in tables:
        op.drop_table("graduation_pathway_templates")


def downgrade() -> None:
    student_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("students")
    }
    if "curriculum_mode" not in student_columns:
        op.add_column("students", sa.Column(
            "curriculum_mode", sa.String(30), nullable=False,
            server_default="MIXED_ROLLOUT",
        ))
    if "governing_curriculum_version" in student_columns:
        op.drop_column("students", "governing_curriculum_version")

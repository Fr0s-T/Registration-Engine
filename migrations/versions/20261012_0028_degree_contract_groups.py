"""Add source-backed degree contracts and requirement groups.

Revision ID: 20261012_0028
Revises: 20261012_0027
"""
import sqlalchemy as sa
from alembic import op


revision = "20261012_0028"
down_revision = "20261012_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "degree_contracts" not in tables:
        op.create_table(
        "degree_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("curriculum_id", sa.Integer(), nullable=False),
        sa.Column("program_code", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("graduation_ects_target", sa.Integer(), nullable=False),
        sa.Column("effective_academic_year", sa.String(20), nullable=False),
        sa.Column("source_document_id", sa.Integer(), nullable=True),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(["curriculum_id"], ["curriculum_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_document_id"], ["source_documents.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("curriculum_id", "program_code", "effective_academic_year"),
        sa.CheckConstraint("graduation_ects_target > 0"),
        )
        tables.add("degree_contracts")
    if "requirement_groups" not in tables:
        op.create_table(
        "requirement_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("required_ects", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(30), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("source_locator", sa.String(255), nullable=True),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["degree_contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["requirement_groups.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("contract_id", "code"),
        sa.CheckConstraint("required_ects >= 0"),
        sa.CheckConstraint("rule_type IN ('ALL_OF','CREDIT_QUOTA','TRACK_CHOICE','PATHWAY')"),
        )
        tables.add("requirement_groups")
    if "requirement_group_courses" not in tables:
        op.create_table(
        "requirement_group_courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("contribution_ects", sa.Integer(), nullable=False),
        sa.Column("membership_type", sa.String(20), nullable=False),
        sa.Column("language_track", sa.String(8), nullable=True),
        sa.Column("source_locator", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["requirement_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("group_id", "course_id"),
        sa.CheckConstraint("contribution_ects >= 0"),
        sa.CheckConstraint("membership_type IN ('REQUIRED','CANDIDATE')"),
        sa.CheckConstraint("language_track IS NULL OR language_track IN ('EN','FR')"),
        )
    # SQLite supports adding a nullable REFERENCES column directly. Avoid batch
    # table recreation here: child transcript rows use ON DELETE CASCADE and a
    # rebuild can erase them while the temporary students table is swapped.
    student_columns = {column["name"] for column in sa.inspect(bind).get_columns("students")}
    if "degree_contract_id" not in student_columns:
        if bind.dialect.name == "sqlite":
            # SQLite accepts a nullable REFERENCES column in one ALTER statement,
            # while Alembic's generic add_column path incorrectly follows it with
            # an unsupported standalone ADD CONSTRAINT operation.
            op.execute(sa.text(
                "ALTER TABLE students ADD COLUMN degree_contract_id INTEGER "
                "REFERENCES degree_contracts(id) ON DELETE SET NULL"
            ))
        else:
            op.add_column(
                "students",
                sa.Column(
                    "degree_contract_id", sa.Integer(),
                    sa.ForeignKey("degree_contracts.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )


def downgrade() -> None:
    op.drop_column("students", "degree_contract_id")
    op.drop_table("requirement_group_courses")
    op.drop_table("requirement_groups")
    op.drop_table("degree_contracts")

"""Persist transcript credit identity and enforce one prerequisite group.

Revision ID: 20261014_0035
Revises: 20261012_0034
"""

import sqlalchemy as sa
from alembic import op


revision = "20261014_0035"
down_revision = "20261012_0034"
branch_labels = None
depends_on = None


def _has_single_course_group_constraint(inspector: sa.Inspector) -> bool:
    return any(
        set(constraint.get("column_names") or ()) == {"course_id"}
        for constraint in inspector.get_unique_constraints("prerequisite_groups")
    )


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    attempt_columns = {
        column["name"] for column in inspector.get_columns("student_attempts")
    }
    if "credit_identity" not in attempt_columns:
        op.add_column(
            "student_attempts",
            sa.Column("credit_identity", sa.String(160), nullable=True),
        )

    duplicate_courses = connection.execute(sa.text("""
        SELECT course_id
        FROM prerequisite_groups
        GROUP BY course_id
        HAVING COUNT(*) > 1
    """)).scalars().all()
    for course_id in duplicate_courses:
        groups = connection.execute(sa.text("""
            SELECT id, logic, ambiguous
            FROM prerequisite_groups
            WHERE course_id = :course_id
            ORDER BY id
        """), {"course_id": course_id}).mappings().all()
        if any(group["logic"] != "AND" or group["ambiguous"] for group in groups):
            raise RuntimeError(
                "Cannot merge duplicate OR or ambiguous prerequisite groups for "
                f"course_id={course_id}; review them before upgrading."
            )
        keep_id = groups[0]["id"]
        for duplicate in groups[1:]:
            connection.execute(sa.text("""
                INSERT INTO prerequisite_items (group_id, prerequisite_course_id)
                SELECT :keep_id, duplicate.prerequisite_course_id
                FROM prerequisite_items AS duplicate
                WHERE duplicate.group_id = :duplicate_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM prerequisite_items AS existing
                      WHERE existing.group_id = :keep_id
                        AND existing.prerequisite_course_id = duplicate.prerequisite_course_id
                  )
            """), {"keep_id": keep_id, "duplicate_id": duplicate["id"]})
            connection.execute(sa.text(
                "DELETE FROM prerequisite_groups WHERE id = :group_id"
            ), {"group_id": duplicate["id"]})

    inspector = sa.inspect(connection)
    if not _has_single_course_group_constraint(inspector):
        with op.batch_alter_table(
            "prerequisite_groups",
            table_args=(sa.CheckConstraint(
                "logic IN ('AND','OR')", name="ck_prerequisite_groups_logic"
            ),),
        ) as batch:
            batch.create_unique_constraint(
                "uq_prerequisite_groups_course_id", ["course_id"]
            )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if _has_single_course_group_constraint(inspector):
        with op.batch_alter_table(
            "prerequisite_groups",
            table_args=(sa.CheckConstraint(
                "logic IN ('AND','OR')", name="ck_prerequisite_groups_logic"
            ),),
        ) as batch:
            batch.drop_constraint(
                "uq_prerequisite_groups_course_id", type_="unique"
            )
    attempt_columns = {
        column["name"] for column in sa.inspect(connection).get_columns("student_attempts")
    }
    if "credit_identity" in attempt_columns:
        op.drop_column("student_attempts", "credit_identity")

"""Repair foreign-key drift in databases upgraded through older migrations.

Revision ID: 20261014_0036
Revises: 20261014_0035
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op


revision = "20261014_0036"
down_revision = "20261014_0035"
branch_labels = None
depends_on = None


NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _foreign_key(
    inspector: sa.Inspector, table: str, columns: Iterable[str],
) -> dict | None:
    expected = tuple(columns)
    return next((
        foreign_key
        for foreign_key in inspector.get_foreign_keys(table)
        if tuple(foreign_key["constrained_columns"]) == expected
    ), None)


def _foreign_key_matches(
    foreign_key: dict | None, referred_table: str, ondelete: str | None,
) -> bool:
    if foreign_key is None or foreign_key["referred_table"] != referred_table:
        return False
    actual_ondelete = (foreign_key.get("options") or {}).get("ondelete")
    return (actual_ondelete or None) == ondelete


def _repair_foreign_keys(
    table: str,
    desired: tuple[tuple[tuple[str, ...], str, tuple[str, ...], str | None], ...],
    *,
    table_args: tuple[sa.SchemaItem, ...] = (),
) -> None:
    inspector = sa.inspect(op.get_bind())
    repairs = []
    for local_columns, referred_table, remote_columns, ondelete in desired:
        existing = _foreign_key(inspector, table, local_columns)
        if not _foreign_key_matches(existing, referred_table, ondelete):
            repairs.append((existing, local_columns, referred_table, remote_columns, ondelete))
    if not repairs:
        return
    with op.batch_alter_table(
        table,
        recreate="always",
        naming_convention=NAMING_CONVENTION,
        table_args=table_args,
    ) as batch:
        for existing, local_columns, referred_table, remote_columns, ondelete in repairs:
            if existing is not None:
                constraint_name = existing.get("name") or (
                    f"fk_{table}_{local_columns[0]}_{existing['referred_table']}"
                )
                batch.drop_constraint(constraint_name, type_="foreignkey")
            batch.create_foreign_key(
                f"fk_{table}_{local_columns[0]}_{referred_table}",
                referred_table,
                list(local_columns),
                list(remote_columns),
                ondelete=ondelete,
            )


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        # Keep child-table references pointed at the stable table name while
        # Alembic performs its temporary rename/copy/drop sequence.
        connection.execute(sa.text("PRAGMA legacy_alter_table=ON"))
    tables = set(sa.inspect(connection).get_table_names())
    orphan = "_alembic_tmp_curriculum_revisions"
    if orphan in tables:
        rows = connection.execute(sa.text(
            f'SELECT COUNT(*) FROM "{orphan}"'
        )).scalar_one()
        if rows:
            raise RuntimeError(
                f"Refusing to remove {orphan}: it contains {rows} row(s)."
            )
        op.drop_table(orphan)

    _repair_foreign_keys("curriculum_revisions", (
        (("source_document_id",), "source_documents", ("id",), None),
    ))
    _repair_foreign_keys(
        "students",
        (
            (("degree_contract_id",), "degree_contracts", ("id",), "SET NULL"),
        ),
        table_args=(
            sa.CheckConstraint(
                "nominal_year BETWEEN 1 AND 5", name="ck_students_nominal_year"
            ),
            sa.CheckConstraint(
                "language_track IN ('EN','FR')", name="ck_students_language_track"
            ),
            sa.CheckConstraint(
                "governing_curriculum_version IN ('OLD','NEW')",
                name="ck_students_governing_curriculum_version",
            ),
            sa.CheckConstraint(
                "reported_earned_credits >= 0",
                name="ck_students_reported_earned_credits",
            ),
            sa.CheckConstraint(
                "graduation_credit_target > 0",
                name="ck_students_graduation_credit_target",
            ),
        ),
    )
    _repair_foreign_keys("degree_requirements", (
        (("course_id",), "courses", ("id",), "CASCADE"),
    ))
    _repair_foreign_keys(
        "equivalencies",
        (
            (("source_course_id",), "courses", ("id",), "CASCADE"),
            (("target_course_id",), "courses", ("id",), "CASCADE"),
        ),
        table_args=(sa.CheckConstraint(
            "source_course_id <> target_course_id",
            name="ck_equivalencies_distinct_courses",
        ),),
    )
    _repair_foreign_keys(
        "offerings",
        (
            (("course_id",), "courses", ("id",), "CASCADE"),
            (("source_document_id",), "source_documents", ("id",), None),
        ),
        table_args=(sa.CheckConstraint(
            "semester IN ('FALL','SPRING')", name="ck_offerings_semester"
        ),),
    )
    _repair_foreign_keys("student_requirements", (
        (("course_id",), "courses", ("id",), "RESTRICT"),
    ))
    _repair_foreign_keys(
        "student_recognitions",
        (
            (("source_course_id",), "courses", ("id",), "RESTRICT"),
            (("target_course_id",), "courses", ("id",), "RESTRICT"),
        ),
        table_args=(sa.CheckConstraint(
            "source_course_id <> target_course_id",
            name="ck_student_recognitions_distinct_courses",
        ),),
    )
    _repair_foreign_keys(
        "student_offering_overrides",
        (
            (("course_id",), "courses", ("id",), "RESTRICT"),
        ),
        table_args=(
            sa.CheckConstraint(
                "semester IN ('FALL','SPRING')",
                name="ck_student_offering_overrides_semester",
            ),
            sa.CheckConstraint(
                "language_track IS NULL OR language_track IN ('EN','FR')",
                name="ck_student_offering_overrides_language_track",
            ),
        ),
    )
    if connection.dialect.name == "sqlite":
        violations = connection.execute(sa.text("PRAGMA foreign_key_check")).all()
        if violations:
            raise RuntimeError(
                "Schema repair produced foreign-key violations: "
                + repr(violations[:10])
            )
        connection.execute(sa.text("PRAGMA legacy_alter_table=OFF"))


def downgrade() -> None:
    # This migration repairs accidental historical drift. Reintroducing the
    # inconsistent constraints would make student-data deletion behavior unsafe.
    pass

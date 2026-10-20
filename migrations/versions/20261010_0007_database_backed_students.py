"""Add database-backed students, attempts, requirements, and local planning rules."""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0007"
down_revision = "20261010_0006"
branch_labels = None
depends_on = None


def upgrade():
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())

    def create_if_missing(name, *columns):
        if name not in existing_tables:
            op.create_table(name, *columns)

    create_if_missing(
        "students",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identifier", sa.String(100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("nominal_year", sa.Integer(), nullable=False),
        sa.Column("language_track", sa.String(8), nullable=False),
        sa.Column("curriculum_mode", sa.String(30), nullable=False, server_default="MIXED_ROLLOUT"),
        sa.Column("reported_earned_credits", sa.Integer(), nullable=False),
        sa.Column("graduation_credit_target", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("passing_grade", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("nominal_year BETWEEN 1 AND 5"),
        sa.CheckConstraint("language_track IN ('EN','FR')"),
        sa.CheckConstraint("reported_earned_credits >= 0"),
        sa.CheckConstraint("graduation_credit_target > 0"),
    )
    create_if_missing(
        "student_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_code", sa.String(40), nullable=False),
        sa.Column("source_title", sa.String(255), nullable=True),
        sa.Column("ects", sa.Integer(), nullable=False),
        sa.Column("source_term", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("grade", sa.Float(), nullable=True),
        sa.Column("earned_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_value", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("student_id", "source_code", "source_term"),
        sa.CheckConstraint("ects >= 0 AND earned_credits >= 0"),
    )
    create_if_missing(
        "student_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("authority", sa.String(80), nullable=False, server_default="LOCAL_ADMIN"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("student_id", "course_id"),
    )
    create_if_missing(
        "student_recognitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recognizes_history", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("verification_status", sa.String(30), nullable=False, server_default="STUDENT_CONFIRMED"),
        sa.Column("authority", sa.String(80), nullable=False, server_default="STUDENT_CONFIRMED"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("student_id", "source_course_id", "target_course_id"),
        sa.CheckConstraint("source_course_id <> target_course_id"),
    )
    create_if_missing(
        "student_capacity_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("academic_year_start", sa.Integer(), nullable=False),
        sa.Column("semester", sa.String(20), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("authority", sa.String(80), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("student_id", "academic_year_start", "semester"),
        sa.CheckConstraint("semester IN ('FALL','SPRING')"),
        sa.CheckConstraint("capacity >= 0 AND capacity <= 60"),
    )
    create_if_missing(
        "student_offering_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("academic_year_start", sa.Integer(), nullable=False),
        sa.Column("semester", sa.String(20), nullable=False),
        sa.Column("language_track", sa.String(8), nullable=True),
        sa.Column("delivery_mode", sa.String(30), nullable=False, server_default="ARRANGED"),
        sa.Column("authority", sa.String(80), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("student_id", "course_id", "academic_year_start", "semester"),
        sa.CheckConstraint("semester IN ('FALL','SPRING')"),
        sa.CheckConstraint("language_track IS NULL OR language_track IN ('EN','FR')"),
    )


def downgrade():
    op.drop_table("student_offering_overrides")
    op.drop_table("student_capacity_overrides")
    op.drop_table("student_recognitions")
    op.drop_table("student_requirements")
    op.drop_table("student_attempts")
    op.drop_table("students")

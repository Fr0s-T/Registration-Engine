"""Classify catalog graduation roles using the confirmed ECTS-band rule."""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0010"
down_revision = "20261011_0009"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("courses")}
    if "graduation_role" not in columns:
        op.add_column("courses", sa.Column(
            "graduation_role", sa.String(30), nullable=False,
            server_default="NEEDS_REVIEW",
        ))
    if "graduation_role_basis" not in columns:
        op.add_column("courses", sa.Column(
            "graduation_role_basis", sa.String(80), nullable=False,
            server_default="USER_CONFIRMED_CREDIT_BAND_RULE",
        ))
    op.execute("""
        UPDATE courses
        SET graduation_role = CASE
            WHEN is_fyp = 1 OR ects >= 5 THEN 'MANDATORY'
            WHEN ects BETWEEN 1 AND 3 THEN 'OPTIONAL'
            ELSE 'NEEDS_REVIEW'
        END,
        graduation_role_basis = 'USER_CONFIRMED_CREDIT_BAND_RULE'
    """)
    # Existing imports treated every catalog row as mandatory. Keep only rows
    # authorized by the new role; student-specific contracts remain untouched.
    op.execute("""
        DELETE FROM degree_requirements
        WHERE course_id IN (
            SELECT id FROM courses WHERE graduation_role <> 'MANDATORY'
        )
    """)


def downgrade():
    op.drop_column("courses", "graduation_role_basis")
    op.drop_column("courses", "graduation_role")

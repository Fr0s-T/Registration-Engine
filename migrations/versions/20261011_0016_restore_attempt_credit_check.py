"""Restore the named attempt-credit constraint after SQLite column migration."""
from alembic import op

revision = "20261011_0016"
down_revision = "20261011_0015"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("student_attempts") as batch:
        batch.create_check_constraint(
            "ck_student_attempts_nonnegative_credits",
            "ects >= 0 AND earned_credits >= 0",
        )


def downgrade():
    with op.batch_alter_table("student_attempts") as batch:
        batch.drop_constraint(
            "ck_student_attempts_nonnegative_credits", type_="check"
        )

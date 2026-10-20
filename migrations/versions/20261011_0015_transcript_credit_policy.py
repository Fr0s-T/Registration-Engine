"""Store transcript credit/GPA policy and evidence status explicitly."""
import sqlalchemy as sa
from alembic import op

revision = "20261011_0015"
down_revision = "20261011_0014"
branch_labels = None
depends_on = None


def upgrade():
    # These are plain SQLite-compatible ADD COLUMN operations.  Recreating the
    # table in batch mode makes SQLAlchemy infer contradictory column-order
    # edges on a clean migration chain and raises CircularDependencyError.
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("student_attempts")
    }
    if "counts_toward_degree_credit" not in existing:
        op.add_column("student_attempts", sa.Column(
            "counts_toward_degree_credit", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ))
    if "counts_toward_gpa" not in existing:
        op.add_column("student_attempts", sa.Column(
            "counts_toward_gpa", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ))
    if "evidence_status" not in existing:
        op.add_column("student_attempts", sa.Column(
            "evidence_status", sa.String(40), nullable=False,
            server_default="OFFICIAL_TRANSCRIPT",
        ))
    op.execute("""
        UPDATE student_attempts
        SET counts_toward_degree_credit = 0,
            counts_toward_gpa = 0,
            earned_credits = 0
        WHERE source_code = 'ENG108'
    """)
    op.execute("""
        UPDATE student_attempts
        SET evidence_status = 'USER_CONFIRMED_PROVISIONAL'
        WHERE source_code = 'ELCC819'
          AND notes IS NOT NULL
    """)


def downgrade():
    with op.batch_alter_table("student_attempts") as batch:
        batch.drop_column("evidence_status")
        batch.drop_column("counts_toward_gpa")
        batch.drop_column("counts_toward_degree_credit")

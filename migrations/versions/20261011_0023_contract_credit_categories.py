"""Add storage for source-reported contract credit-category snapshots.

Revision ID: 20261011_0023
Revises: 20261011_0022
"""
import sqlalchemy as sa
from alembic import op

revision = "20261011_0023"
down_revision = "20261011_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("students")
    }
    if "contract_credit_categories" not in existing:
        op.add_column(
            "students",
            sa.Column("contract_credit_categories", sa.JSON(), nullable=True),
        )
def downgrade() -> None:
    with op.batch_alter_table("students") as batch:
        batch.drop_column("contract_credit_categories")

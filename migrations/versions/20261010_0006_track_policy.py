"""Separate academic track policy from section teaching language."""
from alembic import op
import sqlalchemy as sa

revision = "20261010_0006"
down_revision = "20261010_0005"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("courses")}
    with op.batch_alter_table("courses") as batch:
        if "academic_track_policy" not in columns:
            batch.add_column(sa.Column("academic_track_policy", sa.String(30), nullable=False, server_default="UNCLASSIFIED"))
        if "permitted_student_tracks" not in columns:
            batch.add_column(sa.Column("permitted_student_tracks", sa.JSON(), nullable=False, server_default="[]"))

    # Existing language-scoped requirements are authoritative enough to classify only
    # those courses. Everything else stays fail-closed until an administrator reviews it.
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT course_id, language_track FROM degree_requirements WHERE language_track IN ('EN','FR')"
    )).fetchall()
    for course_id, track in rows:
        connection.execute(sa.text(
            "UPDATE courses SET academic_track_policy='TRACK_SPECIFIC', permitted_student_tracks=:tracks WHERE id=:id"
        ), {"tracks": f'["{track}"]', "id": course_id})
    shared_ids = connection.execute(sa.text(
        "SELECT DISTINCT course_id FROM degree_requirements WHERE language_track IS NULL"
    )).fetchall()
    for (course_id,) in shared_ids:
        connection.execute(sa.text(
            "UPDATE courses SET academic_track_policy='SHARED', permitted_student_tracks='[\"EN\",\"FR\"]' WHERE id=:id"
        ), {"id": course_id})


def downgrade():
    with op.batch_alter_table("courses") as batch:
        batch.drop_column("permitted_student_tracks")
        batch.drop_column("academic_track_policy")

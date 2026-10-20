from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from academic_planner.database.models import (
    CourseRecord, CurriculumRevision, MeetingRecord, Offering,
)
from academic_planner.database.service import generate_year_1_2_placeholders, seed_defaults
from academic_planner.database.session import Base


def test_generation_is_deterministic_labeled_and_preserves_later_years():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_defaults(db)
        revision = CurriculumRevision(version="NEW", revision="test")
        db.add(revision); db.flush()
        for year, code in ((1, "Y1"), (2, "Y2"), (3, "Y3")):
            db.add(CourseRecord(curriculum_id=revision.id, code=code, title=code, ects=5,
                reference_year=year, reference_semester="FALL"))
        db.flush()
        y3 = db.scalar(select(CourseRecord).where(CourseRecord.code == "Y3"))
        real = Offering(course_id=y3.id, academic_year_start=2026, semester="FALL",
                        language_track="EN", provenance="TIMETABLE_CSV_IMPORT",
                        verification_status="SOURCE_IMPORTED")
        db.add(real); db.flush()
        real_id = real.id

        first = generate_year_1_2_placeholders(db)
        db.flush()
        signature_one = [(row.course_id, row.language_track, row.provenance)
                         for row in db.scalars(select(Offering).where(
                             Offering.provenance == "SYNTHETIC_PLACEHOLDER").order_by(
                                 Offering.course_id, Offering.language_track))]
        assert first["generated_offerings"] == 4
        assert {track for _, track, _ in signature_one} == {"EN", "FR"}
        assert db.get(Offering, real_id) is not None

        second = generate_year_1_2_placeholders(db)
        db.flush()
        signature_two = [(row.course_id, row.language_track, row.provenance)
                         for row in db.scalars(select(Offering).where(
                             Offering.provenance == "SYNTHETIC_PLACEHOLDER").order_by(
                                 Offering.course_id, Offering.language_track))]
        assert signature_two == signature_one
        assert second["replaced_placeholders"] == 4
        assert db.scalar(select(func.count(MeetingRecord.id))) == 8
        assert db.get(Offering, real_id) is not None

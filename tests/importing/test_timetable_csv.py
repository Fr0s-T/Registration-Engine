import csv

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.pool import StaticPool

from academic_planner.database.models import (
    ActiveTerm, CourseRecord, CurriculumRevision, Offering, SectionRecord,
)
from academic_planner.database.loader import DatabasePlanningLoader
from academic_planner.database.session import Base
from academic_planner.domain.models import LanguageTrack, StudentAcademicState
from academic_planner.importing import ParsedTimetableCsvImporter


HEADERS = ["source_pdf_page", "year", "language", "day", "start", "end",
           "course", "kind", "group", "instructor", "room", "notes"]


def database():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine


def write_csv(path):
    rows = [
        [1, 3, "English", "Tuesday", "08:00", "10:30", "Digital Signal Processing", "Lecture", "", "Dr. Lecture", "E2-1", ""],
        [1, 3, "English", "Wednesday", "11:00", "12:15", "DSP laboratory", "Lab", "Group 1", "Dr. Lab", "E2-2", ""],
        [1, 3, "English", "Wednesday", "12:15", "13:30", "DSP laboratory", "Lab", "Group 2", "Dr. Lab", "E2-2", ""],
        [2, 3, "French", "Thursday", "08:00", "10:30", "WRN (Work Ready Now)", "Lecture", "", "Dr. WRN", "", "No catalog mapping"],
        [3, 5, "French", "Friday", "08:00", "10:30", "Image Processing", "Lecture", "", "Dr. Image", "E2-3", ""],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(HEADERS); writer.writerows(rows)


def test_timetable_csv_replaces_only_years_3_to_5_and_builds_lab_bundles(tmp_path):
    path = tmp_path / "parsed_timetables.csv"; write_csv(path)
    engine = database()
    with Session(engine) as session:
        old = CurriculumRevision(version="OLD", revision="test")
        new = CurriculumRevision(version="NEW", revision="test")
        session.add_all([old, new]); session.flush()
        year2 = CourseRecord(curriculum_id=new.id, code="Y2", title="Keep", ects=5,
            reference_year=2, reference_semester="FALL")
        dsp = CourseRecord(curriculum_id=new.id, code="CCE450", title="Digital Signal Processing", ects=5,
            reference_year=3, reference_semester="FALL")
        image = CourseRecord(curriculum_id=old.id, code="ELBC901", title="Image Processing + Lab", ects=5,
            reference_year=5, reference_semester="FALL")
        session.add_all([year2, dsp, image]); session.flush()
        session.add(ActiveTerm(id=1, academic_year_start=2026, semester="FALL"))
        session.add(Offering(course_id=year2.id, academic_year_start=2026, semester="FALL",
                             language_track="EN"))
        session.commit()

        result = ParsedTimetableCsvImporter().replace_years_3_to_5(session, path)
        session.commit()
        assert result.rows_read == 5 and result.offerings_inserted == 2
        assert len(result.unresolved_rows) == 1
        assert result.unresolved_rows[0]["course"] == "WRN (Work Ready Now)"
        assert session.scalar(select(Offering).where(Offering.course_id == year2.id)) is not None

        offering = session.scalar(select(Offering).where(
            Offering.course_id == dsp.id).options(
                selectinload(Offering.sections).selectinload(SectionRecord.meetings)))
        assert offering.language_track == "EN" and offering.verification_status == "SOURCE_IMPORTED"
        assert {section.bundle_key for section in offering.sections} == {"EN-1", "EN-2"}
        assert len([section for section in offering.sections if section.component == "LECTURE"]) == 2
        assert len([section for section in offering.sections if section.component == "LAB"]) == 2
        assert all({section.component for section in offering.sections
                    if section.bundle_key == key} == {"LECTURE", "LAB"}
                   for key in {"EN-1", "EN-2"})
        assert any(section.instructor == "Dr. Lab" for section in offering.sections)
        problem = DatabasePlanningLoader().load_problem(
            session, StudentAcademicState(3, LanguageTrack.EN))
        current = problem.configuration.planning_horizon[0]
        active_offerings = [row for row in problem.offerings if row.term == current]
        assert all(row.course_id != str(image.id) for row in active_offerings)  # FR only
        bundle_ids = [bundle.id for row in active_offerings for bundle in row.bundles]
        assert len(bundle_ids) == len(set(bundle_ids))
        assert all(":" in bundle_id for bundle_id in bundle_ids)


def test_synthetic_timetable_reports_only_documented_wrn_gap(tmp_path):
    path = tmp_path / "parsed_timetables.csv"
    write_csv(path)
    rows = ParsedTimetableCsvImporter().parse(path)
    assert len(rows) == 5
    from academic_planner.importing.timetable_csv import COURSE_MAPPING
    unresolved = [row for row in rows if (row.year, row.canonical_course) not in COURSE_MAPPING]
    assert len(unresolved) == 1
    assert {row.source_course for row in unresolved} == {"WRN (Work Ready Now)"}

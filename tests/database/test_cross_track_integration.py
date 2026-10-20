from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from academic_planner.database.loader import DatabasePlanningLoader
from academic_planner.database.models import (
    ActiveTerm, CourseRecord, CurriculumRevision, DegreeRequirement, EngineSetting,
    MeetingRecord, Offering, SectionRecord,
)
from academic_planner.database.service import seed_defaults
from academic_planner.database.session import Base
from academic_planner.domain.models import LanguageTrack, StudentAcademicState
from academic_planner.optimization import GlobalPlanner
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy,
)


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def add_course(db, revision, code, *, policy="SHARED", tracks=("EN", "FR"), requirement_track=None):
    row = CourseRecord(
        curriculum_id=revision.id, code=code, title=code, ects=5,
        reference_year=1, reference_semester="FALL",
        academic_track_policy=policy, permitted_student_tracks=list(tracks),
    )
    db.add(row); db.flush()
    db.add(DegreeRequirement(curriculum_id=revision.id, course_id=row.id,
                             language_track=requirement_track))
    return row


def add_offering(db, course, track, day, start=510, *, bundle="A"):
    row = Offering(course_id=course.id, academic_year_start=2026, semester="FALL",
                   language_track=track, verification_status="VERIFIED")
    db.add(row); db.flush()
    section = SectionRecord(offering_id=row.id, code=f"{track}-{bundle}",
                            component="LECTURE", bundle_key=bundle)
    db.add(section); db.flush()
    db.add(MeetingRecord(section_id=section.id, weekday=day,
                         start_minute=start, end_minute=start + 150))


def solve(db, student):
    problem = DatabasePlanningLoader().load_problem(db, student)
    plan = GlobalPlanner(ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(),
                         AllowAllRegistrationPolicy()).plan(problem)
    return problem, plan


def test_cross_track_sections_are_bundle_alternatives_and_resolve_conflict():
    with session() as db:
        seed_defaults(db)
        revision = CurriculumRevision(version="NEW", revision="test", accepted_credit_target=10)
        db.add(revision); db.flush()
        a = add_course(db, revision, "A")
        b = add_course(db, revision, "B")
        add_offering(db, a, "EN", 0)
        add_offering(db, b, "EN", 0)
        add_offering(db, b, "FR", 1, start=690)
        student = StudentAcademicState(1, LanguageTrack.EN)

        problem, disabled = solve(db, student)
        assert len(disabled.scheduled_terms[0].course_ids) == 1
        assert all(section.teaching_language is not LanguageTrack.FR
                   for offering in problem.offerings for bundle in offering.bundles
                   for section in bundle.sections)

        db.get(EngineSetting, "allow_cross_track_shared_sections").value = True
        problem, enabled = solve(db, student)
        assert set(enabled.scheduled_terms[0].course_ids) == {str(a.id), str(b.id)}
        chosen = {bundle.id: bundle for offering in problem.offerings for bundle in offering.bundles
                  if bundle.id in enabled.scheduled_terms[0].bundle_ids}
        assert any(section.teaching_language is LanguageTrack.FR
                   for bundle in chosen.values() for section in bundle.sections)
        assert sum(problem.courses[c].credits for c in enabled.scheduled_terms[0].course_ids) == 10


def test_track_specific_requirement_cannot_be_replaced_by_other_course():
    with session() as db:
        seed_defaults(db)
        revision = CurriculumRevision(version="NEW", revision="language", accepted_credit_target=5)
        db.add(revision); db.flush()
        english = add_course(db, revision, "ENGLISH", policy="TRACK_SPECIFIC",
                             tracks=("EN",), requirement_track="EN")
        french = add_course(db, revision, "FRENCH", policy="TRACK_SPECIFIC",
                            tracks=("FR",), requirement_track="FR")
        add_offering(db, english, "EN", 0)
        add_offering(db, french, "FR", 1)
        db.get(EngineSetting, "allow_cross_track_shared_sections").value = True

        problem, plan = solve(db, StudentAcademicState(1, LanguageTrack.EN))
        all_selected = {course_id for term in plan.scheduled_terms for course_id in term.course_ids}
        assert str(english.id) in all_selected
        assert str(french.id) not in all_selected
        assert problem.curriculum.resolved_requirements(LanguageTrack.EN) == frozenset({str(english.id)})

        problem, plan = solve(db, StudentAcademicState(1, LanguageTrack.FR))
        all_selected = {course_id for term in plan.scheduled_terms for course_id in term.course_ids}
        assert str(french.id) in all_selected
        assert str(english.id) not in all_selected
        assert problem.curriculum.resolved_requirements(LanguageTrack.FR) == frozenset({str(french.id)})


def test_unclassified_course_does_not_gain_alternate_track_section():
    with session() as db:
        seed_defaults(db)
        revision = CurriculumRevision(version="NEW", revision="unclassified", accepted_credit_target=5)
        db.add(revision); db.flush()
        course = add_course(db, revision, "UNKNOWN", policy="UNCLASSIFIED", tracks=())
        add_offering(db, course, "FR", 1)
        db.get(EngineSetting, "allow_cross_track_shared_sections").value = True
        problem = DatabasePlanningLoader().load_problem(db, StudentAcademicState(1, LanguageTrack.EN))
        current = problem.configuration.planning_horizon[0]
        assert not any(offering.course_id == str(course.id) and offering.term == current
                       for offering in problem.offerings)

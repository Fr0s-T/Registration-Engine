from dataclasses import replace

from academic_planner.domain.models import (
    AcademicTerm, AttemptStatus, CourseAttempt, Curriculum, CurriculumVersion,
    LanguageTrack, PlanningConfiguration, StudentAcademicState, TermKind,
)
from academic_planner.optimization import PlanningProblem
from academic_planner.planning import apply_registered_fyp_track
from tests.conftest import course


def test_in_progress_old_fyp_locks_only_the_complete_old_fyp_pathway():
    old_one = course("OLD_FYP_1", 8, year=5, version=CurriculumVersion.OLD)
    old_two = course(
        "OLD_FYP_2", 14, year=5, version=CurriculumVersion.OLD,
        semester=TermKind.SPRING,
    )
    new_fyp = course(
        "NEW_FYP", 18, year=5, version=CurriculumVersion.NEW,
        semester=TermKind.SPRING,
    )
    regular = course("REGULAR", 5, year=5)
    # Course helper defaults is_fyp=False; preserve all other source metadata.
    old_one = replace(old_one, is_fyp=True)
    old_two = replace(old_two, is_fyp=True)
    new_fyp = replace(new_fyp, is_fyp=True)
    courses = {item.id: item for item in (old_one, old_two, new_fyp, regular)}
    student = StudentAcademicState(5, LanguageTrack.EN, (
        CourseAttempt(
            old_one.id, AcademicTerm(2026, TermKind.FALL),
            AttemptStatus.IN_PROGRESS,
        ),
    ))
    problem = PlanningProblem(
        courses,
        Curriculum(
            CurriculumVersion.NEW,
            frozenset({new_fyp.id, regular.id}),
            300,
            new_fyp.id,
        ),
        student,
        (), (), (), PlanningConfiguration(),
    )

    updated, pathway = apply_registered_fyp_track(problem)

    assert set(pathway) == {old_one.id, old_two.id}
    assert updated.curriculum.requirement_ids == frozenset({
        old_one.id, old_two.id, regular.id,
    })
    assert updated.curriculum.fyp_requirement_id == old_two.id

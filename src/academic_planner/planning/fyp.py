"""Final-project pathway selection for students already inside a curriculum track."""
from __future__ import annotations

from dataclasses import replace

from academic_planner.domain.models import AttemptStatus, Curriculum
from academic_planner.optimization import PlanningProblem


def apply_registered_fyp_track(
    problem: PlanningProblem,
) -> tuple[PlanningProblem, tuple[str, ...]]:
    """Replace the configured FYP with the complete registered FYP pathway.

    Registration in any FYP component locks only the FYP pathway, not the
    student's other course choices.  Every FYP course from that curriculum is
    required, so a two-part OLD project remains two parts with its source ECTS.
    """
    registered_fyp = {
        attempt.course_id
        for attempt in problem.student.attempts
        if attempt.status in {AttemptStatus.REGISTERED, AttemptStatus.IN_PROGRESS}
        and attempt.course_id in problem.courses
        and problem.courses[attempt.course_id].is_fyp
    }
    if not registered_fyp:
        return problem, ()
    versions = {
        problem.courses[course_id].curriculum_version
        for course_id in registered_fyp
    }
    if len(versions) != 1:
        raise ValueError("current FYP registrations span more than one curriculum")
    version = next(iter(versions))
    pathway = frozenset(
        course.id for course in problem.courses.values()
        if course.is_fyp and course.curriculum_version is version
    )
    if not pathway:
        raise ValueError(f"registered {version.value} FYP pathway has no course definitions")
    current_fyp_ids = frozenset(
        course_id for course_id in problem.curriculum.requirement_ids
        if course_id in problem.courses and problem.courses[course_id].is_fyp
    )
    requirements = (problem.curriculum.requirement_ids - current_fyp_ids) | pathway
    final_component = max(
        pathway,
        key=lambda course_id: (
            problem.courses[course_id].reference_year,
            problem.courses[course_id].reference_semester.value,
            problem.courses[course_id].code,
        ),
    )
    curriculum = problem.curriculum
    updated = Curriculum(
        curriculum.version,
        requirements,
        curriculum.accepted_credit_target,
        final_component,
        curriculum.training_requirement_ids,
        curriculum.language_requirements,
    )
    return replace(problem, curriculum=updated), tuple(sorted(pathway))

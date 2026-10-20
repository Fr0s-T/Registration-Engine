"""Translate contract requirements into valid registration alternatives."""
from __future__ import annotations

from typing import TYPE_CHECKING

from academic_planner.domain.models import CurriculumVersion

if TYPE_CHECKING:
    from academic_planner.optimization import PlanningProblem


def requirement_delivery_options(
    problem: PlanningProblem,
    requirement_ids: frozenset[str] | set[str],
) -> dict[str, frozenset[str]]:
    """Return schedulable course identities for each contract requirement.

    OLD students retain OLD requirements. A verified prospective OLD→NEW
    equivalency adds the NEW course as an alternative delivery; it never turns
    the student's contract into the NEW curriculum.
    """
    options = {requirement_id: {requirement_id} for requirement_id in requirement_ids}
    if problem.curriculum.version is CurriculumVersion.OLD:
        for equivalency in problem.equivalencies:
            if not equivalency.prospective_registration_allowed:
                continue
            for requirement_id in equivalency.source_course_ids & options.keys():
                options[requirement_id].update(
                    course_id for course_id in equivalency.target_requirement_ids
                    if course_id in problem.courses
                )
    return {
        requirement_id: frozenset(course_ids)
        for requirement_id, course_ids in options.items()
    }

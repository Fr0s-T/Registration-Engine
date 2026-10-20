from __future__ import annotations

from dataclasses import dataclass
import logging

from academic_planner.domain.models import GraduationPlan
from academic_planner.optimization import PlanningProblem
from academic_planner.policies import (
    AcademicRegistrationPolicy, ProgressiveRolloutPolicy,
    effective_credit_capacity,
)
from academic_planner.reconciliation import ReconciliationService


LOGGER = logging.getLogger("academic_planner.diagnostics")


@dataclass(frozen=True)
class CourseTermAudit:
    course_id: str
    course_code: str
    reference_year: int
    applicable_requirement: bool
    requirement_outstanding: bool
    offered: bool
    missing_prerequisite_ids: tuple[str, ...]
    prerequisites_satisfied: bool
    rollout_permitted: bool
    rollout_reason: str
    registration_rejection: str | None
    eligible: bool
    selected: bool


@dataclass(frozen=True)
class SemesterAudit:
    term_label: str
    rollout_frontier: int
    timetable_basis: str
    satisfied_before_codes: tuple[str, ...]
    remaining_requirement_codes: tuple[str, ...]
    offered_course_codes: tuple[str, ...]
    prerequisite_valid_course_codes: tuple[str, ...]
    rollout_rejected_course_codes: tuple[str, ...]
    prerequisite_rejected_course_codes: tuple[str, ...]
    registration_rejected_course_codes: tuple[str, ...]
    eligible_course_codes: tuple[str, ...]
    eligible_credits: int
    selected_course_codes: tuple[str, ...]
    selected_credits: int
    effective_capacity: int
    capacity_reason: str
    unused_capacity: int
    deferred_eligible_course_codes: tuple[str, ...]
    courses: tuple[CourseTermAudit, ...]


@dataclass(frozen=True)
class PlanningAudit:
    semesters: tuple[SemesterAudit, ...]

    def trace_course(self, course_id_or_code: str) -> tuple[CourseTermAudit, ...]:
        normalized = course_id_or_code.upper()
        exact = [
            course for semester in self.semesters for course in semester.courses
            if course.course_id.upper() == normalized
        ]
        if exact:
            course_id = exact[0].course_id
        else:
            matching_ids = {
                course.course_id for semester in self.semesters for course in semester.courses
                if course.course_code.upper() == normalized
            }
            if not matching_ids:
                raise ValueError(f"unknown course: {course_id_or_code}")
            if len(matching_ids) > 1:
                raise ValueError(
                    f"ambiguous course code {course_id_or_code}; use one of "
                    f"{', '.join(sorted(matching_ids))}"
                )
            course_id = next(iter(matching_ids))
        return tuple(
            next(course for course in semester.courses if course.course_id == course_id)
            for semester in self.semesters
        )


def build_plan_audit(
    problem: PlanningProblem,
    plan: GraduationPlan,
    rollout_policy: ProgressiveRolloutPolicy,
    registration_policy: AcademicRegistrationPolicy,
) -> PlanningAudit:
    reconciliation = ReconciliationService().reconcile(
        problem.student, problem.curriculum, problem.equivalencies
    )
    applicable_ids = problem.curriculum.resolved_requirements(
        problem.student.language_track
    )
    satisfied = set(reconciliation.prerequisite_completion_ids)
    offering_map = {
        (offering.course_id, offering.term): offering
        for offering in problem.offerings
    }
    prerequisites = {
        rule.course_id: rule.all_of for rule in problem.prerequisites
    }
    scheduled_by_term = {
        scheduled.term: set(scheduled.course_ids)
        for scheduled in plan.scheduled_terms
    }
    semesters = []
    for term_index, scheduled in enumerate(plan.scheduled_terms):
        selected_ids = scheduled_by_term.get(scheduled.term, set())
        remaining_ids = applicable_ids - satisfied
        course_audits = []
        for course in sorted(problem.courses.values(), key=lambda item: item.id):
            missing = tuple(sorted(prerequisites.get(course.id, frozenset()) - satisfied))
            rollout = rollout_policy.permits(course, scheduled.term)
            registration_rejection = registration_policy.rejection_reason(
                problem.student, course, scheduled.term
            )
            applicable = course.id in applicable_ids
            outstanding = course.id in remaining_ids
            offered = (course.id, scheduled.term) in offering_map
            eligible = (
                applicable and outstanding and offered and not missing
                and rollout.permitted and registration_rejection is None
            )
            course_audits.append(CourseTermAudit(
                course_id=course.id,
                course_code=course.code,
                reference_year=course.reference_year,
                applicable_requirement=applicable,
                requirement_outstanding=outstanding,
                offered=offered,
                missing_prerequisite_ids=missing,
                prerequisites_satisfied=not missing,
                rollout_permitted=rollout.permitted,
                rollout_reason=rollout.reason,
                registration_rejection=registration_rejection,
                eligible=eligible,
                selected=course.id in selected_ids,
            ))
        active = [course for course in course_audits if course.requirement_outstanding]
        eligible = [course for course in active if course.eligible]
        selected_credits = sum(problem.courses[item].credits for item in selected_ids)
        capacity = effective_credit_capacity(
            problem.student,
            scheduled.term,
            problem.configuration,
            reconciliation.outstanding_requirement_ids,
            frozenset(selected_ids),
        )
        semesters.append(SemesterAudit(
            term_label=scheduled.term.label(),
            rollout_frontier=rollout_policy.new_curriculum_frontier(scheduled.term),
            timetable_basis=(
                "EXACT_CURRENT_SECTIONS" if term_index == 0
                else "FUTURE_AVAILABILITY_ONLY"
            ),
            satisfied_before_codes=_codes(problem, satisfied),
            remaining_requirement_codes=_codes(problem, remaining_ids),
            offered_course_codes=tuple(sorted(
                course.course_code for course in active if course.offered
            )),
            prerequisite_valid_course_codes=tuple(sorted(
                course.course_code for course in active
                if course.offered and course.prerequisites_satisfied
            )),
            rollout_rejected_course_codes=tuple(sorted(
                course.course_code for course in active
                if course.offered and course.prerequisites_satisfied
                and not course.rollout_permitted
            )),
            prerequisite_rejected_course_codes=tuple(sorted(
                course.course_code for course in active
                if course.offered and not course.prerequisites_satisfied
            )),
            registration_rejected_course_codes=tuple(sorted(
                course.course_code for course in active
                if course.offered and course.prerequisites_satisfied
                and course.rollout_permitted
                and course.registration_rejection is not None
            )),
            eligible_course_codes=tuple(sorted(course.course_code for course in eligible)),
            eligible_credits=sum(problem.courses[item.course_id].credits for item in eligible),
            selected_course_codes=_codes(problem, selected_ids),
            selected_credits=selected_credits,
            effective_capacity=capacity.capacity,
            capacity_reason=capacity.reason,
            unused_capacity=max(0, capacity.capacity - selected_credits),
            deferred_eligible_course_codes=tuple(sorted(
                course.course_code for course in eligible if not course.selected
            )),
            courses=tuple(course_audits),
        ))
        satisfied.update(selected_ids)
    return PlanningAudit(tuple(semesters))


def log_plan_audit(
    audit: PlanningAudit, course_id_or_code: str | None = None
) -> None:
    for semester in audit.semesters:
        LOGGER.debug("SEMESTER AUDIT: %s", semester.term_label)
        LOGGER.debug(
            "  rollout=NEW year %d; timetable=%s",
            semester.rollout_frontier, semester.timetable_basis,
        )
        LOGGER.debug("  satisfied before: %s", _display(semester.satisfied_before_codes))
        LOGGER.debug("  remaining: %s", _display(semester.remaining_requirement_codes))
        LOGGER.debug("  offered: %s", _display(semester.offered_course_codes))
        LOGGER.debug(
            "  prerequisite-valid: %s",
            _display(semester.prerequisite_valid_course_codes),
        )
        LOGGER.debug(
            "  rejected by rollout: %s",
            _display(semester.rollout_rejected_course_codes),
        )
        LOGGER.debug(
            "  rejected by prerequisites: %s",
            _display(semester.prerequisite_rejected_course_codes),
        )
        LOGGER.debug(
            "  rejected by registration: %s",
            _display(semester.registration_rejected_course_codes),
        )
        LOGGER.debug(
            "  eligible=%d ECTS [%s]",
            semester.eligible_credits, _display(semester.eligible_course_codes),
        )
        LOGGER.debug(
            "  selected=%d/%d ECTS (%s) [%s]",
            semester.selected_credits, semester.effective_capacity,
            semester.capacity_reason, _display(semester.selected_course_codes),
        )
        LOGGER.debug("  unused capacity=%d", semester.unused_capacity)
        LOGGER.debug(
            "  deferred eligible: %s",
            _display(semester.deferred_eligible_course_codes),
        )
    if course_id_or_code:
        trace = audit.trace_course(course_id_or_code)
        LOGGER.debug("COURSE TRACE: %s", trace[0].course_id)
        for semester, course in zip(audit.semesters, trace):
            LOGGER.debug("%s", semester.term_label)
            LOGGER.debug(
                "  course reference year=%d; NEW rollout frontier=%d",
                course.reference_year, semester.rollout_frontier,
            )
            LOGGER.debug(
                "  applicable=%s outstanding=%s offered=%s prerequisites=%s",
                _yes_no(course.applicable_requirement),
                _yes_no(course.requirement_outstanding),
                _yes_no(course.offered),
                "SATISFIED" if course.prerequisites_satisfied else
                f"BLOCKED ({', '.join(course.missing_prerequisite_ids)})",
            )
            LOGGER.debug(
                "  rollout=%s (%s); eligible=%s; selected=%s",
                "ALLOWED" if course.rollout_permitted else "BLOCKED",
                course.rollout_reason,
                _yes_no(course.eligible), _yes_no(course.selected),
            )
            LOGGER.debug(
                "  term load=%d/%d ECTS (%s)",
                semester.selected_credits, semester.effective_capacity,
                semester.capacity_reason,
            )


def _codes(problem: PlanningProblem, course_ids) -> tuple[str, ...]:
    return tuple(sorted(problem.courses[item].code for item in course_ids))


def _display(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "-"


def _yes_no(value: bool) -> str:
    return "YES" if value else "NO"

from dataclasses import dataclass

from academic_planner.domain.models import GraduationPlan, TermKind
from academic_planner.optimization.planner import PlanningProblem
from academic_planner.policies.credit import effective_credit_capacity
from academic_planner.reconciliation import ReconciliationService
from academic_planner.scheduling.conflicts import bundles_conflict


@dataclass(frozen=True)
class PlanValidationIssue:
    code: str
    detail: str


def validate_plan(plan: GraduationPlan, problem: PlanningProblem) -> tuple[PlanValidationIssue, ...]:
    issues: list[PlanValidationIssue] = []
    offerings = {(o.course_id, o.term): o for o in problem.offerings}
    bundles = {b.id: b for o in problem.offerings for b in o.bundles}
    reconciliation = ReconciliationService().reconcile(
        problem.student, problem.curriculum, problem.equivalencies
    )
    completed = set(reconciliation.prerequisite_completion_ids)
    outstanding = reconciliation.outstanding_requirement_ids
    prerequisites = {r.course_id: r.all_of for r in problem.prerequisites}
    seen: set[str] = set()
    first_academic_year = problem.configuration.planning_horizon[0].academic_year_start
    for index, scheduled in enumerate(plan.scheduled_terms):
        credits = sum(problem.courses[c].credits for c in scheduled.course_ids)
        effective_capacity = effective_credit_capacity(
            problem.student,
            scheduled.term,
            problem.configuration,
            outstanding,
            frozenset(scheduled.course_ids),
            selected_credits=credits,
            graduation_term=plan.graduation_term,
            planning_horizon=problem.configuration.planning_horizon,
        ).capacity
        if credits > effective_capacity:
            issues.append(PlanValidationIssue("CREDIT_LIMIT", scheduled.term.label()))
        for course_id in scheduled.course_ids:
            if course_id in seen:
                issues.append(PlanValidationIssue("DUPLICATE", course_id))
            if (course_id, scheduled.term) not in offerings:
                issues.append(PlanValidationIssue("NOT_OFFERED", course_id))
            missing = prerequisites.get(course_id, frozenset()) - completed - seen
            if missing:
                issues.append(PlanValidationIssue("PREREQUISITE", f"{course_id}: {sorted(missing)}"))
            if course_id in problem.curriculum.training_requirement_ids:
                course = problem.courses[course_id]
                normal_year = first_academic_year + course.reference_year - problem.student.nominal_year
                delay = scheduled.term.academic_year_start - normal_year
                if scheduled.term.kind not in {TermKind.TRAINING_1, TermKind.TRAINING_2}:
                    issues.append(PlanValidationIssue("TRAINING_PERIOD", course_id))
                if delay < 0:
                    issues.append(PlanValidationIssue("TRAINING_TOO_EARLY", course_id))
                if not problem.configuration.allow_training_postponement and delay != 0:
                    issues.append(PlanValidationIssue("TRAINING_POSTPONEMENT", course_id))
                maximum = problem.configuration.max_training_delay_years
                if maximum is not None and delay > maximum:
                    issues.append(PlanValidationIssue("TRAINING_DELAY_LIMIT", course_id))
        if index == 0:
            selected = [bundles[b] for b in scheduled.bundle_ids]
            if {b.course_id for b in selected} != set(scheduled.course_ids):
                issues.append(PlanValidationIssue("BUNDLE_COUPLING", "current course/bundle mismatch"))
            for i, left in enumerate(selected):
                for right in selected[i + 1:]:
                    if bundles_conflict(left, right):
                        issues.append(PlanValidationIssue("TIMETABLE_CONFLICT", f"{left.id}/{right.id}"))
        seen.update(scheduled.course_ids)
    return tuple(issues)

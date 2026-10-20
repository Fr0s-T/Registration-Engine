from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations, product

from academic_planner.domain.models import GraduationPlan, SolverStatus, TermKind
from academic_planner.eligibility import EligibleCoursePool, EligibilityEngine
from academic_planner.fixtures.scenarios import build_scenario
from academic_planner.fixtures.synthetic import (
    BASELINE_FIXTURE, RELAXED_FIXTURE, FixtureVariant,
    SyntheticFixtureConfiguration,
)
from academic_planner.optimization import GlobalPlanner, PlanningProblem
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy,
    ProgressiveRolloutPolicy, effective_credit_capacity,
)
from academic_planner.reconciliation import ReconciliationService
from academic_planner.scheduling.conflicts import bundles_conflict


@dataclass(frozen=True)
class FixtureExperimentResult:
    experiment: str
    prerequisite_variant: str
    timetable_variant: str
    conditional_repeat_allowance: bool
    eligible_course_count: int
    eligible_credits: int
    maximum_schedulable_credits: int
    selected_current_credits: int
    current_effective_capacity: int
    fall_reference_outstanding_credits: int
    graduation_term: str | None
    remaining_regular_semesters: int
    critical_prerequisite_bottlenecks: tuple[str, ...]
    solver_status: str
    constraints_changed: tuple[str, ...]
    problem: PlanningProblem
    plan: GraduationPlan


EXPERIMENT_CONFIGURATIONS = {
    "A": BASELINE_FIXTURE,
    "B": SyntheticFixtureConfiguration(
        FixtureVariant.BASELINE, FixtureVariant.RELAXED
    ),
    "C": SyntheticFixtureConfiguration(
        FixtureVariant.RELAXED, FixtureVariant.BASELINE
    ),
    "D": RELAXED_FIXTURE,
}


def compare_struggling_fixture_variants() -> tuple[FixtureExperimentResult, ...]:
    results = []
    for experiment, fixture_configuration in EXPERIMENT_CONFIGURATIONS.items():
        for conditional in (False, True):
            results.append(_run_experiment(
                experiment, fixture_configuration, conditional
            ))
    return tuple(results)


def _run_experiment(
    experiment: str,
    fixture_configuration: SyntheticFixtureConfiguration,
    conditional: bool,
) -> FixtureExperimentResult:
    scenario = build_scenario(
        "struggling-third",
        regular_credit_capacity=30,
        fixture_configuration=fixture_configuration,
    )
    base_problem = scenario.data.demo_problem()
    problem = replace(
        base_problem,
        configuration=replace(
            base_problem.configuration,
            allow_extended_load_when_repeating_failed_course=conditional,
        ),
    )
    rollout = ProgressiveRolloutPolicy()
    registration = AllowAllRegistrationPolicy()
    reconciliation = ReconciliationService().reconcile(
        problem.student, problem.curriculum, problem.equivalencies
    )
    applicable = {
        course_id: problem.courses[course_id]
        for course_id in problem.curriculum.resolved_requirements(
            problem.student.language_track
        )
    }
    pool = EligibilityEngine(rollout, registration).build_pool(
        problem.student,
        scenario.starting_term,
        applicable,
        reconciliation.outstanding_requirement_ids,
        reconciliation.prerequisite_completion_ids,
        problem.prerequisites,
        problem.offerings,
    )
    planner = GlobalPlanner(
        ConfiguredCreditLimitPolicy(), rollout, registration
    )
    plan = planner.plan(problem)
    selected_current_credits = (
        sum(problem.courses[course_id].credits for course_id in plan.scheduled_terms[0].course_ids)
        if plan.scheduled_terms else 0
    )
    graduation_index = next((
        index for index, scheduled in enumerate(plan.scheduled_terms)
        if scheduled.term == plan.graduation_term
    ), -1)
    remaining_regular = (
        sum(
            scheduled.term.is_regular
            for scheduled in plan.scheduled_terms[:graduation_index + 1]
        )
        if graduation_index >= 0 else 0
    )
    return FixtureExperimentResult(
        experiment=experiment,
        prerequisite_variant=fixture_configuration.prerequisite_variant.value,
        timetable_variant=fixture_configuration.timetable_variant.value,
        conditional_repeat_allowance=conditional,
        eligible_course_count=len(pool.courses),
        eligible_credits=sum(course.credits for course in pool.courses),
        maximum_schedulable_credits=_maximum_schedulable_credits(
            pool, problem, reconciliation.outstanding_requirement_ids
        ),
        selected_current_credits=selected_current_credits,
        current_effective_capacity=(
            plan.credit_usages[0].effective_capacity
            if plan.credit_usages else problem.configuration.capacity_for(scenario.starting_term)
        ),
        fall_reference_outstanding_credits=sum(
            problem.courses[course_id].credits
            for course_id in reconciliation.outstanding_requirement_ids
            if course_id not in problem.curriculum.training_requirement_ids
            and problem.courses[course_id].reference_semester is TermKind.FALL
        ),
        graduation_term=(
            plan.graduation_term.label() if plan.graduation_term else None
        ),
        remaining_regular_semesters=remaining_regular,
        critical_prerequisite_bottlenecks=_critical_bottlenecks(problem, plan),
        solver_status=plan.status.value,
        constraints_changed=fixture_configuration.change_descriptions,
        problem=problem,
        plan=plan,
    )


def _maximum_schedulable_credits(
    pool: EligibleCoursePool, problem: PlanningProblem,
    outstanding_requirement_ids: frozenset[str],
) -> int:
    offering_by_course = {
        offering.course_id: offering for offering in pool.offerings
    }
    courses = tuple(pool.courses)
    best = 0
    for size in range(len(courses) + 1):
        for selected_courses in combinations(courses, size):
            selected_ids = frozenset(course.id for course in selected_courses)
            credits = sum(course.credits for course in selected_courses)
            capacity = effective_credit_capacity(
                problem.student,
                pool.term,
                problem.configuration,
                outstanding_requirement_ids,
                selected_ids,
            ).capacity
            if credits <= best or credits > capacity:
                continue
            bundle_options = [
                offering_by_course[course.id].bundles
                for course in selected_courses
            ]
            if any(not options for options in bundle_options):
                continue
            if any(
                all(
                    not bundles_conflict(left, right)
                    for index, left in enumerate(bundle_selection)
                    for right in bundle_selection[index + 1:]
                )
                for bundle_selection in product(*bundle_options)
            ):
                best = credits
    return best


def _critical_bottlenecks(
    problem: PlanningProblem, plan: GraduationPlan
) -> tuple[str, ...]:
    if plan.status not in {
        SolverStatus.OPTIMAL, SolverStatus.FEASIBLE_NOT_PROVEN_OPTIMAL
    }:
        return ("No feasible schedule was available for bottleneck analysis.",)
    scheduled_term = {
        course_id: scheduled.term.label()
        for scheduled in plan.scheduled_terms
        for course_id in scheduled.course_ids
    }
    rules = {rule.course_id: rule.all_of for rule in problem.prerequisites}
    if rules.get("NEW:CCE650") == frozenset({"NEW:CCE561"}):
        chain = ("NEW:CSC333", "NEW:CSC437", "NEW:CCE561", "NEW:CCE650")
        chain_text = " → ".join(problem.courses[item].code for item in chain)
        timing = " → ".join(scheduled_term.get(item, "completed") for item in chain)
        primary = f"{chain_text}: {timing}"
    else:
        primary = (
            "relaxed branches: CSC333 → CCE561 and CCE443 → CCE650; "
            f"CCE561 {scheduled_term.get('NEW:CCE561', 'unscheduled')}, "
            f"CCE650 {scheduled_term.get('NEW:CCE650', 'unscheduled')}"
        )
    fan_out = (
        "CCE555 gates four Fall courses (CCE651/CCE654/CCE655/CCE657); "
        f"CCE555 {scheduled_term.get('NEW:CCE555', 'unscheduled')}"
    )
    return primary, fan_out

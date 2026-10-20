from __future__ import annotations

from dataclasses import dataclass, replace

from academic_planner.diagnostics.audit import PlanningAudit, build_plan_audit
from academic_planner.domain.models import AcademicTerm, SolverStatus, TermKind
from academic_planner.fixtures import build_scenario
from academic_planner.optimization import GlobalPlanner, PlanningProblem
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy,
    ProgressiveRolloutPolicy,
)


CCE640_ID = "NEW:CCE640"
SPRING_2027 = AcademicTerm(2026, TermKind.SPRING)
SPRING_2028 = AcademicTerm(2027, TermKind.SPRING)
TRAINING_2_2028 = AcademicTerm(2027, TermKind.TRAINING_2)


@dataclass(frozen=True)
class CourseDeferralExperiment:
    name: str
    cce640_spring_2027_eligible: bool
    cce640_earliest_eligible_term: str | None
    cce640_selected_term: str | None
    spring_2027_selected_credits: int
    spring_2028_selected_credits: int
    graduation_term: str | None
    solver_status: str
    optimality_proven: bool
    audit: PlanningAudit


@dataclass(frozen=True)
class FeasibilityCheck:
    name: str
    status: str
    solver_status: str
    optimality_proven: bool
    known_blockers: tuple[str, ...]


def run_cce640_experiments() -> tuple[CourseDeferralExperiment, ...]:
    return (
        _run_experiment("A_BASELINE_30"),
        _run_experiment("B_CONDITIONAL_REPEAT", conditional=True),
        _run_experiment(
            "C_SPRING_2028_OVERRIDE", conditional=True,
            spring_2028_override=True,
        ),
        _run_experiment(
            "D_CCE640_ROLLOUT_OVERRIDE", conditional=True,
            cce640_rollout_override=True,
        ),
    )


def run_cce640_feasibility_checks() -> tuple[FeasibilityCheck, ...]:
    base = build_scenario("failed-fourth").data.demo_problem()
    return (
        _solve_check(
            "CCE640 forced in Spring 2027",
            _with_forced_course(base, CCE640_ID, SPRING_2027),
            ProgressiveRolloutPolicy(),
            (
                "NEW Year 5 is blocked by the 2026-2027 rollout frontier (Year 4).",
            ),
        ),
        _solve_check(
            "CCE640 in Spring 2028 at 30 ECTS, graduation by Spring 2028",
            _with_deadline(
                _with_forced_course(base, CCE640_ID, SPRING_2028),
                SPRING_2028,
            ),
            ProgressiveRolloutPolicy(),
            (
                "The Spring 2028 classroom demand is 35 ECTS under this forced placement, above 30.",
                "Training II remains outstanding until a later TRAINING_2 period.",
            ),
        ),
        _solve_check(
            "Conditional policy, graduation by Spring 2028",
            _with_deadline(_with_conditional(base), SPRING_2028),
            ProgressiveRolloutPolicy(),
            (
                "No recorded failed repeat is selected in Spring 2028, so its cap remains 30 ECTS.",
                "Training II remains outstanding until a later TRAINING_2 period.",
            ),
        ),
        _solve_check(
            "Explicit Spring 2028 override, graduation by Spring 2028",
            _with_deadline(
                _with_spring_2028_override(_with_conditional(base)),
                SPRING_2028,
            ),
            ProgressiveRolloutPolicy(),
            ("Training II remains outstanding until a later TRAINING_2 period.",),
        ),
        _solve_check(
            "Conditional policy, completion by 2027-2028 Training II",
            _with_deadline(_with_conditional(base), TRAINING_2_2028),
            ProgressiveRolloutPolicy(),
            (
                "No recorded failed repeat is selected in Spring 2028, so its cap remains 30 ECTS.",
            ),
        ),
        _solve_check(
            "Explicit Spring 2028 override, completion by 2027-2028 Training II",
            _with_deadline(
                _with_spring_2028_override(_with_conditional(base)),
                TRAINING_2_2028,
            ),
            ProgressiveRolloutPolicy(),
            (),
        ),
    )


def _run_experiment(
    name: str,
    conditional: bool = False,
    spring_2028_override: bool = False,
    cce640_rollout_override: bool = False,
) -> CourseDeferralExperiment:
    problem = build_scenario("failed-fourth").data.demo_problem()
    if conditional:
        problem = _with_conditional(problem)
    if spring_2028_override:
        problem = _with_spring_2028_override(problem)
    rollout = ProgressiveRolloutPolicy(
        explicit_overrides=(
            {(CCE640_ID, SPRING_2027): True}
            if cce640_rollout_override else {}
        )
    )
    registration = AllowAllRegistrationPolicy()
    plan = GlobalPlanner(
        ConfiguredCreditLimitPolicy(), rollout, registration
    ).plan(problem)
    audit = build_plan_audit(problem, plan, rollout, registration)
    trace = audit.trace_course(CCE640_ID)
    spring_2027_index = next(
        index for index, semester in enumerate(audit.semesters)
        if semester.term_label == SPRING_2027.label()
    )
    earliest_eligible_index = next(
        (index for index, course in enumerate(trace) if course.eligible), None
    )
    selected_index = next(
        (index for index, course in enumerate(trace) if course.selected), None
    )
    return CourseDeferralExperiment(
        name=name,
        cce640_spring_2027_eligible=trace[spring_2027_index].eligible,
        cce640_earliest_eligible_term=(
            audit.semesters[earliest_eligible_index].term_label
            if earliest_eligible_index is not None else None
        ),
        cce640_selected_term=(
            audit.semesters[selected_index].term_label
            if selected_index is not None else None
        ),
        spring_2027_selected_credits=_selected_credits(audit, SPRING_2027),
        spring_2028_selected_credits=_selected_credits(audit, SPRING_2028),
        graduation_term=plan.graduation_term.label() if plan.graduation_term else None,
        solver_status=plan.status.value,
        optimality_proven=plan.status is SolverStatus.OPTIMAL,
        audit=audit,
    )


def _solve_check(
    name: str,
    problem: PlanningProblem,
    rollout: ProgressiveRolloutPolicy,
    infeasible_blockers: tuple[str, ...],
) -> FeasibilityCheck:
    plan = GlobalPlanner(
        ConfiguredCreditLimitPolicy(), rollout, AllowAllRegistrationPolicy()
    ).plan(problem)
    feasibility_status = (
        "FEASIBLE"
        if plan.status in {
            SolverStatus.OPTIMAL, SolverStatus.FEASIBLE_NOT_PROVEN_OPTIMAL
        }
        else "INFEASIBLE"
        if plan.status is SolverStatus.INFEASIBLE
        else "UNKNOWN"
    )
    return FeasibilityCheck(
        name=name,
        status=feasibility_status,
        solver_status=plan.status.value,
        optimality_proven=plan.status is SolverStatus.OPTIMAL,
        known_blockers=(
            infeasible_blockers if plan.status is SolverStatus.INFEASIBLE else ()
        ),
    )


def _with_conditional(problem: PlanningProblem) -> PlanningProblem:
    return replace(
        problem,
        configuration=replace(
            problem.configuration,
            allow_extended_load_when_repeating_failed_course=True,
        ),
    )


def _with_spring_2028_override(problem: PlanningProblem) -> PlanningProblem:
    capacities = dict(problem.configuration.term_credit_capacities)
    capacities[SPRING_2028] = 36
    return replace(
        problem,
        configuration=replace(
            problem.configuration,
            term_credit_capacities=capacities,
            explicit_capacity_override_terms=(
                problem.configuration.explicit_capacity_override_terms
                | {SPRING_2028}
            ),
        ),
    )


def _with_forced_course(
    problem: PlanningProblem, course_id: str, term: AcademicTerm
) -> PlanningProblem:
    return replace(
        problem,
        configuration=replace(
            problem.configuration,
            forced_course_terms={
                **problem.configuration.forced_course_terms,
                course_id: term,
            },
        ),
    )


def _with_deadline(
    problem: PlanningProblem, final_term: AcademicTerm
) -> PlanningProblem:
    terms = problem.configuration.planning_horizon
    cutoff_index = terms.index(final_term)
    shortened = terms[:cutoff_index + 1]
    regular_count = sum(term.is_regular for term in shortened)
    return replace(
        problem,
        configuration=replace(
            problem.configuration,
            planning_horizon=shortened,
            initial_horizon_semesters=regular_count,
            max_horizon_semesters=regular_count,
            auto_extend_horizon=False,
        ),
    )


def _selected_credits(audit: PlanningAudit, term: AcademicTerm) -> int:
    return next(
        semester.selected_credits for semester in audit.semesters
        if semester.term_label == term.label()
    )

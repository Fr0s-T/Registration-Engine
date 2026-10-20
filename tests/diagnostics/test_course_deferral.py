import logging

from academic_planner.diagnostics import (
    build_plan_audit, log_plan_audit, run_cce640_experiments,
    run_cce640_feasibility_checks,
)
from academic_planner.domain.models import SolverStatus
from academic_planner.fixtures import build_scenario
from academic_planner.optimization import GlobalPlanner
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy,
    ProgressiveRolloutPolicy,
)


def _solve_failed_fourth():
    problem = build_scenario("failed-fourth").data.demo_problem()
    rollout = ProgressiveRolloutPolicy()
    registration = AllowAllRegistrationPolicy()
    planner = GlobalPlanner(
        ConfiguredCreditLimitPolicy(), rollout, registration
    )
    return problem, rollout, registration, planner.plan(problem)


def test_cce640_prerequisite_is_satisfied_but_rollout_blocks_spring_2027():
    problem, rollout, registration, plan = _solve_failed_fourth()
    audit = build_plan_audit(problem, plan, rollout, registration)
    spring = next(
        semester for semester in audit.semesters
        if semester.term_label == "2026-2027 SPRING"
    )
    cce640 = next(
        course for course in spring.courses if course.course_id == "NEW:CCE640"
    )
    assert cce640.requirement_outstanding
    assert cce640.prerequisites_satisfied
    assert cce640.offered
    assert not cce640.rollout_permitted
    assert "year 4" in cce640.rollout_reason
    assert not cce640.eligible
    assert spring.unused_capacity == 5


def test_old_image_processing_is_not_a_new_curriculum_requirement():
    problem, rollout, registration, plan = _solve_failed_fourth()
    audit = build_plan_audit(problem, plan, rollout, registration)
    trace = audit.trace_course("ELBC901")
    assert all(not course.applicable_requirement for course in trace)
    assert all(not course.eligible for course in trace)


def test_rollout_frontier_advances_and_eligible_course_may_be_deferred():
    experiments = {item.name: item for item in run_cce640_experiments()}
    baseline = experiments["A_BASELINE_30"]
    assert not baseline.cce640_spring_2027_eligible
    assert baseline.cce640_earliest_eligible_term == "2027-2028 SPRING"
    assert baseline.cce640_selected_term == "2028-2029 SPRING"
    assert baseline.solver_status == SolverStatus.OPTIMAL.value
    assert baseline.optimality_proven


def test_controlled_cce640_experiments_have_expected_outcomes():
    experiments = {item.name: item for item in run_cce640_experiments()}
    assert {
        name: (
            item.cce640_spring_2027_eligible,
            item.cce640_selected_term,
            item.spring_2027_selected_credits,
            item.spring_2028_selected_credits,
            item.graduation_term,
        )
        for name, item in experiments.items()
    } == {
        "A_BASELINE_30": (
            False, "2028-2029 SPRING", 25, 30, "2028-2029 SPRING"
        ),
        "B_CONDITIONAL_REPEAT": (
            False, "2028-2029 SPRING", 25, 30, "2028-2029 SPRING"
        ),
        "C_SPRING_2028_OVERRIDE": (
            False, "2027-2028 SPRING", 25, 35, "2027-2028 TRAINING_2"
        ),
        "D_CCE640_ROLLOUT_OVERRIDE": (
            True, "2026-2027 SPRING", 30, 30, "2027-2028 TRAINING_2"
        ),
    }
    assert all(item.optimality_proven for item in experiments.values())
    assert (
        experiments["D_CCE640_ROLLOUT_OVERRIDE"].graduation_term
        < experiments["B_CONDITIONAL_REPEAT"].graduation_term
    )


def test_independent_forced_selection_and_deadline_checks():
    checks = {item.name: item for item in run_cce640_feasibility_checks()}
    assert checks["CCE640 forced in Spring 2027"].status == "INFEASIBLE"
    assert checks[
        "CCE640 in Spring 2028 at 30 ECTS, graduation by Spring 2028"
    ].status == "INFEASIBLE"
    assert checks[
        "Conditional policy, graduation by Spring 2028"
    ].status == "INFEASIBLE"
    assert checks[
        "Explicit Spring 2028 override, graduation by Spring 2028"
    ].status == "INFEASIBLE"
    assert checks[
        "Conditional policy, completion by 2027-2028 Training II"
    ].status == "INFEASIBLE"
    assert checks[
        "Explicit Spring 2028 override, completion by 2027-2028 Training II"
    ].status == "FEASIBLE"
    assert all(
        item.known_blockers
        for item in checks.values() if item.status == "INFEASIBLE"
    )


def test_audit_logging_is_observational_and_does_not_change_plan(caplog):
    problem, rollout, registration, before = _solve_failed_fourth()
    audit = build_plan_audit(problem, before, rollout, registration)
    with caplog.at_level(logging.DEBUG, logger="academic_planner.diagnostics"):
        log_plan_audit(audit, "CCE640")
    after = GlobalPlanner(
        ConfiguredCreditLimitPolicy(), rollout, registration
    ).plan(problem)
    assert after == before
    assert "COURSE TRACE: NEW:CCE640" in caplog.text
    assert "rollout=BLOCKED" in caplog.text


def test_conditional_capacity_appears_only_in_repeat_semester_audit():
    conditional = next(
        item for item in run_cce640_experiments()
        if item.name == "B_CONDITIONAL_REPEAT"
    )
    spring_2027 = next(
        semester for semester in conditional.audit.semesters
        if semester.term_label == "2026-2027 SPRING"
    )
    spring_2028 = next(
        semester for semester in conditional.audit.semesters
        if semester.term_label == "2027-2028 SPRING"
    )
    assert spring_2027.effective_capacity == 36
    assert spring_2027.capacity_reason == "FAILED_COURSE_REPEAT_ALLOWANCE"
    assert spring_2028.effective_capacity == 30
    assert spring_2028.capacity_reason == "NORMAL_REGULAR_CAPACITY"
    assert spring_2027.unused_capacity == 11

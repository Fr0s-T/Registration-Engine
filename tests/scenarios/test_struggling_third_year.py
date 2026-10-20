from dataclasses import replace

from academic_planner.domain.models import AttemptStatus, SolverStatus, TermKind
from academic_planner.validation import validate_plan
from tests.fixtures import build_pool, planner, reconcile, scheduled_index, struggling_third


def test_struggling_third_year_has_complex_reconciled_history():
    scenario = struggling_third()
    problem = scenario.data.demo_problem()
    result = reconcile(scenario)
    attempts = problem.student.attempts

    failed = {a.course_id for a in attempts if a.status is AttemptStatus.FAILED}
    recognized = {a.course_id for a in attempts if a.status in {
        AttemptStatus.TRANSFERRED, AttemptStatus.EXEMPTED
    }}
    assert failed == {"NEW:CCE340", "NEW:CCE341", "NEW:CSC333"}
    assert all(a.earned_credits == 0 for a in attempts if a.status is AttemptStatus.FAILED)
    assert recognized == {"NEW:CCE653", "NEW:CCE660"}
    assert result.official_earned_credits == 113
    assert sum(problem.courses[c].credits for c in result.outstanding_requirement_ids) == 187


def test_struggling_plan_uses_relaxed_section_to_select_full_eligible_pool():
    scenario = struggling_third()
    problem = scenario.data.demo_problem()
    pool = build_pool(scenario, scenario.starting_term)
    plan = planner().plan(problem)

    assert sum(course.credits for course in pool.courses) == 20
    assert {course.code for course in pool.courses} == {
        "CCE340", "CCE420", "CCE431", "CCE440", "SHM350"
    }
    current_codes = {problem.courses[c].code for c in plan.scheduled_terms[0].course_ids}
    assert current_codes == {
        "CCE340", "CCE420", "CCE431", "CCE440", "SHM350"
    }
    assert sum(problem.courses[c].credits for c in plan.scheduled_terms[0].course_ids) == 20
    assert scheduled_index(plan, "NEW:CCE340") < scheduled_index(plan, "NEW:CCE430")
    assert scheduled_index(plan, "NEW:CCE340") < scheduled_index(plan, "NEW:CCE450")
    assert plan.status is SolverStatus.OPTIMAL
    assert not validate_plan(plan, problem)


def test_struggling_poc_has_no_empty_regular_gap_or_single_course_final_spring():
    scenario = struggling_third()
    problem = scenario.data.demo_problem()
    plan = planner().plan(problem)
    graduation_index = next(
        index for index, scheduled in enumerate(plan.scheduled_terms)
        if scheduled.term == plan.graduation_term
    )
    periods = plan.scheduled_terms[:graduation_index + 1]
    regular_periods = [term for term in periods if term.term.is_regular]
    assert regular_periods
    assert all(term.course_ids for term in regular_periods)

    springs = [term for term in regular_periods if term.term.kind is TermKind.SPRING]
    final_spring = springs[-1]
    assert {problem.courses[c].code for c in final_spring.course_ids} == {"CCE640", "CCE690"}
    assert len(final_spring.course_ids) == 2
    assert sum(problem.courses[c].credits for c in final_spring.course_ids) == 23
    assert plan.graduation_term.academic_year_start == 2029
    assert plan.graduation_term.kind is TermKind.FALL

    scheduled_ids = {course for term in periods for course in term.course_ids}
    assert "NEW:CCE653" not in scheduled_ids
    assert "NEW:CCE660" not in scheduled_ids


def test_spring_2029_deadline_is_proven_infeasible_for_struggling_fixture():
    scenario = struggling_third()
    problem = scenario.data.demo_problem()
    cutoff_terms = tuple(
        term for term in problem.configuration.planning_horizon
        if term.academic_year_start < 2029
    )
    regular_count = sum(term.is_regular for term in cutoff_terms)
    constrained = replace(
        problem,
        configuration=replace(
            problem.configuration,
            planning_horizon=cutoff_terms,
            initial_horizon_semesters=regular_count,
            max_horizon_semesters=regular_count,
            auto_extend_horizon=False,
        ),
    )
    plan = planner().plan(constrained)
    assert plan.status is SolverStatus.INFEASIBLE

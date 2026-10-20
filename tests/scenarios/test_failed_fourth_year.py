from dataclasses import replace

from academic_planner.domain.models import AcademicTerm, AttemptStatus, CourseAttempt, SolverStatus, TermKind
from academic_planner.eligibility import EligibilityEngine, RejectionCode
from academic_planner.policies import AllowAllRegistrationPolicy, ProgressiveRolloutPolicy
from academic_planner.reconciliation import ReconciliationService
from academic_planner.validation import validate_plan
from tests.fixtures import build_pool, failed_fourth, planner, reconcile, scheduled_index


def test_failed_course_blocks_dependent_until_a_later_spring():
    scenario = failed_fourth(30)
    data = scenario.data
    problem = data.demo_problem()
    result = reconcile(scenario)
    plan = planner().plan(problem)

    failed_attempt = next(a for a in problem.student.attempts if a.status is AttemptStatus.FAILED)
    assert failed_attempt.course_id == "NEW:CCE443"
    assert failed_attempt.earned_credits == 0
    assert result.official_earned_credits == 175
    assert "NEW:CCE443" in result.outstanding_requirement_ids
    assert plan.status is SolverStatus.OPTIMAL
    assert not validate_plan(plan, problem)
    assert scheduled_index(plan, "NEW:CCE443") < scheduled_index(plan, "NEW:CCE550")
    assert plan.scheduled_terms[scheduled_index(plan, "NEW:CCE443")].term.kind is TermKind.SPRING
    assert plan.scheduled_terms[scheduled_index(plan, "NEW:CCE550")].term.kind is TermKind.SPRING


def test_pool_regenerates_after_network_essentials_completion():
    scenario = failed_fourth()
    problem = scenario.data.demo_problem()
    first_spring = AcademicTerm(2026, TermKind.SPRING)
    initial = build_pool(scenario, first_spring)
    assert "CCE443" in {c.code for c in initial.courses}
    rejection = next(r for r in initial.rejections if r.course_id == "NEW:CCE550")
    assert rejection.code is RejectionCode.PREREQUISITE

    passed_attempt = CourseAttempt("NEW:CCE443", first_spring, AttemptStatus.PASSED, earned_credits=5)
    projected_student = replace(problem.student, attempts=problem.student.attempts + (passed_attempt,))
    projected_problem = replace(problem, student=projected_student)
    reconciled = ReconciliationService().reconcile(
        projected_student, projected_problem.curriculum, projected_problem.equivalencies
    )
    next_spring = AcademicTerm(2027, TermKind.SPRING)
    applicable = {
        cid: problem.courses[cid] for cid in problem.curriculum.requirement_ids
    }
    regenerated = EligibilityEngine(
        ProgressiveRolloutPolicy(), AllowAllRegistrationPolicy()
    ).build_pool(
        projected_student, next_spring, applicable,
        reconciled.outstanding_requirement_ids, reconciled.satisfied_requirement_ids,
        problem.prerequisites, problem.offerings,
    )
    assert "CCE550" in {c.code for c in regenerated.courses}


def test_explicit_36_ects_assumption_can_mitigate_delay():
    normal = failed_fourth(30)
    increased = failed_fourth(36)
    normal_plan = planner().plan(normal.data.demo_problem())
    increased_plan = planner().plan(increased.data.demo_problem())
    assert normal_plan.status is SolverStatus.OPTIMAL
    assert increased_plan.status is SolverStatus.OPTIMAL
    assert not validate_plan(normal_plan, normal.data.demo_problem())
    assert not validate_plan(increased_plan, increased.data.demo_problem())
    assert increased_plan.graduation_term < normal_plan.graduation_term
    for scheduled in increased_plan.scheduled_terms:
        assert sum(increased.data.courses[c].credits for c in scheduled.course_ids) <= increased.data.demo_configuration.capacity_for(scheduled.term)

from academic_planner.domain.models import SolverStatus, TermKind
from academic_planner.validation import validate_plan
from tests.fixtures import fresh_student, planner, reconcile, scheduled_index


def test_fresh_student_covers_curriculum_and_respects_dependencies():
    scenario = fresh_student()
    data = scenario.data
    problem = data.demo_problem()
    result = reconcile(scenario)
    plan = planner().plan(problem)

    assert result.official_earned_credits == 0
    assert plan.status is SolverStatus.OPTIMAL
    assert not validate_plan(plan, problem)
    scheduled = [course for term in plan.scheduled_terms for course in term.course_ids]
    assert len(scheduled) == len(set(scheduled))
    assert set(scheduled) == set(problem.curriculum.requirement_ids)
    assert sum(data.courses[c].credits for c in scheduled) == 300
    assert {"NEW:CCE471", "NEW:CCE572", "NEW:CCE690"} <= set(scheduled)
    for rule in problem.prerequisites:
        if rule.course_id in scheduled:
            assert all(scheduled_index(plan, prerequisite) < scheduled_index(plan, rule.course_id) for prerequisite in rule.all_of)
    for scheduled_term in plan.scheduled_terms:
        for course_id in scheduled_term.course_ids:
            if course_id not in {"NEW:CCE471", "NEW:CCE572"}:
                assert data.courses[course_id].reference_semester is scheduled_term.term.kind
    assert any(term.term.kind is TermKind.TRAINING_1 for term in plan.scheduled_terms)
    assert any(term.term.kind is TermKind.TRAINING_2 for term in plan.scheduled_terms)

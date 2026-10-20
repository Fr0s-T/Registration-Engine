from academic_planner.domain.models import AttemptStatus, SolverStatus, TermKind
from academic_planner.eligibility import RejectionCode
from academic_planner.validation import validate_plan
from tests.fixtures import build_pool, planner, reconcile, regular_fourth


def test_regular_fourth_year_reconciliation_pool_and_plan():
    scenario = regular_fourth()
    data = scenario.data
    problem = data.demo_problem()
    result = reconcile(scenario)
    pool = build_pool(scenario, scenario.starting_term)
    plan = planner().plan(problem)

    passed_credits = sum(a.earned_credits for a in problem.student.attempts if a.status is AttemptStatus.PASSED)
    assert result.official_earned_credits == passed_credits == 180
    assert sum(data.courses[c].credits for c in result.outstanding_requirement_ids) == 120
    assert all(data.courses[c].reference_year >= 4 for c in result.outstanding_requirement_ids)
    assert {c.code for c in pool.courses} == {
        "CCE540", "CCE541", "CCE554", "CCE556", "CCE560", "CCE561", "CCE562", "CCE563"
    }
    year_five_rollout_rejections = {
        data.courses[r.course_id].code for r in pool.rejections if r.code is RejectionCode.ROLLOUT
    }
    assert "CCE652" in year_five_rollout_rejections
    assert plan.status is SolverStatus.OPTIMAL
    assert not validate_plan(plan, problem)
    assert not result.satisfied_requirement_ids.intersection(
        course for term in plan.scheduled_terms for course in term.course_ids
    )
    assert set(plan.scheduled_terms[0].course_ids) == {c.id for c in pool.courses}
    assert plan.graduation_term.academic_year_start == 2027
    assert plan.graduation_term.kind is TermKind.SPRING


def test_regular_fourth_year_exact_schedule_characterizes_current_tie_breaking():
    """Protect the complete deterministic schedule, not only graduation speed."""
    scenario = regular_fourth()
    problem = scenario.data.demo_problem()

    plan = planner().plan(problem)

    populated_terms = [
        (
            scheduled.term.label(),
            tuple(problem.courses[course_id].code for course_id in scheduled.course_ids),
            sum(problem.courses[course_id].credits for course_id in scheduled.course_ids),
        )
        for scheduled in plan.scheduled_terms
        if scheduled.course_ids
    ]
    assert plan.status is SolverStatus.OPTIMAL
    assert populated_terms == [
        (
            "2026-2027 FALL",
            (
                "CCE540", "CCE541", "CCE554", "CCE556",
                "CCE560", "CCE561", "CCE562", "CCE563",
            ),
            30,
        ),
        (
            "2026-2027 SPRING",
            ("CCE550", "CCE551", "CCE552", "CCE553", "CCE555"),
            25,
        ),
        ("2026-2027 TRAINING_2", ("CCE572",), 5),
        (
            "2027-2028 FALL",
            (
                "CCE650", "CCE651", "CCE652", "CCE654",
                "CCE655", "CCE656", "CCE657",
            ),
            30,
        ),
        (
            "2027-2028 SPRING",
            ("CCE640", "CCE653", "CCE660", "CCE690"),
            30,
        ),
    ]
    assert [
        (usage.term.label(), usage.selected_credits, usage.effective_capacity, usage.reason)
        for usage in plan.credit_usages
        if usage.selected_credits
    ] == [
        ("2026-2027 FALL", 30, 30, "NORMAL_REGULAR_CAPACITY"),
        ("2026-2027 SPRING", 25, 30, "NORMAL_REGULAR_CAPACITY"),
        ("2026-2027 TRAINING_2", 5, 5, "TRAINING_PERIOD_CAP"),
        ("2027-2028 FALL", 30, 30, "NORMAL_REGULAR_CAPACITY"),
        ("2027-2028 SPRING", 30, 30, "NORMAL_REGULAR_CAPACITY"),
    ]

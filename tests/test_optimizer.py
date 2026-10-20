import pytest

from academic_planner.domain.models import *
import academic_planner.optimization.planner as planner_module
from academic_planner.optimization import GlobalPlanner, PlanningProblem
from academic_planner.policies import AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy
from academic_planner.validation import validate_plan
from tests.conftest import bundle, course, term


def planner() -> GlobalPlanner:
    return GlobalPlanner(ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(), AllowAllRegistrationPolicy())


def problem(courses, terms, offerings, prerequisites=(), capacity=30, nominal=1):
    by_id = {c.id: c for c in courses}
    return PlanningProblem(by_id, Curriculum(CurriculumVersion.NEW, frozenset(by_id), accepted_credit_target=sum(c.credits for c in courses)), StudentAcademicState(nominal, LanguageTrack.EN), (), prerequisites, offerings, PlanningConfiguration(default_credit_capacity=capacity, planning_horizon=terms))


def test_conflicts_eliminate_invalid_combinations():
    t = term()
    a, b = course("A", 5), course("B", 5)
    offerings = (CourseOffering("A", t, (bundle("A", start=600, end=660),)), CourseOffering("B", t, (bundle("B", start=630, end=690),)))
    plan = planner().plan(problem((a, b), (t,), offerings, capacity=10))
    assert plan.status is SolverStatus.INFEASIBLE


def test_mandatory_zero_credit_lab_stays_in_bundle():
    t = term()
    c = course("IMG", 5)
    b = bundle("IMG", lab=True)
    assert len(b.sections) == 2 and b.sections[1].grade_weight == .2
    plan = planner().plan(problem((c,), (t,), (CourseOffering("IMG", t, (b,)),)))
    assert plan.scheduled_terms[0].bundle_ids == (b.id,)
    assert not validate_plan(plan, problem((c,), (t,), (CourseOffering("IMG", t, (b,)),)))


def test_on_track_course_preferred_to_premature_higher_year_when_capacity_ties():
    t0, t1 = term(2023), term(2023, TermKind.SPRING)
    current = course("Y1", 5, year=1)
    future = course("Y3", 5, year=3, version=CurriculumVersion.OLD, semester=TermKind.SPRING)
    os = (CourseOffering("Y1", t0, (bundle("Y1"),)), CourseOffering("Y3", t0, (bundle("Y3", day=Weekday.TUESDAY),)), CourseOffering("Y1", t1), CourseOffering("Y3", t1))
    p = planner().plan(problem((current, future), (t0, t1), os, capacity=5))
    assert p.scheduled_terms[0].course_ids == ("Y1",)


def test_global_choice_beats_local_credit_maximization():
    t0, t1 = term(2023), term(2023, TermKind.SPRING)
    a, b, c = course("A", 30), course("B", 15), course("C", 0)
    # A is the locally maximal current load. B now is globally necessary to unlock C next term.
    os = (
        CourseOffering("A", t0, (bundle("A", start=540, end=600),)),
        CourseOffering("B", t0, (bundle("B", start=570, end=630),)),
        CourseOffering("A", t1), CourseOffering("B", t1), CourseOffering("C", t1),
    )
    p = planner().plan(problem((a, b, c), (t0, t1), os, (PrerequisiteRule("C", frozenset({"B"})),), capacity=30))
    assert p.status is SolverStatus.OPTIMAL
    assert p.scheduled_terms[0].course_ids == ("B",)
    assert set(p.scheduled_terms[1].course_ids) == {"A", "C"}
    assert not validate_plan(p, problem((a, b, c), (t0, t1), os, (PrerequisiteRule("C", frozenset({"B"})),), capacity=30))


def test_unverified_future_offering_warning_and_status():
    t0, t1 = term(2023), term(2023, TermKind.SPRING)
    a, b = course("A", 30), course("B", 30)
    os = (CourseOffering("A", t0, (bundle("A"),)), CourseOffering("B", t1, availability_verified=False))
    p = planner().plan(problem((a, b), (t0, t1), os))
    assert p.status is SolverStatus.OPTIMAL
    assert p.warnings


@pytest.mark.parametrize(
    "attempt_status",
    [AttemptStatus.RESULT_PENDING, AttemptStatus.IN_PROGRESS],
)
def test_pending_or_older_in_progress_course_is_not_scheduled_again(attempt_status):
    previous = term(2022)
    current = term(2023)
    later = term(2023, TermKind.SPRING)
    required = course("PENDING", 5)
    pending_student = StudentAcademicState(
        1,
        LanguageTrack.EN,
        attempts=(CourseAttempt(
            "PENDING", previous, attempt_status,
            earned_credits=0, credit_identity="course:NEW:PENDING",
        ),),
    )
    planning_problem = PlanningProblem(
        {required.id: required},
        Curriculum(CurriculumVersion.NEW, frozenset({required.id}), 5),
        pending_student,
        (),
        (),
        (
            CourseOffering(required.id, current, (bundle(required.id),)),
            CourseOffering(required.id, later),
        ),
        PlanningConfiguration(planning_horizon=(current, later)),
    )

    plan = planner().plan(planning_problem)

    assert plan.status is SolverStatus.OPTIMAL
    assert not any(
        required.id in scheduled.course_ids for scheduled in plan.scheduled_terms
    )
    assert "not scheduled again" in " ".join(plan.explanations)


def test_later_unknown_solve_returns_the_last_feasible_incumbent(monkeypatch):
    real_solver = planner_module.cp_model.CpSolver

    class UnknownAfterFirstSolve:
        def __init__(self):
            self.delegate = real_solver()
            self.parameters = self.delegate.parameters
            self.solve_count = 0

        def Solve(self, model):
            self.solve_count += 1
            if self.solve_count > 1:
                return planner_module.cp_model.UNKNOWN
            return self.delegate.Solve(model)

        def Value(self, expression):
            return self.delegate.Value(expression)

    monkeypatch.setattr(planner_module.cp_model, "CpSolver", UnknownAfterFirstSolve)
    current = term()
    required = course("A", 5)
    planning_problem = problem(
        (required,),
        (current,),
        (CourseOffering("A", current, (bundle("A"),)),),
    )

    plan = planner().plan(planning_problem)

    assert plan.status is SolverStatus.FEASIBLE_NOT_PROVEN_OPTIMAL
    assert plan.scheduled_terms[0].course_ids == ("A",)
    assert any("last verified feasible plan" in warning for warning in plan.warnings)

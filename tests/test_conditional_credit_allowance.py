from dataclasses import replace

from academic_planner.domain.models import (
    AcademicTerm, AttemptStatus, CourseAttempt, CourseOffering, Curriculum,
    CurriculumVersion, LanguageTrack, PlanningConfiguration, SolverStatus,
    StudentAcademicState, TermKind,
)
from academic_planner.optimization import GlobalPlanner, PlanningProblem
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy,
    ProgressiveRolloutPolicy,
)
from academic_planner.validation import validate_plan
from tests.conftest import bundle, course


def _planner():
    return GlobalPlanner(
        ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(),
        AllowAllRegistrationPolicy(),
    )


def _problem(
    *, failed=False, passed_after_failure=False, enabled=False,
    override=None, training=False,
):
    kind = TermKind.TRAINING_1 if training else TermKind.FALL
    current = AcademicTerm(2023, kind)
    repeat = course("REPEAT", 5, semester=TermKind.SPRING)
    other = course("OTHER", 29)
    courses = (repeat,) if training else (repeat, other)
    attempts = []
    if failed:
        attempts.append(CourseAttempt(
            "REPEAT", AcademicTerm(2022, TermKind.SPRING),
            AttemptStatus.FAILED,
        ))
    if passed_after_failure:
        attempts.append(CourseAttempt(
            "REPEAT", AcademicTerm(2022, TermKind.SPRING),
            AttemptStatus.PASSED, earned_credits=5,
        ))
    student = StudentAcademicState(1, LanguageTrack.EN, tuple(attempts))
    offerings = [CourseOffering("REPEAT", current, (bundle("REPEAT"),))]
    if not training:
        offerings.append(CourseOffering(
            "OTHER", current,
            (bundle("OTHER", day=1, start=660, end=720),),
        ))
    capacities = {current: 5 if training else (override if override is not None else 30)}
    explicit = frozenset({current}) if override is not None else frozenset()
    config = PlanningConfiguration(
        term_credit_capacities=capacities,
        default_credit_capacity=30,
        planning_horizon=(current,),
        allow_extended_load_when_repeating_failed_course=enabled,
        explicit_capacity_override_terms=explicit,
    )
    curriculum = Curriculum(
        CurriculumVersion.NEW,
        frozenset(item.id for item in courses),
        accepted_credit_target=sum(item.credits for item in courses),
        training_requirement_ids=(frozenset({"REPEAT"}) if training else frozenset()),
    )
    return PlanningProblem(
        {item.id: item for item in courses}, curriculum, student, (), (),
        tuple(offerings), config,
    )


def test_toggle_off_keeps_30_and_blocks_34_credits():
    plan = _planner().plan(_problem(failed=True, enabled=False))
    assert plan.status is SolverStatus.INFEASIBLE


def test_course_with_no_attempt_history_is_not_treated_as_failed():
    plan = _planner().plan(_problem(enabled=True))
    assert plan.status is SolverStatus.INFEASIBLE


def test_toggle_on_with_nonfailed_attempt_keeps_30():
    problem = _problem(enabled=True)
    student = replace(problem.student, attempts=(CourseAttempt(
        "REPEAT", AcademicTerm(2022, TermKind.SPRING), AttemptStatus.WITHDRAWN,
    ),))
    plan = _planner().plan(replace(problem, student=student))
    assert plan.status is SolverStatus.INFEASIBLE


def test_selected_failed_repeat_unlocks_36_and_validates_34_credit_plan():
    problem = _problem(failed=True, enabled=True)
    plan = _planner().plan(problem)
    assert plan.status is SolverStatus.OPTIMAL
    assert plan.credit_usages[0].selected_credits == 34
    assert plan.credit_usages[0].effective_capacity == 36
    assert plan.credit_usages[0].reason == "FAILED_COURSE_REPEAT_ALLOWANCE"
    assert plan.credit_usages[0].repeated_course_ids == ("REPEAT",)
    assert not validate_plan(plan, problem)


def test_failed_course_offered_later_activates_only_that_later_semester():
    fall = AcademicTerm(2023, TermKind.FALL)
    spring = AcademicTerm(2023, TermKind.SPRING)
    repeat, regular = course("REPEAT", 5, semester=TermKind.SPRING), course("REGULAR", 30)
    student = StudentAcademicState(1, LanguageTrack.EN, (
        CourseAttempt("REPEAT", AcademicTerm(2022, TermKind.SPRING), AttemptStatus.FAILED),
    ))
    config = PlanningConfiguration(
        planning_horizon=(fall, spring),
        allow_extended_load_when_repeating_failed_course=True,
    )
    problem = PlanningProblem(
        {item.id: item for item in (repeat, regular)},
        Curriculum(CurriculumVersion.NEW, frozenset({"REPEAT", "REGULAR"}), 35),
        student, (), (),
        (
            CourseOffering("REGULAR", fall, (bundle("REGULAR"),)),
            CourseOffering("REPEAT", spring),
        ),
        config,
    )
    plan = _planner().plan(problem)
    assert plan.status is SolverStatus.OPTIMAL
    assert [(usage.effective_capacity, usage.reason) for usage in plan.credit_usages] == [
        (30, "NORMAL_REGULAR_CAPACITY"),
        (36, "FAILED_COURSE_REPEAT_ALLOWANCE"),
    ]


def test_failed_then_passed_does_not_unlock_allowance():
    base = _problem(failed=True, passed_after_failure=True, enabled=True)
    # REPEAT is already satisfied; the remaining 29-credit course does not need an allowance.
    plan = _planner().plan(base)
    assert plan.status is SolverStatus.OPTIMAL
    assert plan.credit_usages[0].effective_capacity == 30
    assert plan.credit_usages[0].reason == "NORMAL_REGULAR_CAPACITY"
    assert plan.scheduled_terms[0].course_ids == ("OTHER",)


def test_explicit_capacity_override_takes_precedence_over_conditional_rule():
    feasible = _problem(failed=True, enabled=False, override=34)
    plan = _planner().plan(feasible)
    assert plan.status is SolverStatus.OPTIMAL
    assert plan.credit_usages[0].effective_capacity == 34
    assert plan.credit_usages[0].reason == "EXPLICIT_TERM_OVERRIDE"

    capped = _problem(failed=True, enabled=True, override=33)
    assert _planner().plan(capped).status is SolverStatus.INFEASIBLE


def test_training_period_capacity_is_not_extended():
    problem = _problem(failed=True, enabled=True, training=True)
    plan = _planner().plan(problem)
    assert plan.status is SolverStatus.OPTIMAL
    assert plan.credit_usages[0].effective_capacity == 5
    assert plan.credit_usages[0].reason == "TRAINING_PERIOD_CAP"


def test_final_two_semester_allowance_uses_36_only_when_needed_to_graduate():
    problem = _problem()
    enabled = replace(problem, configuration=replace(
        problem.configuration,
        allow_final_two_semester_graduation_load=True,
    ))
    plan = _planner().plan(enabled)

    assert plan.status is SolverStatus.OPTIMAL
    assert plan.credit_usages[0].selected_credits == 34
    assert plan.credit_usages[0].effective_capacity == 36
    assert plan.credit_usages[0].reason == "FINAL_TWO_SEMESTER_GRADUATION_ALLOWANCE"

    thirty_credit_problem = replace(
        enabled,
        courses={
            **enabled.courses,
            "OTHER": replace(enabled.courses["OTHER"], credits=25),
        },
        curriculum=replace(enabled.curriculum, accepted_credit_target=30),
    )
    normal = _planner().plan(thirty_credit_problem)
    assert normal.credit_usages[0].selected_credits == 30
    assert normal.credit_usages[0].effective_capacity == 30
    assert normal.credit_usages[0].reason == "NORMAL_REGULAR_CAPACITY"

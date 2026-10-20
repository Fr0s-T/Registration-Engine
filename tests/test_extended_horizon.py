from dataclasses import replace

from academic_planner.domain.models import (
    AcademicTerm, CourseOffering, Curriculum, CurriculumVersion, LanguageTrack,
    PlanningConfiguration, SolverStatus, StudentAcademicState, TermKind,
)
from academic_planner.optimization import GlobalPlanner, PlanningProblem
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy,
    ProgressiveRolloutPolicy,
)
from tests.conftest import bundle, course


def _planner():
    return GlobalPlanner(
        ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(),
        AllowAllRegistrationPolicy(),
    )


def _delayed_problem(maximum=12, auto_extend=True):
    regular = tuple(
        AcademicTerm(2023 + index // 2, TermKind.FALL if index % 2 == 0 else TermKind.SPRING)
        for index in range(12)
    )
    training = AcademicTerm(2025, TermKind.TRAINING_1)
    terms = regular[:6] + (training,) + regular[6:]
    first = course("FIRST", 5, year=1)
    delayed = course("DELAYED-Y5", 5, year=5)
    placement = course("TRAINING", 5, year=3, semester=TermKind.SPRING)
    config = PlanningConfiguration(
        term_credit_capacities={training: 5},
        default_credit_capacity=30,
        planning_horizon=terms,
        initial_horizon_semesters=10,
        max_horizon_semesters=maximum,
        auto_extend_horizon=auto_extend,
        horizon_extension_step=2,
    )
    problem = PlanningProblem(
        {item.id: item for item in (first, delayed, placement)},
        Curriculum(
            CurriculumVersion.NEW,
            frozenset({"FIRST", "DELAYED-Y5", "TRAINING"}),
            15,
            training_requirement_ids=frozenset({"TRAINING"}),
        ),
        StudentAcademicState(1, LanguageTrack.EN), (), (),
        (
            CourseOffering("FIRST", regular[0], (bundle("FIRST"),)),
            CourseOffering("TRAINING", training),
            CourseOffering("DELAYED-Y5", regular[10]),
        ),
        config,
    )
    return problem, regular, training


def test_auto_extension_finds_plan_beyond_ten_regular_semesters():
    problem, regular, _ = _delayed_problem()
    plan = _planner().plan(problem)
    assert plan.status is SolverStatus.OPTIMAL
    assert plan.graduation_term == regular[10]
    assert any("extended from 10 to 12" in text for text in plan.explanations)


def test_rollout_is_applied_at_the_extended_academic_year():
    problem, regular, _ = _delayed_problem()
    delayed = problem.courses["DELAYED-Y5"]
    policy = ProgressiveRolloutPolicy()
    assert policy.permits(delayed, regular[8]).permitted
    plan = _planner().plan(problem)
    scheduled = next(
        item.term for item in plan.scheduled_terms
        if "DELAYED-Y5" in item.course_ids
    )
    assert scheduled == regular[10]


def test_insufficient_maximum_horizon_is_informative_and_proven_infeasible():
    problem, _, _ = _delayed_problem(maximum=10)
    config = replace(
        problem.configuration,
        initial_horizon_semesters=10,
        max_horizon_semesters=10,
    )
    plan = _planner().plan(replace(problem, configuration=config))
    assert plan.status is SolverStatus.INFEASIBLE
    assert any("configured maximum reached" in text for text in plan.explanations)


def test_training_period_is_preserved_but_not_counted_as_regular_horizon():
    problem, regular, training = _delayed_problem()
    plan = _planner().plan(problem)
    through_graduation = plan.scheduled_terms[:
        next(i for i, item in enumerate(plan.scheduled_terms) if item.term == plan.graduation_term) + 1
    ]
    assert training in {item.term for item in through_graduation}
    assert sum(item.term.is_regular for item in through_graduation) == 11
    assert len(through_graduation) == 12
    assert plan.graduation_term == regular[10]


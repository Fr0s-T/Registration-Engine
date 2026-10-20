from academic_planner.domain.models import (
    AcademicTerm, Course, CourseOffering, Curriculum, CurriculumVersion,
    GraduationPlan, LanguageTrack, Meeting, PlanningConfiguration,
    PrerequisiteRule, RegistrationBundle, Section, SolverStatus,
    StudentAcademicState, TermKind, Weekday,
)
from academic_planner.eligibility import EligibilityEngine
from academic_planner.optimization import GlobalPlanner, PlanningProblem
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy,
)
from academic_planner.validation import validate_plan


def _course(cid: str, credits: int, year: int, semester: TermKind, version=CurriculumVersion.NEW):
    return Course(cid, cid, cid, credits, version, year, semester)


def _bundle(course_id: str, day: Weekday, start: int, end: int):
    section = Section(
        f"{course_id}-SECTION", course_id, "LECTURE", "TEST",
        (Meeting(day, start, end),),
    )
    return RegistrationBundle(f"{course_id}-BUNDLE", course_id, (section,))


def _solve(problem: PlanningProblem, rollout=None) -> GraduationPlan:
    policy = rollout or ProgressiveRolloutPolicy()
    return GlobalPlanner(
        ConfiguredCreditLimitPolicy(), policy, AllowAllRegistrationPolicy()
    ).plan(problem)


def _training_problem(
    *, normal_offered: bool, delayed_offered: bool, allow_postponement: bool
) -> PlanningProblem:
    fall = AcademicTerm(2026, TermKind.FALL)
    normal = AcademicTerm(2026, TermKind.TRAINING_2)
    delayed = AcademicTerm(2027, TermKind.TRAINING_2)
    final_spring = AcademicTerm(2028, TermKind.SPRING)
    training = _course("TRAINING-II", 5, 4, TermKind.SPRING)
    final = _course("FINAL", 5, 5, TermKind.SPRING)
    offerings = [CourseOffering(final.id, final_spring)]
    if normal_offered:
        offerings.append(CourseOffering(training.id, normal))
    if delayed_offered:
        offerings.append(CourseOffering(training.id, delayed))
    config = PlanningConfiguration(
        term_credit_capacities={fall: 30, normal: 5, delayed: 5, final_spring: 30},
        planning_horizon=(fall, normal, delayed, final_spring),
        allow_training_postponement=allow_postponement,
        training_delay_penalty=25,
    )
    courses = {training.id: training, final.id: final}
    curriculum = Curriculum(
        CurriculumVersion.NEW, frozenset(courses), accepted_credit_target=10,
        fyp_requirement_id=final.id, training_requirement_ids=frozenset({training.id}),
    )
    return PlanningProblem(
        courses, curriculum, StudentAcademicState(4, LanguageTrack.EN), (), (),
        tuple(offerings), config,
    )


def _term_for(plan: GraduationPlan, course_id: str) -> AcademicTerm:
    return next(term.term for term in plan.scheduled_terms if course_id in term.course_ids)


def test_normal_training_period_wins_when_graduation_is_unchanged():
    problem = _training_problem(
        normal_offered=True, delayed_offered=True, allow_postponement=True
    )
    plan = _solve(problem)
    assert plan.status is SolverStatus.OPTIMAL
    assert _term_for(plan, "TRAINING-II") == AcademicTerm(2026, TermKind.TRAINING_2)
    assert plan.graduation_term == AcademicTerm(2028, TermKind.SPRING)
    assert not validate_plan(plan, problem)


def test_training_can_be_postponed_but_only_to_a_configured_training_period():
    problem = _training_problem(
        normal_offered=False, delayed_offered=True, allow_postponement=True
    )
    plan = _solve(problem)
    selected = _term_for(plan, "TRAINING-II")
    assert plan.status is SolverStatus.OPTIMAL
    assert selected == AcademicTerm(2027, TermKind.TRAINING_2)
    assert selected in problem.configuration.planning_horizon
    assert selected.kind is TermKind.TRAINING_2
    assert not validate_plan(plan, problem)


def test_training_postponement_can_be_prohibited():
    problem = _training_problem(
        normal_offered=False, delayed_offered=True, allow_postponement=False
    )
    plan = _solve(problem)
    assert plan.status is SolverStatus.INFEASIBLE


def _pressure_problem(*, dependent_available_early: bool, capacity: int = 30):
    fall_now = AcademicTerm(2026, TermKind.FALL)
    spring_now = AcademicTerm(2026, TermKind.SPRING)
    fall_next = AcademicTerm(2027, TermKind.FALL)
    spring_next = AcademicTerm(2027, TermKind.SPRING)
    current = _course("CURRENT-Y4", 30, 4, TermKind.FALL)
    backlog = _course("BACKLOG-Y3", 10, 3, TermKind.FALL)
    higher = _course("HIGHER-Y5", 5, 5, TermKind.FALL)
    dependent = _course("DEPENDENT", 5, 4, TermKind.SPRING)
    courses = {course.id: course for course in (current, backlog, higher, dependent)}
    offerings = [
        CourseOffering(current.id, fall_now, (_bundle(current.id, Weekday.MONDAY, 540, 660),)),
        CourseOffering(backlog.id, fall_now, (_bundle(backlog.id, Weekday.MONDAY, 570, 630),)),
        CourseOffering(higher.id, fall_now, (_bundle(higher.id, Weekday.TUESDAY, 540, 600),)),
        CourseOffering(current.id, fall_next),
        CourseOffering(backlog.id, fall_next),
        CourseOffering(higher.id, fall_next),
        CourseOffering(dependent.id, spring_next),
    ]
    if dependent_available_early:
        offerings.append(CourseOffering(dependent.id, spring_now))
    terms = (fall_now, spring_now, fall_next, spring_next)
    config = PlanningConfiguration(
        term_credit_capacities={term: capacity for term in terms},
        planning_horizon=terms,
        academic_year_deviation_weight=10,
        reference_semester_deviation_weight=2,
    )
    problem = PlanningProblem(
        courses,
        Curriculum(CurriculumVersion.NEW, frozenset(courses), accepted_credit_target=50),
        StudentAcademicState(4, LanguageTrack.EN),
        (), (PrerequisiteRule(dependent.id, frozenset({backlog.id})),),
        tuple(offerings), config,
    )
    overrides = {(higher.id, fall_now): True, (higher.id, fall_next): True}
    rollout = ProgressiveRolloutPolicy(explicit_overrides=overrides)
    return problem, rollout


def test_lower_credit_cross_year_schedule_wins_when_it_graduates_earlier():
    problem, rollout = _pressure_problem(dependent_available_early=True)
    pool = EligibilityEngine(rollout, AllowAllRegistrationPolicy()).build_pool(
        problem.student, problem.configuration.planning_horizon[0], problem.courses,
        frozenset(problem.courses), frozenset(), problem.prerequisites, problem.offerings,
    )
    plan = _solve(problem, rollout)
    current = set(plan.scheduled_terms[0].course_ids)

    assert sum(course.credits for course in pool.courses) == 45 > 36
    assert current == {"BACKLOG-Y3", "HIGHER-Y5"}
    assert sum(problem.courses[c].credits for c in current) == 15
    assert _term_for(plan, "DEPENDENT") == AcademicTerm(2026, TermKind.SPRING)
    assert plan.graduation_term == AcademicTerm(2027, TermKind.FALL)
    assert plan.status is SolverStatus.OPTIMAL
    assert not validate_plan(plan, problem)


def test_backlog_breaks_tie_before_current_year_alignment_and_load():
    problem, rollout = _pressure_problem(dependent_available_early=False)
    plan = _solve(problem, rollout)
    assert set(plan.scheduled_terms[0].course_ids) == {
        "BACKLOG-Y3", "HIGHER-Y5",
    }
    assert plan.graduation_term == AcademicTerm(2027, TermKind.SPRING)
    assert not validate_plan(plan, problem)


def test_requirement_without_verified_later_delivery_is_taken_first():
    current = AcademicTerm(2026, TermKind.FALL)
    later = AcademicTerm(2026, TermKind.SPRING)
    scarce = _course("SCARCE", 5, 4, TermKind.FALL)
    recurring = _course("RECURRING", 5, 4, TermKind.FALL)
    problem = PlanningProblem(
        courses={course.id: course for course in (scarce, recurring)},
        curriculum=Curriculum(
            CurriculumVersion.NEW,
            frozenset({scarce.id, recurring.id}),
            accepted_credit_target=10,
        ),
        student=StudentAcademicState(4, LanguageTrack.EN),
        equivalencies=(),
        prerequisites=(),
        offerings=(
            CourseOffering(
                scarce.id, current,
                (_bundle(scarce.id, Weekday.MONDAY, 540, 600),),
            ),
            CourseOffering(
                recurring.id, current,
                (_bundle(recurring.id, Weekday.TUESDAY, 540, 600),),
            ),
            CourseOffering(recurring.id, later, availability_verified=True),
        ),
        configuration=PlanningConfiguration(
            term_credit_capacities={current: 5, later: 5},
            planning_horizon=(current, later),
        ),
    )

    plan = _solve(problem)

    assert plan.status is SolverStatus.OPTIMAL
    assert plan.scheduled_terms[0].course_ids == ("SCARCE",)
    assert _term_for(plan, "RECURRING") == later


def test_36_credit_limit_does_not_override_faster_graduation_choice():
    problem, rollout = _pressure_problem(dependent_available_early=True, capacity=36)
    plan = _solve(problem, rollout)
    assert "BACKLOG-Y3" in plan.scheduled_terms[0].course_ids
    assert "CURRENT-Y4" not in plan.scheduled_terms[0].course_ids
    assert sum(problem.courses[c].credits for c in plan.scheduled_terms[0].course_ids) <= 36
    assert plan.graduation_term == AcademicTerm(2027, TermKind.FALL)
    assert not validate_plan(plan, problem)

from dataclasses import replace

from academic_planner.domain.models import (
    AcademicTerm, ApprovalStatus, AttemptStatus, CourseAttempt, CourseEquivalency,
    CourseOffering, CreditRequirementGroup, Curriculum, CurriculumVersion, LanguageTrack,
    OptionalCreditApproval, PlanningConfiguration, PrerequisiteRule, SolverStatus,
    StudentAcademicState, TermKind, Weekday,
)
from academic_planner.optimization import GlobalPlanner, PlanningProblem
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy,
)
from academic_planner.reconciliation import ReconciliationService
from tests.conftest import bundle, course


def _problem(*, approvals=(), prerequisites=(), target=12):
    terms = (
        AcademicTerm(2026, TermKind.FALL),
        AcademicTerm(2026, TermKind.SPRING),
    )
    courses = {
        "M": course("M", 4, year=1),
        "O8": course("O8", 8, year=1),
        "O5": course("O5", 5, year=1),
        "O3": course("O3", 3, year=1),
        "P": course("P", 2, year=1),
    }
    offerings = tuple(
        CourseOffering(cid, term, (bundle(cid, f"{index}"),) if index == 0 else ())
        for cid in courses for index, term in enumerate(terms)
    )
    return PlanningProblem(
        courses,
        Curriculum(CurriculumVersion.NEW, frozenset({"M"}), target),
        StudentAcademicState(1, LanguageTrack.EN),
        (), prerequisites, offerings,
        PlanningConfiguration(planning_horizon=terms, initial_horizon_semesters=2,
                              max_horizon_semesters=2),
        approvals,
    )


def _approval(course_id, status=ApprovalStatus.APPROVED):
    return OptionalCreditApproval(
        course_id, "PROGRAM_ELECTIVE", status,
        "Faculty Council", "decision:test-2026-01",
    )


def _planner():
    return GlobalPlanner(
        ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(),
        AllowAllRegistrationPolicy(),
    )


def test_documented_approved_optional_course_closes_real_credit_gap():
    problem = _problem(approvals=(_approval("O8"),))
    plan = _planner().plan(problem)
    assert plan.status is SolverStatus.OPTIMAL
    assert plan.selected_optional_course_ids == ("O8",)
    assert {cid for term in plan.scheduled_terms for cid in term.course_ids} == {"M", "O8"}
    assert all(not ({"M", "O8"} <= set(term.course_ids)) for term in plan.scheduled_terms)
    assert plan.scheduled_terms[0].term == problem.configuration.planning_horizon[0]
    assert plan.scheduled_terms[0].course_ids == ("M",)


def test_optimizer_chooses_no_unnecessary_optional_courses():
    problem = _problem(approvals=tuple(_approval(cid) for cid in ("O8", "O5", "O3")))
    plan = _planner().plan(problem)
    assert plan.status is SolverStatus.OPTIMAL
    assert plan.selected_optional_course_ids == ("O8",)


def _credit_priority_problem(*, gap, credits, prerequisites=()):
    base = _problem(target=4 + gap)
    _current, future = base.configuration.planning_horizon
    courses = {
        "M": course("M", 4, year=1),
        **{
            course_id: course(course_id, course_credits, year=1)
            for course_id, course_credits in credits.items()
        },
    }
    return replace(
        base,
        courses=courses,
        offerings=tuple(CourseOffering(course_id, future) for course_id in courses),
        prerequisites=tuple(prerequisites),
        optional_credit_approvals=tuple(
            _approval(course_id) for course_id in credits
        ),
    )


def test_optional_pool_prefers_higher_credit_courses_at_equal_total_and_count():
    problem = _credit_priority_problem(
        gap=8,
        credits={"HIGH": 4, "MID_A": 3, "MID_B": 3, "LOW": 2, "ONE": 1},
    )

    plan = _planner().plan(problem)

    assert plan.status is SolverStatus.OPTIMAL
    assert sorted(
        (problem.courses[cid].credits for cid in plan.selected_optional_course_ids),
        reverse=True,
    ) == [4, 3, 1]


def test_lower_credit_prerequisite_is_selected_when_it_unlocks_higher_credit_course():
    problem = _credit_priority_problem(
        gap=5,
        credits={"HIGH": 4, "PREREQ": 1, "MID": 3, "LOW": 2},
        prerequisites=(PrerequisiteRule("HIGH", frozenset({"PREREQ"})),),
    )
    current = problem.configuration.planning_horizon[0]
    problem = replace(
        problem,
        offerings=problem.offerings + (
            CourseOffering("PREREQ", current, (bundle("PREREQ"),)),
        ),
    )

    plan = _planner().plan(problem)

    assert plan.status is SolverStatus.OPTIMAL
    assert set(plan.selected_optional_course_ids) == {"HIGH", "PREREQ"}


def test_optional_credit_can_extend_graduation_after_last_mandatory_course():
    problem = _problem(approvals=(_approval("O8"),))
    first, second = problem.configuration.planning_horizon
    offerings = tuple(
        offering
        for offering in problem.offerings
        if not (offering.course_id == "O8" and offering.term == first)
    )
    plan = _planner().plan(replace(problem, offerings=offerings))

    assert plan.status is SolverStatus.OPTIMAL
    assert plan.graduation_term == second
    assert plan.selected_optional_course_ids == ("O8",)


def test_unverified_optional_is_strictly_infeasible_and_exploratory_is_hypothetical():
    problem = _problem(approvals=(_approval("O8", ApprovalStatus.UNVERIFIED),))
    strict = _planner().plan(problem)
    exploratory = _planner().plan(replace(problem, exploratory=True))
    assert strict.status is SolverStatus.INFEASIBLE
    assert "provide only 0 ECTS" in strict.explanations[0]
    assert exploratory.status is SolverStatus.OPTIMAL
    assert exploratory.hypothetical is True


def test_insufficient_approved_optional_credit_reports_the_remaining_gap():
    plan = _planner().plan(_problem(approvals=(_approval("O3"),)))
    assert plan.status is SolverStatus.INFEASIBLE
    assert "remaining graduation-credit requirement is 12 ECTS" in plan.explanations[0]
    assert "provide only 3 ECTS" in plan.explanations[0]


def test_transition_credit_adjustment_does_not_consume_semester_capacity():
    problem = replace(
        _problem(approvals=(_approval("O3"),)),
        allow_credit_adjustment_proposal=True,
    )
    plan = _planner().plan(problem)

    assert plan.status is SolverStatus.OPTIMAL
    assert plan.credit_adjustment_proposal is not None
    assert plan.credit_adjustment_proposal.credits == 5
    assert sum(item.selected_credits for item in plan.credit_usages) == 7
    assert "academic approval is required" in " ".join(plan.warnings)


def _pure_residual_deficit_problem(earned_credits):
    current = AcademicTerm(2026, TermKind.FALL)
    return PlanningProblem(
        courses={"O2": course("O2", 2, year=1)},
        curriculum=Curriculum(
            CurriculumVersion.NEW, frozenset(), accepted_credit_target=300
        ),
        student=StudentAcademicState(
            5, LanguageTrack.EN, earned_credits=earned_credits
        ),
        equivalencies=(),
        prerequisites=(),
        offerings=(CourseOffering("O2", current, (bundle("O2"),)),),
        configuration=PlanningConfiguration(
            planning_horizon=(current,),
            initial_horizon_semesters=1,
            max_horizon_semesters=1,
        ),
        optional_credit_approvals=(_approval("O2"),),
        allow_credit_adjustment_proposal=True,
    )


def test_one_credit_deficit_uses_adjustment_instead_of_excess_course():
    plan = _planner().plan(_pure_residual_deficit_problem(299))

    assert plan.status is SolverStatus.OPTIMAL
    assert plan.selected_optional_course_ids == ()
    assert plan.credit_adjustment_proposal is not None
    assert plan.credit_adjustment_proposal.credits == 1
    assert all(item.selected_credits == 0 for item in plan.credit_usages)


def test_two_credit_deficit_uses_exact_real_course_not_adjustment():
    plan = _planner().plan(_pure_residual_deficit_problem(298))

    assert plan.status is SolverStatus.OPTIMAL
    assert plan.selected_optional_course_ids == ("O2",)
    assert plan.credit_adjustment_proposal is None
    assert sum(item.selected_credits for item in plan.credit_usages) == 2


def _old_transition_delivery_problem(*, offer_old_requirement):
    current = AcademicTerm(2026, TermKind.FALL)
    courses = {
        "OLD-REQ": course(
            "OLD-REQ", 6, year=5, version=CurriculumVersion.OLD
        ),
        "NEW-REPL": course(
            "NEW-REPL", 5, year=4, version=CurriculumVersion.NEW
        ),
        "OLD-FILL1": course(
            "OLD-FILL1", 1, year=5, version=CurriculumVersion.OLD
        ),
    }
    offered = ["NEW-REPL", "OLD-FILL1"]
    if offer_old_requirement:
        offered.append("OLD-REQ")
    return PlanningProblem(
        courses=courses,
        curriculum=Curriculum(
            CurriculumVersion.OLD,
            frozenset({"OLD-REQ"}),
            accepted_credit_target=300,
        ),
        student=StudentAcademicState(
            5, LanguageTrack.EN, earned_credits=294
        ),
        equivalencies=(CourseEquivalency(
            "old-to-new-replacement",
            frozenset({"OLD-REQ"}),
            frozenset({"NEW-REPL"}),
            prospective_registration_allowed=True,
        ),),
        prerequisites=(),
        offerings=tuple(
            CourseOffering(
                course_id,
                current,
                (bundle(course_id, day=Weekday(index)),),
            )
            for index, course_id in enumerate(offered)
        ),
        configuration=PlanningConfiguration(
            planning_horizon=(current,),
            initial_horizon_semesters=1,
            max_horizon_semesters=1,
        ),
        optional_credit_approvals=(_approval("OLD-FILL1"),),
    )


def test_old_student_prefers_native_requirement_when_both_versions_are_available():
    plan = _planner().plan(
        _old_transition_delivery_problem(offer_old_requirement=True)
    )

    assert plan.status is SolverStatus.OPTIMAL
    assert {
        course_id
        for scheduled_term in plan.scheduled_terms
        for course_id in scheduled_term.course_ids
    } == {"OLD-REQ"}
    assert plan.selected_optional_course_ids == ()


def test_old_student_uses_new_replacement_and_fills_real_credit_difference():
    plan = _planner().plan(
        _old_transition_delivery_problem(offer_old_requirement=False)
    )

    assert plan.status is SolverStatus.OPTIMAL
    assert {
        course_id
        for scheduled_term in plan.scheduled_terms
        for course_id in scheduled_term.course_ids
    } == {"NEW-REPL", "OLD-FILL1"}
    assert plan.selected_optional_course_ids == ("OLD-FILL1",)


def test_optional_course_cannot_bypass_missing_prerequisite():
    problem = _problem(
        approvals=(_approval("O8"),),
        prerequisites=(PrerequisiteRule("O8", frozenset({"MISSING"})),),
    )
    assert _planner().plan(problem).status is SolverStatus.INFEASIBLE


def test_classification_separates_approved_registration_only_and_review():
    problem = _problem(approvals=(
        _approval("O8"), _approval("O5", ApprovalStatus.UNVERIFIED),
    ))
    result = ReconciliationService().reconcile(
        problem.student, problem.curriculum, (), courses=problem.courses,
        optional_approvals=problem.optional_credit_approvals,
        registration_course_ids=frozenset({"O3"}),
    )
    actual = {item.course_id: item.classification.value for item in result.classifications}
    assert actual == {
        "M": "MANDATORY_OUTSTANDING",
        "O3": "REGISTRATION_ONLY",
        "O5": "NEEDS_REVIEW",
        "O8": "APPROVED_OPTIONAL",
    }
    assert result.unresolved_credit_difference == 8


def test_completed_equivalent_cannot_be_selected_again_as_optional_credit():
    base = _problem(approvals=(_approval("O8"),), target=20)
    historical = CourseAttempt(
        "H8", AcademicTerm(2025, TermKind.SPRING),
        AttemptStatus.PASSED, earned_credits=8,
    )
    problem = replace(
        base,
        courses={**base.courses, "H8": course("H8", 8)},
        student=replace(base.student, attempts=(historical,)),
        equivalencies=(CourseEquivalency(
            "H8-O8", frozenset({"H8"}), frozenset({"O8"}),
        ),),
    )

    assert _planner().plan(problem).status is SolverStatus.INFEASIBLE


def test_both_sides_of_equivalency_cannot_be_selected_prospectively():
    base = _problem(
        approvals=(_approval("O8"), _approval("O5")),
        target=17,
    )
    problem = replace(base, equivalencies=(CourseEquivalency(
        "O8-O5", frozenset({"O8"}), frozenset({"O5"}),
    ),))

    assert _planner().plan(problem).status is SolverStatus.INFEASIBLE


def test_global_credit_total_cannot_hide_an_unsatisfied_contract_group():
    base = _problem(
        approvals=(_approval("O8"), _approval("O3")),
        target=12,
    )
    problem = replace(
        base,
        offerings=tuple(
            offering for offering in base.offerings
            if offering.course_id != "O3"
        ),
        credit_requirement_groups=(
            CreditRequirementGroup("GROUP_A", "A", 3, {"O8": 8}),
            CreditRequirementGroup("GROUP_B", "B", 3, {"O3": 3}),
        ),
    )

    plan = _planner().plan(problem)

    assert plan.status is SolverStatus.INFEASIBLE
    assert any("O3" in explanation for explanation in plan.explanations)

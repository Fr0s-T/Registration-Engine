import pytest

from academic_planner.domain.models import *
from academic_planner.domain.validation import validate_catalog
from academic_planner.eligibility import EligibilityEngine, RejectionCode
from academic_planner.policies import AllowAllRegistrationPolicy, ProgressiveRolloutPolicy
from academic_planner.reconciliation import ReconciliationService
from tests.conftest import course, term


def test_interval_boundaries_and_overlap():
    a = Meeting(Weekday.MONDAY, 600, 660)
    assert not a.overlaps(Meeting(Weekday.MONDAY, 660, 720))
    assert a.overlaps(Meeting(Weekday.MONDAY, 659, 720))
    assert not a.overlaps(Meeting(Weekday.TUESDAY, 600, 660))


def test_status_handling_transfer_and_in_progress():
    t = term()
    curriculum = Curriculum(CurriculumVersion.NEW, frozenset({"R1", "R2"}), accepted_credit_target=10)
    student = StudentAcademicState(2, LanguageTrack.EN, (
        CourseAttempt("X", t, AttemptStatus.TRANSFERRED, earned_credits=5),
        CourseAttempt("R2", t, AttemptStatus.IN_PROGRESS),
    ))
    eq = CourseEquivalency("e", frozenset({"X"}), frozenset({"R1"}))
    result = ReconciliationService().reconcile(student, curriculum, (eq,))
    assert result.satisfied_requirement_ids == {"R1"}
    assert result.outstanding_requirement_ids == {"R2"}
    assert result.official_earned_credits == 5


def test_equivalent_completion_is_allocated_only_once():
    curriculum = Curriculum(CurriculumVersion.NEW, frozenset({"R1", "R2"}))
    student = StudentAcademicState(1, LanguageTrack.EN, (CourseAttempt("OLD", term(), AttemptStatus.PASSED),))
    eq = CourseEquivalency("e", frozenset({"OLD"}), frozenset({"R1", "R2"}))
    result = ReconciliationService().reconcile(student, curriculum, (eq,))
    assert len(result.satisfied_requirement_ids) == 1


def test_new_replacement_satisfies_old_requirement_without_inflating_earned_credit():
    curriculum = Curriculum(
        CurriculumVersion.OLD,
        frozenset({"OLD-MICROPROCESSORS"}),
        accepted_credit_target=300,
    )
    student = StudentAcademicState(5, LanguageTrack.EN, (
        CourseAttempt(
            "NEW-MICROPROCESSORS",
            term(2026),
            AttemptStatus.PASSED,
            earned_credits=5,
        ),
    ))
    equivalency = CourseEquivalency(
        "microprocessors-transition",
        frozenset({"OLD-MICROPROCESSORS"}),
        frozenset({"NEW-MICROPROCESSORS"}),
    )

    result = ReconciliationService().reconcile(
        student, curriculum, (equivalency,)
    )

    assert result.satisfied_requirement_ids == {"OLD-MICROPROCESSORS"}
    assert result.allocations == (
        ("NEW-MICROPROCESSORS", "OLD-MICROPROCESSORS"),
    )
    assert result.official_earned_credits == 5


def test_repeated_successful_attempts_do_not_duplicate_earned_credit():
    curriculum = Curriculum(CurriculumVersion.NEW, frozenset({"R1"}),
                            accepted_credit_target=5)
    student = StudentAcademicState(1, LanguageTrack.EN, (
        CourseAttempt("R1", term(2022), AttemptStatus.PASSED, earned_credits=5),
        CourseAttempt("R1", term(2023), AttemptStatus.PASSED, earned_credits=5),
    ))
    result = ReconciliationService().reconcile(student, curriculum, ())
    assert result.official_earned_credits == 5


def test_equivalent_old_completion_unlocks_new_code_prerequisite():
    current = term(2026)
    courses = {
        "OLD-P": course("OLD-P", year=1, version=CurriculumVersion.OLD),
        "NEW-P": course("NEW-P", year=1, version=CurriculumVersion.NEW),
        "NEW-D": course("NEW-D", year=4, version=CurriculumVersion.NEW),
    }
    curriculum = Curriculum(
        CurriculumVersion.NEW, frozenset({"NEW-D"}), accepted_credit_target=5
    )
    student = StudentAcademicState(5, LanguageTrack.EN, (
        CourseAttempt("OLD-P", term(2023), AttemptStatus.PASSED, earned_credits=4),
    ))
    verified = CourseEquivalency(
        "verified", frozenset({"OLD-P"}), frozenset({"NEW-P"})
    )
    recognized = ReconciliationService().reconcile(student, curriculum, (verified,))
    assert "NEW-P" in recognized.prerequisite_completion_ids
    rule = (PrerequisiteRule("NEW-D", frozenset({"NEW-P"})),)
    offering = (CourseOffering("NEW-D", current),)
    engine = EligibilityEngine(ProgressiveRolloutPolicy(), AllowAllRegistrationPolicy())
    allowed = engine.build_pool(
        student, current, courses, recognized.outstanding_requirement_ids,
        recognized.prerequisite_completion_ids, rule, offering,
    )
    assert [item.id for item in allowed.courses] == ["NEW-D"]

    unrecognized = ReconciliationService().reconcile(student, curriculum, ())
    blocked = engine.build_pool(
        student, current, courses, unrecognized.outstanding_requirement_ids,
        unrecognized.prerequisite_completion_ids, rule, offering,
    )
    assert not blocked.courses
    dependent_rejection = next(
        rejection for rejection in blocked.rejections if rejection.course_id == "NEW-D"
    )
    assert dependent_rejection.code is RejectionCode.PREREQUISITE


def test_language_requirement_is_resolved_deterministically():
    curriculum = Curriculum(CurriculumVersion.NEW, frozenset({"M", "EN", "FR"}), language_requirements={LanguageTrack.EN: frozenset({"EN"}), LanguageTrack.FR: frozenset({"FR"})})
    assert curriculum.resolved_requirements(LanguageTrack.EN) == {"M", "EN"}


def test_invalid_credit_cycle_and_contradictory_equivalency_validation():
    with pytest.raises(ValueError):
        course("bad", -1)
    courses = {x.id: x for x in (course("A"), course("B"))}
    with pytest.raises(ValueError, match="cycle"):
        validate_catalog(courses, (PrerequisiteRule("A", frozenset({"B"})), PrerequisiteRule("B", frozenset({"A"}))), ())
    with pytest.raises(ValueError, match="contradictory"):
        validate_catalog(courses, (), (CourseEquivalency("1", frozenset({"A"}), frozenset({"A"})), CourseEquivalency("2", frozenset({"A"}), frozenset({"B"}))))

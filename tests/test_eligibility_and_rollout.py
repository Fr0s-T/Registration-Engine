from academic_planner.domain.models import *
from academic_planner.eligibility import EligibilityEngine, RejectionCode
from academic_planner.policies import AllowAllRegistrationPolicy, ProgressiveRolloutPolicy
from tests.conftest import course, term


def engine() -> EligibilityEngine:
    return EligibilityEngine(ProgressiveRolloutPolicy(), AllowAllRegistrationPolicy())


def test_completed_prerequisite_unlocks_and_incomplete_blocks():
    t = term(2024)
    courses = {c.id: c for c in (course("CLC2"), course("ODE", year=2))}
    offerings = (CourseOffering("ODE", t),)
    rule = (PrerequisiteRule("ODE", frozenset({"CLC2"})),)
    student = StudentAcademicState(3, LanguageTrack.EN)
    open_pool = engine().build_pool(student, t, courses, frozenset({"ODE"}), frozenset({"CLC2"}), rule, offerings)
    blocked_pool = engine().build_pool(student, t, courses, frozenset({"ODE"}), frozenset(), rule, offerings)
    assert [c.id for c in open_pool.courses] == ["ODE"]
    assert next(r for r in blocked_pool.rejections if r.course_id == "ODE").code is RejectionCode.PREREQUISITE


def test_pool_can_exceed_registration_allowance_and_include_earlier_year():
    t = term(2025)
    courses = {str(i): course(str(i), 20, year=1) for i in range(3)}
    offerings = tuple(CourseOffering(c, t) for c in courses)
    pool = engine().build_pool(StudentAcademicState(4, LanguageTrack.EN), t, courses, frozenset(courses), frozenset(), (), offerings)
    assert sum(c.credits for c in pool.courses) == 60


def test_eligibility_updates_after_projected_completion():
    t1, t2 = term(2024), term(2024, TermKind.SPRING)
    courses = {c.id: c for c in (course("P"), course("D", year=2))}
    student = StudentAcademicState(2, LanguageTrack.EN)
    rules = (PrerequisiteRule("D", frozenset({"P"})),)
    p1 = engine().build_pool(student, t1, courses, frozenset({"P", "D"}), frozenset(), rules, (CourseOffering("D", t1),))
    p2 = engine().build_pool(student, t2, courses, frozenset({"D"}), frozenset({"P"}), rules, (CourseOffering("D", t2),))
    assert not p1.courses and [c.id for c in p2.courses] == ["D"]


def test_rollout_advances_and_fourth_year_can_take_old_fifth_not_new_fifth():
    policy = ProgressiveRolloutPolicy()
    old5 = course("O5", year=5, version=CurriculumVersion.OLD)
    new5 = course("N5", year=5, version=CurriculumVersion.NEW)
    t = term(2026)
    assert policy.permits(old5, t).permitted
    assert not policy.permits(new5, t).permitted
    assert policy.permits(new5, term(2027)).permitted
    courses = {c.id: c for c in (old5, new5)}
    pool = engine().build_pool(StudentAcademicState(4, LanguageTrack.EN), t, courses, frozenset(courses), frozenset(), (), (CourseOffering("O5", t), CourseOffering("N5", t)))
    assert [c.id for c in pool.courses] == ["O5"]


def test_rollout_boundary_is_calendar_based_at_both_student_year_extremes():
    current = term(2026)
    courses = {
        c.id: c for c in (
            course("N1", year=1, version=CurriculumVersion.NEW),
            course("N4", year=4, version=CurriculumVersion.NEW),
            course("N5", year=5, version=CurriculumVersion.NEW),
            course("O1", year=1, version=CurriculumVersion.OLD),
            course("O4", year=4, version=CurriculumVersion.OLD),
            course("O5", year=5, version=CurriculumVersion.OLD),
        )
    }
    offerings = tuple(CourseOffering(cid, current) for cid in courses)
    for nominal_year in (1, 5):
        pool = engine().build_pool(
            StudentAcademicState(nominal_year, LanguageTrack.EN), current,
            courses, frozenset(courses), frozenset(), (), offerings,
        )
        assert {c.id for c in pool.courses} == {"N1", "N4", "O5"}
        rollout_blocked = {
            item.course_id for item in pool.rejections
            if item.code is RejectionCode.ROLLOUT
        }
        assert rollout_blocked == {"N5", "O1", "O4"}


def test_rollout_boundary_flips_to_new_year_five_for_both_student_extremes():
    next_fall = term(2027)
    old5 = course("O5", year=5, version=CurriculumVersion.OLD)
    new5 = course("N5", year=5, version=CurriculumVersion.NEW)
    courses = {c.id: c for c in (old5, new5)}
    offerings = tuple(CourseOffering(cid, next_fall) for cid in courses)
    for nominal_year in (1, 5):
        pool = engine().build_pool(
            StudentAcademicState(nominal_year, LanguageTrack.EN), next_fall,
            courses, frozenset(courses), frozenset(), (), offerings,
        )
        assert [c.id for c in pool.courses] == ["N5"]
        assert next(item for item in pool.rejections if item.course_id == "O5").code is RejectionCode.ROLLOUT


def test_missing_offering_data_has_structured_reason():
    c = course("A")
    pool = engine().build_pool(StudentAcademicState(1, LanguageTrack.EN), term(), {"A": c}, frozenset({"A"}), frozenset(), (), ())
    assert pool.rejections[0].code is RejectionCode.NOT_OFFERED


def test_transfer_student_can_have_earlier_year_outstanding_without_failures():
    t = term(2025)
    c = course("EARLY", year=1)
    student = StudentAcademicState(4, LanguageTrack.EN, attempts=(CourseAttempt("OTHER", t, AttemptStatus.TRANSFERRED),))
    pool = engine().build_pool(student, t, {c.id: c}, frozenset({c.id}), frozenset(), (), (CourseOffering(c.id, t),))
    assert pool.courses == (c,)

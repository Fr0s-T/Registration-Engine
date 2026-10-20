from types import SimpleNamespace

from academic_planner.domain.models import (
    AcademicTerm, Course, Curriculum, CurriculumVersion, LanguageTrack,
    StudentAcademicState, TermKind,
)
from academic_planner.reconciliation import ReconciliationService
from academic_planner.transcripts import normalize_attempt_rows


def _row(code, *, course_id=None, ects=0, earned=0, status="PASSED"):
    return SimpleNamespace(
        course_id=course_id,
        source_code=code,
        source_term="FALL2026",
        status=status,
        grade=None,
        ects=ects,
        earned_credits=earned,
        counts_toward_degree_credit=True,
    )


def test_zero_credit_lab_with_transcript_parent_is_component_not_unknown():
    normalized = normalize_attempt_rows(
        (_row("ELBC501", course_id=10, ects=4, earned=4), _row("ELBC501L")),
        lambda _value: AcademicTerm(2026, TermKind.FALL),
    )

    assert normalized.component_codes == ("ELBC501L",)
    assert normalized.unknown_codes == ()
    assert len(normalized.attempts) == 1
    assert normalized.completed_credits == 4


def test_lab_without_parent_remains_unknown_for_review():
    normalized = normalize_attempt_rows(
        (_row("ELBC501L"),),
        lambda _value: AcademicTerm(2026, TermKind.FALL),
    )

    assert normalized.component_codes == ()
    assert normalized.unknown_codes == ("ELBC501L",)


def test_reviewed_non_credit_lab_is_removed_before_status_normalization():
    lab = _row("CCE441L", status="NEEDS_REVIEW")
    lab.counts_toward_degree_credit = False
    normalized = normalize_attempt_rows(
        (
            _row("ELCC632", course_id=10, ects=3, earned=3),
            lab,
        ),
        lambda _value: AcademicTerm(2026, TermKind.FALL),
    )

    assert normalized.component_codes == ("CCE441L",)
    assert normalized.unknown_codes == ()
    assert len(normalized.attempts) == 1
    assert normalized.completed_credits == 3


def test_transcript_credit_exclusion_overrides_recorded_ects_and_earned_value():
    row = _row("ENG108", ects=8, earned=8)
    row.counts_toward_degree_credit = False
    normalized = normalize_attempt_rows(
        (row,), lambda _value: AcademicTerm(2026, TermKind.FALL)
    )

    assert normalized.completed_credits == 0
    assert normalized.unresolved_earned_credits == 0


def test_distinct_historical_aliases_preserve_credit_while_satisfying_one_requirement():
    normalized = normalize_attempt_rows(
        (_row("ENG221", ects=4, earned=4), _row("ENG222", ects=4, earned=4)),
        lambda _value: AcademicTerm(2026, TermKind.FALL),
        course_id_by_source_code={"ENG221": "GER221", "ENG222": "GER221"},
    )
    student = StudentAcademicState(1, LanguageTrack.EN, normalized.attempts)
    result = ReconciliationService().reconcile(
        student,
        Curriculum(CurriculumVersion.NEW, frozenset({"GER221"}), 8),
        (),
        courses={
            "GER221": Course(
                "GER221", "GER221", "English communication", 4,
                CurriculumVersion.NEW, 1, TermKind.SPRING,
            )
        },
    )

    assert result.satisfied_requirement_ids == {"GER221"}
    assert result.official_earned_credits == 8


def test_persisted_alias_rows_keep_separate_source_credit_identities():
    normalized = normalize_attempt_rows(
        (
            _row("ENG221", course_id="GER221", ects=4, earned=4),
            _row("ENG222", course_id="GER221", ects=4, earned=4),
        ),
        lambda _value: AcademicTerm(2026, TermKind.FALL),
        credit_identity_by_course_id={"GER221": "course:NEW:GER221"},
        separate_source_identity_codes=frozenset({"ENG221", "ENG222"}),
    )

    assert normalized.completed_credits == 8
    assert {attempt.credit_identity for attempt in normalized.attempts} == {
        "source:ENG221", "source:ENG222",
    }


def test_equivalent_persisted_courses_share_one_credit_identity():
    normalized = normalize_attempt_rows(
        (
            _row("ELCC100", course_id=10, ects=5, earned=5),
            _row("CCE100", course_id=20, ects=5, earned=5),
        ),
        lambda _value: AcademicTerm(2026, TermKind.FALL),
        credit_identity_by_course_id={
            10: "course:OLD:ELCC100",
            20: "course:OLD:ELCC100",
        },
    )

    assert normalized.completed_credits == 5
    assert {attempt.credit_identity for attempt in normalized.attempts} == {
        "course:OLD:ELCC100"
    }


def test_repeated_unresolved_course_credit_is_counted_once():
    normalized = normalize_attempt_rows(
        (
            _row("HIST100", ects=3, earned=3),
            _row("HIST100", ects=3, earned=3),
        ),
        lambda _value: AcademicTerm(2026, TermKind.FALL),
    )

    assert normalized.unresolved_earned_credits == 3
    assert normalized.completed_credits == 3

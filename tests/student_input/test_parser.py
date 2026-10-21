from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from academic_planner.database.models import (
    CourseRecord,
    CurriculumRevision,
    DegreeRequirement,
    StudentAttemptRecord,
    StudentRecord,
)
from academic_planner.database.session import SessionLocal
from academic_planner.student_input.parser import parse_student_contract
from academic_planner.web.app import app
from academic_planner.web.database_student_service import DatabaseStudentPlanningService


MULTI_ATTEMPT_TEXT = """
EN
Contract Sheet | 100001 - Sample Student
ELCC - Computer and Communication Engineering L - Bachelor Degree 2003-10-02
ELCC-L-1 - Bachelor Degree - Computer and Communication Engineering Total Earned Credits : 10 Credits
The total number of credits needed to graduate is 300 credits (ECTS)
The Passing Grade For GER and Common Core courses Emphasis courses and Capstone, is 60/100.
Common Core
#  Course Code  Course Title  Credits  Semester  Grade
1  MAT331  Differential Equation and Vector Analysis  5
FALL2025
FALL2024
D+ - 64
W - 0
2  CCE341  Analog Electronics I  5  SPRING2025
D+ - 60
Required Credits! 67  Earned Credits! 10  Passing Grade! 60
Courses Not in Contract Sheet
#  Course Code  Course Title  Credits  Semester  Grade
89  MAT331  Differential Equation and Vector Analysis  5  FALL2025
D+ - 64
90  CCE341L  Analog Electronics I Lab  0  SPRING2025
- 0
Earned Credits! 5
"""


PAST_UNGRADED_TEXT = """
EN
Contract Sheet | 42 - Review Student
ELCC - Computer and Communication Engineering L - Bachelor Degree 2000-01-01
ELCC-L-1 - Bachelor Degree - Computer and Communication Engineering Total Earned Credits : 0 Credits
The total number of credits needed to graduate is 300 credits (ECTS)
The Passing Grade For GER and Common Core courses Emphasis courses and Capstone, is 60/100.
Courses Not in Contract Sheet
#  Course Code  Course Title  Credits  Semester  Grade
1  ELCC819  Training II  4  SUMMERI2026
- 0
Earned Credits! 0
"""


TRANSCRIPT_TRUTH_TEXT = """
EN
Contract Sheet | 43 - Transcript Truth Student
ELCC - Computer and Communication Engineering L - Bachelor Degree 2000-01-01
ELCC-L-1 - Bachelor Degree - Computer and Communication Engineering Total Earned Credits : 8 Credits
The total number of credits needed to graduate is 300 credits (ECTS)
The Passing Grade For GER and Common Core courses Emphasis courses and Capstone, is 60/100.
Common Core
#  Course Code  Course Title  Credits  Semester  Grade
1  CHM224  Chemistry for Engineering  3  SPRING2024
D - 55
Required Credits! 67  Earned Credits! 3  Passing Grade! 60
Emphasis: CCE
#  Course Code  Course Title  Credits  Semester  Grade
1  CCE550  Routing and Switching Concepts  5  FALL2026
- 0
Required Credits! 135  Earned Credits! 0  Passing Grade! 60
Courses Not in Contract Sheet
#  Course Code  Course Title  Credits  Semester  Grade
1  ELCM122  Introduction to Computer  5  FALL2023
S - 49
2  ENG107  English Level B1  8  SPRING2023
S - 60 Excluded From GPA
3  CCE550L  Routing and Switching Concepts Lab  0  FALL2026
- 0
Earned Credits! 5
"""


LAB_PARENT_REVIEW_TEXT = MULTI_ATTEMPT_TEXT.replace(
    "90  CCE341L  Analog Electronics I Lab  0  SPRING2025",
    "90  CCE341L  Analog Electronics I Lab  0  FALL2024",
)


LAB_EQUIVALENT_PARENT_TEXT = """
EN
Contract Sheet | 44 - Equivalent Lab Student
ELCC - Computer and Communication Engineering L - Bachelor Degree 2000-01-01
ELCC-L-1 - Bachelor Degree - Computer and Communication Engineering Total Earned Credits : 5 Credits
The total number of credits needed to graduate is 300 credits (ECTS)
The Passing Grade For GER and Common Core courses Emphasis courses and Capstone, is 60/100.
Courses Not in Contract Sheet
#  Course Code  Course Title  Credits  Semester  Grade
1  ELCC632  Computer Architecture  5  FALL2024
A - 90
2  CCE441L  Computer Architecture Lab  0  FALL2025
- 0
Earned Credits! 5
"""


TOTAL_MISMATCH_TEXT = """
EN
Contract Sheet | 45 - Total Review Student
ELCC - Computer and Communication Engineering L - Bachelor Degree 2000-01-01
ELCC-L-1 - Bachelor Degree - Computer and Communication Engineering Total Earned Credits : 8 Credits
The total number of credits needed to graduate is 300 credits (ECTS)
The Passing Grade For GER and Common Core courses Emphasis courses and Capstone, is 60/100.
Courses Not in Contract Sheet
#  Course Code  Course Title  Credits  Semester  Grade
1  CLEN121  General English 1  3  FALL2020
A - 90
Earned Credits! 8
"""


def test_parser_pairs_multiple_attempts_deduplicates_and_attaches_lab():
    parsed = parse_student_contract(MULTI_ATTEMPT_TEXT, "FALL2026")

    assert parsed.identity.student_id == "100001"
    assert len(parsed.attempts) == 3
    assert parsed.duplicate_attempts_merged == 1
    mat331 = [attempt for attempt in parsed.attempts if attempt.source_code == "MAT331"]
    assert {(attempt.term, attempt.status) for attempt in mat331} == {
        ("FALL2025", "PASSED"), ("FALL2024", "WITHDRAWN"),
    }
    duplicate = next(attempt for attempt in mat331 if attempt.term == "FALL2025")
    assert duplicate.duplicate_occurrences == 2
    assert set(duplicate.source_sections) == {
        "Common Core", "Courses Not in Contract Sheet",
    }
    assert len(parsed.components) == 1
    assert parsed.components[0].parent_code == "CCE341"
    assert parsed.components[0].parent_attempt_id is not None
    assert not parsed.issues


def test_past_ungraded_course_requires_review_but_future_course_is_registered():
    text = MULTI_ATTEMPT_TEXT.replace(
        "89  MAT331  Differential Equation and Vector Analysis  5  FALL2025\nD+ - 64",
        "89  ELCC819  Training II  4  SUMMERI2026\n- 0\n"
        "91  CCE550  Routing and Switching Concepts  5  FALL2026\n- 0",
    )
    parsed = parse_student_contract(text, "FALL2026")

    by_code = {attempt.source_code: attempt for attempt in parsed.attempts}
    assert by_code["ELCC819"].status == "NEEDS_REVIEW"
    assert by_code["CCE550"].status == "REGISTERED"
    issue = next(issue for issue in parsed.issues if issue.code == "PAST_UNGRADED_ATTEMPT")
    assert "Training II (ELCC819)" in issue.message
    assert any(option.startswith("Enter the final grade") for option in issue.options)
    assert any("credit or GPA" in option for option in issue.options)


def test_completed_unknown_course_is_kept_as_historical_unmapped_credit():
    text = """
EN
Contract Sheet | 42 - Historical Student
ELCC - Computer and Communication Engineering L - Bachelor Degree 2000-01-01
ELCC-L-1 - Bachelor Degree - Computer and Communication Engineering Total Earned Credits : 3 Credits
The total number of credits needed to graduate is 300 credits (ECTS)
The Passing Grade For GER and Common Core courses Emphasis courses and Capstone, is 60/100.
Courses Not in Contract Sheet
#  Course Code  Course Title  Credits  Semester  Grade
1  CLEN121  General English 1  3  FALL2020
A - 90
Earned Credits! 3
"""

    response = TestClient(app).post(
        "/api/student-input/preview", json={"text": text, "current_term": "FALL2026"}
    )

    assert response.status_code == 200
    body = response.json()
    group = next(group for group in body["course_groups"] if "CLEN121" in group["codes"])
    assert group["effective_status"] == "COMPLETED"
    assert group["mapping_status"] == "HISTORICAL_UNMAPPED"
    assert group["attempts"][0]["match_status"] == "HISTORICAL_UNMAPPED"
    assert body["credit_check"]["status"] == "MATCH"
    assert body["review_issues"] == []
    assert body["can_continue_without_review"] is True


def test_reviewer_can_confirm_a_past_ungraded_course_is_still_pending():
    client = TestClient(app)
    initial = client.post(
        "/api/student-input/preview",
        json={"text": PAST_UNGRADED_TEXT, "current_term": "FALL2026"},
    ).json()
    issue = initial["review_issues"][0]

    response = client.post(
        "/api/student-input/preview",
        json={
            "text": PAST_UNGRADED_TEXT,
            "current_term": "FALL2026",
            "decisions": [{
                "issue_code": issue["code"],
                "attempt_id": issue["attempt_id"],
                "action": "COMPLETED_GRADE_PENDING",
            }],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_issues"] == []
    assert body["applied_decisions"][0]["course_label"] == "Training II (ELCC819)"
    assert body["course_groups"][0]["effective_status"] == "RESULT_PENDING"
    assert body["credit_check"]["status"] == "MATCH"
    assert body["can_continue_without_review"] is True


def test_common_core_grade_entered_during_review_uses_fifty_as_pass_mark():
    text = """
EN
Contract Sheet | 4201 - Common Core Review Student
ELCC - Computer and Communication Engineering L - Bachelor Degree 2000-01-01
ELCC-L-1 - Bachelor Degree - Computer and Communication Engineering Total Earned Credits : 0 Credits
The total number of credits needed to graduate is 300 credits (ECTS)
The Passing Grade For GER and Common Core courses Emphasis courses and Capstone, is 60/100.
Common Core
#  Course Code  Course Title  Credits  Semester  Grade
1  CHM224  Chemistry for Engineering  3  SPRING2024
- 0
Required Credits! 67  Earned Credits! 0  Passing Grade! 60
"""
    client = TestClient(app)
    initial = client.post(
        "/api/student-input/preview",
        json={"text": text, "current_term": "FALL2026"},
    ).json()
    issue = next(
        item for item in initial["review_issues"]
        if item["code"] == "PAST_UNGRADED_ATTEMPT"
    )

    response = client.post("/api/student-input/preview", json={
        "text": text,
        "current_term": "FALL2026",
        "decisions": [{
            "issue_code": issue["code"],
            "attempt_id": issue["attempt_id"],
            "action": "ENTER_FINAL_GRADE",
            "grade_value": 55,
        }],
    })

    assert response.status_code == 200, response.text
    body = response.json()
    attempt = body["course_groups"][0]["attempts"][0]
    assert attempt["status"] == "PASSED"
    assert attempt["earned_ects"] == 3


def test_review_action_must_match_the_issue_type():
    client = TestClient(app)
    initial = client.post(
        "/api/student-input/preview",
        json={"text": PAST_UNGRADED_TEXT, "current_term": "FALL2026"},
    ).json()
    issue = initial["review_issues"][0]

    response = client.post("/api/student-input/preview", json={
        "text": PAST_UNGRADED_TEXT,
        "current_term": "FALL2026",
        "decisions": [{
            "issue_code": issue["code"],
            "attempt_id": issue["attempt_id"],
            "action": "KEEP_LAB_FOR_AUDIT",
        }],
    })

    assert response.status_code == 422
    assert "not valid for review issue" in response.json()["detail"]


def test_commit_rejects_text_changed_after_preview():
    client = TestClient(app)
    preview = client.post("/api/student-input/preview", json={
        "text": TRANSCRIPT_TRUTH_TEXT,
        "current_term": "FALL2026",
    }).json()

    response = client.post("/api/student-input/commit", json={
        "text": TRANSCRIPT_TRUTH_TEXT.replace(
            "Transcript Truth Student", "Changed Transcript Student"
        ),
        "current_term": "FALL2026",
        "preview_token": preview["preview_token"],
    })

    assert response.status_code == 422
    assert "changed after preview" in response.json()["detail"]


def test_reviewer_entered_passing_grade_recalculates_credit_as_adjusted():
    client = TestClient(app)
    initial = client.post(
        "/api/student-input/preview",
        json={"text": PAST_UNGRADED_TEXT, "current_term": "FALL2026"},
    ).json()
    issue = initial["review_issues"][0]

    response = client.post(
        "/api/student-input/preview",
        json={
            "text": PAST_UNGRADED_TEXT,
            "current_term": "FALL2026",
            "decisions": [{
                "issue_code": issue["code"],
                "attempt_id": issue["attempt_id"],
                "action": "ENTER_FINAL_GRADE",
                "grade_value": 90,
            }],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_issues"] == []
    assert body["credit_check"]["status"] == "ADJUSTED"
    assert body["credit_check"]["parsed_degree_earned_ects"] == 4
    assert body["categories"][0]["validation_status"] == "ADJUSTED"
    assert body["course_groups"][0]["effective_status"] == "COMPLETED"
    assert body["applied_decisions"][0]["action"] == "ENTER_FINAL_GRADE"


def test_enter_final_grade_action_requires_a_numeric_grade():
    response = TestClient(app).post(
        "/api/student-input/preview",
        json={
            "text": PAST_UNGRADED_TEXT,
            "current_term": "FALL2026",
            "decisions": [{
                "issue_code": "PAST_UNGRADED_ATTEMPT",
                "attempt_id": "attempt-1",
                "action": "ENTER_FINAL_GRADE",
            }],
        },
    )

    assert response.status_code == 422


def test_reviewer_can_attach_a_zero_credit_lab_to_its_catalog_parent():
    client = TestClient(app)
    initial = client.post(
        "/api/student-input/preview",
        json={"text": LAB_PARENT_REVIEW_TEXT, "current_term": "FALL2026"},
    ).json()
    issue = next(
        issue for issue in initial["review_issues"]
        if issue["code"] == "LAB_PARENT_MISSING"
    )

    response = client.post(
        "/api/student-input/preview",
        json={
            "text": LAB_PARENT_REVIEW_TEXT,
            "current_term": "FALL2026",
            "decisions": [{
                "issue_code": issue["code"],
                "attempt_id": issue["attempt_id"],
                "action": "ATTACH_LAB_TO_PARENT",
            }],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_issues"] == []
    assert body["can_continue_without_review"] is True
    group = next(group for group in body["course_groups"] if "CCE341" in group["codes"])
    assert len(group["components"]) == 1
    assert group["components"][0]["parent_attempt_id"] is not None
    assert body["applied_decisions"][0]["action"] == "ATTACH_LAB_TO_PARENT"
    assert "Analog Electronics I (CCE341)" in body["applied_decisions"][0]["summary"]


def test_lab_can_attach_to_an_old_code_parent_through_verified_equivalency():
    client = TestClient(app)
    initial = client.post(
        "/api/student-input/preview",
        json={"text": LAB_EQUIVALENT_PARENT_TEXT, "current_term": "FALL2026"},
    ).json()
    issue = next(
        issue for issue in initial["review_issues"]
        if issue["code"] == "LAB_PARENT_MISSING"
    )

    body = client.post(
        "/api/student-input/preview",
        json={
            "text": LAB_EQUIVALENT_PARENT_TEXT,
            "current_term": "FALL2026",
            "decisions": [{
                "issue_code": issue["code"],
                "attempt_id": issue["attempt_id"],
                "action": "ATTACH_LAB_TO_PARENT",
            }],
        },
    ).json()

    group = next(group for group in body["course_groups"] if group["display_code"] == "CCE441")
    assert group["components"][0]["source_code"] == "CCE441L"
    assert group["components"][0]["parent_attempt_id"] is not None
    assert body["review_issues"] == []
    summary = body["applied_decisions"][0]["summary"]
    assert "Computer Architecture (CCE441)" in summary
    assert "Computer Architecture (ELCC632)" in summary


def test_reviewer_can_keep_an_unattached_lab_for_audit_only():
    client = TestClient(app)
    initial = client.post(
        "/api/student-input/preview",
        json={"text": LAB_PARENT_REVIEW_TEXT, "current_term": "FALL2026"},
    ).json()
    issue = next(
        issue for issue in initial["review_issues"]
        if issue["code"] == "LAB_PARENT_MISSING"
    )

    body = client.post(
        "/api/student-input/preview",
        json={
            "text": LAB_PARENT_REVIEW_TEXT,
            "current_term": "FALL2026",
            "decisions": [{
                "issue_code": issue["code"],
                "attempt_id": issue["attempt_id"],
                "action": "KEEP_LAB_FOR_AUDIT",
            }],
        },
    ).json()

    audit_group = next(
        group for group in body["course_groups"]
        if group["mapping_status"] == "TRANSCRIPT_AUDIT"
    )
    assert audit_group["effective_status"] == "AUDIT_ONLY"
    assert body["review_issues"] == []
    assert body["can_continue_without_review"] is True


def test_reviewer_can_ignore_an_unattached_lab_row():
    client = TestClient(app)
    initial = client.post(
        "/api/student-input/preview",
        json={"text": LAB_PARENT_REVIEW_TEXT, "current_term": "FALL2026"},
    ).json()
    issue = next(
        issue for issue in initial["review_issues"]
        if issue["code"] == "LAB_PARENT_MISSING"
    )

    body = client.post(
        "/api/student-input/preview",
        json={
            "text": LAB_PARENT_REVIEW_TEXT,
            "current_term": "FALL2026",
            "decisions": [{
                "issue_code": issue["code"],
                "attempt_id": issue["attempt_id"],
                "action": "IGNORE_LAB_ROW",
            }],
        },
    ).json()

    assert body["lab_components"] == 0
    assert body["review_issues"] == []
    assert body["can_continue_without_review"] is True


def test_reviewer_can_accept_parsed_category_and_overall_credit_totals():
    client = TestClient(app)
    initial = client.post(
        "/api/student-input/preview",
        json={"text": TOTAL_MISMATCH_TEXT, "current_term": "FALL2026"},
    ).json()
    issues = {issue["code"]: issue for issue in initial["review_issues"]}

    assert issues["CATEGORY_TOTAL_MISMATCH"]["attempt_id"].startswith("category:")
    assert issues["CREDIT_TOTAL_MISMATCH"]["attempt_id"] == "credit-ledger"
    response = client.post(
        "/api/student-input/preview",
        json={
            "text": TOTAL_MISMATCH_TEXT,
            "current_term": "FALL2026",
            "decisions": [
                {
                    "issue_code": "CATEGORY_TOTAL_MISMATCH",
                    "attempt_id": issues["CATEGORY_TOTAL_MISMATCH"]["attempt_id"],
                    "action": "ACCEPT_PARSED_CATEGORY_TOTAL",
                },
                {
                    "issue_code": "CREDIT_TOTAL_MISMATCH",
                    "attempt_id": issues["CREDIT_TOTAL_MISMATCH"]["attempt_id"],
                    "action": "ACCEPT_PARSED_CREDIT_TOTAL",
                },
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_issues"] == []
    assert body["can_continue_without_review"] is True
    assert body["categories"][0]["validation_status"] == "ADJUSTED"
    assert body["categories"][0]["reported_earned_ects"] == 3
    assert body["credit_check"]["status"] == "ADJUSTED"
    assert body["credit_check"]["reported_earned_ects"] == 3
    assert body["credit_check"]["difference"] == 0
    assert {item["action"] for item in body["applied_decisions"]} == {
        "ACCEPT_PARSED_CATEGORY_TOTAL", "ACCEPT_PARSED_CREDIT_TOTAL",
    }


def test_transcript_status_credit_exclusions_and_current_registration_are_authoritative():
    response = TestClient(app).post(
        "/api/student-input/preview",
        json={"text": TRANSCRIPT_TRUTH_TEXT, "current_term": "FALL2026"},
    )

    assert response.status_code == 200
    body = response.json()
    attempts = {
        attempt["source_code"]: attempt
        for group in body["course_groups"]
        for attempt in group["attempts"]
    }
    groups = {
        source_code: group
        for group in body["course_groups"]
        for source_code in group["codes"]
    }

    assert attempts["CHM224"]["status"] == "PASSED"
    assert attempts["ELCM122"]["status"] == "PASSED"
    assert attempts["ENG107"]["status"] == "PASSED"
    assert attempts["ENG107"]["counts_toward_degree_credit"] is False
    assert attempts["ENG107"]["counts_toward_gpa"] is False
    assert attempts["ENG107"]["earned_ects"] == 0
    assert groups["ENG107"]["mapping_status"] == "TRANSCRIPT_EXCLUDED"
    assert groups["CCE550"]["currently_registered"] is True
    assert body["currently_registered_courses"] == 1
    assert body["lab_components"] == 1
    assert body["credit_check"]["status"] == "MATCH"
    assert body["credit_check"]["parsed_degree_earned_ects"] == 8
    assert all(category["validation_status"] == "MATCH" for category in body["categories"])
    assert body["review_issues"] == []


def test_student_input_page_and_preview_endpoint_are_available():
    client = TestClient(app)
    page = client.get("/student-input")
    assert page.status_code == 200
    assert "Paste the Contract Sheet" in page.text
    assert "Student Workspace" in page.text
    assert "Analyze and plan" in page.text
    assert 'id="planning-options-panel"' in page.text
    assert 'id="print-analysis"' in page.text
    assert 'id="timetable-panel"' in page.text
    assert 'id="analysis-print-notes"' in page.text

    script = client.get("/student-input-assets/student-input.js")
    assert script.status_code == 200
    assert "per_semester_capacity_overrides" in script.text
    assert "academic_year_deviation_weight" in script.text
    assert "allow_training_postponement" in script.text
    assert "enable_course_selection_diagnostics" in script.text
    assert "exploratory_recognition" in script.text
    assert "renderStudentTimetableGrid(currentMeetings, 0.5)" in script.text
    assert "courseLabel(item.course.title, item.course.code)" in script.text
    assert 'querySelectorAll("#future-plan-panel details.term-card")' in script.text
    assert "LAB_PARENT_MISSING" in script.text
    assert "ATTACH_LAB_TO_PARENT" in script.text
    assert "CATEGORY_TOTAL_MISMATCH" in script.text
    assert "ACCEPT_PARSED_CREDIT_TOTAL" in script.text
    assert "preview_token: preview.preview_token" in script.text
    assert "reviewDecisions = [];" in script.text
    assert "...(data.solver?.explanations || [])" in script.text
    assert "This exception has no safe automatic action" in script.text

    styles = client.get("/student-input-assets/student-input.css")
    assert styles.status_code == 200
    assert "@page { size: landscape; margin: 9mm; }" in styles.text
    assert "#current-plan-panel, #plan-warnings, .audit-details { display: none !important; }" in styles.text
    assert "#future-plan-panel { break-before: page; page-break-before: always; }" in styles.text

    response = client.post(
        "/api/student-input/preview",
        json={"text": MULTI_ATTEMPT_TEXT, "current_term": "FALL2026"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["persistence"] == "PREVIEW_ONLY"
    assert body["duplicate_attempts_merged"] == 1
    assert body["lab_components"] == 1
    assert body["credit_check"]["status"] == "MATCH"
    assert body["review_issues"] == []


def test_failed_old_code_and_passed_new_equivalent_form_completed_group():
    text = """
EN
Contract Sheet | 42 - Equivalency Student
ELCC - Computer and Communication Engineering L - Bachelor Degree 2000-01-01
ELCC-L-1 - Bachelor Degree - Computer and Communication Engineering Total Earned Credits : 5 Credits
The total number of credits needed to graduate is 300 credits (ECTS)
The Passing Grade For GER and Common Core courses Emphasis courses and Capstone, is 60/100.
Common Core
#  Course Code  Course Title  Credits  Semester  Grade
1  MAT331  Differential Equation and Vector Analysis  5  FALL2025
D+ - 64
Required Credits! 67  Earned Credits! 5  Passing Grade! 60
Courses Not in Contract Sheet
#  Course Code  Course Title  Credits  Semester  Grade
1  ELCM317  Differential Equation and Vector Analysis  5  FALL2023
F - 37 To be repeated
Earned Credits! 0
"""
    response = TestClient(app).post(
        "/api/student-input/preview", json={"text": text, "current_term": "FALL2026"}
    )

    assert response.status_code == 200
    body = response.json()
    group = next(group for group in body["course_groups"] if "ELCM317" in group["codes"])
    assert group["codes"] == ["ELCM317", "MAT331"]
    assert group["effective_status"] == "COMPLETED"
    assert group["unresolved_failed"] is False
    assert body["failed_outstanding_courses"] == 0


def test_verified_preview_can_be_saved_and_current_registration_can_be_locked():
    text = TRANSCRIPT_TRUTH_TEXT.replace(
        "Contract Sheet | 43 - Transcript Truth Student",
        "Contract Sheet | 990001 - Workspace Student",
    )
    identifier = "student_990001"
    try:
        with TestClient(app) as client:
            preview = client.post("/api/student-input/preview", json={
                "text": text,
                "current_term": "FALL2026",
            }).json()
            saved = client.post("/api/student-input/commit", json={
                "text": text,
                "current_term": "FALL2026",
                "preview_token": preview["preview_token"],
            })
            assert saved.status_code == 200, saved.text
            assert saved.json()["identifier"] == identifier
            assert saved.json()["currently_registered_courses"] == 1
            assert saved.json()["recommended_registration_mode"] == "KEEP_CURRENT"
            with SessionLocal() as session:
                student = session.scalar(select(StudentRecord).where(
                    StudentRecord.identifier == identifier
                ))
                credit_attempts = list(session.scalars(
                    select(StudentAttemptRecord).where(
                        StudentAttemptRecord.student_id == student.id,
                        StudentAttemptRecord.counts_toward_degree_credit.is_(True),
                    )
                ))
                assert credit_attempts
                assert all(row.credit_identity for row in credit_attempts)

            conflict = client.post("/api/student-input/commit", json={
                "text": text,
                "current_term": "FALL2026",
                "preview_token": preview["preview_token"],
            })
            assert conflict.status_code == 409
            assert conflict.json()["detail"]["code"] == "STUDENT_EXISTS"

            replaced = client.post("/api/student-input/commit", json={
                "text": text,
                "current_term": "FALL2026",
                "preview_token": preview["preview_token"],
                "replace_existing": True,
            })
            assert replaced.status_code == 200, replaced.text
            assert replaced.json()["replaced_existing"] is True
    finally:
        with SessionLocal.begin() as session:
            session.execute(delete(StudentRecord).where(
                StudentRecord.identifier == identifier
            ))


def test_reviewed_old_new_lab_component_is_safe_for_the_planning_engine():
    text = LAB_EQUIVALENT_PARENT_TEXT.replace(
        "Contract Sheet | 44 - Equivalent Lab Student",
        "Contract Sheet | 990002 - Engine Safe Lab Student",
    )
    identifier = "student_990002"
    try:
        with TestClient(app) as client:
            initial = client.post("/api/student-input/preview", json={
                "text": text,
                "current_term": "FALL2026",
            }).json()
            issue = next(
                item for item in initial["review_issues"]
                if item["code"] == "LAB_PARENT_MISSING"
            )
            saved = client.post("/api/student-input/commit", json={
                "text": text,
                "current_term": "FALL2026",
                "preview_token": initial["preview_token"],
                "decisions": [{
                    "issue_code": issue["code"],
                    "attempt_id": issue["attempt_id"],
                    "action": "ATTACH_LAB_TO_PARENT",
                }],
            })
            assert saved.status_code == 200, saved.text

        summary = DatabaseStudentPlanningService(identifier).scenario_summary()
        assert summary.identifier == identifier
        assert summary.completed_credits == 5
    finally:
        with SessionLocal.begin() as session:
            session.execute(delete(StudentRecord).where(
                StudentRecord.identifier == identifier
            ))


def test_fresh_public_seed_can_plan_a_completed_legacy_transcript():
    """Synthetic filler rows must never become transcript graduation blockers."""
    identifier = "student_990003"
    with SessionLocal() as session:
        mandatory = list(session.scalars(
            select(CourseRecord)
            .join(DegreeRequirement, DegreeRequirement.course_id == CourseRecord.id)
            .join(
                CurriculumRevision,
                CurriculumRevision.id == CourseRecord.curriculum_id,
            )
            .where(
                CurriculumRevision.version == "OLD",
                CurriculumRevision.revision == "synthetic-demo",
            )
            .order_by(CourseRecord.code)
        ))
    assert mandatory
    assert all(not course.code.startswith("SYN-") for course in mandatory)
    assert all(course.code != "ENG108" for course in mandatory)

    earned = sum(course.ects for course in mandatory if course.code != "ELCM900")
    rows = []
    for index, course in enumerate(mandatory, 1):
        current = course.code == "ELCM900"
        term = "FALL2026" if current else "SPRING2026"
        grade = "- 0" if current else "A - 90"
        rows.append(
            f"{index}  {course.code}  {course.title}  {course.ects}  {term}\n{grade}"
        )
    text = f"""
EN
Contract Sheet | 990003 - Seed Transcript Student
ELCC - Computer and Communication Engineering L - Bachelor Degree 2000-01-01
ELCC-L-1 - Bachelor Degree - Computer and Communication Engineering Total Earned Credits : {earned} Credits
The total number of credits needed to graduate is 300 credits (ECTS)
The Passing Grade For GER and Common Core courses Emphasis courses and Capstone, is 60/100.
Courses Not in Contract Sheet
#  Course Code  Course Title  Credits  Semester  Grade
{chr(10).join(rows)}
Earned Credits! {earned}
"""
    try:
        with TestClient(app) as client:
            preview = client.post("/api/student-input/preview", json={
                "text": text,
                "current_term": "FALL2026",
            })
            assert preview.status_code == 200, preview.text
            preview_body = preview.json()
            assert preview_body["can_continue_without_review"] is True
            saved = client.post("/api/student-input/commit", json={
                "text": text,
                "current_term": "FALL2026",
                "preview_token": preview_body["preview_token"],
            })
            assert saved.status_code == 200, saved.text

            plan = client.post("/api/plan", json={
                "scenario_id": identifier,
                "registration_mode": "KEEP_CURRENT",
                "solver_time_limit_seconds": 5,
            })
            assert plan.status_code == 200, plan.text
            body = plan.json()
            assert body["solver"]["status"] in {
                "OPTIMAL", "FEASIBLE_NOT_PROVEN_OPTIMAL",
            }
            assert all(
                not course["code"].startswith("SYN-")
                for course in body["mandatory_outstanding"]
            )
    finally:
        with SessionLocal.begin() as session:
            session.execute(delete(StudentRecord).where(
                StudentRecord.identifier == identifier
            ))

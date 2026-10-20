"""Request and response contracts for the student-input preview."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


ReviewAction = Literal[
    "ENTER_FINAL_GRADE",
    "COMPLETED_GRADE_PENDING",
    "WITHDRAWN",
    "STILL_IN_PROGRESS",
    "NOT_TAKEN",
    "ATTACH_LAB_TO_PARENT",
    "KEEP_LAB_FOR_AUDIT",
    "IGNORE_LAB_ROW",
    "ACCEPT_PARSED_CATEGORY_TOTAL",
    "ACCEPT_PARSED_CREDIT_TOTAL",
    "LEAVE_UNRESOLVED",
]


class ReviewDecisionInput(BaseModel):
    issue_code: str
    attempt_id: str
    action: ReviewAction
    grade_value: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def final_grade_is_required(self) -> "ReviewDecisionInput":
        if self.action == "ENTER_FINAL_GRADE" and self.grade_value is None:
            raise ValueError("A final grade from 0 to 100 is required for this action.")
        return self


class StudentInputPreviewRequest(BaseModel):
    text: str = Field(min_length=20, max_length=250_000)
    current_term: str | None = Field(default=None, pattern=r"^(FALL|SPRING|SUMMERI|SUMMERII|SUMMER)\d{4}$")
    decisions: list[ReviewDecisionInput] = Field(default_factory=list)


class StudentInputCommitRequest(StudentInputPreviewRequest):
    """Validated source snapshot to persist before opening planning analysis."""

    preview_token: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    replace_existing: bool = False


class StudentInputCommitResponse(BaseModel):
    identifier: str
    display_name: str
    created: bool
    replaced_existing: bool
    attempts_saved: int
    currently_registered_courses: int
    current_term: str
    recommended_registration_mode: str


class StudentIdentityPreview(BaseModel):
    student_id: str | None = None
    name: str | None = None
    program_code: str | None = None
    program_title: str | None = None
    date_of_birth: str | None = None
    language_track: str | None = None
    reported_earned_credits: int | None = None
    graduation_target: int | None = None
    passing_grade: int = 60


class CategoryPreview(BaseModel):
    label: str
    required_ects: int | None = None
    reported_earned_ects: int | None = None
    parsed_earned_ects: int | None = None
    validation_status: str = "NOT_CHECKED"


class CatalogMatchPreview(BaseModel):
    course_id: int
    version: str
    code: str
    title: str
    ects: int
    match_kind: str
    selected: bool = False


class AttemptPreview(BaseModel):
    id: str = ""
    source_code: str
    source_title: str
    ects: int
    term: str
    grade_token: str
    grade_value: float | None = None
    note: str | None = None
    status: str
    passing_grade: int = Field(default=60, ge=0, le=100)
    source_sections: list[str] = Field(default_factory=list)
    duplicate_occurrences: int = 1
    counts_toward_degree_credit: bool = True
    counts_toward_gpa: bool = True
    counts_toward_source_subtotal: bool = True
    earned_ects: int = 0
    match_status: str = "UNRESOLVED"
    catalog_matches: list[CatalogMatchPreview] = Field(default_factory=list)
    selected_course_id: int | None = None
    selected_course_code: str | None = None
    selected_curriculum_version: str | None = None
    logical_key: str | None = None
    credit_identity: str | None = None


class ComponentPreview(BaseModel):
    id: str = ""
    source_code: str
    source_title: str
    term: str
    status: str
    note: str | None = None
    parent_code: str
    parent_attempt_id: str | None = None
    source_sections: list[str] = Field(default_factory=list)
    logical_key: str | None = None
    review_disposition: str | None = None


class CourseGroupPreview(BaseModel):
    key: str
    display_code: str
    title: str
    codes: list[str]
    effective_status: str
    mapping_status: str
    completed: bool
    unresolved_failed: bool
    currently_registered: bool
    attempts: list[AttemptPreview]
    components: list[ComponentPreview] = Field(default_factory=list)


class ReviewIssuePreview(BaseModel):
    id: str
    severity: str
    code: str
    message: str
    question: str | None = None
    attempt_id: str | None = None
    options: list[str] = Field(default_factory=list)


class CreditCheckPreview(BaseModel):
    reported_earned_ects: int | None
    parsed_degree_earned_ects: int
    difference: int | None
    status: str
    explanation: str


class AppliedReviewDecisionPreview(BaseModel):
    issue_code: str
    attempt_id: str
    action: str
    course_label: str
    summary: str


class StudentInputPreviewResponse(BaseModel):
    current_term: str
    preview_token: str
    identity: StudentIdentityPreview
    categories: list[CategoryPreview]
    course_groups: list[CourseGroupPreview]
    credit_check: CreditCheckPreview
    review_issues: list[ReviewIssuePreview]
    applied_decisions: list[AppliedReviewDecisionPreview] = Field(default_factory=list)
    attempts_parsed: int
    duplicate_attempts_merged: int
    lab_components: int
    completed_courses: int
    failed_outstanding_courses: int
    currently_registered_courses: int
    can_continue_without_review: bool
    persistence: str = "PREVIEW_ONLY"

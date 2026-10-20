"""Stable request and response contracts for the public planning API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PlanRequest(BaseModel):
    """Request-scoped planner preferences; none of these fields are persisted."""

    scenario_id: str = "fresh"
    regular_credit_capacity: int | None = Field(default=None, ge=1, le=60)
    per_semester_capacity_overrides: dict[str, int] = Field(default_factory=dict)
    academic_year_deviation_weight: int | None = Field(default=None, ge=0, le=1000)
    reference_semester_deviation_weight: int | None = Field(default=None, ge=0, le=1000)
    allow_training_postponement: bool | None = None
    training_delay_penalty: int | None = Field(default=None, ge=0, le=1000)
    max_training_delay_years: int | None = Field(default=None, ge=0, le=10)
    solver_time_limit_seconds: float | None = Field(default=None, gt=0, le=120)
    initial_horizon_semesters: int | None = Field(default=None, ge=1, le=40)
    max_horizon_semesters: int | None = Field(default=None, ge=1, le=40)
    auto_extend_horizon: bool | None = None
    horizon_extension_step: int | None = Field(default=None, ge=1, le=10)
    allow_extended_load_when_repeating_failed_course: bool | None = None
    allow_final_two_semester_graduation_load: bool | None = None
    enable_course_selection_diagnostics: bool = False
    max_diagnostic_courses: int = Field(default=5, ge=0, le=10)
    exploratory_recognition: bool = False
    registration_mode: Literal["KEEP_CURRENT", "REBUILD_CURRENT"] = "REBUILD_CURRENT"

    @model_validator(mode="after")
    def validate_horizon(self) -> "PlanRequest":
        if (
            self.max_horizon_semesters is not None
            and self.initial_horizon_semesters is not None
            and self.max_horizon_semesters < self.initial_horizon_semesters
        ):
            raise ValueError("max_horizon_semesters must be at least initial_horizon_semesters")
        return self


class ScenarioResponse(BaseModel):
    identifier: str
    description: str
    nominal_year: int
    language_track: str
    curriculum_version: str
    starting_term: str
    completed_credits: int
    remaining_credits: int
    available_terms: list[str]
    fixture_prerequisites: str
    fixture_timetable: str
    student_type: str | None = None
    original_reported_earned_credits: int | None = None
    adjusted_source_credits: int | None = None
    training_ii_correction: str | None = None


class CourseResponse(BaseModel):
    id: str
    code: str
    title: str
    credits: int
    reference_year: int
    reference_semester: str
    curriculum_version: str
    provenance: str


class ClassifiedCourseResponse(CourseResponse):
    classification: str
    explanation: str
    credit_category: str | None = None
    approval_status: str | None = None
    approval_authority: str | None = None
    approval_source: str | None = None
    selected_for_graduation: bool = False


class BlockedCourseResponse(CourseResponse):
    reason_code: str
    reason: str
    missing_prerequisites: list[str] = Field(default_factory=list)


class MeetingResponse(BaseModel):
    weekday: str
    weekday_index: int
    start_minute: int
    end_minute: int
    start_time: str
    end_time: str


class SectionResponse(BaseModel):
    crn: str
    component: str
    component_credits: int
    campus: str
    instructor: str | None = None
    room: str | None = None
    provenance: str
    teaching_language: str | None = None
    cross_track: bool = False
    meetings: list[MeetingResponse]


class SelectedCourseResponse(CourseResponse):
    bundle_id: str | None = None
    sections: list[SectionResponse] = Field(default_factory=list)


class CurrentSemesterResponse(BaseModel):
    term: str
    total_credits: int
    selected_courses: list[SelectedCourseResponse]
    has_meeting_data: bool
    effective_credit_capacity: int
    credit_capacity_reason: str
    repeated_course_codes: list[str] = Field(default_factory=list)


class FutureSemesterResponse(BaseModel):
    term: str
    period_type: str
    status: str
    total_credits: int
    courses: list[CourseResponse]
    effective_credit_capacity: int
    credit_capacity_reason: str
    repeated_course_codes: list[str] = Field(default_factory=list)


class CourseSelectionDiagnosticResponse(BaseModel):
    course_id: str
    course_code: str
    status: str
    detail: str
    counterfactual_graduation_term: str | None = None
    conflicts_with_selected_course_codes: list[str] = Field(default_factory=list)
    would_exceed_current_cap_if_added_without_changes: bool = False


class PlanResponse(BaseModel):
    """Complete planner payload rendered by the dashboard and print view."""

    scenario: dict[str, Any]
    student: dict[str, Any]
    configuration: dict[str, Any]
    academic_summary: dict[str, Any]
    eligible_pool: list[CourseResponse]
    eligible_pool_total_credits: int
    blocked_courses: list[BlockedCourseResponse]
    course_selection_diagnostics: list[CourseSelectionDiagnosticResponse] = Field(default_factory=list)
    current_semester: CurrentSemesterResponse | None
    future_semesters: list[FutureSemesterResponse]
    graduation: dict[str, Any]
    solver: dict[str, Any]
    warnings: list[str]
    transition_diagnostics: dict[str, Any] | None = None
    mandatory_outstanding: list[ClassifiedCourseResponse] = Field(default_factory=list)
    satisfied_requirements: list[ClassifiedCourseResponse] = Field(default_factory=list)
    approved_optional_candidates: list[ClassifiedCourseResponse] = Field(default_factory=list)
    registration_only_courses: list[ClassifiedCourseResponse] = Field(default_factory=list)
    courses_needing_review: list[ClassifiedCourseResponse] = Field(default_factory=list)
    graduation_credit_breakdown: dict[str, Any] = Field(default_factory=dict)

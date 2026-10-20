from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CourseWrite(BaseModel):
    curriculum_id: int
    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=255)
    ects: int = Field(ge=0, le=60)
    reference_year: int = Field(ge=1, le=5)
    reference_semester: Literal["FALL", "SPRING", "TRAINING_1", "TRAINING_2"]
    course_type: str = "COURSE"
    is_fyp: bool = False
    notes: str | None = None
    verification_status: str = "UNVERIFIED"
    academic_track_policy: Literal["SHARED", "TRACK_SPECIFIC", "UNCLASSIFIED"] = "UNCLASSIFIED"
    permitted_student_tracks: list[Literal["EN", "FR"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def track_policy(self):
        if self.academic_track_policy == "TRACK_SPECIFIC" and len(self.permitted_student_tracks) != 1:
            raise ValueError("track-specific courses require exactly one permitted student track")
        if self.academic_track_policy == "SHARED" and not self.permitted_student_tracks:
            self.permitted_student_tracks = ["EN", "FR"]
        if self.academic_track_policy == "UNCLASSIFIED":
            self.permitted_student_tracks = []
        return self


class PrerequisiteWrite(BaseModel):
    logic: Literal["AND", "OR"] = "AND"
    prerequisite_course_ids: list[int]
    ambiguous: bool = False


class EquivalencyWrite(BaseModel):
    source_course_id: int
    target_course_id: int
    recognizes_history: bool = True
    prospective_registration_allowed: bool | None = None
    verification_status: str = "UNVERIFIED"
    notes: str | None = None

    @model_validator(mode="after")
    def distinct(self):
        if self.source_course_id == self.target_course_id:
            raise ValueError("equivalency courses must be distinct")
        return self


class ActiveTermWrite(BaseModel):
    academic_year_start: int = Field(ge=2000, le=2200)
    semester: Literal["FALL", "SPRING"]
    confirm_replace: bool = False


class MeetingWrite(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(gt=0, le=1440)

    @model_validator(mode="after")
    def interval(self):
        if self.end_minute <= self.start_minute: raise ValueError("end time must be after start time")
        return self


class SectionWrite(BaseModel):
    code: str
    component: str = "LECTURE"
    bundle_key: str = "A"
    campus: str | None = None
    room: str | None = None
    instructor: str | None = None
    notes: str | None = None
    meetings: list[MeetingWrite] = Field(default_factory=list)


class OfferingWrite(BaseModel):
    course_id: int
    language_track: str | None = None
    verification_status: str = "UNVERIFIED"
    sections: list[SectionWrite] = Field(default_factory=list)


class SettingsWrite(BaseModel):
    values: dict[str, Any]


class DatabasePlanRequest(BaseModel):
    curriculum_version: Literal["OLD", "NEW"] = "NEW"
    nominal_year: int = Field(default=1, ge=1, le=5)
    language_track: Literal["EN", "FR"] = "EN"
    earned_credits: int = Field(default=0, ge=0)
    completed_requirement_ids: list[int] = Field(default_factory=list)
    attempts: list[dict[str, Any]] = Field(default_factory=list)


class ImportConfirm(BaseModel):
    confirm_replace: bool = False


class MatchVerify(BaseModel):
    old_course_id: int | None = None
    new_course_id: int | None = None
    verified_by: str = Field(default="LOCAL_ADMIN", min_length=1, max_length=100)


class StudentCourseDecisionWrite(BaseModel):
    decision: Literal[
        "MANDATORY", "APPROVED_OPTIONAL", "UNVERIFIED_OPTIONAL",
        "REJECTED_OPTIONAL", "CLEAR",
    ]
    credit_category: str | None = Field(default=None, max_length=80)
    authority: str | None = Field(default=None, max_length=120)
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    academic_period: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def evidence(self):
        if self.decision == "MANDATORY" and (
            not self.authority or not self.source_reference
        ):
            raise ValueError("mandatory requirements require authority and source reference")
        if self.decision.endswith("OPTIONAL") and not self.credit_category:
            raise ValueError("optional decisions require a credit category")
        if self.decision in {"APPROVED_OPTIONAL", "REJECTED_OPTIONAL"} and (
            not self.authority or not self.source_reference
        ):
            raise ValueError("approved or rejected decisions require authority and source reference")
        return self

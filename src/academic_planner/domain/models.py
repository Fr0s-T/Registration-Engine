"""Immutable domain values shared by academic, scheduling, and web layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class CurriculumVersion(str, Enum):
    OLD = "OLD"
    NEW = "NEW"


class LanguageTrack(str, Enum):
    EN = "EN"
    FR = "FR"


class AcademicTrackPolicy(str, Enum):
    SHARED = "SHARED"
    TRACK_SPECIFIC = "TRACK_SPECIFIC"
    UNCLASSIFIED = "UNCLASSIFIED"


class TermKind(str, Enum):
    FALL = "FALL"
    SPRING = "SPRING"
    TRAINING_1 = "TRAINING_1"
    TRAINING_2 = "TRAINING_2"


class AttemptStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    TRANSFERRED = "TRANSFERRED"
    EXEMPTED = "EXEMPTED"
    REGISTERED = "REGISTERED"
    IN_PROGRESS = "IN_PROGRESS"
    RESULT_PENDING = "RESULT_PENDING"
    WITHDRAWN = "WITHDRAWN"

    @property
    def satisfies_requirement(self) -> bool:
        return self in {self.PASSED, self.TRANSFERRED, self.EXEMPTED}


class DataProvenance(str, Enum):
    UNSPECIFIED = "UNSPECIFIED"
    USER_SUPPLIED = "USER_SUPPLIED"
    SYNTHETIC_UNVERIFIED = "SYNTHETIC_UNVERIFIED"
    SYNTHETIC_PLACEHOLDER = "SYNTHETIC_PLACEHOLDER"


class RequirementClassification(str, Enum):
    MANDATORY_OUTSTANDING = "MANDATORY_OUTSTANDING"
    SATISFIED = "SATISFIED"
    APPROVED_OPTIONAL = "APPROVED_OPTIONAL"
    REGISTRATION_ONLY = "REGISTRATION_ONLY"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ApprovalStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Weekday(int, Enum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


@dataclass(frozen=True, order=True)
class AcademicTerm:
    academic_year_start: int
    kind: TermKind

    @property
    def is_regular(self) -> bool:
        return self.kind in {TermKind.FALL, TermKind.SPRING}

    def label(self) -> str:
        return f"{self.academic_year_start}-{self.academic_year_start + 1} {self.kind.value}"


@dataclass(frozen=True)
class Course:
    id: str
    code: str
    name: str
    credits: int
    curriculum_version: CurriculumVersion
    reference_year: int
    reference_semester: TermKind
    is_fyp: bool = False
    provenance: DataProvenance = DataProvenance.UNSPECIFIED
    academic_track_policy: AcademicTrackPolicy = AcademicTrackPolicy.UNCLASSIFIED
    permitted_student_tracks: frozenset[LanguageTrack] = frozenset()

    def __post_init__(self) -> None:
        if not self.id or not self.code:
            raise ValueError("course id and code are required")
        if self.credits < 0:
            raise ValueError("course credits cannot be negative")
        if not 1 <= self.reference_year <= 5:
            raise ValueError("reference year must be in 1..5")
        if self.reference_semester not in set(TermKind):
            raise ValueError("invalid course reference term")


@dataclass(frozen=True)
class Curriculum:
    """A governing graduation contract, not a registration-course pool."""

    version: CurriculumVersion
    requirement_ids: frozenset[str]
    accepted_credit_target: int = 300
    fyp_requirement_id: str | None = None
    training_requirement_ids: frozenset[str] = frozenset()
    language_requirements: Mapping[LanguageTrack, frozenset[str]] = field(default_factory=dict)

    def resolved_requirements(self, track: LanguageTrack) -> frozenset[str]:
        """Select one language-track branch while preserving shared requirements."""
        language_ids = frozenset().union(*self.language_requirements.values()) if self.language_requirements else frozenset()
        return (self.requirement_ids - language_ids) | self.language_requirements.get(track, frozenset())


@dataclass(frozen=True)
class PrerequisiteRule:
    course_id: str
    all_of: frozenset[str] = frozenset()
    provenance: DataProvenance = DataProvenance.UNSPECIFIED


@dataclass(frozen=True)
class CourseEquivalency:
    id: str
    source_course_ids: frozenset[str]
    target_requirement_ids: frozenset[str]
    provenance: DataProvenance = DataProvenance.UNSPECIFIED
    prospective_registration_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.source_course_ids or not self.target_requirement_ids:
            raise ValueError("equivalency sides cannot be empty")


@dataclass(frozen=True)
class OptionalCreditApproval:
    """Student-scoped authorization for a course to contribute optional degree credit."""
    course_id: str
    category: str
    status: ApprovalStatus
    authority: str | None = None
    source_reference: str | None = None
    notes: str | None = None
    academic_period: str | None = None

    @property
    def sufficiently_documented(self) -> bool:
        return bool(self.authority and self.source_reference)


@dataclass(frozen=True)
class CreditRequirementGroup:
    """A bounded set of courses that must contribute a source-defined ECTS quota."""

    code: str
    title: str
    required_credits: int
    course_credits: Mapping[str, int]
    recognized_credits: int = 0

    def __post_init__(self) -> None:
        if not self.code or self.required_credits < 0 or self.recognized_credits < 0:
            raise ValueError("invalid credit requirement group")
        if any(value < 0 for value in self.course_credits.values()):
            raise ValueError("group contribution credits cannot be negative")


@dataclass(frozen=True)
class CourseAttempt:
    """One transcript attempt with source credit kept separate from recognition."""

    course_id: str
    term: AcademicTerm
    status: AttemptStatus
    grade: float | None = None
    earned_credits: int = 0
    # Stable source identity for credit accounting. Multiple historical codes
    # may satisfy one modern requirement without collapsing their earned credit.
    credit_identity: str | None = None

    def __post_init__(self) -> None:
        if self.earned_credits < 0:
            raise ValueError("earned credits cannot be negative")


@dataclass(frozen=True)
class StudentAcademicState:
    """Planning-ready student facts after source normalization."""

    nominal_year: int
    language_track: LanguageTrack
    attempts: tuple[CourseAttempt, ...] = ()
    completed_requirement_ids: frozenset[str] = frozenset()
    earned_credits: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.nominal_year <= 5 or self.earned_credits < 0:
            raise ValueError("invalid nominal year or earned credits")


@dataclass(frozen=True)
class Meeting:
    weekday: Weekday
    start_minute: int
    end_minute: int

    def __post_init__(self) -> None:
        if not 0 <= self.start_minute < self.end_minute <= 24 * 60:
            raise ValueError("invalid meeting interval")

    def overlaps(self, other: Meeting) -> bool:
        return self.weekday == other.weekday and self.start_minute < other.end_minute and other.start_minute < self.end_minute


@dataclass(frozen=True)
class Section:
    crn: str
    course_id: str
    component: str
    campus: str
    meetings: tuple[Meeting, ...]
    grade_weight: float | None = None
    provenance: DataProvenance = DataProvenance.UNSPECIFIED
    teaching_language: LanguageTrack | None = None


@dataclass(frozen=True)
class RegistrationBundle:
    id: str
    course_id: str
    sections: tuple[Section, ...]

    def __post_init__(self) -> None:
        if not self.sections or any(s.course_id != self.course_id for s in self.sections):
            raise ValueError("bundle sections must belong to its course")


@dataclass(frozen=True)
class CourseOffering:
    course_id: str
    term: AcademicTerm
    bundles: tuple[RegistrationBundle, ...] = ()
    availability_verified: bool = True
    provenance: DataProvenance = DataProvenance.UNSPECIFIED


@dataclass(frozen=True)
class PlanningConfiguration:
    """Solver horizon, capacity rules, policy toggles, and soft weights."""

    term_credit_capacities: Mapping[AcademicTerm, int] = field(default_factory=dict)
    default_credit_capacity: int = 30
    planning_horizon: tuple[AcademicTerm, ...] = ()
    time_limit_seconds: float = 20.0
    academic_year_deviation_weight: int = 10
    reference_semester_deviation_weight: int = 2
    allow_training_postponement: bool = True
    training_delay_penalty: int = 10
    max_training_delay_years: int | None = None
    initial_horizon_semesters: int = 10
    max_horizon_semesters: int = 20
    auto_extend_horizon: bool = True
    horizon_extension_step: int = 2
    allow_extended_load_when_repeating_failed_course: bool = False
    extended_failed_repeat_capacity: int = 36
    allow_final_two_semester_graduation_load: bool = False
    final_two_semester_graduation_capacity: int = 36
    explicit_capacity_override_terms: frozenset[AcademicTerm] = frozenset()
    forced_course_terms: Mapping[str, AcademicTerm] = field(default_factory=dict)
    # A narrower subset of forced assignments backed by observed enrollment.
    # These bypass prospective registration checks because the student is
    # already enrolled; diagnostic/user-forced experiments remain unchanged.
    authoritative_course_terms: Mapping[str, AcademicTerm] = field(default_factory=dict)
    # When a term is present, its value is the complete permitted roster for
    # that term. This is used to plan around an observed registration without
    # treating any of those courses as already passed.
    locked_term_course_ids: Mapping[AcademicTerm, frozenset[str]] = field(default_factory=dict)
    allow_cross_track_shared_sections: bool = False
    prefer_own_track_sections: bool = True

    def __post_init__(self) -> None:
        if self.default_credit_capacity < 0 or any(v < 0 for v in self.term_credit_capacities.values()):
            raise ValueError("credit capacities cannot be negative")
        if self.time_limit_seconds <= 0:
            raise ValueError("solver time limit must be positive")
        if self.academic_year_deviation_weight < 0 or self.reference_semester_deviation_weight < 0:
            raise ValueError("academic alignment weights cannot be negative")
        if self.training_delay_penalty < 0:
            raise ValueError("training delay penalty cannot be negative")
        if self.max_training_delay_years is not None and self.max_training_delay_years < 0:
            raise ValueError("maximum training delay cannot be negative")
        if self.initial_horizon_semesters <= 0 or self.max_horizon_semesters <= 0:
            raise ValueError("planning horizon semester counts must be positive")
        if self.max_horizon_semesters < self.initial_horizon_semesters:
            raise ValueError("maximum horizon cannot be shorter than the initial horizon")
        if self.horizon_extension_step <= 0:
            raise ValueError("horizon extension step must be positive")
        if self.extended_failed_repeat_capacity < self.default_credit_capacity:
            raise ValueError("extended failed-repeat capacity cannot be below the regular capacity")
        if self.final_two_semester_graduation_capacity < self.default_credit_capacity:
            raise ValueError("final-two-semester capacity cannot be below the regular capacity")

    def capacity_for(self, term: AcademicTerm) -> int:
        return self.term_credit_capacities.get(term, self.default_credit_capacity)


class SolverStatus(str, Enum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE_NOT_PROVEN_OPTIMAL = "FEASIBLE_NOT_PROVEN_OPTIMAL"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ScheduledTerm:
    term: AcademicTerm
    course_ids: tuple[str, ...]
    bundle_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TermCreditUsage:
    term: AcademicTerm
    selected_credits: int
    effective_capacity: int
    reason: str
    repeated_course_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CreditAdjustmentProposal:
    """Unapproved administrative placeholder for a transition-credit deficit."""

    credits: int
    term: AcademicTerm
    reason: str


@dataclass(frozen=True)
class GraduationPlan:
    """Solver result plus the academic warnings and capacity audit used by clients."""

    status: SolverStatus
    scheduled_terms: tuple[ScheduledTerm, ...] = ()
    graduation_term: AcademicTerm | None = None
    explanations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    credit_usages: tuple[TermCreditUsage, ...] = ()
    selected_optional_course_ids: tuple[str, ...] = ()
    hypothetical: bool = False
    credit_adjustment_proposal: CreditAdjustmentProposal | None = None

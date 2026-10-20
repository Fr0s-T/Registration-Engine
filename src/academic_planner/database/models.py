"""SQLAlchemy persistence model for catalog, student, and import state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


def _utc_now() -> datetime:
    """Return naive UTC for existing timezone-naive database columns."""
    return datetime.now(UTC).replace(tzinfo=None)


class CurriculumRevision(Base):
    __tablename__ = "curriculum_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(12))
    revision: Mapped[str] = mapped_column(String(60), default="default")
    accepted_credit_target: Mapped[int] = mapped_column(Integer, default=300)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    courses: Mapped[list[CourseRecord]] = relationship(back_populates="curriculum")
    __table_args__ = (UniqueConstraint("version", "revision"),)


class SourceDocument(Base):
    __tablename__ = "source_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(30), default="OTHER")
    sha256: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING_REVIEW")
    notes: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class CourseRecord(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    curriculum_id: Mapped[int] = mapped_column(ForeignKey("curriculum_revisions.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(255))
    ects: Mapped[int] = mapped_column(Integer)
    reference_year: Mapped[int] = mapped_column(Integer)
    reference_semester: Mapped[str] = mapped_column(String(20))
    course_type: Mapped[str] = mapped_column(String(40), default="COURSE")
    is_fyp: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(String(40), default="MANUAL_CORRECTION")
    verification_status: Mapped[str] = mapped_column(String(30), default="UNVERIFIED")
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    source_locator: Mapped[str | None] = mapped_column(String(255))
    academic_track_policy: Mapped[str] = mapped_column(String(30), default="UNCLASSIFIED")
    permitted_student_tracks: Mapped[Any] = mapped_column(JSON, default=list)
    graduation_role: Mapped[str] = mapped_column(String(30), default="NEEDS_REVIEW")
    graduation_role_basis: Mapped[str] = mapped_column(
        String(80), default="USER_CONFIRMED_CREDIT_BAND_RULE"
    )
    curriculum: Mapped[CurriculumRevision] = relationship(back_populates="courses")
    __table_args__ = (
        UniqueConstraint("curriculum_id", "code"),
        CheckConstraint("ects >= 0"),
        CheckConstraint("reference_year BETWEEN 1 AND 5"),
        CheckConstraint("reference_semester IN ('FALL','SPRING','TRAINING_1','TRAINING_2')"),
        CheckConstraint("academic_track_policy IN ('SHARED','TRACK_SPECIFIC','UNCLASSIFIED')"),
        CheckConstraint("graduation_role IN ('MANDATORY','OPTIONAL','NEEDS_REVIEW')"),
    )


class DegreeRequirement(Base):
    __tablename__ = "degree_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    curriculum_id: Mapped[int] = mapped_column(ForeignKey("curriculum_revisions.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    language_track: Mapped[str | None] = mapped_column(String(8))
    requirement_type: Mapped[str] = mapped_column(String(30), default="COURSE")
    __table_args__ = (UniqueConstraint("curriculum_id", "course_id", "language_track"),)


class DegreeContract(Base):
    """Versioned, source-backed graduation contract for one program."""

    __tablename__ = "degree_contracts"
    id: Mapped[int] = mapped_column(primary_key=True)
    curriculum_id: Mapped[int] = mapped_column(
        ForeignKey("curriculum_revisions.id", ondelete="CASCADE")
    )
    program_code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(255))
    graduation_ects_target: Mapped[int] = mapped_column(Integer)
    effective_academic_year: Mapped[str] = mapped_column(String(20))
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="SET NULL")
    )
    verification_status: Mapped[str] = mapped_column(
        String(30), default="SOURCE_IMPORTED"
    )
    groups: Mapped[list[RequirementGroupRecord]] = relationship(
        cascade="all, delete-orphan", back_populates="contract"
    )
    __table_args__ = (
        UniqueConstraint("curriculum_id", "program_code", "effective_academic_year"),
        CheckConstraint("graduation_ects_target > 0"),
    )


class RequirementGroupRecord(Base):
    """A fixed or credit-quota node from an official contract sheet."""

    __tablename__ = "requirement_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("degree_contracts.id", ondelete="CASCADE")
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_groups.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(255))
    required_ects: Mapped[int] = mapped_column(Integer)
    rule_type: Mapped[str] = mapped_column(String(30))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    source_locator: Mapped[str | None] = mapped_column(String(255))
    verification_status: Mapped[str] = mapped_column(
        String(30), default="SOURCE_IMPORTED"
    )
    contract: Mapped[DegreeContract] = relationship(back_populates="groups")
    memberships: Mapped[list[RequirementGroupCourseRecord]] = relationship(
        cascade="all, delete-orphan", back_populates="group"
    )
    __table_args__ = (
        UniqueConstraint("contract_id", "code"),
        CheckConstraint("required_ects >= 0"),
        CheckConstraint("rule_type IN ('ALL_OF','CREDIT_QUOTA','TRACK_CHOICE','PATHWAY')"),
    )


class RequirementGroupCourseRecord(Base):
    __tablename__ = "requirement_group_courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_groups.id", ondelete="CASCADE")
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT")
    )
    contribution_ects: Mapped[int] = mapped_column(Integer)
    membership_type: Mapped[str] = mapped_column(String(20))
    language_track: Mapped[str | None] = mapped_column(String(8))
    source_locator: Mapped[str | None] = mapped_column(String(255))
    group: Mapped[RequirementGroupRecord] = relationship(back_populates="memberships")
    __table_args__ = (
        UniqueConstraint("group_id", "course_id"),
        CheckConstraint("contribution_ects >= 0"),
        CheckConstraint("membership_type IN ('REQUIRED','CANDIDATE')"),
        CheckConstraint("language_track IS NULL OR language_track IN ('EN','FR')"),
    )


class CourseRequirementGroupRecognition(Base):
    """Auditable broad-category recognition when no exact course map exists."""

    __tablename__ = "course_requirement_group_recognitions"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE")
    )
    requirement_group_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_groups.id", ondelete="CASCADE")
    )
    recognition_scope: Mapped[str] = mapped_column(
        String(30), default="CATEGORY_CREDIT"
    )
    verification_status: Mapped[str] = mapped_column(
        String(30), default="INFERRED_PROGRAM_STRUCTURE"
    )
    provenance: Mapped[str] = mapped_column(
        String(40), default="OFFICIAL_CONTRACT_CATEGORY_INFERENCE"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("source_course_id", "requirement_group_id"),
        CheckConstraint("recognition_scope = 'CATEGORY_CREDIT'"),
    )


class PrerequisiteGroup(Base):
    __tablename__ = "prerequisite_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    logic: Mapped[str] = mapped_column(String(3), default="AND")
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[str] = mapped_column(String(40), default="MANUAL_CORRECTION")
    source_text: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list[PrerequisiteItem]] = relationship(cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("course_id", name="uq_prerequisite_groups_course_id"),
        CheckConstraint(
            "logic IN ('AND','OR')", name="ck_prerequisite_groups_logic"
        ),
    )


class PrerequisiteItem(Base):
    __tablename__ = "prerequisite_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("prerequisite_groups.id", ondelete="CASCADE"))
    prerequisite_course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    __table_args__ = (UniqueConstraint("group_id", "prerequisite_course_id"),)


class LabRelationship(Base):
    __tablename__ = "lab_relationships"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    lab_course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    source_locator: Mapped[str | None] = mapped_column(String(255))
    __table_args__ = (
        UniqueConstraint("course_id", "lab_course_id"),
        CheckConstraint("course_id <> lab_course_id"),
    )


class Equivalency(Base):
    __tablename__ = "equivalencies"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    target_course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    recognizes_history: Mapped[bool] = mapped_column(Boolean, default=True)
    prospective_registration_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="UNVERIFIED")
    provenance: Mapped[str] = mapped_column(String(40), default="MANUAL_CORRECTION")
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("source_course_id", "target_course_id"),
        CheckConstraint("source_course_id <> target_course_id"),
    )


class TransitionCourseDisposition(Base):
    """Explicit outcome for an OLD course without a direct NEW equivalency."""

    __tablename__ = "transition_course_dispositions"
    id: Mapped[int] = mapped_column(primary_key=True)
    old_course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), unique=True
    )
    disposition: Mapped[str] = mapped_column(String(40))
    verification_status: Mapped[str] = mapped_column(
        String(30), default="CATALOGUE_REVIEWED"
    )
    provenance: Mapped[str] = mapped_column(
        String(40), default="CURATED_TRANSITION_CATALOGUE"
    )
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint(
            "disposition IN ('LEGACY_CREDIT_ONLY','PATHWAY_SPECIFIC')"
        ),
    )


class EquivalencyMatch(Base):
    """Algorithmic or human matching decision, separate from academic recognition."""
    __tablename__ = "equivalency_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    old_course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    new_course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    equivalency_id: Mapped[int | None] = mapped_column(
        ForeignKey("equivalencies.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30))
    method: Mapped[str] = mapped_column(String(40))
    review_reasons: Mapped[Any] = mapped_column(JSON, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    verified_by: Mapped[str | None] = mapped_column(String(100))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    __table_args__ = (
        UniqueConstraint("old_course_id", "new_course_id"),
        CheckConstraint("old_course_id <> new_course_id"),
        CheckConstraint(
            "status IN ('AUTO_MATCHED','NEEDS_REVIEW','HUMAN_VERIFIED','REJECTED')"
        ),
    )


class ActiveTerm(Base):
    __tablename__ = "active_term"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    academic_year_start: Mapped[int] = mapped_column(Integer, default=2026)
    semester: Mapped[str] = mapped_column(String(10), default="FALL")
    generation: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("semester IN ('FALL','SPRING')"),)


class Offering(Base):
    __tablename__ = "offerings"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    academic_year_start: Mapped[int] = mapped_column(Integer)
    semester: Mapped[str] = mapped_column(String(10))
    language_track: Mapped[str | None] = mapped_column(String(8))
    provenance: Mapped[str] = mapped_column(String(40), default="MANUAL_CORRECTION")
    verification_status: Mapped[str] = mapped_column(String(30), default="UNVERIFIED")
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_documents.id"))
    course: Mapped[CourseRecord] = relationship()
    sections: Mapped[list[SectionRecord]] = relationship(cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("course_id", "academic_year_start", "semester", "language_track"),
        CheckConstraint("semester IN ('FALL','SPRING')"),
    )


class SectionRecord(Base):
    __tablename__ = "sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    offering_id: Mapped[int] = mapped_column(ForeignKey("offerings.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(50))
    component: Mapped[str] = mapped_column(String(30), default="LECTURE")
    bundle_key: Mapped[str] = mapped_column(String(50), default="A")
    campus: Mapped[str | None] = mapped_column(String(100))
    room: Mapped[str | None] = mapped_column(String(100))
    instructor: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    meetings: Mapped[list[MeetingRecord]] = relationship(cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("offering_id", "code"),)


class MeetingRecord(Base):
    __tablename__ = "meetings"
    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(Integer)
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6"),
        CheckConstraint("start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute"),
    )


class EngineSetting(Base):
    __tablename__ = "engine_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text, default="")
    unverified_assumption: Mapped[bool] = mapped_column(Boolean, default=False)


class TermCapacityOverride(Base):
    __tablename__ = "term_capacity_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    academic_year_start: Mapped[int] = mapped_column(Integer)
    semester: Mapped[str] = mapped_column(String(20))
    capacity: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("academic_year_start", "semester"),
        CheckConstraint("capacity >= 0 AND capacity <= 60"),
    )


class StudentRecord(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    identifier: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    nominal_year: Mapped[int] = mapped_column(Integer)
    language_track: Mapped[str] = mapped_column(String(8))
    governing_curriculum_version: Mapped[str] = mapped_column(String(10), default="OLD")
    reported_earned_credits: Mapped[int] = mapped_column(Integer)
    graduation_credit_target: Mapped[int] = mapped_column(Integer, default=300)
    degree_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("degree_contracts.id", ondelete="SET NULL"), nullable=True
    )
    passing_grade: Mapped[int] = mapped_column(Integer, default=60)
    # Source snapshot for category-level contract auditing.  It is intentionally
    # separate from course requirements because portal category totals may
    # overlap and therefore cannot safely be treated as additive constraints.
    contract_credit_categories: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    attempts: Mapped[list[StudentAttemptRecord]] = relationship(cascade="all, delete-orphan")
    requirements: Mapped[list[StudentRequirementRecord]] = relationship(cascade="all, delete-orphan")
    recognitions: Mapped[list[StudentRecognitionRecord]] = relationship(cascade="all, delete-orphan")
    capacity_overrides: Mapped[list[StudentCapacityOverride]] = relationship(cascade="all, delete-orphan")
    offering_overrides: Mapped[list[StudentOfferingOverride]] = relationship(cascade="all, delete-orphan")
    optional_credit_approvals: Mapped[list[StudentOptionalCreditApproval]] = relationship(
        cascade="all, delete-orphan"
    )
    __table_args__ = (
        CheckConstraint("nominal_year BETWEEN 1 AND 5"),
        CheckConstraint("language_track IN ('EN','FR')"),
        CheckConstraint("governing_curriculum_version IN ('OLD','NEW')"),
        CheckConstraint("reported_earned_credits >= 0"),
        CheckConstraint("graduation_credit_target > 0"),
    )


class TranscriptCodeMapping(Base):
    """Institution-approved resolution for transcript codes absent from the catalog."""

    __tablename__ = "transcript_code_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_code: Mapped[str] = mapped_column(String(40), unique=True)
    target_course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )
    mapping_kind: Mapped[str] = mapped_column(String(30))
    verification_status: Mapped[str] = mapped_column(String(30), default="HUMAN_VERIFIED")
    provenance: Mapped[str] = mapped_column(String(40), default="SOURCE_REVIEW")
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("mapping_kind IN ('COURSE_ALIAS','NON_DEGREE')"),
        CheckConstraint(
            "(mapping_kind = 'COURSE_ALIAS' AND target_course_id IS NOT NULL) OR "
            "(mapping_kind = 'NON_DEGREE' AND target_course_id IS NULL)"
        ),
    )


class StudentAttemptRecord(Base):
    __tablename__ = "student_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    source_code: Mapped[str] = mapped_column(String(40))
    source_title: Mapped[str | None] = mapped_column(String(255))
    ects: Mapped[int] = mapped_column(Integer)
    source_term: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    grade: Mapped[float | None] = mapped_column(Float)
    earned_credits: Mapped[int] = mapped_column(Integer, default=0)
    counts_toward_degree_credit: Mapped[bool] = mapped_column(Boolean, default=True)
    counts_toward_gpa: Mapped[bool] = mapped_column(Boolean, default=True)
    credit_identity: Mapped[str | None] = mapped_column(String(160), nullable=True)
    evidence_status: Mapped[str] = mapped_column(String(40), default="OFFICIAL_TRANSCRIPT")
    source_value: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("student_id", "source_code", "source_term"),
        CheckConstraint("ects >= 0 AND earned_credits >= 0"),
    )


class StudentRequirementRecord(Base):
    __tablename__ = "student_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    authority: Mapped[str] = mapped_column(String(80), default="LOCAL_ADMIN")
    source_reference: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("student_id", "course_id"),)


class StudentRecognitionRecord(Base):
    __tablename__ = "student_recognitions"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    source_course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    target_course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    recognizes_history: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="STUDENT_CONFIRMED")
    authority: Mapped[str] = mapped_column(String(80), default="STUDENT_CONFIRMED")
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("student_id", "source_course_id", "target_course_id"),
        CheckConstraint("source_course_id <> target_course_id"),
    )


class StudentCapacityOverride(Base):
    __tablename__ = "student_capacity_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    academic_year_start: Mapped[int] = mapped_column(Integer)
    semester: Mapped[str] = mapped_column(String(20))
    capacity: Mapped[int] = mapped_column(Integer)
    authority: Mapped[str] = mapped_column(String(80))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        UniqueConstraint("student_id", "academic_year_start", "semester"),
        CheckConstraint("semester IN ('FALL','SPRING')"),
        CheckConstraint("capacity >= 0 AND capacity <= 60"),
    )


class StudentOfferingOverride(Base):
    __tablename__ = "student_offering_overrides"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"))
    academic_year_start: Mapped[int] = mapped_column(Integer)
    semester: Mapped[str] = mapped_column(String(20))
    language_track: Mapped[str | None] = mapped_column(String(8))
    delivery_mode: Mapped[str] = mapped_column(String(30), default="ARRANGED")
    authority: Mapped[str] = mapped_column(String(80))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", "academic_year_start", "semester"),
        CheckConstraint("semester IN ('FALL','SPRING')"),
        CheckConstraint("language_track IS NULL OR language_track IN ('EN','FR')"),
    )


class StudentOptionalCreditApproval(Base):
    __tablename__ = "student_optional_credit_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    course_code_snapshot: Mapped[str] = mapped_column(String(40))
    credit_category: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="UNVERIFIED")
    authority: Mapped[str | None] = mapped_column(String(120))
    source_reference: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    academic_period: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", "credit_category"),
        CheckConstraint("status IN ('UNVERIFIED','APPROVED','REJECTED')"),
    )


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_documents.id"))
    status: Mapped[str] = mapped_column(String(30), default="PARSED")
    candidates: Mapped[list[ImportCandidate]] = relationship(cascade="all, delete-orphan")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class ImportCandidate(Base):
    __tablename__ = "import_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    record_type: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(20), default="AMBIGUOUS")
    payload: Mapped[Any] = mapped_column(JSON)
    errors: Mapped[Any] = mapped_column(JSON, default=list)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)

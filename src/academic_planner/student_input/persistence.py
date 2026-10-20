"""Persist a fully reconciled portal snapshot for the shared planning engine."""

from __future__ import annotations

import re
from secrets import compare_digest

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from academic_planner.database.models import (
    CourseRecord, CurriculumRevision, DegreeContract, StudentAttemptRecord,
    StudentRecord,
)

from .schemas import (
    StudentInputCommitRequest, StudentInputCommitResponse,
)
from .service import preview_student_input, student_input_preview_token


class StudentAlreadyExistsError(ValueError):
    def __init__(
        self, existing: StudentRecord, existing_attempts: int,
        incoming_attempts: int, incoming_credits: int,
    ) -> None:
        self.existing = existing
        self.existing_attempts = existing_attempts
        self.incoming_attempts = incoming_attempts
        self.incoming_credits = incoming_credits
        super().__init__(
            f"{existing.display_name} ({existing.identifier}) already exists."
        )


def _identifier(source_id: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", source_id.strip()).strip("_")
    if not normalized:
        raise ValueError("A usable student ID was not detected in the portal text.")
    return f"student_{normalized.lower()}"


def _language_track(program_code: str | None, detected: str | None) -> str:
    if detected in {"EN", "FR"}:
        return detected
    code = (program_code or "").upper()
    if code.endswith("EN"):
        return "EN"
    if code.endswith("FR"):
        return "FR"
    raise ValueError("The student's EN or FR language track was not detected.")


def _curriculum_version(program_code: str | None, source_codes: set[str]) -> str:
    code = (program_code or "").upper()
    legacy_codes = sum(item.startswith("EL") for item in source_codes)
    modern_codes = sum(item.startswith("CCE") for item in source_codes)
    if code.startswith("EL") or legacy_codes > modern_codes:
        return "OLD"
    return "NEW"


def _contract_for_new_curriculum(
    session: Session, program_code: str | None,
) -> DegreeContract | None:
    code = re.sub(r"(?:EN|FR)$", "", (program_code or "").upper())
    aliases = {code}
    if code == "ELCC":
        aliases.add("CCE")
    return session.scalar(
        select(DegreeContract)
        .join(CurriculumRevision)
        .where(
            CurriculumRevision.active.is_(True),
            CurriculumRevision.version == "NEW",
            DegreeContract.program_code.in_(aliases),
        )
        .order_by(DegreeContract.effective_academic_year.desc())
        .limit(1)
    )


def _category_code(label: str) -> str:
    code = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")
    return code[:80] or "UNCLASSIFIED"


def persist_student_input(
    session: Session,
    payload: StudentInputCommitRequest,
    current_term: str,
) -> StudentInputCommitResponse:
    """Revalidate and atomically replace the student's transcript snapshot."""
    expected_token = student_input_preview_token(payload.text, current_term)
    if not compare_digest(payload.preview_token, expected_token):
        raise ValueError(
            "The transcript text changed after preview. Preview it again before saving."
        )
    preview = preview_student_input(
        session, payload.text, current_term, payload.decisions
    )
    if not preview.can_continue_without_review:
        raise ValueError(
            "Resolve every blocking review item before saving this student."
        )
    identity = preview.identity
    if not identity.student_id or not identity.name:
        raise ValueError("The student's ID and name must be detected before saving.")
    identifier = _identifier(identity.student_id)
    existing = session.scalar(select(StudentRecord).where(
        StudentRecord.identifier == identifier
    ))
    attempts = [
        attempt
        for group in preview.course_groups
        for attempt in group.attempts
    ]
    components = [
        component
        for group in preview.course_groups
        for component in group.components
    ]
    if existing is not None and not payload.replace_existing:
        existing_attempts = session.scalar(
            select(func.count(StudentAttemptRecord.id)).where(
                StudentAttemptRecord.student_id == existing.id
            )
        ) or 0
        raise StudentAlreadyExistsError(
            existing, existing_attempts, len(attempts) + len(components),
            preview.credit_check.parsed_degree_earned_ects,
        )

    source_codes = {attempt.source_code.upper() for attempt in attempts}
    curriculum_version = _curriculum_version(identity.program_code, source_codes)
    selected_ids = {
        attempt.selected_course_id
        for attempt in attempts
        if attempt.selected_course_id is not None
    }
    courses = {
        course.id: course
        for course in session.scalars(
            select(CourseRecord).where(CourseRecord.id.in_(selected_ids))
        )
    } if selected_ids else {}
    current_years = [
        courses[attempt.selected_course_id].reference_year
        for attempt in attempts
        if attempt.term == current_term
        and attempt.status in {"REGISTERED", "IN_PROGRESS"}
        and attempt.selected_course_id in courses
    ]
    credit_estimate = min(
        5,
        max(1, 1 + preview.credit_check.parsed_degree_earned_ects // 60),
    )
    nominal_year = max([credit_estimate, *current_years])
    language_track = _language_track(
        identity.program_code, identity.language_track
    )
    contract = (
        _contract_for_new_curriculum(session, identity.program_code)
        if curriculum_version == "NEW"
        else None
    )
    categories = [
        {
            "code": _category_code(category.label),
            "label": category.label,
            "required_ects": category.required_ects or 0,
            "source_reported_earned_ects": category.reported_earned_ects or 0,
        }
        for category in preview.categories
    ]

    created = existing is None
    if existing is None:
        student = StudentRecord(
            identifier=identifier,
            display_name=identity.name,
            nominal_year=nominal_year,
            language_track=language_track,
            governing_curriculum_version=curriculum_version,
            reported_earned_credits=(
                identity.reported_earned_credits
                if identity.reported_earned_credits is not None
                else preview.credit_check.parsed_degree_earned_ects
            ),
            graduation_credit_target=identity.graduation_target or 300,
            passing_grade=identity.passing_grade,
            contract_credit_categories=categories,
            degree_contract_id=contract.id if contract else None,
            active=True,
        )
        session.add(student)
    else:
        student = existing
        session.execute(delete(StudentAttemptRecord).where(
            StudentAttemptRecord.student_id == student.id
        ))
    student.display_name = identity.name
    student.nominal_year = nominal_year
    student.language_track = language_track
    student.governing_curriculum_version = curriculum_version
    student.reported_earned_credits = (
        identity.reported_earned_credits
        if identity.reported_earned_credits is not None
        else preview.credit_check.parsed_degree_earned_ects
    )
    student.graduation_credit_target = identity.graduation_target or 300
    student.passing_grade = identity.passing_grade
    student.contract_credit_categories = categories
    student.degree_contract_id = contract.id if contract else None
    student.active = True
    session.flush()

    confirmed_attempt_ids = {
        decision.attempt_id for decision in payload.decisions
        if decision.action != "LEAVE_UNRESOLVED"
    }
    for attempt in attempts:
        session.add(StudentAttemptRecord(
            student_id=student.id,
            course_id=attempt.selected_course_id,
            source_code=attempt.source_code,
            source_title=attempt.source_title,
            ects=attempt.ects,
            source_term=attempt.term,
            status=attempt.status,
            grade=attempt.grade_value,
            earned_credits=attempt.earned_ects,
            counts_toward_degree_credit=attempt.counts_toward_degree_credit,
            counts_toward_gpa=attempt.counts_toward_gpa,
            credit_identity=attempt.credit_identity,
            evidence_status=(
                "USER_CONFIRMED_PROVISIONAL"
                if attempt.id in confirmed_attempt_ids
                else "OFFICIAL_PORTAL_COPY"
            ),
            source_value=attempt.grade_token,
            notes=attempt.note,
        ))
    parent_by_id = {attempt.id: attempt for attempt in attempts}
    for component in components:
        parent = parent_by_id.get(component.parent_attempt_id or "")
        session.add(StudentAttemptRecord(
            student_id=student.id,
            course_id=None,
            source_code=component.source_code,
            source_title=component.source_title,
            ects=0,
            source_term=component.term,
            status=component.status,
            grade=None,
            earned_credits=0,
            counts_toward_degree_credit=False,
            counts_toward_gpa=False,
            evidence_status="OFFICIAL_PORTAL_COPY",
            source_value=None,
            notes=(
                f"Lab component of {parent.source_title} ({parent.source_code})"
                if parent else component.note
            ),
        ))
    return StudentInputCommitResponse(
        identifier=student.identifier,
        display_name=student.display_name,
        created=created,
        replaced_existing=not created,
        attempts_saved=len(attempts) + len(components),
        currently_registered_courses=preview.currently_registered_courses,
        current_term=current_term,
        recommended_registration_mode=(
            "KEEP_CURRENT"
            if preview.currently_registered_courses
            else "REBUILD_CURRENT"
        ),
    )

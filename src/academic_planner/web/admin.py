from __future__ import annotations

from collections import Counter
from dataclasses import asdict, replace
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from academic_planner.database.models import (
    ActiveTerm, CourseRecord, CurriculumRevision, EngineSetting, Equivalency, EquivalencyMatch,
    ImportBatch, ImportCandidate, MeetingRecord, Offering, PrerequisiteGroup,
    PrerequisiteItem, SectionRecord, SourceDocument, StudentAttemptRecord,
    StudentOfferingOverride, StudentRecognitionRecord, StudentRequirementRecord,
)
from academic_planner.database.service import (
    DEFAULT_SETTINGS, generate_year_1_2_placeholders, list_courses, replace_active_term,
)
from academic_planner.database.session import get_session
from academic_planner.database.loader import DatabasePlanningLoader
from academic_planner.database.config import PROJECT_ROOT
from academic_planner.importing import (
    CurriculumImportService, NewCurriculumPdfParser, OldCurriculumExcelParser,
    ParsedCurriculum, validate_curriculum,
)
from academic_planner.domain.models import (
    AcademicTerm, AttemptStatus, CourseAttempt, LanguageTrack, StudentAcademicState,
    TermKind,
)
from academic_planner.optimization import GlobalPlanner
from academic_planner.matching import EquivalencyMatchingService
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy,
)
from academic_planner.policies.graduation_role import (
    IUL_CREDIT_BAND_RULE,
    graduation_role_for,
)
from .admin_schemas import (
    ActiveTermWrite, CourseWrite, EquivalencyWrite, OfferingWrite,
    DatabasePlanRequest, ImportConfirm, MatchVerify, PrerequisiteWrite, SettingsWrite,
)

router = APIRouter(prefix="/api/admin", tags=["administration"])


def _commit(session: Session):
    try: session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, f"Database constraint rejected the change: {exc.orig}") from exc


@router.get("/curricula")
def curricula(session: Session = Depends(get_session)):
    return [{"id": r.id, "version": r.version, "revision": r.revision,
             "accepted_credit_target": r.accepted_credit_target, "active": r.active}
            for r in session.scalars(select(CurriculumRevision).order_by(CurriculumRevision.version)).all()]


@router.get("/courses")
def courses(session: Session = Depends(get_session)): return list_courses(session)


@router.post("/courses", status_code=201)
def create_course(payload: CourseWrite, session: Session = Depends(get_session)):
    row = CourseRecord(
        **payload.model_dump(), provenance="MANUAL_CORRECTION",
        graduation_role=graduation_role_for(
            payload.ects, payload.is_fyp, payload.course_type
        ),
        graduation_role_basis=IUL_CREDIT_BAND_RULE,
    )
    session.add(row); _commit(session); return {"id": row.id}


@router.put("/courses/{course_id}")
def update_course(course_id: int, payload: CourseWrite, session: Session = Depends(get_session)):
    row = session.get(CourseRecord, course_id)
    if row is None: raise HTTPException(404, "Course not found")
    for key, value in payload.model_dump().items(): setattr(row, key, value)
    row.graduation_role = graduation_role_for(
        payload.ects, payload.is_fyp, payload.course_type
    )
    row.graduation_role_basis = IUL_CREDIT_BAND_RULE
    row.provenance = "MANUAL_CORRECTION"; _commit(session); return {"id": row.id}


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: int, session: Session = Depends(get_session)):
    row = session.get(CourseRecord, course_id)
    if row is None: raise HTTPException(404, "Course not found")
    student_link = (
        session.scalar(select(StudentAttemptRecord.id).where(
            StudentAttemptRecord.course_id == course_id).limit(1))
        or session.scalar(select(StudentRequirementRecord.id).where(
            StudentRequirementRecord.course_id == course_id).limit(1))
        or session.scalar(select(StudentRecognitionRecord.id).where(
            (StudentRecognitionRecord.source_course_id == course_id)
            | (StudentRecognitionRecord.target_course_id == course_id)).limit(1))
        or session.scalar(select(StudentOfferingOverride.id).where(
            StudentOfferingOverride.course_id == course_id).limit(1))
    )
    if student_link is not None:
        raise HTTPException(
            409,
            "Course is referenced by persisted student data; update that student record "
            "or use curriculum replacement so links can be safely rebound.",
        )
    session.delete(row); _commit(session)


def _would_cycle(session: Session, course_id: int, prereq_ids: list[int]) -> bool:
    groups = session.scalars(select(PrerequisiteGroup).options(selectinload(PrerequisiteGroup.items))).all()
    graph = {g.course_id: {i.prerequisite_course_id for i in g.items} for g in groups if g.course_id != course_id}
    graph[course_id] = set(prereq_ids)
    def visit(node, path):
        if node in path: return True
        return any(visit(n, path | {node}) for n in graph.get(node, ()))
    return any(visit(node, set()) for node in graph)


@router.post("/courses/{course_id}/prerequisites", status_code=201)
def create_prerequisite(course_id: int, payload: PrerequisiteWrite,
                        session: Session = Depends(get_session)):
    if course_id in payload.prerequisite_course_ids: raise HTTPException(422, "A course cannot require itself")
    if _would_cycle(session, course_id, payload.prerequisite_course_ids): raise HTTPException(422, "Cyclic prerequisite detected")
    group = session.scalar(
        select(PrerequisiteGroup)
        .where(PrerequisiteGroup.course_id == course_id)
        .options(selectinload(PrerequisiteGroup.items))
    )
    if group is None:
        group = PrerequisiteGroup(course_id=course_id, provenance="MANUAL_CORRECTION")
        session.add(group)
    else:
        for existing_item in list(group.items):
            session.delete(existing_item)
    group.logic = payload.logic
    group.ambiguous = payload.ambiguous
    group.provenance = "MANUAL_CORRECTION"
    session.flush()
    for item in payload.prerequisite_course_ids:
        session.add(PrerequisiteItem(group_id=group.id, prerequisite_course_id=item))
    _commit(session); return {"id": group.id}


@router.delete("/prerequisites/{group_id}", status_code=204)
def delete_prerequisite(group_id: int, session: Session = Depends(get_session)):
    group = session.get(PrerequisiteGroup, group_id)
    if not group: raise HTTPException(404, "Prerequisite group not found")
    session.delete(group); _commit(session)


@router.get("/equivalencies")
def equivalencies(session: Session = Depends(get_session)):
    return [{c.name: getattr(row, c.name) for c in Equivalency.__table__.columns}
            for row in session.scalars(select(Equivalency)).all()]


@router.post("/equivalencies", status_code=201)
def create_equivalency(payload: EquivalencyWrite, session: Session = Depends(get_session)):
    row = Equivalency(**payload.model_dump(), provenance="MANUAL_CORRECTION")
    session.add(row); _commit(session); return {"id": row.id}


@router.delete("/equivalencies/{equivalency_id}", status_code=204)
def delete_equivalency(equivalency_id: int, session: Session = Depends(get_session)):
    row = session.get(Equivalency, equivalency_id)
    if not row: raise HTTPException(404, "Equivalency not found")
    session.delete(row); _commit(session)


def _match_course(data: dict | None) -> dict | None:
    if data is None:
        return None
    return {key: data[key] for key in (
        "id", "code", "title", "ects", "reference_year", "reference_semester",
        "prerequisite_groups", "lab_relationships",
    )}


@router.get("/equivalency-matches")
def equivalency_matches(session: Session = Depends(get_session)):
    course_data = list_courses(session)
    courses_by_id = {row["id"]: row for row in course_data}
    rows = list(session.scalars(select(EquivalencyMatch).order_by(
        EquivalencyMatch.status, EquivalencyMatch.id)))
    entries = [{
        "id": row.id, "status": row.status, "method": row.method,
        "review_reasons": row.review_reasons or [], "explanation": row.explanation,
        "verified_by": row.verified_by, "decided_at": row.decided_at,
        "old_course": _match_course(courses_by_id.get(row.old_course_id)),
        "new_course": _match_course(courses_by_id.get(row.new_course_id)),
    } for row in rows]
    active = [row for row in rows if row.status != "REJECTED"]
    paired_old = {row.old_course_id for row in active}
    paired_new = {row.new_course_id for row in active}
    entries.extend({"id": f"old-{course['id']}", "status": "UNMATCHED", "method": None,
        "review_reasons": [], "explanation": "No credible NEW candidate was found.",
        "verified_by": None, "decided_at": None, "old_course": _match_course(course),
        "new_course": None} for course in course_data
        if course["curriculum_version"] == "OLD" and course["id"] not in paired_old)
    entries.extend({"id": f"new-{course['id']}", "status": "UNMATCHED", "method": None,
        "review_reasons": [], "explanation": "No credible OLD candidate was found.",
        "verified_by": None, "decided_at": None, "old_course": None,
        "new_course": _match_course(course)} for course in course_data
        if course["curriculum_version"] == "NEW" and course["id"] not in paired_new)
    return {"summary": EquivalencyMatchingService.summary(session), "entries": entries}


@router.post("/equivalency-matches/auto-match")
def auto_match_equivalencies(session: Session = Depends(get_session)):
    try:
        summary = EquivalencyMatchingService().run(session)
        session.commit()
    except ValueError as exc:
        session.rollback(); raise HTTPException(422, str(exc)) from exc
    except Exception:
        session.rollback(); raise
    return {"message": "Equivalency matching completed", "summary": summary}


@router.post("/equivalency-matches/{match_id}/verify")
def verify_equivalency_match(match_id: int, payload: MatchVerify,
                             session: Session = Depends(get_session)):
    try:
        row = EquivalencyMatchingService().verify(session, match_id,
            old_course_id=payload.old_course_id, new_course_id=payload.new_course_id,
            verified_by=payload.verified_by)
        session.commit()
    except ValueError as exc:
        session.rollback(); raise HTTPException(422, str(exc)) from exc
    return {"message": "Equivalency locally verified", "id": row.id,
            "status": row.status, "official_approval": False,
            "prospective_registration_allowed": None}


@router.post("/equivalency-matches/{match_id}/reject")
def reject_equivalency_match(match_id: int, session: Session = Depends(get_session)):
    try:
        row = EquivalencyMatchingService().reject(session, match_id)
        session.commit()
    except ValueError as exc:
        session.rollback(); raise HTTPException(404, str(exc)) from exc
    return {"message": "Candidate pair rejected", "id": row.id, "status": row.status}


def _offering(row: Offering):
    return {"id": row.id, "course_id": row.course_id, "code": row.course.code,
        "title": row.course.title, "year": row.course.reference_year,
        "curriculum_version": row.course.curriculum.version,
        "language_track": row.language_track, "verification_status": row.verification_status,
        "provenance": row.provenance,
        "synthetic_placeholder": row.provenance == "SYNTHETIC_PLACEHOLDER",
        "sections": [{"id": s.id, "code": s.code, "component": s.component,
            "bundle_key": s.bundle_key, "campus": s.campus, "room": s.room,
            "instructor": s.instructor, "notes": s.notes,
            "meetings": [{"id": m.id, "weekday": m.weekday,
                "start_minute": m.start_minute, "end_minute": m.end_minute} for m in s.meetings]}
            for s in row.sections]}


@router.get("/timetable")
def timetable(session: Session = Depends(get_session)):
    active = session.get(ActiveTerm, 1)
    rows = session.scalars(select(Offering).where(
        Offering.academic_year_start == active.academic_year_start,
        Offering.semester == active.semester).options(
        selectinload(Offering.course).selectinload(CourseRecord.curriculum),
        selectinload(Offering.sections).selectinload(SectionRecord.meetings))).all()
    return {"active_term": {"academic_year_start": active.academic_year_start,
        "semester": active.semester, "generation": active.generation},
        "offerings": [_offering(row) for row in rows]}


@router.post("/timetable/generate-year-1-2")
def generate_missing_timetable(session: Session = Depends(get_session)):
    try:
        result = generate_year_1_2_placeholders(session)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from exc
    return {"message": "Deterministic Year 1-2 placeholders generated", **result}


@router.put("/active-term")
def active_term(payload: ActiveTermWrite, session: Session = Depends(get_session)):
    active = session.get(ActiveTerm, 1)
    changed = (active.academic_year_start, active.semester) != (payload.academic_year_start, payload.semester)
    if changed and session.scalar(select(Offering.id).limit(1)) and not payload.confirm_replace:
        raise HTTPException(409, "Changing the active term discards current offerings; confirm_replace is required")
    active = replace_active_term(session, payload.academic_year_start, payload.semester)
    _commit(session); return {"academic_year_start": active.academic_year_start,
                              "semester": active.semester, "generation": active.generation}


@router.post("/offerings", status_code=201)
def create_offering(payload: OfferingWrite, session: Session = Depends(get_session)):
    active = session.get(ActiveTerm, 1)
    row = Offering(course_id=payload.course_id, academic_year_start=active.academic_year_start,
        semester=active.semester, language_track=payload.language_track,
        provenance="MANUAL_CORRECTION", verification_status=payload.verification_status)
    session.add(row); session.flush()
    for section in payload.sections:
        sec = SectionRecord(offering_id=row.id, **section.model_dump(exclude={"meetings"}))
        session.add(sec); session.flush()
        for meeting in section.meetings: session.add(MeetingRecord(section_id=sec.id, **meeting.model_dump()))
    _commit(session); return {"id": row.id}


@router.put("/offerings/{offering_id}")
def update_offering(offering_id: int, payload: OfferingWrite, session: Session = Depends(get_session)):
    row = session.get(Offering, offering_id)
    if not row: raise HTTPException(404, "Offering not found")
    row.course_id, row.language_track = payload.course_id, payload.language_track
    row.verification_status = payload.verification_status; row.provenance = "MANUAL_CORRECTION"
    for old in list(row.sections): session.delete(old)
    session.flush()
    for section in payload.sections:
        sec = SectionRecord(offering_id=row.id, **section.model_dump(exclude={"meetings"}))
        session.add(sec); session.flush()
        for meeting in section.meetings: session.add(MeetingRecord(section_id=sec.id, **meeting.model_dump()))
    _commit(session); return {"id": row.id}


@router.delete("/offerings/{offering_id}", status_code=204)
def delete_offering(offering_id: int, session: Session = Depends(get_session)):
    row = session.get(Offering, offering_id)
    if not row: raise HTTPException(404, "Offering not found")
    session.delete(row); _commit(session)


@router.get("/settings")
def settings(session: Session = Depends(get_session)):
    active = session.get(ActiveTerm, 1)
    return {"values": {r.key: r.value for r in session.scalars(select(EngineSetting)).all()},
            "metadata": {r.key: {"description": r.description,
                "unverified_assumption": r.unverified_assumption} for r in session.scalars(select(EngineSetting)).all()},
            "active_term": {"academic_year_start": active.academic_year_start, "semester": active.semester}}


def _validate_settings(values):
    integer_bounds = {
        "default_credit_capacity": (1, 60),
        "extended_failed_repeat_capacity": (1, 60),
        "training_1_capacity": (0, 60),
        "training_2_capacity": (0, 60),
        "initial_horizon_semesters": (1, 40),
        "max_horizon_semesters": (1, 40),
        "horizon_extension_step": (1, 10),
        "academic_year_deviation_weight": (0, 1000),
        "reference_semester_deviation_weight": (0, 1000),
        "training_delay_penalty": (0, 1000),
        "max_training_delay_years": (0, 10),
        "final_two_semester_graduation_capacity": (1, 60),
        "new_curriculum_rollout_first_year_start": (1900, 2200),
    }
    for key, (minimum, maximum) in integer_bounds.items():
        if key not in values:
            continue
        value = values[key]
        if key == "max_training_delay_years" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(422, f"{key} must be an integer")
        if not minimum <= value <= maximum:
            raise HTTPException(422, f"{key} must be between {minimum} and {maximum}")
    solver_limit = values.get("solver_time_limit_seconds")
    if (
        isinstance(solver_limit, bool)
        or not isinstance(solver_limit, (int, float))
        or not 0 < solver_limit <= 120
    ):
        raise HTTPException(422, "solver_time_limit_seconds must be above 0 and at most 120")
    initial = values.get("initial_horizon_semesters")
    maximum = values.get("max_horizon_semesters")
    if initial is not None and maximum is not None and maximum < initial: raise HTTPException(422, "Maximum horizon cannot be shorter than initial horizon")
    if values.get("extended_failed_repeat_capacity", 36) < values.get("default_credit_capacity", 30):
        raise HTTPException(422, "Extended failed-repeat capacity cannot be below regular capacity")
    if values.get("final_two_semester_graduation_capacity", 36) < values.get("default_credit_capacity", 30):
        raise HTTPException(422, "Final-two-semester capacity cannot be below regular capacity")
    boolean_keys = {"allow_extended_load_when_repeating_failed_course",
        "allow_training_postponement", "auto_extend_horizon", "diagnostic_logging",
        "allow_cross_track_shared_sections", "prefer_own_track_sections",
        "allow_final_two_semester_graduation_load"}
    for key in boolean_keys & values.keys():
        if not isinstance(values[key], bool):
            raise HTTPException(422, f"{key} must be true or false")
    if values.get("future_offering_assumption") not in {"REFERENCE_SEMESTER", "NONE"}:
        raise HTTPException(422, "future_offering_assumption must be REFERENCE_SEMESTER or NONE")


@router.put("/settings")
def update_settings(payload: SettingsWrite, session: Session = Depends(get_session)):
    unknown = set(payload.values) - DEFAULT_SETTINGS.keys()
    if unknown: raise HTTPException(422, f"Unknown settings: {', '.join(sorted(unknown))}")
    current = {r.key: r.value for r in session.scalars(select(EngineSetting)).all()}
    merged = current | payload.values; _validate_settings(merged)
    for key, value in payload.values.items(): session.get(EngineSetting, key).value = value
    _commit(session); return {"message": "Saved; changes apply to the next database planning run", "values": merged}


@router.post("/settings/reset")
def reset_settings(session: Session = Depends(get_session)):
    for key, (value, _, _) in DEFAULT_SETTINGS.items(): session.get(EngineSetting, key).value = value
    _commit(session); return {"values": {k: v[0] for k, v in DEFAULT_SETTINGS.items()}}


@router.get("/imports")
def imports(session: Session = Depends(get_session)):
    docs = session.scalars(select(SourceDocument)).all()
    batches = session.scalars(select(ImportBatch).options(selectinload(ImportBatch.candidates))).all()
    return {"documents": [{"id": d.id, "filename": d.filename, "kind": d.kind,
        "status": d.status, "notes": d.notes} for d in docs],
        "batches": [{"id": b.id, "source_document_id": b.source_document_id,
            "status": b.status, "candidates": [{"id": c.id, "record_type": c.record_type,
                "action": c.action, "payload": c.payload, "errors": c.errors,
                "approved": c.approved} for c in b.candidates]} for b in batches]}


@router.post("/imports/preview", status_code=201)
async def preview_curriculum_import(
    curriculum_version: str = Form(...), file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    version = curriculum_version.upper()
    if version not in {"OLD", "NEW"}:
        raise HTTPException(422, "curriculum_version must be OLD or NEW")
    filename = Path(file.filename or "").name
    expected = ".xlsx" if version == "OLD" else ".pdf"
    if Path(filename).suffix.lower() != expected:
        raise HTTPException(422, f"{version} curriculum requires a {expected} file")
    content = await file.read()
    if not content: raise HTTPException(422, "Uploaded file is empty")
    digest = hashlib.sha256(content).hexdigest()
    directory = PROJECT_ROOT / "data" / "import_sources"
    directory.mkdir(parents=True, exist_ok=True)
    stored = directory / f"{digest}{expected}"
    if not stored.exists(): stored.write_bytes(content)
    try:
        parser = OldCurriculumExcelParser() if version == "OLD" else NewCurriculumPdfParser()
        parsed = parser.parse(stored)
        # The stored digest name is an implementation detail; preserve the uploaded identity.
        parsed.source_document = filename
        parsed.courses = [replace(item, source=replace(item.source, document=filename)) for item in parsed.courses]
        parsed.prerequisite_rules = [replace(item, source=replace(item.source, document=filename)) for item in parsed.prerequisite_rules]
        parsed.lab_relationships = [replace(item, source=replace(item.source, document=filename)) for item in parsed.lab_relationships]
        report = validate_curriculum(parsed)
    except Exception as exc:
        raise HTTPException(422, f"Could not parse {filename}: {exc}") from exc
    document = session.scalar(select(SourceDocument).where(SourceDocument.sha256 == digest))
    if document is None:
        document = SourceDocument(filename=filename, kind=f"{version}_CURRICULUM", sha256=digest,
            status="VALIDATED" if report.publishable else "INVALID",
            notes="Uploaded curriculum source retained for reproducible replacement.",
            storage_path=str(stored.relative_to(PROJECT_ROOT)))
        session.add(document); session.flush()
    batch = ImportBatch(source_document_id=document.id,
        status="READY_TO_REPLACE" if report.publishable else "VALIDATION_FAILED")
    session.add(batch); session.flush()
    candidate = ImportCandidate(batch_id=batch.id, record_type="CURRICULUM",
        action="FULL_REPLACEMENT", payload={"parsed": parsed.to_dict(), "validation": report.to_dict()},
        errors=[issue.message for issue in report.fatal_errors], approved=False)
    session.add(candidate); _commit(session)
    existing_count = len(session.scalars(select(CourseRecord.id).join(CurriculumRevision).where(CurriculumRevision.version == version)).all())
    return {"batch_id": batch.id, "curriculum_version": version, "source": filename,
        "courses_parsed": len(parsed.courses), "prerequisite_rules": len(parsed.prerequisite_rules),
        "prerequisite_links": sum(len(r.prerequisite_codes) for r in parsed.prerequisite_rules),
        "requirements": len(parsed.degree_requirements), "lab_relationships": len(parsed.lab_relationships),
        "curriculum_credits": report.total_ects, "existing_courses_to_replace": existing_count,
        "validation": report.to_dict(),
        "confirmation": f"Reimporting the {version} curriculum will replace all existing {version} courses and prerequisites. Manual corrections will be lost. Continue?"}


@router.post("/imports/{batch_id}/confirm")
def confirm_curriculum_import(batch_id: int, payload: ImportConfirm,
                              session: Session = Depends(get_session)):
    if not payload.confirm_replace:
        raise HTTPException(409, "confirm_replace=true is required for complete replacement")
    batch = session.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).options(selectinload(ImportBatch.candidates)))
    if batch is None: raise HTTPException(404, "Import batch not found")
    if batch.status == "IMPORTED": raise HTTPException(409, "This import batch was already applied")
    candidate = next((c for c in batch.candidates if c.record_type == "CURRICULUM"), None)
    if candidate is None: raise HTTPException(422, "Batch does not contain a curriculum preview")
    parsed = ParsedCurriculum.from_dict(candidate.payload["parsed"])
    report = validate_curriculum(parsed)
    if report.fatal_errors:
        raise HTTPException(422, {"message": "Fatal validation errors prevent replacement", "validation": report.to_dict()})
    document = session.get(SourceDocument, batch.source_document_id)
    try:
        result = CurriculumImportService().replace(session, parsed, document, report)
        batch.status = "IMPORTED"; candidate.approved = True
        session.commit()
    except Exception as exc:
        session.rollback()
        if isinstance(exc, ValueError): raise HTTPException(422, str(exc)) from exc
        raise HTTPException(500, "Replacement failed; the previous curriculum was left intact") from exc
    return {"message": f"{result.curriculum_version} curriculum replaced atomically", **asdict(result)}


@router.post("/plan")
def database_plan(payload: DatabasePlanRequest, session: Session = Depends(get_session)):
    attempts = []
    for item in payload.attempts:
        try:
            attempts.append(CourseAttempt(
                str(item["course_id"]),
                AcademicTerm(int(item["academic_year_start"]), TermKind(item["semester"])),
                AttemptStatus(item["status"]), item.get("grade"), int(item.get("earned_credits", 0)),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, f"Invalid student attempt: {exc}") from exc
    student = StudentAcademicState(payload.nominal_year, LanguageTrack(payload.language_track),
        tuple(attempts), frozenset(str(i) for i in payload.completed_requirement_ids),
        payload.earned_credits)
    try:
        problem = DatabasePlanningLoader().load_problem(session, student, payload.curriculum_version)
        rollout_start = int(session.get(EngineSetting, "new_curriculum_rollout_first_year_start").value)
        plan = GlobalPlanner(ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(rollout_start),
                             AllowAllRegistrationPolicy()).plan(problem)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    bundles = {bundle.id: bundle for offering in problem.offerings for bundle in offering.bundles}
    academic_policy_exclusions = [{"course_id": str(course.id), "course_code": course.code,
        "reason_code": "TRACK_SPECIFIC_REQUIREMENT",
        "reason": f"Course is restricted to {', '.join(course.permitted_student_tracks or [])} students and does not replace the {student.language_track.value}-track requirement."}
        for course in session.scalars(select(CourseRecord).where(
            CourseRecord.curriculum_id == next(r.id for r in session.scalars(select(CurriculumRevision).where(
                CurriculumRevision.active.is_(True), CurriculumRevision.version == payload.curriculum_version)).all()),
            CourseRecord.academic_track_policy == "TRACK_SPECIFIC",
        )).all() if student.language_track.value not in (course.permitted_student_tracks or [])]
    return {"status": plan.status.value,
        "graduation_term": plan.graduation_term.label() if plan.graduation_term else None,
        "scheduled_terms": [{"term": t.term.label(), "course_ids": list(t.course_ids),
            "courses": [problem.courses[c].code for c in t.course_ids],
            "bundle_ids": list(t.bundle_ids),
            "selected_sections": [{"course_id": bundles[b].course_id,
                "section_codes": [section.crn for section in bundles[b].sections],
                "section_language": next((section.teaching_language.value for section in bundles[b].sections
                    if section.teaching_language is not None), None),
                "cross_track": any(section.teaching_language is not None and
                    section.teaching_language is not student.language_track for section in bundles[b].sections),
                "provenance": bundles[b].sections[0].provenance.value}
                for b in t.bundle_ids]
            } for t in plan.scheduled_terms],
        "warnings": list(plan.warnings), "explanations": list(plan.explanations),
        "academic_policy_exclusions": academic_policy_exclusions,
        "student_persisted": False}

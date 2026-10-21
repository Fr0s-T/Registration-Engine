"""Database seeding, catalog serialization, and active-term maintenance services."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from academic_planner.fixtures.synthetic import SyntheticFixtureLoader
from academic_planner.policies.graduation_role import (
    IUL_CREDIT_BAND_RULE,
    graduation_role_for,
)

from .models import (
    ActiveTerm, CourseRecord, CurriculumRevision, DegreeRequirement, EngineSetting,
    Equivalency, ImportBatch, ImportCandidate, LabRelationship, MeetingRecord, Offering,
    PrerequisiteGroup, PrerequisiteItem, SectionRecord, SourceDocument,
    TermCapacityOverride,
)

DEFAULT_SETTINGS = {
    "default_credit_capacity": (30, "Regular-semester ECTS capacity", False),
    "extended_failed_repeat_capacity": (36, "Capacity only when a failed repeat is selected", False),
    "training_1_capacity": (5, "Training I period ECTS capacity", False),
    "training_2_capacity": (5, "Training II period ECTS capacity", False),
    "allow_extended_load_when_repeating_failed_course": (False, "Enable conditional repeat allowance", False),
    "allow_final_two_semester_graduation_load": (True, "Allow up to 36 ECTS in the final two regular semesters only when it improves graduation", False),
    "final_two_semester_graduation_capacity": (36, "IUL final-two-semester graduation capacity", False),
    "solver_time_limit_seconds": (20.0, "Solver time budget", False),
    "initial_horizon_semesters": (10, "Initial regular-semester horizon", False),
    "max_horizon_semesters": (20, "Maximum regular-semester horizon", False),
    "auto_extend_horizon": (True, "Extend after proven infeasibility", False),
    "horizon_extension_step": (2, "Regular semesters per extension", False),
    "academic_year_deviation_weight": (10, "Academic-year alignment tie-breaker", False),
    "reference_semester_deviation_weight": (2, "Fall/Spring alignment tie-breaker", False),
    "allow_training_postponement": (True, "Permit later training periods", False),
    "training_delay_penalty": (10, "Training delay tie-breaker", False),
    "max_training_delay_years": (None, "Optional training delay maximum", False),
    "future_offering_assumption": ("REFERENCE_SEMESTER", "Projection assumption", True),
    "new_curriculum_rollout_first_year_start": (2023, "Academic year when NEW Year 1 rollout began", False),
    "diagnostic_logging": (False, "Enable extra diagnostics", False),
    "allow_cross_track_shared_sections": (False, "Allow alternate-language sections of explicitly shared courses", True),
    "prefer_own_track_sections": (True, "Prefer the student's own-track section after higher-priority objectives", False),
}

_DEMO_TRAINING_CODES = {
    "NEW": frozenset({"CCE471", "CCE572"}),
    "OLD": frozenset({"ELCC608", "ELCC819"}),
}

def seed_defaults(session: Session) -> None:
    if session.get(ActiveTerm, 1) is None:
        session.add(ActiveTerm(id=1, academic_year_start=2026, semester="FALL"))
    for key, (value, description, unverified) in DEFAULT_SETTINGS.items():
        if session.get(EngineSetting, key) is None:
            session.add(EngineSetting(key=key, value=value, description=description,
                                      unverified_assumption=unverified))


def seed_demo_catalog(session: Session) -> None:
    existing = session.scalar(select(CourseRecord.id).limit(1)) is not None
    if existing:
        _normalize_demo_graduation_policy(session)
        return
    data = SyntheticFixtureLoader().load()
    revisions = {}
    for version in ("OLD", "NEW"):
        revision = CurriculumRevision(version=version, revision="synthetic-demo", active=True)
        session.add(revision)
        session.flush()
        revisions[version] = revision
    ids: dict[str, int] = {}
    for course in data.courses.values():
        curriculum = data.curricula[course.curriculum_version]
        is_fyp = course.is_fyp and not course.code.startswith("SYN-")
        course_type = (
            "TRAINING"
            if course.id in curriculum.training_requirement_ids
            else "FINAL_PROJECT" if is_fyp else "COURSE"
        )
        degree_credit_eligible = not (
            course.curriculum_version.value == "OLD" and course.code == "ENG108"
        )
        role = (
            "NEEDS_REVIEW"
            if course.code.startswith("SYN-")
            else graduation_role_for(
                course.credits,
                is_fyp,
                course_type,
                degree_credit_eligible=degree_credit_eligible,
            )
        )
        row = CourseRecord(
            curriculum_id=revisions[course.curriculum_version.value].id,
            code=course.code, title=course.name, ects=course.credits,
            reference_year=course.reference_year,
            reference_semester=course.reference_semester.value,
            course_type=course_type, is_fyp=is_fyp,
            graduation_role=role,
            graduation_role_basis=(
                "SYNTHETIC_PLACEHOLDER_NOT_A_DEGREE_REQUIREMENT"
                if course.code.startswith("SYN-")
                else IUL_CREDIT_BAND_RULE
            ),
            provenance="SYNTHETIC_TEST_FIXTURE",
            verification_status="UNVERIFIED",
        )
        session.add(row); session.flush(); ids[course.id] = row.id
        if role == "MANDATORY":
            session.add(DegreeRequirement(
                curriculum_id=row.curriculum_id,
                course_id=row.id,
                requirement_type=(
                    "FYP" if is_fyp
                    else "TRAINING" if course_type == "TRAINING"
                    else "COURSE"
                ),
            ))
    for rule in data.prerequisites:
        group = PrerequisiteGroup(course_id=ids[rule.course_id], logic="AND",
                                  provenance="SYNTHETIC_TEST_FIXTURE")
        session.add(group); session.flush()
        for prerequisite in rule.all_of:
            session.add(PrerequisiteItem(group_id=group.id,
                                         prerequisite_course_id=ids[prerequisite]))
    for eq in data.equivalencies:
        for source in eq.source_course_ids:
            for target in eq.target_requirement_ids:
                session.add(Equivalency(
                    source_course_id=ids[source], target_course_id=ids[target],
                    recognizes_history=True, prospective_registration_allowed=None,
                    provenance="SYNTHETIC_TEST_FIXTURE", verification_status="VERIFIED",
                ))
    active = session.get(ActiveTerm, 1)
    current = data.demo_configuration.planning_horizon[0]
    for source in data.offerings:
        if source.term != current or not source.bundles:
            continue
        offering = Offering(
            course_id=ids[source.course_id], academic_year_start=active.academic_year_start,
            semester=active.semester, provenance="SYNTHETIC_TEST_FIXTURE",
            verification_status="UNVERIFIED",
        )
        session.add(offering); session.flush()
        seen = set()
        for bundle in source.bundles:
            for section in bundle.sections:
                marker = (bundle.id, section.crn)
                if marker in seen: continue
                seen.add(marker)
                row = SectionRecord(offering_id=offering.id, code=section.crn,
                                    component=section.component, bundle_key=bundle.id,
                                    campus=section.campus)
                session.add(row); session.flush()
                for meeting in section.meetings:
                    session.add(MeetingRecord(section_id=row.id, weekday=meeting.weekday.value,
                                              start_minute=meeting.start_minute,
                                              end_minute=meeting.end_minute))


def _normalize_demo_graduation_policy(session: Session) -> None:
    """Apply post-migration policy to a new or previously seeded demo catalog.

    Alembic runs before the public seeder on a blank deployment, so migration
    data fixes cannot classify rows that do not exist yet.  Keeping this repair
    in the idempotent seeder also upgrades databases created by older releases.
    """
    rows = list(session.scalars(
        select(CourseRecord)
        .join(CurriculumRevision)
        .where(CurriculumRevision.revision == "synthetic-demo")
    ))
    desired_requirements: dict[int, str] = {}
    for row in rows:
        if row.code.startswith("SYN-"):
            row.is_fyp = False
            row.course_type = "COURSE"
        if row.code in _DEMO_TRAINING_CODES.get(row.curriculum.version, ()):
            row.course_type = "TRAINING"
        degree_credit_eligible = not (
            row.curriculum.version == "OLD" and row.code == "ENG108"
        )
        if row.code.startswith("SYN-"):
            row.graduation_role = "NEEDS_REVIEW"
            row.graduation_role_basis = (
                "SYNTHETIC_PLACEHOLDER_NOT_A_DEGREE_REQUIREMENT"
            )
        else:
            row.graduation_role = graduation_role_for(
                row.ects,
                row.is_fyp,
                row.course_type,
                degree_credit_eligible=degree_credit_eligible,
            )
            row.graduation_role_basis = IUL_CREDIT_BAND_RULE
        if row.graduation_role == "MANDATORY":
            desired_requirements[row.id] = (
                "FYP" if row.is_fyp
                else "TRAINING" if row.course_type == "TRAINING"
                else "COURSE"
            )

    existing_requirements = list(session.scalars(
        select(DegreeRequirement)
        .join(CurriculumRevision)
        .where(CurriculumRevision.revision == "synthetic-demo")
    ))
    existing_by_course = {item.course_id: item for item in existing_requirements}
    for item in existing_requirements:
        requirement_type = desired_requirements.get(item.course_id)
        if requirement_type is None:
            session.delete(item)
        else:
            item.requirement_type = requirement_type
    for row in rows:
        if row.id in desired_requirements and row.id not in existing_by_course:
            session.add(DegreeRequirement(
                curriculum_id=row.curriculum_id,
                course_id=row.id,
                requirement_type=desired_requirements[row.id],
            ))


def generate_year_1_2_placeholders(session: Session) -> dict:
    """Replace only synthetic Year 1-2 rows with deterministic active-term placeholders."""
    active = session.get(ActiveTerm, 1)
    if active is None:
        raise ValueError("Active term is not configured")
    revision = session.scalar(select(CurriculumRevision).where(
        CurriculumRevision.active.is_(True), CurriculumRevision.version == "NEW"
    ).order_by(CurriculumRevision.id.desc()))
    if revision is None:
        raise ValueError("No active NEW curriculum is available for Year 1-2 generation")
    courses = list(session.scalars(select(CourseRecord).where(
        CourseRecord.curriculum_id == revision.id,
        CourseRecord.reference_year.in_([1, 2]),
        CourseRecord.reference_semester == active.semester,
    ).order_by(CourseRecord.reference_year, CourseRecord.code)))
    if not courses:
        raise ValueError(f"No Year 1-2 NEW courses match the active {active.semester} term")
    course_ids = [course.id for course in courses]
    existing = list(session.scalars(select(Offering).where(
        Offering.academic_year_start == active.academic_year_start,
        Offering.semester == active.semester,
        Offering.course_id.in_(course_ids),
    )))
    preserved = {(row.course_id, row.language_track) for row in existing
                 if row.provenance != "SYNTHETIC_PLACEHOLDER"}
    replaced = sum(row.provenance == "SYNTHETIC_PLACEHOLDER" for row in existing)
    for row in existing:
        if row.provenance == "SYNTHETIC_PLACEHOLDER":
            session.delete(row)
    session.flush()
    lab_course_ids = set(session.scalars(select(LabRelationship.course_id).where(
        LabRelationship.course_id.in_(course_ids))))
    generated = 0
    for index, course in enumerate(courses):
        allowed = set(course.permitted_student_tracks or [])
        tracks = sorted(allowed) if course.academic_track_policy == "TRACK_SPECIFIC" else ["EN", "FR"]
        for track_index, track in enumerate(tracks):
            if (course.id, track) in preserved:
                continue
            offering = Offering(
                course_id=course.id, academic_year_start=active.academic_year_start,
                semester=active.semester, language_track=track,
                provenance="SYNTHETIC_PLACEHOLDER", verification_status="UNVERIFIED",
            )
            session.add(offering); session.flush()
            day = (index + track_index) % 5
            start = (510, 690, 870)[(index // 5 + track_index) % 3]
            lecture = SectionRecord(
                offering_id=offering.id, code=f"{track}-A", component="LECTURE",
                bundle_key="A", campus="MAIN", notes="SYNTHETIC_PLACEHOLDER",
            )
            session.add(lecture); session.flush()
            session.add_all([
                MeetingRecord(section_id=lecture.id, weekday=day,
                              start_minute=start, end_minute=start + 90),
                MeetingRecord(section_id=lecture.id, weekday=(day + 2) % 5,
                              start_minute=start, end_minute=start + 60),
            ])
            if course.id in lab_course_ids:
                lab_start = 990 if start >= 870 else start + 120
                lab = SectionRecord(
                    offering_id=offering.id, code=f"{track}-LAB-A", component="LAB",
                    bundle_key="A", campus="LAB", notes="SYNTHETIC_PLACEHOLDER",
                )
                session.add(lab); session.flush()
                session.add(MeetingRecord(section_id=lab.id, weekday=(day + 1) % 5,
                                          start_minute=lab_start, end_minute=lab_start + 90))
            generated += 1
    return {"generated_offerings": generated, "replaced_placeholders": replaced,
            "preserved_non_synthetic": len(preserved), "curriculum": "NEW",
            "years": [1, 2], "tracks": ["EN", "FR"], "semester": active.semester}


def serialize_course(row: CourseRecord, groups=(), equivalents=()) -> dict:
    return {
        "id": row.id, "code": row.code, "title": row.title, "ects": row.ects,
        "curriculum_id": row.curriculum_id, "curriculum_version": row.curriculum.version,
        "revision": row.curriculum.revision, "reference_year": row.reference_year,
        "reference_semester": row.reference_semester, "course_type": row.course_type,
        "is_fyp": row.is_fyp, "notes": row.notes, "provenance": row.provenance,
        "verification_status": row.verification_status,
        "source_document": None,
        "source_reference": row.source_locator,
        "academic_track_policy": row.academic_track_policy,
        "graduation_role": row.graduation_role,
        "graduation_role_basis": row.graduation_role_basis,
        "permitted_student_tracks": row.permitted_student_tracks or [],
        "prerequisite_groups": groups, "equivalencies": equivalents,
    }


def list_courses(session: Session) -> list[dict]:
    rows = session.scalars(select(CourseRecord).join(CourseRecord.curriculum)
                           .options(selectinload(CourseRecord.curriculum))
                           .order_by(CurriculumRevision.version, CourseRecord.code)).all()
    groups = session.scalars(select(PrerequisiteGroup).options(
        selectinload(PrerequisiteGroup.items))).all()
    by_course = defaultdict(list)
    course_map = {row.id: row for row in rows}
    for group in groups:
        by_course[group.course_id].append({
            "id": group.id, "logic": group.logic, "ambiguous": group.ambiguous,
            "source_text": group.source_text,
            "courses": [{"id": item.prerequisite_course_id,
                         "code": course_map[item.prerequisite_course_id].code,
                         "title": course_map[item.prerequisite_course_id].title}
                        for item in group.items if item.prerequisite_course_id in course_map],
        })
    eqs = session.scalars(select(Equivalency)).all()
    by_eq = defaultdict(list)
    for eq in eqs:
        data = {"id": eq.id, "source_course_id": eq.source_course_id,
                "target_course_id": eq.target_course_id,
                "source_code": course_map[eq.source_course_id].code,
                "target_code": course_map[eq.target_course_id].code,
                "recognizes_history": eq.recognizes_history,
                "prospective_registration_allowed": eq.prospective_registration_allowed,
                "verification_status": eq.verification_status}
        by_eq[eq.source_course_id].append(data); by_eq[eq.target_course_id].append(data)
    documents = {d.id: d.filename for d in session.scalars(select(SourceDocument)).all()}
    labs = session.scalars(select(LabRelationship)).all()
    offering_languages = defaultdict(set)
    for offering in session.scalars(select(Offering)).all():
        offering_languages[offering.course_id].add(offering.language_track or "TRACK_NEUTRAL")
    by_lab = defaultdict(list)
    for relation in labs:
        if relation.course_id in course_map and relation.lab_course_id in course_map:
            data = {"course_id": relation.course_id, "lab_course_id": relation.lab_course_id,
                    "lab_code": course_map[relation.lab_course_id].code,
                    "mandatory": relation.mandatory}
            by_lab[relation.course_id].append(data)
    output = []
    for row in rows:
        data = serialize_course(row, by_course[row.id], by_eq[row.id])
        data["source_document"] = documents.get(row.source_document_id)
        data["lab_relationships"] = by_lab[row.id]
        data["available_section_languages"] = sorted(offering_languages[row.id])
        output.append(data)
    return output


def register_source_documents(session: Session, directory: Path) -> None:
    if not directory.exists(): return
    for path in directory.glob("*"):
        if not path.is_file(): continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if session.scalar(select(SourceDocument).where(SourceDocument.sha256 == digest)): continue
        kind = "TIMETABLE" if "timetable" in path.name.lower() else "CURRICULUM"
        doc = SourceDocument(filename=path.name, kind=kind, sha256=digest,
                             status="PENDING_REVIEW",
                             notes="Located locally; not committed as verified data.")
        session.add(doc); session.flush()
        batch = ImportBatch(source_document_id=doc.id, status="AWAITING_REVIEW")
        session.add(batch); session.flush()
        session.add(ImportCandidate(batch_id=batch.id, record_type="DOCUMENT",
                                    action="AMBIGUOUS", payload={"filename": path.name},
                                    errors=["Source requires human verification before commit."]))


def replace_active_term(session: Session, year: int, semester: str) -> ActiveTerm:
    active = session.get(ActiveTerm, 1)
    if active.academic_year_start != year or active.semester != semester:
        active.academic_year_start, active.semester = year, semester
        active.generation += 1
    return active

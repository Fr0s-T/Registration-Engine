"""Durable OLD-to-NEW transition-catalogue coverage."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from academic_planner.database.models import (
    CourseRecord, CurriculumRevision, Equivalency, TransitionCourseDisposition,
    TranscriptCodeMapping,
)


# Stable course-code crosswalk.  Integer course IDs are intentionally resolved
# only after each import because curriculum replacement recreates those IDs.
IUL_OLD_TO_NEW_EQUIVALENCIES: tuple[tuple[str, str], ...] = (
    ("ELCM119", "MAT230"),
    ("ELCM120", "MAT220"),
    ("ELCM121", "PHY224"),
    ("ELCM122", "CSC230"),
    ("ELCM123", "GRD204"),
    ("ELCM203", "MAT224"),
    ("ELCM211", "CSC320"),
    ("ELCM212", "MAT231"),
    ("ELCM215", "PHY234"),
    ("ELCM216", "PHY235"),
    ("ELCM217", "CHM224"),
    ("DRH310", "GER310"),
    ("SOC221", "GER224"),
    ("ELBC401", "CCE330"),
    ("ELBC403", "CCE341"),
    ("ELBC404", "CCE340"),
    ("ELBC503", "CCE451"),
    ("ELBC504", "CCE450"),
    ("ELBC701", "CCE552"),
    ("ELBC801", "CCE431"),
    ("ELBC803", "CCE562"),
    ("ELBC901", "CCE640"),
    ("ELCC410", "CSC340"),
    ("ELCC523", "CCE430"),
    ("ELCC524", "CCE440"),
    ("ELCC608", "CCE471"),
    ("ELCC619", "CCE442"),
    ("ELCC620", "CSC437"),
    ("ELCC623", "CCE443"),
    ("ELCC627", "CCE471"),
    ("ELCC630", "CCE420"),
    ("ELCC631", "CCE432"),
    ("ELCC632", "CCE441"),
    ("ELCC711", "CCE550"),
    ("ELCC712", "CCE551"),
    ("ELCC722", "CCE541"),
    ("ELCC724", "CCE560"),
    ("ELCC812", "CCE555"),
    ("ELCC819", "CCE572"),
    ("ELCC820", "CCE563"),
    ("ELCC823", "CCE561"),
    ("ELCC825", "CCE553"),
    ("ELCC914", "CCE653"),
    ("ELCC916", "CCE651"),
    ("ELCC919", "CCE655"),
    ("ELCC923", "CCE652"),
    ("ELCC1011", "CCE657"),
    ("ELCC1017", "CCE556"),
    ("ELCM312", "CSC333"),
    ("ELCM317", "MAT331"),
    ("ELCM318", "STA222"),
    ("ELCM320", "PHY334"),
    ("ELCM412", "MAT343"),
    ("ELCM700", "GER225"),
)

# Transcript labels used by the portal/transfer record that differ from the
# active NEW catalogue code.  These are identity aliases, not extra earned
# credit and not speculative OLD-to-NEW course equivalencies.
IUL_TRANSCRIPT_CODE_ALIASES: tuple[tuple[str, str, str], ...] = (
    (
        "REL312", "GER312",
        "Transferred Culture, Moral, Religion: exact title and 2-ECTS match.",
    ),
    (
        "DRH320", "GER333",
        "Transferred Ethics of the Profession: Professional Ethics, 2 ECTS.",
    ),
)


def _active_courses(session: Session) -> tuple[list[CourseRecord], list[CourseRecord]]:
    courses = list(session.scalars(
        select(CourseRecord).join(CurriculumRevision).where(
            CurriculumRevision.active.is_(True)
        )
    ))
    return (
        [course for course in courses if course.curriculum.version == "OLD"],
        [course for course in courses if course.curriculum.version == "NEW"],
    )


def synchronize_transition_catalogue(session: Session) -> None:
    """Rebind the curated code crosswalk and explicitly dispose every OLD course."""
    old, new = _active_courses(session)
    old_by_code = {course.code: course for course in old}
    new_by_code = {course.code: course for course in new}
    transcript_mappings = {
        row.source_code: row
        for row in session.scalars(select(TranscriptCodeMapping))
    }
    for source_code, target_code, notes in IUL_TRANSCRIPT_CODE_ALIASES:
        target = new_by_code.get(target_code)
        if target is None:
            continue
        mapping = transcript_mappings.get(source_code)
        if mapping is None:
            session.add(TranscriptCodeMapping(
                source_code=source_code,
                target_course_id=target.id,
                mapping_kind="COURSE_ALIAS",
                verification_status="HUMAN_VERIFIED",
                provenance="SOURCE_REVIEW",
                notes=notes,
            ))
        else:
            mapping.target_course_id = target.id
            mapping.mapping_kind = "COURSE_ALIAS"
            mapping.verification_status = "HUMAN_VERIFIED"
            mapping.provenance = "SOURCE_REVIEW"
            mapping.notes = notes
    existing_rows = {
        (row.source_course_id, row.target_course_id): row
        for row in session.scalars(select(Equivalency))
    }
    for old_code, new_code in IUL_OLD_TO_NEW_EQUIVALENCIES:
        source, target = old_by_code.get(old_code), new_by_code.get(new_code)
        if source is None or target is None:
            continue
        row = existing_rows.get((source.id, target.id))
        if row is None:
            session.add(Equivalency(
                source_course_id=source.id,
                target_course_id=target.id,
                recognizes_history=True,
                prospective_registration_allowed=True,
                verification_status="HUMAN_VERIFIED",
                provenance="CURATED_TRANSITION_CATALOGUE",
                notes=(
                    "IUL OLD-to-NEW transition crosswalk. Historical earned ECTS "
                    "are preserved; approved final-year rollout substitutions are "
                    "explicitly marked for prospective registration."
                ),
            ))
        else:
            row.prospective_registration_allowed = True
    session.flush()

    mapped_sources = set(session.scalars(select(Equivalency.source_course_id)))
    if mapped_sources:
        session.execute(delete(TransitionCourseDisposition).where(
            TransitionCourseDisposition.old_course_id.in_(mapped_sources)
        ))
    disposed = set(session.scalars(select(
        TransitionCourseDisposition.old_course_id
    )))
    for course in old:
        if course.id in mapped_sources or course.id in disposed:
            continue
        pathway = course.is_fyp
        session.add(TransitionCourseDisposition(
            old_course_id=course.id,
            disposition="PATHWAY_SPECIFIC" if pathway else "LEGACY_CREDIT_ONLY",
            notes=(
                "Handled by the registered FYP pathway policy; no direct NEW "
                "course substitution is applied."
                if pathway else
                "No direct NEW mapping exists in the curated crosswalk. Earned "
                "source ECTS remain valid without satisfying another course."
            ),
        ))
    session.flush()


def transition_catalogue_gaps(session: Session) -> tuple[CourseRecord, ...]:
    """Return active OLD courses with neither equivalency nor explicit disposition."""
    old, _new = _active_courses(session)
    mapped = set(session.scalars(select(Equivalency.source_course_id)))
    disposed = set(session.scalars(select(
        TransitionCourseDisposition.old_course_id
    )))
    return tuple(sorted(
        (course for course in old if course.id not in mapped | disposed),
        key=lambda course: course.code,
    ))


def transition_catalogue_coverage(session: Session) -> dict[str, object]:
    old, _new = _active_courses(session)
    old_ids = {course.id for course in old}
    mapped = set(session.scalars(select(Equivalency.source_course_id))) & old_ids
    dispositions = list(session.scalars(select(TransitionCourseDisposition).where(
        TransitionCourseDisposition.old_course_id.in_(old_ids)
    ))) if old_ids else []
    gaps = transition_catalogue_gaps(session)
    return {
        "active_old_courses": len(old),
        "direct_historical_equivalencies": len(mapped),
        "legacy_credit_only": sum(
            item.disposition == "LEGACY_CREDIT_ONLY" for item in dispositions
        ),
        "pathway_specific": sum(
            item.disposition == "PATHWAY_SPECIFIC" for item in dispositions
        ),
        "uncovered_old_courses": len(gaps),
        "uncovered_old_course_codes": [course.code for course in gaps],
        "complete": not gaps,
    }


def require_complete_transition_catalogue(session: Session) -> None:
    gaps = transition_catalogue_gaps(session)
    if gaps:
        codes = ", ".join(course.code for course in gaps)
        raise ValueError(
            "Transition catalogue is incomplete; OLD courses lack an accepted "
            f"equivalency or explicit legacy disposition: {codes}"
        )

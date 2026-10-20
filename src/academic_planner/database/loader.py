"""Translate active persisted records into the optimizer's immutable input model."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from academic_planner.domain.models import (
    AcademicTerm, AcademicTrackPolicy, Course, CourseEquivalency, CourseOffering, Curriculum,
    CurriculumVersion, DataProvenance, LanguageTrack, Meeting, PlanningConfiguration,
    PrerequisiteRule, RegistrationBundle, Section, StudentAcademicState, TermKind,
    Weekday,
)
from academic_planner.optimization import PlanningProblem

from .models import (
    ActiveTerm, CourseRecord, CurriculumRevision, DegreeRequirement, EngineSetting,
    Equivalency, Offering, PrerequisiteGroup, SectionRecord, TermCapacityOverride,
)


def _provenance(value: str) -> DataProvenance:
    """Map persistence provenance labels to the smaller planning-domain enum."""
    if value == "SYNTHETIC_TEST_FIXTURE": return DataProvenance.SYNTHETIC_UNVERIFIED
    if value == "SYNTHETIC_PLACEHOLDER": return DataProvenance.SYNTHETIC_PLACEHOLDER
    if value == "MANUAL_CORRECTION": return DataProvenance.USER_SUPPLIED
    return DataProvenance.UNSPECIFIED


class DatabasePlanningLoader:
    """Load active catalog, policy, offering, and horizon data for one student."""

    def load_problem(
        self,
        session: Session,
        student: StudentAcademicState,
        curriculum_version: str = "NEW",
    ) -> PlanningProblem:
        """Build a planning problem without mutating source rows.

        Ambiguous and OR prerequisite groups are rejected explicitly because the
        optimizer currently supports only conjunctive prerequisite sets. Future
        offerings intentionally contain availability but no fabricated sections.
        """
        revisions = session.scalars(select(CurriculumRevision).where(
            CurriculumRevision.active.is_(True))).all()
        revision = next((r for r in revisions if r.version == curriculum_version), None)
        if revision is None: raise ValueError(f"No active {curriculum_version} curriculum revision")
        rows = session.scalars(
            select(CourseRecord)
            .join(CurriculumRevision)
            .where(CurriculumRevision.active.is_(True))
            .options(selectinload(CourseRecord.curriculum))
        ).all()
        courses = {
            str(row.id): Course(str(row.id), row.code, row.title, row.ects,
                CurriculumVersion(row.curriculum.version), row.reference_year,
                TermKind(row.reference_semester),
                row.is_fyp, _provenance(row.provenance),
                AcademicTrackPolicy(row.academic_track_policy),
                frozenset(LanguageTrack(track) for track in (row.permitted_student_tracks or [])))
            for row in rows
        }
        requirements = session.scalars(select(DegreeRequirement).where(
            DegreeRequirement.curriculum_id == revision.id)).all()
        requirement_ids = frozenset(str(r.course_id) for r in requirements)
        language_requirements = {
            track: frozenset(str(r.course_id) for r in requirements
                             if r.language_track == track.value)
            for track in LanguageTrack
        }
        curriculum = Curriculum(CurriculumVersion(curriculum_version), requirement_ids,
            revision.accepted_credit_target,
            next((str(r.course_id) for r in requirements if r.requirement_type == "FYP"), None),
            frozenset(str(r.course_id) for r in requirements if r.requirement_type == "TRAINING"),
            language_requirements)
        groups = session.scalars(select(PrerequisiteGroup).options(
            selectinload(PrerequisiteGroup.items))).all()
        # The proven engine supports AND sets. OR groups stay explicit in storage and are rejected
        # here instead of being silently weakened.
        selected_course_ids = {row.id for row in rows if row.curriculum_id == revision.id}
        selected_groups = [g for g in groups if g.course_id in selected_course_ids]
        unsupported = [g.id for g in selected_groups if g.logic == "OR" or g.ambiguous]
        if unsupported: raise ValueError(f"Ambiguous or OR prerequisite groups require review before solving: {unsupported}")
        prereqs = tuple(PrerequisiteRule(str(g.course_id),
            frozenset(str(i.prerequisite_course_id) for i in g.items),
            _provenance(g.provenance)) for g in selected_groups)
        eqs = session.scalars(select(Equivalency).where(
            Equivalency.recognizes_history.is_(True),
            Equivalency.verification_status.in_([
                "AUTO_MATCHED", "HUMAN_VERIFIED", "OFFICIALLY_DOCUMENTED", "VERIFIED",
            ]),
        )).all()
        equivalencies = tuple(CourseEquivalency(
            str(e.id), frozenset({str(e.source_course_id)}),
            frozenset({str(e.target_course_id)}), _provenance(e.provenance),
            e.prospective_registration_allowed is True,
        ) for e in eqs)
        active = session.get(ActiveTerm, 1)
        current = AcademicTerm(active.academic_year_start, TermKind(active.semester))
        settings = {s.key: s.value for s in session.scalars(select(EngineSetting)).all()}
        count = int(settings.get("max_horizon_semesters", 20))
        horizon = []
        year, kind = current.academic_year_start, current.kind
        regular_count = 0
        while regular_count < count:
            horizon.append(AcademicTerm(year, kind))
            if kind is TermKind.FALL:
                regular_count += 1
                kind = TermKind.SPRING
            elif kind is TermKind.SPRING:
                regular_count += 1
                horizon.extend((AcademicTerm(year, TermKind.TRAINING_1),
                                AcademicTerm(year, TermKind.TRAINING_2)))
                year += 1
                kind = TermKind.FALL
        offerings = []
        active_rows = session.scalars(select(Offering).where(
            Offering.academic_year_start == active.academic_year_start,
            Offering.semester == active.semester).options(
                selectinload(Offering.sections).selectinload(SectionRecord.meetings))).all()
        allow_cross_track = bool(settings.get("allow_cross_track_shared_sections", False))
        active_bundles = defaultdict(list)
        active_provenance = {}
        active_verified = {}
        for row in active_rows:
            course = courses[str(row.course_id)]
            home_or_neutral = row.language_track in {None, student.language_track.value}
            alternate_shared = (
                allow_cross_track
                and row.language_track in {track.value for track in LanguageTrack}
                and row.language_track != student.language_track.value
                and course.academic_track_policy is AcademicTrackPolicy.SHARED
                and student.language_track in course.permitted_student_tracks
            )
            if not (home_or_neutral or alternate_shared):
                continue
            by_bundle = defaultdict(list)
            for sec in row.sections:
                by_bundle[sec.bundle_key].append(Section(
                    sec.code, str(row.course_id), sec.component, sec.campus or "",
                    tuple(Meeting(Weekday(m.weekday), m.start_minute, m.end_minute)
                          for m in sec.meetings), None, _provenance(row.provenance),
                    LanguageTrack(row.language_track) if row.language_track else None))
            active_bundles[str(row.course_id)].extend(
                RegistrationBundle(f"{row.id}:{key}", str(row.course_id), tuple(sections))
                for key, sections in by_bundle.items()
            )
            active_provenance[str(row.course_id)] = _provenance(row.provenance)
            active_verified[str(row.course_id)] = (
                active_verified.get(str(row.course_id), True)
                and row.verification_status in {"VERIFIED", "SOURCE_IMPORTED"}
            )
        for course_id, bundles in active_bundles.items():
            offerings.append(CourseOffering(course_id, current, tuple(bundles),
                active_verified[course_id], active_provenance[course_id]))
        # Future offerings intentionally have no fabricated sections.
        future_mode = settings.get("future_offering_assumption", "REFERENCE_SEMESTER")
        if future_mode not in {"REFERENCE_SEMESTER", "NONE"}:
            raise ValueError(f"Unsupported future offering assumption: {future_mode}")
        if future_mode == "REFERENCE_SEMESTER":
            for course in courses.values():
                for term in horizon[1:]:
                    if term.kind is course.reference_semester:
                        offerings.append(CourseOffering(course.id, term, (), False, course.provenance))
        capacities = {}
        for override in session.scalars(select(TermCapacityOverride)).all():
            capacities[AcademicTerm(override.academic_year_start, TermKind(override.semester))] = override.capacity
        for term in horizon:
            if term.kind is TermKind.TRAINING_1:
                capacities.setdefault(term, int(settings.get("training_1_capacity", 5)))
            elif term.kind is TermKind.TRAINING_2:
                capacities.setdefault(term, int(settings.get("training_2_capacity", 5)))
        config = PlanningConfiguration(
            term_credit_capacities=capacities,
            default_credit_capacity=int(settings.get("default_credit_capacity", 30)),
            planning_horizon=tuple(horizon), time_limit_seconds=float(settings.get("solver_time_limit_seconds", 20)),
            academic_year_deviation_weight=int(settings.get("academic_year_deviation_weight", 10)),
            reference_semester_deviation_weight=int(settings.get("reference_semester_deviation_weight", 2)),
            allow_training_postponement=bool(settings.get("allow_training_postponement", True)),
            training_delay_penalty=int(settings.get("training_delay_penalty", 10)),
            max_training_delay_years=settings.get("max_training_delay_years"),
            initial_horizon_semesters=int(settings.get("initial_horizon_semesters", 10)),
            max_horizon_semesters=count,
            auto_extend_horizon=bool(settings.get("auto_extend_horizon", True)),
            horizon_extension_step=int(settings.get("horizon_extension_step", 2)),
            allow_extended_load_when_repeating_failed_course=bool(settings.get("allow_extended_load_when_repeating_failed_course", False)),
            extended_failed_repeat_capacity=int(settings.get("extended_failed_repeat_capacity", 36)),
            allow_final_two_semester_graduation_load=bool(settings.get("allow_final_two_semester_graduation_load", True)),
            final_two_semester_graduation_capacity=int(settings.get("final_two_semester_graduation_capacity", 36)),
            explicit_capacity_override_terms=frozenset(capacities),
            allow_cross_track_shared_sections=allow_cross_track,
            prefer_own_track_sections=bool(settings.get("prefer_own_track_sections", True)),
        )
        return PlanningProblem(courses, curriculum, student, equivalencies,
                               prereqs, tuple(offerings), config)

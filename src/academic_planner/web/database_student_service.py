"""One data-driven planning path for every persisted student scenario."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from academic_planner.database.loader import DatabasePlanningLoader
from academic_planner.database.models import (
    CourseRecord, CourseRequirementGroupRecognition, CurriculumRevision, DegreeContract, EngineSetting, Equivalency,
    RequirementGroupRecord, StudentAttemptRecord, StudentRecord,
    StudentCapacityOverride, StudentRequirementRecord, TranscriptCodeMapping,
)
from academic_planner.database.session import session_scope
from academic_planner.domain.models import (
    AcademicTerm, ApprovalStatus, AttemptStatus, CourseOffering,
    CreditRequirementGroup, Curriculum, CurriculumVersion, DataProvenance,
    LanguageTrack, OptionalCreditApproval, RegistrationBundle,
    RequirementClassification, Section, StudentAcademicState, TermKind,
)
from academic_planner.eligibility import EligibilityEngine
from academic_planner.fixtures.synthetic import RELAXED_FIXTURE
from academic_planner.matching import (
    require_complete_transition_catalogue, transition_catalogue_coverage,
)
from academic_planner.optimization import GlobalPlanner
from academic_planner.planning import AcademicPlanningEngine, apply_registered_fyp_track
from academic_planner.policies import (
    CatalogRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy,
)
from academic_planner.requirement_delivery import requirement_delivery_options
from academic_planner.transcripts import (
    canonical_course_credit_identities, normalize_attempt_rows,
)
from academic_planner.web.schemas import (
    ClassifiedCourseResponse, PlanRequest, PlanResponse, ScenarioResponse,
)
from academic_planner.web.services import PlanningWebService, _course_response


def _term(source: str) -> AcademicTerm:
    """Parse the persisted transcript-period labels used by source fixtures."""
    if source.startswith("FALL"):
        return AcademicTerm(int(source[-4:]), TermKind.FALL)
    if source.startswith("SPRING"):
        return AcademicTerm(int(source[-4:]) - 1, TermKind.SPRING)
    if source.startswith("SUMMERI"):
        return AcademicTerm(int(source[-4:]) - 1, TermKind.TRAINING_2)
    if source.startswith("SUMMER"):
        return AcademicTerm(int(source[-4:]) - 1, TermKind.TRAINING_1)
    raise ValueError(f"Unsupported transcript term: {source}")


class DatabaseStudentPlanningService:
    """Plans any student record without identifier- or course-specific branches."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier

    def _record(self, session) -> StudentRecord:
        record = session.scalar(select(StudentRecord).where(
            StudentRecord.identifier == self.identifier,
            StudentRecord.active.is_(True),
        ))
        if record is None:
            raise ValueError(f"Database student scenario is not configured: {self.identifier}")
        return record

    def _student(self, session, record: StudentRecord):
        """Normalize persisted attempts while retaining unresolved source credit."""
        rows = list(session.scalars(select(StudentAttemptRecord).where(
            StudentAttemptRecord.student_id == record.id
        ).order_by(StudentAttemptRecord.id)))
        mappings = list(session.scalars(select(TranscriptCodeMapping)))
        courses = list(session.scalars(
            select(CourseRecord).options(selectinload(CourseRecord.curriculum))
        ))
        equivalencies = list(session.scalars(select(Equivalency).where(
            Equivalency.recognizes_history.is_(True),
            Equivalency.verification_status.in_([
                "AUTO_MATCHED", "HUMAN_VERIFIED", "OFFICIALLY_DOCUMENTED",
                "VERIFIED",
            ]),
        )))
        credit_identities = canonical_course_credit_identities(
            {
                course.id: (course.curriculum.version, course.code)
                for course in courses
            },
            (
                (equivalency.source_course_id, equivalency.target_course_id)
                for equivalency in equivalencies
            ),
        )
        normalized = normalize_attempt_rows(
            rows,
            _term,
            course_id_by_source_code={
                row.source_code: row.target_course_id
                for row in mappings if row.mapping_kind == "COURSE_ALIAS"
            },
            credit_identity_by_course_id=credit_identities,
            separate_source_identity_codes=frozenset(
                row.source_code
                for row in mappings if row.mapping_kind == "COURSE_ALIAS"
            ),
            recognized_non_degree_codes=frozenset(
                row.source_code
                for row in mappings if row.mapping_kind == "NON_DEGREE"
            ),
        )
        student = StudentAcademicState(
            record.nominal_year, LanguageTrack(record.language_track), normalized.attempts,
            earned_credits=normalized.unresolved_earned_credits,
        )
        return student, normalized

    def scenario_summary(self) -> ScenarioResponse:
        """Describe this persisted student without running the optimizer."""
        with session_scope() as session:
            record = self._record(session)
            _student, normalized = self._student(session, record)
            training_correction = session.scalar(
                select(StudentAttemptRecord.notes).where(
                    StudentAttemptRecord.student_id == record.id,
                    StudentAttemptRecord.source_title.ilike("%Training II%"),
                    StudentAttemptRecord.evidence_status
                    == "USER_CONFIRMED_PROVISIONAL",
                ).limit(1)
            )
            return ScenarioResponse(
                identifier=record.identifier,
                description=(
                    "Persisted scenario using the shared database planner"
                ),
                nominal_year=record.nominal_year,
                language_track=record.language_track,
                curriculum_version=record.governing_curriculum_version,
                starting_term="2026-2027 FALL",
                completed_credits=normalized.completed_credits,
                remaining_credits=max(
                    0, record.graduation_credit_target - normalized.completed_credits
                ),
                available_terms=[
                    f"{year}-{year + 1} {semester}"
                    for year in range(2026, 2036)
                    for semester in ("FALL", "SPRING")
                ],
                fixture_prerequisites="DATABASE",
                fixture_timetable="DATABASE_ACTIVE_TERM",
                student_type="Persisted shared-engine scenario",
                original_reported_earned_credits=record.reported_earned_credits,
                adjusted_source_credits=normalized.completed_credits,
                training_ii_correction=training_correction,
            )

    @staticmethod
    def _configure(problem, request: PlanRequest):
        config = problem.configuration
        labels = {term.label(): term for term in config.planning_horizon}
        unknown = set(request.per_semester_capacity_overrides) - labels.keys()
        if unknown:
            raise ValueError(f"Unknown term override(s): {', '.join(sorted(unknown))}")
        capacities = dict(config.term_credit_capacities)
        capacities.update({
            labels[label]: capacity
            for label, capacity in request.per_semester_capacity_overrides.items()
        })
        overrides = {
            config_name: value
            for config_name, value in {
                "default_credit_capacity": request.regular_credit_capacity,
                "academic_year_deviation_weight": request.academic_year_deviation_weight,
                "reference_semester_deviation_weight": request.reference_semester_deviation_weight,
                "allow_training_postponement": request.allow_training_postponement,
                "training_delay_penalty": request.training_delay_penalty,
                "max_training_delay_years": request.max_training_delay_years,
                "time_limit_seconds": request.solver_time_limit_seconds,
                "initial_horizon_semesters": request.initial_horizon_semesters,
                "max_horizon_semesters": request.max_horizon_semesters,
                "auto_extend_horizon": request.auto_extend_horizon,
                "horizon_extension_step": request.horizon_extension_step,
                "allow_extended_load_when_repeating_failed_course": (
                    request.allow_extended_load_when_repeating_failed_course
                ),
                "allow_final_two_semester_graduation_load": (
                    request.allow_final_two_semester_graduation_load
                ),
            }.items()
            if value is not None
        }
        if "max_training_delay_years" in request.model_fields_set:
            overrides["max_training_delay_years"] = request.max_training_delay_years
        return replace(problem, configuration=replace(
            config,
            **overrides,
            term_credit_capacities=capacities,
            explicit_capacity_override_terms=frozenset(
                set(config.explicit_capacity_override_terms)
                | {labels[label] for label in request.per_semester_capacity_overrides}
            ),
        ))

    @staticmethod
    def _classified(problem, item, approval_by_id, selected_optional):
        course = problem.courses[item.course_id]
        approval = approval_by_id.get(item.course_id)
        return ClassifiedCourseResponse(
            **_course_response(course).model_dump(),
            classification=item.classification.value,
            explanation=item.explanation,
            credit_category=item.category,
            approval_status=item.approval_status.value if item.approval_status else None,
            approval_authority=approval.authority if approval else None,
            approval_source=approval.source_reference if approval else None,
            selected_for_graduation=item.course_id in selected_optional,
        )

    def plan(self, request: PlanRequest) -> PlanResponse:
        """Load, reconcile, optimize, and serialize one persisted student."""
        with session_scope() as session:
            record = self._record(session)
            if record.governing_curriculum_version == "OLD":
                require_complete_transition_catalogue(session)
            catalogue_coverage = transition_catalogue_coverage(session)
            student, normalized = self._student(session, record)
            governing_version = CurriculumVersion(
                record.governing_curriculum_version
            )
            problem = DatabasePlanningLoader().load_problem(
                session, student, governing_version.value
            )
            student_requirement_rows = list(session.scalars(
                select(StudentRequirementRecord).where(
                    StudentRequirementRecord.student_id == record.id
                )
            ))
            contract = None
            contract_groups = []
            contract_recognized_credits: dict[str, int] = {}
            contract_recognition_basis: dict[str, list[str]] = {}
            contract_candidate_credits: dict[str, dict[str, int]] = {}
            requirement_ids = problem.curriculum.requirement_ids | frozenset(
                str(row.course_id) for row in student_requirement_rows
            )
            if (
                governing_version is CurriculumVersion.NEW
                and record.degree_contract_id is not None
            ):
                contract = session.scalar(
                    select(DegreeContract)
                    .where(DegreeContract.id == record.degree_contract_id)
                    .options(
                        selectinload(DegreeContract.groups)
                        .selectinload(RequirementGroupRecord.memberships)
                    )
                )
                if contract is None:
                    raise ValueError("student references a missing degree contract")
                contract_groups = sorted(contract.groups, key=lambda group: group.display_order)
                by_group_id = {group.id: group for group in contract_groups}

                def root_of(group):
                    while group.parent_id is not None:
                        group = by_group_id[group.parent_id]
                    return group

                roots = {
                    group.code: group for group in contract_groups
                    if group.parent_id is None
                }
                broad_recognitions = {
                    str(row.source_course_id): root_of(by_group_id[row.requirement_group_id]).code
                    for row in session.scalars(
                        select(CourseRequirementGroupRecognition).where(
                            CourseRequirementGroupRecognition.requirement_group_id.in_(
                                by_group_id
                            )
                        )
                    )
                }
                course_root: dict[str, str] = {}
                for group in contract_groups:
                    root = root_of(group)
                    for item in group.memberships:
                        if item.language_track not in {None, record.language_track}:
                            continue
                        course_root[str(item.course_id)] = root.code
                        if root.code != "CAPSTONE":
                            contract_candidate_credits.setdefault(root.code, {})[
                                str(item.course_id)
                            ] = item.contribution_ects

                # The capstone is pathway-specific rather than a fungible
                # category: a registered OLD FYP I locks the student into OLD
                # FYP I + II through apply_registered_fyp_track below.
                requirement_ids = frozenset(
                    str(item.course_id)
                    for group in contract_groups
                    if root_of(group).code == "CAPSTONE"
                    for item in group.memberships
                    if item.language_track in {None, record.language_track}
                )

                equivalency_targets = {
                    source: target
                    for equivalency in problem.equivalencies
                    for source in equivalency.source_course_ids
                    for target in equivalency.target_requirement_ids
                }
                earned_by_identity: dict[str, tuple[str, int]] = {}
                for attempt in student.attempts:
                    if not attempt.status.satisfies_requirement:
                        continue
                    identity = attempt.credit_identity or attempt.course_id
                    previous = earned_by_identity.get(identity)
                    if previous is None or attempt.earned_credits > previous[1]:
                        earned_by_identity[identity] = (attempt.course_id, attempt.earned_credits)
                recognized = {code: 0 for code in roots if code != "CAPSTONE"}
                bases = {code: [] for code in recognized}
                for _identity, (course_id, earned) in earned_by_identity.items():
                    if earned <= 0:
                        continue
                    target = equivalency_targets.get(course_id, course_id)
                    root_code = course_root.get(target)
                    basis = "direct or exact equivalency"
                    if root_code is None:
                        root_code = broad_recognitions.get(course_id)
                        basis = "persisted inferred same-category legacy credit"
                    if root_code in recognized:
                        recognized[root_code] += earned
                        bases[root_code].append(
                            f"{problem.courses[course_id].code if course_id in problem.courses else course_id}: {earned} ECTS ({basis})"
                        )
                contract_recognized_credits = {
                    code: min(roots[code].required_ects, credits)
                    for code, credits in recognized.items()
                }
                contract_recognition_basis = bases

                # Approved current OLD delivery may satisfy the same contract
                # category prospectively without pretending it is a second
                # independent degree requirement.
                for equivalency in problem.equivalencies:
                    if not equivalency.prospective_registration_allowed:
                        continue
                    for source in equivalency.source_course_ids:
                        for target in equivalency.target_requirement_ids:
                            root_code = course_root.get(target)
                            if root_code in contract_candidate_credits and source in problem.courses:
                                contract_candidate_credits[root_code][source] = problem.courses[source].credits
            fyp_ids = sorted(
                cid for cid in requirement_ids
                if cid in problem.courses and problem.courses[cid].is_fyp
            )
            problem = replace(problem, curriculum=Curriculum(
                governing_version, requirement_ids,
                accepted_credit_target=(
                    contract.graduation_ects_target if contract
                    else record.graduation_credit_target
                ),
                fyp_requirement_id=fyp_ids[-1] if fyp_ids else None,
            ))
            problem, fyp_pathway = apply_registered_fyp_track(problem)
            if contract:
                approvals = tuple(
                    OptionalCreditApproval(
                        course_id, root_code, ApprovalStatus.APPROVED,
                        "OFFICIAL_CCE_DEGREE_CONTRACT",
                        f"{contract.effective_academic_year}:{root_code}",
                        "Candidate in a source-imported contract category.",
                    )
                    for root_code, candidates in contract_candidate_credits.items()
                    for course_id in candidates
                )
                credit_groups = tuple(CreditRequirementGroup(
                    root_code,
                    next(group.title for group in contract_groups if group.code == root_code),
                    next(group.required_ects for group in contract_groups if group.code == root_code),
                    candidates,
                    contract_recognized_credits.get(root_code, 0),
                ) for root_code, candidates in contract_candidate_credits.items())
                problem = replace(
                    problem,
                    optional_credit_approvals=approvals,
                    credit_requirement_groups=credit_groups,
                    allow_credit_adjustment_proposal=False,
                )
            elif not contract:
                non_degree_codes = select(TranscriptCodeMapping.source_code).where(
                    TranscriptCodeMapping.mapping_kind == "NON_DEGREE"
                )
                optional_rows = list(session.scalars(
                    select(CourseRecord)
                    .join(CurriculumRevision)
                    .where(
                        CurriculumRevision.active.is_(True),
                        CourseRecord.graduation_role == "OPTIONAL",
                        CourseRecord.ects.between(1, 4),
                        CourseRecord.course_type.notin_(("TRAINING", "FINAL_PROJECT")),
                        CourseRecord.is_fyp.is_(False),
                        CourseRecord.code.notin_(non_degree_codes),
                    )
                ))
                approvals = tuple(OptionalCreditApproval(
                    str(row.id), "CREDIT_BAND_OPTIONAL", ApprovalStatus.APPROVED,
                    "IUL_300_ECTS_CREDIT_BAND_POLICY",
                    "CATALOG_ROLE_OPTIONAL_1_TO_4_ECTS",
                    "Legacy fallback optional pool; no degree contract is assigned.",
                ) for row in optional_rows)
                problem = replace(
                    problem, optional_credit_approvals=approvals,
                    allow_credit_adjustment_proposal=True,
                )
            else:
                approvals = ()
                problem = replace(
                    problem,
                    optional_credit_approvals=(),
                    credit_requirement_groups=(),
                    allow_credit_adjustment_proposal=False,
                )

            verified_capacity_rows = list(session.scalars(
                select(StudentCapacityOverride).where(
                    StudentCapacityOverride.student_id == record.id,
                    StudentCapacityOverride.verified.is_(True),
                )
            ))
            if verified_capacity_rows:
                persisted_capacities = dict(problem.configuration.term_credit_capacities)
                persisted_terms = set(problem.configuration.explicit_capacity_override_terms)
                horizon_terms = {
                    (term.academic_year_start, term.kind.value): term
                    for term in problem.configuration.planning_horizon
                }
                for row in verified_capacity_rows:
                    term = horizon_terms.get((row.academic_year_start, row.semester))
                    if term is not None:
                        persisted_capacities[term] = row.capacity
                        persisted_terms.add(term)
                problem = replace(problem, configuration=replace(
                    problem.configuration,
                    term_credit_capacities=persisted_capacities,
                    explicit_capacity_override_terms=frozenset(persisted_terms),
                ))
            problem = self._configure(problem, request)

            current = problem.configuration.planning_horizon[0]
            observed_current = {
                attempt.course_id: problem.courses[attempt.course_id].credits
                for attempt in student.attempts
                if attempt.term == current
                and attempt.status in {
                    AttemptStatus.REGISTERED, AttemptStatus.IN_PROGRESS,
                }
                and attempt.course_id in problem.courses
                and problem.courses[attempt.course_id].credits > 0
            }
            keep_current_registration = (
                request.registration_mode == "KEEP_CURRENT" and bool(observed_current)
            )
            observed_offerings_added: list[str] = []
            if keep_current_registration:
                offerings = list(problem.offerings)
                for course_id in observed_current:
                    has_schedulable_offering = any(
                        offering.course_id == course_id
                        and offering.term == current
                        and offering.bundles
                        for offering in offerings
                    )
                    if has_schedulable_offering:
                        continue
                    offerings = [
                        offering for offering in offerings
                        if not (
                            offering.course_id == course_id
                            and offering.term == current
                        )
                    ]
                    observed_section = Section(
                        crn=f"OBSERVED-{course_id}",
                        course_id=course_id,
                        component="REGISTERED",
                        campus="",
                        meetings=(),
                        provenance=DataProvenance.USER_SUPPLIED,
                    )
                    offerings.append(CourseOffering(
                        course_id=course_id,
                        term=current,
                        bundles=(RegistrationBundle(
                            id=f"observed-registration-{course_id}",
                            course_id=course_id,
                            sections=(observed_section,),
                        ),),
                        availability_verified=True,
                        provenance=DataProvenance.USER_SUPPLIED,
                    ))
                    observed_offerings_added.append(course_id)
                capacities = dict(problem.configuration.term_credit_capacities)
                observed_ects = sum(observed_current.values())
                capacities[current] = max(
                    problem.configuration.capacity_for(current), observed_ects
                )
                problem = replace(
                    problem,
                    offerings=tuple(offerings),
                    configuration=replace(
                        problem.configuration,
                        term_credit_capacities=capacities,
                        forced_course_terms={
                            **problem.configuration.forced_course_terms,
                            **{course_id: current for course_id in observed_current},
                        },
                        authoritative_course_terms={
                            **problem.configuration.authoritative_course_terms,
                            **{course_id: current for course_id in observed_current},
                        },
                        locked_term_course_ids={
                            **problem.configuration.locked_term_course_ids,
                            current: frozenset(observed_current),
                        },
                    ),
                )

            rollout_start = int(session.get(
                EngineSetting, "new_curriculum_rollout_first_year_start"
            ).value)
            rollout = ProgressiveRolloutPolicy(rollout_start)
            registration = CatalogRegistrationPolicy()
            planner = GlobalPlanner(ConfiguredCreditLimitPolicy(), rollout, registration)
            current_offered = frozenset(
                offering.course_id for offering in problem.offerings
                if offering.term == current
            )
            review_course_ids = frozenset()
            if governing_version is CurriculumVersion.NEW:
                authorized_sources = frozenset(
                    source for equivalency in problem.equivalencies
                    for source in equivalency.source_course_ids
                )
                completed_old = frozenset(
                    attempt.course_id for attempt in student.attempts
                    if attempt.status.satisfies_requirement
                    and problem.courses.get(attempt.course_id)
                    and problem.courses[attempt.course_id].curriculum_version
                    is CurriculumVersion.OLD
                )
                review_course_ids = completed_old - authorized_sources
            run = AcademicPlanningEngine(planner).run(
                problem,
                registration_course_ids=current_offered,
                review_course_ids=review_course_ids,
            )
            plan = run.plan
            reconciliation = run.audit
            optional_ids = {approval.course_id for approval in approvals}
            outstanding_delivery = requirement_delivery_options(
                problem, reconciliation.outstanding_requirement_ids
            )
            candidate_ids = (
                frozenset().union(*outstanding_delivery.values())
                if outstanding_delivery else frozenset()
            ) | (optional_ids & current_offered)
            candidate_ids -= reconciliation.prerequisite_completion_ids
            applicable = {
                cid: problem.courses[cid] for cid in candidate_ids
                if cid in problem.courses
            }
            pool = EligibilityEngine(rollout, registration).build_pool(
                student, current, applicable, frozenset(candidate_ids),
                reconciliation.prerequisite_completion_ids,
                problem.prerequisites, problem.offerings,
            )
            diagnostics = PlanningWebService._selection_diagnostics(
                request, problem, pool.courses, plan, planner
            )
            scenario = SimpleNamespace(
                identifier=record.identifier,
                description=record.display_name,
                starting_term=current,
                data=SimpleNamespace(fixture_configuration=RELAXED_FIXTURE),
            )
            response = PlanningWebService()._response(
                scenario, request, problem, reconciliation, pool, plan, diagnostics
            )
            selected_optional = frozenset(plan.selected_optional_course_ids)
            selected_all = {
                course_id
                for scheduled_term in plan.scheduled_terms
                for course_id in scheduled_term.course_ids
            }
            selected_substitutions = {
                (course_id, requirement_id)
                for requirement_id, course_ids in outstanding_delivery.items()
                for course_id in course_ids & selected_all
                if course_id != requirement_id
            }
            approval_by_id = {approval.course_id: approval for approval in approvals}
            grouped = {kind: [] for kind in RequirementClassification}
            for item in reconciliation.classifications:
                if item.course_id in problem.courses:
                    grouped[item.classification].append(self._classified(
                        problem, item, approval_by_id, selected_optional
                    ))
            mandatory_delivery_ids = (
                frozenset().union(*outstanding_delivery.values())
                if outstanding_delivery else frozenset()
            )
            mandatory_credits = sum(
                problem.courses[cid].credits
                for cid in mandatory_delivery_ids & selected_all
            )
            optional_credits = sum(
                problem.courses[cid].credits for cid in selected_optional
            )
            proposed_adjustment = (
                plan.credit_adjustment_proposal.credits
                if plan.credit_adjustment_proposal else 0
            )
            total = (
                reconciliation.official_earned_credits
                + mandatory_credits
                + optional_credits
                + proposed_adjustment
            )
            scenario_payload = {
                **response.scenario,
                "description": record.display_name,
                "student_type": "Persisted shared-engine scenario",
                "original_reported_earned_credits": record.reported_earned_credits,
            }
            source_categories = list(record.contract_credit_categories or [])
            category_required_total = sum(
                int(item["required_ects"]) for item in source_categories
            )
            category_earned_total = sum(
                int(item["source_reported_earned_ects"]) for item in source_categories
            )
            contract_category_audit = {
                "source_reference": "IUL portal Contract Sheet",
                "solver_enforced": False,
                "reason": (
                    "Source categories are preserved for audit but are not additive "
                    "solver constraints until category overlap/allocation rules are verified."
                ),
                "required_ects_total": category_required_total,
                "source_reported_earned_ects_total": category_earned_total,
                "graduation_ects_target": record.graduation_credit_target,
                "required_total_above_graduation_target": max(
                    0, category_required_total - record.graduation_credit_target
                ),
                "categories": [
                    {
                        **item,
                        "source_reported_remaining_ects": max(
                            0,
                            int(item["required_ects"])
                            - int(item["source_reported_earned_ects"]),
                        ),
                    }
                    for item in source_categories
                ],
            }
            warnings = [
                warning for warning in response.warnings
                if not warning.startswith("All fixture curricula")
            ]
            warnings.insert(0, "Student scenario uses the same catalog, equivalencies, eligibility rules, and optimizer as every other database student.")
            if keep_current_registration:
                warnings.insert(1, (
                    "The active semester is locked to the student's observed registration. "
                    "Registered courses remain unearned until final results are recorded; "
                    "future courses may use them only after the active semester."
                ))
                if observed_offerings_added:
                    names = ", ".join(
                        f"{problem.courses[course_id].name} "
                        f"({problem.courses[course_id].code})"
                        for course_id in observed_offerings_added
                    )
                    warnings.insert(2, (
                        "The transcript confirms registration but no schedulable timetable "
                        f"bundle was loaded for {names}; those courses are kept without "
                        "inventing meeting times."
                    ))
            if verified_capacity_rows:
                warnings.insert(1, (
                    "Verified student capacity exception applied: "
                    + ", ".join(
                        f"{row.academic_year_start}-{row.academic_year_start + 1} "
                        f"{row.semester} = {row.capacity} ECTS"
                        for row in verified_capacity_rows
                    )
                    + "."
                ))
            selected_current_ids = next(
                (set(scheduled.course_ids) for scheduled in plan.scheduled_terms
                 if scheduled.term == current),
                set(),
            )
            matched_current_ids = observed_current.keys() & selected_current_ids
            missed_current_ids = observed_current.keys() - selected_current_ids
            additional_current_ids = selected_current_ids - observed_current.keys()
            observed_current_ects = sum(observed_current.values())
            matched_current_ects = sum(
                observed_current[course_id] for course_id in matched_current_ids
            )
            current_registration_comparison = {
                "mode": request.registration_mode,
                "evaluation_only": not keep_current_registration,
                "influenced_optimizer": keep_current_registration,
                "observed_status": "REGISTERED_OR_IN_PROGRESS",
                "observed_courses": [
                    {
                        "course_id": course_id,
                        "code": problem.courses[course_id].code,
                        "title": problem.courses[course_id].name,
                        "ects": problem.courses[course_id].credits,
                    }
                    for course_id in sorted(
                        observed_current,
                        key=lambda item: problem.courses[item].code,
                    )
                ],
                "observed_course_codes": sorted(
                    problem.courses[course_id].code for course_id in observed_current
                ),
                "engine_selected_course_codes": sorted(
                    problem.courses[course_id].code for course_id in selected_current_ids
                ),
                "matched_course_codes": sorted(
                    problem.courses[course_id].code for course_id in matched_current_ids
                ),
                "matched_courses": [
                    {
                        "code": problem.courses[course_id].code,
                        "title": problem.courses[course_id].name,
                    }
                    for course_id in sorted(
                        matched_current_ids,
                        key=lambda item: problem.courses[item].code,
                    )
                ],
                "missed_course_codes": sorted(
                    problem.courses[course_id].code for course_id in missed_current_ids
                ),
                "missed_courses": [
                    {
                        "code": problem.courses[course_id].code,
                        "title": problem.courses[course_id].name,
                    }
                    for course_id in sorted(
                        missed_current_ids,
                        key=lambda item: problem.courses[item].code,
                    )
                ],
                "additional_course_codes": sorted(
                    problem.courses[course_id].code for course_id in additional_current_ids
                ),
                "additional_courses": [
                    {
                        "code": problem.courses[course_id].code,
                        "title": problem.courses[course_id].name,
                    }
                    for course_id in sorted(
                        additional_current_ids,
                        key=lambda item: problem.courses[item].code,
                    )
                ],
                "observed_ects": observed_current_ects,
                "matched_ects": matched_current_ects,
                "course_match_rate": (
                    len(matched_current_ids) / len(observed_current)
                    if observed_current else None
                ),
                "ects_match_rate": (
                    matched_current_ects / observed_current_ects
                    if observed_current_ects else None
                ),
                "exact_course_match": (
                    bool(observed_current)
                    and not missed_current_ids
                    and not additional_current_ids
                ),
            }
            degree_contract_audit = None
            if contract:
                completion_ids = reconciliation.prerequisite_completion_ids
                degree_contract_audit = {
                    "contract_id": contract.id,
                    "program_code": contract.program_code,
                    "title": contract.title,
                    "effective_academic_year": contract.effective_academic_year,
                    "source_document_id": contract.source_document_id,
                    "verification_status": contract.verification_status,
                    "graduation_ects_target": contract.graduation_ects_target,
                    "solver_enforced": True,
                    "enforcement_model": (
                        "Top-level PDF category quotas with exact equivalencies first, "
                        "same-category legacy credit second, and pathway-locked capstone."
                    ),
                    "groups": [
                        {
                            "code": group.code,
                            "title": group.title,
                            "rule_type": group.rule_type,
                            "required_ects": group.required_ects,
                            "recognized_ects": (
                                contract_recognized_credits.get(group.code, 0)
                                if group.parent_id is None and group.code != "CAPSTONE"
                                else min(
                                    group.required_ects,
                                    sum(
                                        item.contribution_ects
                                        for item in group.memberships
                                        if str(item.course_id) in completion_ids
                                        and item.language_track in {None, record.language_track}
                                    ),
                                )
                            ),
                            "recognition_basis": contract_recognition_basis.get(
                                group.code, []
                            ),
                            "solver_enforced": group.parent_id is None,
                            "candidate_course_codes": sorted(
                                problem.courses[course_id].code
                                for course_id in (
                                    contract_candidate_credits.get(group.code, {})
                                    if group.parent_id is None
                                    else {
                                        str(item.course_id)
                                        for item in group.memberships
                                        if item.language_track in {None, record.language_track}
                                    }
                                )
                                if course_id in problem.courses
                            ),
                        }
                        for group in contract_groups
                    ],
                }
            return response.model_copy(update={
                "scenario": scenario_payload,
                "warnings": warnings,
                "transition_diagnostics": {
                    "source_reported_earned_credits": record.reported_earned_credits,
                    "recomputed_completed_source_credits": normalized.completed_credits,
                    "recognition_mode": "GLOBAL_AUTO_AND_HUMAN_VERIFIED",
                    "transition_catalogue_coverage": catalogue_coverage,
                    "recognized_old_to_new_mappings": sum(
                        source != target for source, target in reconciliation.allocations
                    ),
                    "unknown_transcript_codes": list(normalized.unknown_codes),
                    "transcript_component_codes": list(normalized.component_codes),
                    "student_specific_recognitions": 0,
                    "prospective_registration_substitutions": [
                        {
                            "registration_course": problem.courses[source].code,
                            "satisfied_requirement": problem.courses[target].code,
                        }
                        for source, target in sorted(
                            selected_substitutions,
                            key=lambda pair: problem.courses[pair[0]].code,
                        )
                    ],
                    "registered_fyp_pathway": [
                        problem.courses[course_id].code for course_id in fyp_pathway
                    ],
                    "governing_curriculum": governing_version.value,
                    "current_registration_comparison": current_registration_comparison,
                    "contract_credit_category_audit": contract_category_audit,
                    "degree_contract_audit": degree_contract_audit,
                },
                "mandatory_outstanding": grouped[RequirementClassification.MANDATORY_OUTSTANDING],
                "satisfied_requirements": grouped[RequirementClassification.SATISFIED],
                "approved_optional_candidates": grouped[RequirementClassification.APPROVED_OPTIONAL],
                "registration_only_courses": grouped[RequirementClassification.REGISTRATION_ONLY],
                "courses_needing_review": grouped[RequirementClassification.NEEDS_REVIEW],
                "graduation_credit_breakdown": {
                    "graduation_ects_target": record.graduation_credit_target,
                    "accepted_completed_ects": reconciliation.official_earned_credits,
                    "mandatory_outstanding_ects": mandatory_credits,
                    "approved_optional_ects_selected": optional_credits,
                    "proposed_credit_adjustment_ects": proposed_adjustment,
                    "proposed_credit_adjustment_term": (
                        plan.credit_adjustment_proposal.term.label()
                        if plan.credit_adjustment_proposal else None
                    ),
                    "credit_adjustment_requires_approval": bool(
                        plan.credit_adjustment_proposal
                    ),
                    "remaining_unresolved_ects": max(0, record.graduation_credit_target - total),
                    "excess_accepted_ects": max(0, total - record.graduation_credit_target),
                    "hypothetical": False,
                },
            })

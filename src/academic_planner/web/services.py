"""Application services that expose synthetic planning through web schemas."""

from __future__ import annotations

from dataclasses import replace

from academic_planner.domain.models import (
    Course, GraduationPlan, ScheduledTerm, SolverStatus, TermCreditUsage, TermKind,
)
from academic_planner.eligibility import EligibilityEngine, RejectionCode
from academic_planner.fixtures import StudentScenario, build_scenario, list_scenarios
from academic_planner.optimization import GlobalPlanner
from academic_planner.planning import AcademicPlanningEngine
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy,
)
from academic_planner.reconciliation import ReconciliationService
from academic_planner.scheduling.conflicts import bundles_conflict
from academic_planner.web.schemas import (
    BlockedCourseResponse, CourseResponse, CourseSelectionDiagnosticResponse,
    CurrentSemesterResponse,
    FutureSemesterResponse, MeetingResponse, PlanRequest, PlanResponse,
    ScenarioResponse, SectionResponse, SelectedCourseResponse,
)


class UnknownScenarioError(ValueError):
    """Raised when a request names no configured synthetic scenario."""


class InvalidTermOverrideError(ValueError):
    """Raised when a request supplies an unknown or invalid term capacity."""


def _course_response(course: Course) -> CourseResponse:
    return CourseResponse(
        id=course.id,
        code=course.code,
        title=course.name,
        credits=course.credits,
        reference_year=course.reference_year,
        reference_semester=course.reference_semester.value,
        curriculum_version=course.curriculum_version.value,
        provenance=course.provenance.value,
    )


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class PlanningWebService:
    """Configure, solve, diagnose, and serialize in-memory planning scenarios."""

    def scenario_summaries(self) -> list[ScenarioResponse]:
        summaries = []
        for identifier, description in list_scenarios().items():
            scenario = build_scenario(identifier)
            problem = scenario.data.demo_problem()
            reconciliation = ReconciliationService().reconcile(
                problem.student, problem.curriculum, problem.equivalencies
            )
            remaining = sum(
                problem.courses[c].credits for c in reconciliation.outstanding_requirement_ids
            )
            summaries.append(ScenarioResponse(
                identifier=identifier,
                description=description,
                nominal_year=problem.student.nominal_year,
                language_track=problem.student.language_track.value,
                curriculum_version=problem.curriculum.version.value,
                starting_term=scenario.starting_term.label(),
                completed_credits=reconciliation.official_earned_credits,
                remaining_credits=remaining,
                available_terms=[term.label() for term in problem.configuration.planning_horizon],
                fixture_prerequisites=(
                    scenario.data.fixture_configuration.prerequisite_variant.value
                ),
                fixture_timetable=(
                    scenario.data.fixture_configuration.timetable_variant.value
                ),
            ))
        return summaries

    def plan(self, request: PlanRequest) -> PlanResponse:
        """Run one synthetic scenario without persisting request preferences."""
        try:
            scenario = build_scenario(request.scenario_id, request.regular_credit_capacity)
        except ValueError as exc:
            raise UnknownScenarioError(str(exc)) from exc
        scenario = self._configure(scenario, request)
        data = scenario.data
        problem = data.demo_problem()
        rollout = ProgressiveRolloutPolicy()
        registration = AllowAllRegistrationPolicy()
        planner = GlobalPlanner(ConfiguredCreditLimitPolicy(), rollout, registration)
        run = AcademicPlanningEngine(planner).run(problem)
        plan = run.plan
        reconciliation = run.audit
        applicable = {
            cid: problem.courses[cid]
            for cid in problem.curriculum.resolved_requirements(problem.student.language_track)
        }
        pool = EligibilityEngine(rollout, registration).build_pool(
            problem.student,
            scenario.starting_term,
            applicable,
            reconciliation.outstanding_requirement_ids,
            reconciliation.prerequisite_completion_ids,
            problem.prerequisites,
            problem.offerings,
        )
        diagnostics = self._selection_diagnostics(
            request, problem, pool.courses, plan, planner
        )
        return self._response(scenario, request, problem, reconciliation, pool, plan, diagnostics)

    @staticmethod
    def _configure(scenario: StudentScenario, request: PlanRequest) -> StudentScenario:
        data = scenario.data
        config = data.demo_configuration
        terms_by_label = {term.label(): term for term in config.planning_horizon}
        unknown = set(request.per_semester_capacity_overrides) - terms_by_label.keys()
        if unknown:
            raise InvalidTermOverrideError(
                f"unknown planning term override(s): {', '.join(sorted(unknown))}"
            )
        capacities = dict(config.term_credit_capacities)
        for label, capacity in request.per_semester_capacity_overrides.items():
            if capacity < 1 or capacity > 60:
                raise InvalidTermOverrideError(
                    f"capacity for {label} must be between 1 and 60"
                )
            capacities[terms_by_label[label]] = capacity
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
        configured = replace(
            config,
            **overrides,
            term_credit_capacities=capacities,
            explicit_capacity_override_terms=frozenset(
                terms_by_label[label]
                for label in request.per_semester_capacity_overrides
            ),
        )
        return replace(scenario, data=replace(data, demo_configuration=configured))

    @staticmethod
    def _selection_diagnostics(request, problem, eligible_courses, plan, planner):
        current = problem.configuration.planning_horizon[0]
        factual_current = plan.scheduled_terms[0] if plan.scheduled_terms else None
        selected_ids = set(factual_current.course_ids) if factual_current else set()
        selected_bundle_ids = set(factual_current.bundle_ids) if factual_current else set()
        bundles = {
            bundle.id: bundle
            for offering in problem.offerings for bundle in offering.bundles
        }
        selected_bundles = [bundles[b] for b in selected_bundle_ids]
        offering_map = {
            (offering.course_id, offering.term): offering
            for offering in problem.offerings
        }
        current_usage = next(
            (usage for usage in plan.credit_usages if usage.term == current), None
        )
        current_credits = current_usage.selected_credits if current_usage else 0
        current_cap = (
            current_usage.effective_capacity
            if current_usage else problem.configuration.capacity_for(current)
        )
        term_indexes = {
            term: index
            for index, term in enumerate(problem.configuration.planning_horizon)
        }
        factual_graduation_index = term_indexes.get(plan.graduation_term, 10**6)
        diagnosed = 0
        results = []
        for course in sorted(eligible_courses, key=lambda item: (item.reference_year, item.code)):
            if course.id in selected_ids:
                candidate_bundles = [
                    bundle for bundle in selected_bundles
                    if bundle.course_id == course.id
                ]
            else:
                offering = offering_map.get((course.id, current))
                candidate_bundles = list(offering.bundles) if offering else []
            conflicts = sorted({
                problem.courses[selected.course_id].code
                for candidate in candidate_bundles
                for selected in selected_bundles
                if selected.course_id != course.id and bundles_conflict(candidate, selected)
            })
            would_exceed = current_credits + course.credits > current_cap
            if course.id in selected_ids:
                status = "SELECTED"
                detail = "Selected by the global plan."
                counterfactual = plan.graduation_term
            elif not request.enable_course_selection_diagnostics:
                status = "UNKNOWN_NOT_DIAGNOSED"
                detail = "Counterfactual diagnostics are disabled."
                counterfactual = None
            elif diagnosed >= request.max_diagnostic_courses:
                status = "UNKNOWN_NOT_DIAGNOSED"
                detail = "Not checked because the configured diagnostic bound was reached."
                counterfactual = None
            else:
                diagnosed += 1
                diagnostic_config = replace(
                    problem.configuration,
                    forced_course_terms={
                        **problem.configuration.forced_course_terms,
                        course.id: current,
                    },
                    time_limit_seconds=min(
                        problem.configuration.time_limit_seconds, 3.0
                    ),
                )
                forced = planner.plan(replace(problem, configuration=diagnostic_config))
                counterfactual = forced.graduation_term
                forced_index = term_indexes.get(forced.graduation_term, 10**6)
                if forced.status is SolverStatus.INFEASIBLE:
                    status = "COUNTERFACTUAL_INFEASIBLE"
                    detail = (
                        "Forcing this course into the current term was proven "
                        "infeasible under the modeled horizon and constraints."
                    )
                elif forced.status is SolverStatus.UNKNOWN:
                    status = "UNKNOWN_INCONCLUSIVE"
                    detail = "The bounded counterfactual solve was inconclusive."
                elif forced_index > factual_graduation_index:
                    status = "NOT_SELECTED_EARLIER_GRADUATION_OBJECTIVE"
                    detail = (
                        "A forced plan was feasible, but its projected graduation "
                        "was later than the factual plan."
                    )
                else:
                    status = "FEASIBLE_ALTERNATIVE_NOT_SELECTED"
                    detail = (
                        "A forced plan was feasible without a later modeled "
                        "graduation; lower-priority objectives selected another plan."
                    )
            results.append(CourseSelectionDiagnosticResponse(
                course_id=course.id,
                course_code=course.code,
                status=status,
                detail=detail,
                counterfactual_graduation_term=(
                    counterfactual.label() if counterfactual else None
                ),
                conflicts_with_selected_course_codes=conflicts,
                would_exceed_current_cap_if_added_without_changes=(
                    would_exceed and course.id not in selected_ids
                ),
            ))
        return results

    def _response(
        self, scenario, request, problem, reconciliation, pool, plan, diagnostics=(),
    ) -> PlanResponse:
        data = scenario.data
        missing_by_course = {
            rule.course_id: sorted(
                problem.courses[p].code
                for p in rule.all_of - reconciliation.prerequisite_completion_ids
            )
            for rule in problem.prerequisites
        }
        blocked = []
        for rejection in pool.rejections:
            course = problem.courses[rejection.course_id]
            blocked.append(BlockedCourseResponse(
                **_course_response(course).model_dump(),
                reason_code=rejection.code.value,
                reason=rejection.detail,
                missing_prerequisites=(
                    missing_by_course.get(course.id, [])
                    if rejection.code is RejectionCode.PREREQUISITE else []
                ),
            ))
        current = None
        if plan.scheduled_terms:
            current = self._current_response(
                plan.scheduled_terms[0], problem, self._usage_for(plan, plan.scheduled_terms[0])
            )
        graduation_index = next(
            (i for i, scheduled in enumerate(plan.scheduled_terms)
             if scheduled.term == plan.graduation_term),
            -1,
        )
        future = [
            self._future_response(
                scheduled, problem, self._usage_for(plan, scheduled)
            )
            for scheduled in plan.scheduled_terms[1:graduation_index + 1]
            if scheduled.term.is_regular or scheduled.course_ids
        ] if graduation_index >= 1 else []
        config = problem.configuration
        warnings = list(plan.warnings)
        warnings.insert(0, "All fixture curricula, prerequisites, equivalencies, sections, and future offerings are synthetic and unverified.")
        if config.default_credit_capacity > 30 or any(
            value > 30 for value in request.per_semester_capacity_overrides.values()
        ):
            warnings.append(
                "A capacity above 30 ECTS is a planning assumption, not verified administrative approval."
            )
        if config.allow_extended_load_when_repeating_failed_course:
            warnings.append(
                "The failed-repeat 36-ECTS allowance is a planning assumption, not verified administrative approval."
            )
        selected_periods = sum(bool(term.course_ids) for term in plan.scheduled_terms[:graduation_index + 1])
        # "Remaining" is the complete graduation-credit deficit.  Mandatory
        # outstanding credits are reported separately and may be smaller when
        # the student also needs approved optional credit to reach the target.
        remaining = max(
            0,
            problem.curriculum.accepted_credit_target
            - reconciliation.official_earned_credits,
        )
        eligible = sorted(pool.courses, key=lambda c: (c.reference_year, c.code))
        planned_through_graduation = (
            plan.scheduled_terms[:graduation_index + 1]
            if graduation_index >= 0 else ()
        )
        regular_semesters_remaining = sum(
            scheduled.term.is_regular for scheduled in planned_through_graduation
        )
        training_periods_remaining = sum(
            scheduled.term.kind in {TermKind.TRAINING_1, TermKind.TRAINING_2}
            and bool(scheduled.course_ids)
            for scheduled in planned_through_graduation
        )
        earlier_term = next((
            scheduled.term
            for scheduled in reversed(plan.scheduled_terms[:graduation_index])
            if scheduled.term.is_regular
        ), None)
        return PlanResponse(
            scenario={
                "identifier": scenario.identifier,
                "description": scenario.description,
                "starting_term": scenario.starting_term.label(),
                "fixture_prerequisites": (
                    data.fixture_configuration.prerequisite_variant.value
                ),
                "fixture_timetable": (
                    data.fixture_configuration.timetable_variant.value
                ),
            },
            student={
                "nominal_year": problem.student.nominal_year,
                "language_track": problem.student.language_track.value,
                "curriculum_version": problem.curriculum.version.value,
            },
            configuration={
                "regular_credit_capacity": config.default_credit_capacity,
                "per_semester_capacity_overrides": request.per_semester_capacity_overrides,
                "academic_year_deviation_weight": config.academic_year_deviation_weight,
                "reference_semester_deviation_weight": config.reference_semester_deviation_weight,
                "allow_training_postponement": config.allow_training_postponement,
                "training_delay_penalty": config.training_delay_penalty,
                "max_training_delay_years": config.max_training_delay_years,
                "solver_time_limit_seconds": config.time_limit_seconds,
                "initial_horizon_semesters": config.initial_horizon_semesters,
                "max_horizon_semesters": config.max_horizon_semesters,
                "auto_extend_horizon": config.auto_extend_horizon,
                "horizon_extension_step": config.horizon_extension_step,
                "allow_extended_load_when_repeating_failed_course": (
                    config.allow_extended_load_when_repeating_failed_course
                ),
                "allow_final_two_semester_graduation_load": (
                    config.allow_final_two_semester_graduation_load
                ),
                "enable_course_selection_diagnostics": (
                    request.enable_course_selection_diagnostics
                ),
                "max_diagnostic_courses": request.max_diagnostic_courses,
            },
            academic_summary={
                "completed_credits": reconciliation.official_earned_credits,
                "remaining_credits": remaining,
                "accepted_credit_target": problem.curriculum.accepted_credit_target,
                "satisfied_requirements": len(reconciliation.satisfied_requirement_ids),
                "outstanding_requirements": len(reconciliation.outstanding_requirement_ids),
                "projected_remaining_periods": selected_periods,
                "regular_semesters_remaining": regular_semesters_remaining,
                "training_periods_remaining": training_periods_remaining,
            },
            eligible_pool=[_course_response(course) for course in eligible],
            eligible_pool_total_credits=sum(course.credits for course in eligible),
            blocked_courses=sorted(blocked, key=lambda item: (item.reason_code, item.reference_year, item.code)),
            course_selection_diagnostics=list(diagnostics),
            current_semester=current,
            future_semesters=future,
            graduation={
                "term": plan.graduation_term.label() if plan.graduation_term else None,
                "is_projected": plan.graduation_term is not None,
                "basis": "supplied horizon and synthetic offering assumptions",
                "earliest_feasible_under_model": plan.status is SolverStatus.OPTIMAL,
                "earlier_deadline_tested": earlier_term.label() if earlier_term else None,
                "earlier_deadline_proven_infeasible": (
                    plan.status is SolverStatus.OPTIMAL and earlier_term is not None
                ),
            },
            solver={
                "status": plan.status.value,
                "is_success": plan.status in {
                    SolverStatus.OPTIMAL, SolverStatus.FEASIBLE_NOT_PROVEN_OPTIMAL
                },
                "global_optimality_proven": plan.status is SolverStatus.OPTIMAL,
                "explanations": list(plan.explanations),
            },
            warnings=list(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _usage_for(plan: GraduationPlan, scheduled: ScheduledTerm):
        return next(
            (usage for usage in plan.credit_usages if usage.term == scheduled.term),
            None,
        )

    @staticmethod
    def _current_response(
        scheduled: ScheduledTerm, problem, usage: TermCreditUsage | None = None
    ) -> CurrentSemesterResponse:
        bundles = {
            bundle.id: bundle for offering in problem.offerings for bundle in offering.bundles
        }
        selected = []
        for course_id in scheduled.course_ids:
            course = problem.courses[course_id]
            bundle = next(
                (bundles[b] for b in scheduled.bundle_ids if bundles[b].course_id == course_id),
                None,
            )
            sections = []
            if bundle:
                for section in bundle.sections:
                    sections.append(SectionResponse(
                        crn=section.crn,
                        component=section.component,
                        component_credits=0 if section.component.startswith("LAB") else course.credits,
                        campus=section.campus,
                        provenance=section.provenance.value,
                        teaching_language=(section.teaching_language.value
                                           if section.teaching_language else None),
                        cross_track=(section.teaching_language is not None and
                                     section.teaching_language is not problem.student.language_track),
                        meetings=[MeetingResponse(
                            weekday=meeting.weekday.name.title(),
                            weekday_index=int(meeting.weekday),
                            start_minute=meeting.start_minute,
                            end_minute=meeting.end_minute,
                            start_time=_clock(meeting.start_minute),
                            end_time=_clock(meeting.end_minute),
                        ) for meeting in section.meetings],
                    ))
            selected.append(SelectedCourseResponse(
                **_course_response(course).model_dump(),
                bundle_id=bundle.id if bundle else None,
                sections=sections,
            ))
        return CurrentSemesterResponse(
            term=scheduled.term.label(),
            total_credits=sum(problem.courses[c].credits for c in scheduled.course_ids),
            selected_courses=selected,
            has_meeting_data=any(section.meetings for course in selected for section in course.sections),
            effective_credit_capacity=(
                usage.effective_capacity
                if usage else problem.configuration.capacity_for(scheduled.term)
            ),
            credit_capacity_reason=(usage.reason if usage else "CONFIGURED_CAPACITY"),
            repeated_course_codes=(
                [problem.courses[c].code for c in usage.repeated_course_ids]
                if usage else []
            ),
        )

    @staticmethod
    def _future_response(
        scheduled: ScheduledTerm, problem, usage: TermCreditUsage | None = None
    ) -> FutureSemesterResponse:
        courses = [_course_response(problem.courses[c]) for c in scheduled.course_ids]
        return FutureSemesterResponse(
            term=scheduled.term.label(),
            period_type=scheduled.term.kind.value,
            status="PROJECTED_UNVERIFIED",
            total_credits=sum(course.credits for course in courses),
            courses=courses,
            effective_credit_capacity=(
                usage.effective_capacity
                if usage else problem.configuration.capacity_for(scheduled.term)
            ),
            credit_capacity_reason=(usage.reason if usage else "CONFIGURED_CAPACITY"),
            repeated_course_codes=(
                [problem.courses[c].code for c in usage.repeated_course_ids]
                if usage else []
            ),
        )

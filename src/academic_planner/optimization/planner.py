"""Behavior-critical CP-SAT formulation for graduation planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import monotonic

from ortools.sat.python import cp_model

from academic_planner.domain.models import (
    AcademicTerm, ApprovalStatus, AttemptStatus, Course, CourseEquivalency, CourseOffering,
    CreditAdjustmentProposal, CreditRequirementGroup, Curriculum, GraduationPlan, OptionalCreditApproval,
    PlanningConfiguration, PrerequisiteRule,
    ScheduledTerm, SolverStatus, StudentAcademicState, TermCreditUsage, TermKind,
)
from academic_planner.policies.credit import CreditLimitPolicy
from academic_planner.policies.credit import (
    effective_credit_capacity, has_explicit_capacity_override,
    unresolved_failed_course_ids,
)
from academic_planner.policies.registration import AcademicRegistrationPolicy
from academic_planner.policies.rollout import ProgressiveRolloutPolicy
from academic_planner.reconciliation.service import ReconciliationResult, ReconciliationService
from academic_planner.requirement_delivery import requirement_delivery_options
from academic_planner.scheduling.conflicts import bundles_conflict


@dataclass(frozen=True)
class PlanningProblem:
    """Complete immutable input boundary for one graduation-plan request."""

    courses: dict[str, Course]
    curriculum: Curriculum
    student: StudentAcademicState
    equivalencies: tuple[CourseEquivalency, ...]
    prerequisites: tuple[PrerequisiteRule, ...]
    offerings: tuple[CourseOffering, ...]
    configuration: PlanningConfiguration
    optional_credit_approvals: tuple[OptionalCreditApproval, ...] = ()
    credit_requirement_groups: tuple[CreditRequirementGroup, ...] = ()
    exploratory: bool = False
    allow_credit_adjustment_proposal: bool = False


class GlobalPlanner:
    """A single CP-SAT model for current exact scheduling and future projection."""

    def __init__(
        self,
        credit_policy: CreditLimitPolicy,
        rollout_policy: ProgressiveRolloutPolicy,
        registration_policy: AcademicRegistrationPolicy,
    ) -> None:
        self.credit_policy = credit_policy
        self.rollout_policy = rollout_policy
        self.registration_policy = registration_policy

    def plan(
        self,
        problem: PlanningProblem,
        *,
        audit: ReconciliationResult | None = None,
    ) -> GraduationPlan:
        audit = audit or ReconciliationService().reconcile(
            problem.student,
            problem.curriculum,
            problem.equivalencies,
            courses=problem.courses,
            optional_approvals=problem.optional_credit_approvals,
        )
        config = problem.configuration
        available_regular = sum(term.is_regular for term in config.planning_horizon)
        if available_regular == 0:
            return self._solve_horizon(problem, audit)
        initial = min(config.initial_horizon_semesters, available_regular)
        maximum = min(config.max_horizon_semesters, available_regular)
        limits = [initial]
        if config.auto_extend_horizon:
            while limits[-1] < maximum:
                limits.append(min(maximum, limits[-1] + config.horizon_extension_step))
        last_plan: GraduationPlan | None = None
        for regular_limit in limits:
            active_terms = self._horizon_prefix(config.planning_horizon, regular_limit)
            active_config = replace(
                config,
                planning_horizon=active_terms,
                auto_extend_horizon=False,
            )
            candidate = self._solve_horizon(
                replace(problem, configuration=active_config), audit
            )
            if candidate.status in {
                SolverStatus.OPTIMAL, SolverStatus.FEASIBLE_NOT_PROVEN_OPTIMAL
            }:
                if regular_limit > initial:
                    candidate = replace(
                        candidate,
                        explanations=candidate.explanations + (
                            f"planning horizon extended from {initial} to "
                            f"{regular_limit} future regular semesters",
                        ),
                    )
                return candidate
            if candidate.status is SolverStatus.UNKNOWN:
                return replace(
                    candidate,
                    explanations=candidate.explanations + (
                        f"search was inconclusive at {regular_limit} regular semesters; "
                        "the horizon was not extended because infeasibility was not proven",
                    ),
                )
            last_plan = candidate
        assert last_plan is not None
        boundary = "configured maximum" if maximum == config.max_horizon_semesters else "available academic calendar"
        return replace(
            last_plan,
            explanations=last_plan.explanations + (
                f"no feasible plan was found within {maximum} future regular semesters "
                f"({boundary} reached)",
            ),
        )

    @staticmethod
    def _horizon_prefix(
        terms: tuple[AcademicTerm, ...], regular_semesters: int
    ) -> tuple[AcademicTerm, ...]:
        selected: list[AcademicTerm] = []
        regular_count = 0
        reached = False
        for term in terms:
            if reached and term.is_regular:
                break
            selected.append(term)
            if term.is_regular:
                regular_count += 1
                reached = regular_count >= regular_semesters
        return tuple(selected)

    def _solve_horizon(
        self,
        problem: PlanningProblem,
        reconciliation: ReconciliationResult,
    ) -> GraduationPlan:
        terms = problem.configuration.planning_horizon
        if not terms:
            return GraduationPlan(
                SolverStatus.INFEASIBLE,
                explanations=("planning horizon is empty",),
            )
        current_term = terms[0]
        blocked_attempts = tuple(
            attempt
            for attempt in problem.student.attempts
            if (
                attempt.status is AttemptStatus.RESULT_PENDING
                or (
                    attempt.status is AttemptStatus.IN_PROGRESS
                    and attempt.term < current_term
                )
            )
        )
        blocked_course_ids = {attempt.course_id for attempt in blocked_attempts}
        all_delivery_options = requirement_delivery_options(
            problem, reconciliation.outstanding_requirement_ids
        )
        deferred_requirement_ids = frozenset(
            requirement_id
            for requirement_id, course_ids in all_delivery_options.items()
            if course_ids & blocked_course_ids
        )
        schedulable_requirement_ids = (
            reconciliation.outstanding_requirement_ids - deferred_requirement_ids
        )
        mandatory_requirements = sorted(schedulable_requirement_ids)
        delivery_options = requirement_delivery_options(
            problem, schedulable_requirement_ids
        )
        mandatory_delivery_ids = frozenset().union(*delivery_options.values()) \
            if delivery_options else frozenset()
        owners: dict[str, list[str]] = {}
        for requirement_id, course_ids in delivery_options.items():
            for course_id in course_ids:
                owners.setdefault(course_id, []).append(requirement_id)
        ambiguous_delivery = {
            course_id: requirement_ids
            for course_id, requirement_ids in owners.items()
            if len(requirement_ids) > 1
        }
        if ambiguous_delivery:
            details = ", ".join(
                f"{course_id} -> {sorted(requirement_ids)}"
                for course_id, requirement_ids in sorted(ambiguous_delivery.items())
            )
            return GraduationPlan(
                SolverStatus.INFEASIBLE,
                explanations=(
                    "a registration course is configured to satisfy multiple "
                    f"outstanding requirements without an allocation rule: {details}",
                ),
            )
        missing_definitions = mandatory_delivery_ids - problem.courses.keys()
        if missing_definitions:
            return GraduationPlan(SolverStatus.INFEASIBLE, explanations=(f"outstanding requirements lack schedulable course definitions: {', '.join(sorted(missing_definitions))}",))
        completed_course_ids = {
            attempt.course_id for attempt in problem.student.attempts
            if attempt.status.satisfies_requirement
        }
        completed_equivalent_ids: set[str] = set()
        for equivalency in problem.equivalencies:
            if equivalency.source_course_ids & completed_course_ids:
                completed_equivalent_ids.update(equivalency.target_requirement_ids)
            if equivalency.target_requirement_ids & completed_course_ids:
                completed_equivalent_ids.update(equivalency.source_course_ids)
        optional_approvals = {
            item.course_id: item for item in problem.optional_credit_approvals
            if item.course_id in problem.courses
            and item.course_id not in reconciliation.prerequisite_completion_ids
            and item.course_id not in completed_equivalent_ids
            and item.course_id not in mandatory_delivery_ids
            and (
                (item.status is ApprovalStatus.APPROVED and item.sufficiently_documented)
                or (problem.exploratory and item.status is ApprovalStatus.UNVERIFIED)
            )
        }
        optional = sorted(optional_approvals)
        group_remaining: dict[str, int] = {}
        pending_degree_course_ids = {
            attempt.course_id
            for attempt in blocked_attempts
            if any(
                attempt.course_id in all_delivery_options[requirement_id]
                for requirement_id in deferred_requirement_ids
            )
        }
        for group in problem.credit_requirement_groups:
            pending_by_identity: dict[str, int] = {}
            for attempt in blocked_attempts:
                if attempt.course_id not in group.course_credits:
                    continue
                identity = attempt.credit_identity or attempt.course_id
                pending_by_identity[identity] = max(
                    pending_by_identity.get(identity, 0),
                    group.course_credits[attempt.course_id],
                )
                pending_degree_course_ids.add(attempt.course_id)
            satisfied_credits = group.recognized_credits + sum(
                pending_by_identity.values()
            )
            group_remaining[group.code] = max(0, group.required_credits - satisfied_credits)
        projected_pending_by_identity: dict[str, int] = {}
        for attempt in blocked_attempts:
            if attempt.course_id not in pending_degree_course_ids:
                continue
            identity = attempt.credit_identity or attempt.course_id
            projected_pending_by_identity[identity] = max(
                projected_pending_by_identity.get(identity, 0),
                problem.courses[attempt.course_id].credits,
            )
        projected_pending_credits = sum(projected_pending_by_identity.values())
        credits_needed = max(
            0,
            problem.curriculum.accepted_credit_target
            - reconciliation.official_earned_credits
            - projected_pending_credits,
        )
        if not mandatory_requirements and credits_needed == 0 and not any(group_remaining.values()):
            explanation = "all configured requirements were already satisfied"
            if deferred_requirement_ids:
                explanation = (
                    "remaining requirements are awaiting results or confirmed as still "
                    "in progress and were not scheduled again"
                )
            return GraduationPlan(
                SolverStatus.OPTIMAL,
                graduation_term=terms[0],
                explanations=(explanation,),
            )
        approved_optional_credits = sum(problem.courses[c].credits for c in optional)
        maximum_mandatory_credits = sum(
            max(problem.courses[course_id].credits for course_id in course_ids)
            for course_ids in delivery_options.values()
        )
        maximum_schedulable_credits = (
            maximum_mandatory_credits + approved_optional_credits
        )
        if (
            maximum_schedulable_credits < credits_needed
            and not problem.allow_credit_adjustment_proposal
        ):
            return GraduationPlan(
                SolverStatus.INFEASIBLE,
                explanations=(
                    f"remaining graduation-credit requirement is {credits_needed} ECTS, but "
                    f"applicable {'hypothetical' if problem.exploratory else 'approved'} "
                    f"optional candidates provide only {approved_optional_credits} ECTS",
                ),
            )

        offering_map = {(o.course_id, o.term): o for o in problem.offerings}
        prereq_map = {r.course_id: r.all_of for r in problem.prerequisites}
        completed = reconciliation.prerequisite_completion_ids
        failed_repeat_ids = unresolved_failed_course_ids(
            problem.student, frozenset(mandatory_requirements)
        )
        # Optional prerequisites may be scheduled only as supporting courses; they
        # never acquire graduation-credit authority merely by being prerequisites.
        # A persisted current registration may contain a course that is not a
        # graduation candidate by itself. Keep it in the model so the observed
        # roster can be represented without granting it degree-credit authority.
        course_pool = set(mandatory_delivery_ids) | set(optional)
        if problem.configuration.authoritative_course_terms:
            course_pool.update(problem.configuration.authoritative_course_terms)
        pending = list(course_pool)
        while pending:
            dependent = pending.pop()
            for prerequisite in prereq_map.get(dependent, frozenset()):
                if prerequisite in completed or prerequisite in course_pool:
                    continue
                if prerequisite in problem.courses:
                    course_pool.add(prerequisite)
                    pending.append(prerequisite)
        auxiliary = sorted(course_pool - set(mandatory_delivery_ids) - set(optional))
        planning_courses = sorted(course_pool)
        model = cp_model.CpModel()
        x: dict[tuple[str, int], cp_model.IntVar] = {}
        unavailable: list[str] = []
        graduation_index = model.NewIntVar(0, len(terms) - 1, "graduation_index")
        adjustment_amount = model.NewIntVar(
            0,
            credits_needed if problem.allow_credit_adjustment_proposal else 0,
            "administrative_credit_adjustment",
        )

        for course_id in planning_courses:
            course = problem.courses[course_id]
            for ti, term in enumerate(terms):
                var = model.NewBoolVar(f"course_{course_id}_{ti}")
                x[course_id, ti] = var
                offering = offering_map.get((course_id, term))
                rollout = self.rollout_policy.permits(course, term)
                registration_reason = self.registration_policy.rejection_reason(problem.student, course, term)
                authoritative_here = (
                    problem.configuration.authoritative_course_terms.get(course_id)
                    == term
                )
                if (
                    offering is None
                    or (
                        not authoritative_here
                        and (not rollout.permitted or registration_reason)
                    )
                ):
                    model.Add(var == 0)
                if course_id in blocked_course_ids:
                    model.Add(var == 0)
            occurrences = sum(x[course_id, ti] for ti in range(len(terms)))
            model.Add(occurrences <= 1)
            if not any((course_id, term) in offering_map for term in terms):
                unavailable.append(course_id)

        for requirement_id, course_ids in delivery_options.items():
            model.Add(sum(
                x[course_id, ti]
                for course_id in course_ids
                for ti in range(len(terms))
            ) == 1)

        for locked_term, allowed_course_ids in (
            problem.configuration.locked_term_course_ids.items()
        ):
            if locked_term not in terms:
                continue
            locked_index = terms.index(locked_term)
            for course_id in planning_courses:
                if course_id not in allowed_course_ids:
                    model.Add(x[course_id, locked_index] == 0)

        # Accepted equivalencies are alternatives, not two independent courses.
        # Historical completion filtering handles already-passed work above;
        # this constraint prevents both sides being selected prospectively.
        for equivalency in problem.equivalencies:
            equivalent_planning_ids = sorted(
                (equivalency.source_course_ids | equivalency.target_requirement_ids)
                & course_pool
            )
            if len(equivalent_planning_ids) > 1:
                model.Add(sum(
                    x[course_id, ti]
                    for course_id in equivalent_planning_ids
                    for ti in range(len(terms))
                ) <= 1)

        # Choice pools are independent degree requirements. Credits from one
        # pool can never satisfy another merely because the global total fits.
        for group in problem.credit_requirement_groups:
            remaining = group_remaining[group.code]
            if remaining == 0:
                continue
            available_ids = sorted(set(group.course_credits) & set(planning_courses))
            if not available_ids:
                return GraduationPlan(
                    SolverStatus.INFEASIBLE,
                    explanations=(f"requirement group {group.code} has {remaining} ECTS remaining but no schedulable candidates",),
                )
            model.Add(sum(
                group.course_credits[course_id] * x[course_id, ti]
                for course_id in available_ids for ti in range(len(terms))
            ) >= remaining)

        final_load_activations: list[cp_model.IntVar] = []
        for ti, term in enumerate(terms):
            selected_credits = sum(problem.courses[c].credits * x[c, ti] for c in planning_courses)
            config = problem.configuration
            conditional_repeat = (
                term.is_regular
                and config.allow_extended_load_when_repeating_failed_course
                and not has_explicit_capacity_override(config, term)
            )
            final_two_semesters = (
                term.is_regular
                and config.allow_final_two_semester_graduation_load
                and not has_explicit_capacity_override(config, term)
            )
            bonuses: list[cp_model.LinearExpr] = []
            if conditional_repeat:
                repeat_activation = model.NewBoolVar(f"repeat_allowance_{ti}")
                repeat_vars = [
                    x[c, ti] for c in failed_repeat_ids
                    if c in mandatory_delivery_ids
                ]
                if repeat_vars:
                    model.Add(repeat_activation <= sum(repeat_vars))
                    for repeat_var in repeat_vars:
                        model.Add(repeat_var <= repeat_activation)
                else:
                    model.Add(repeat_activation == 0)
                bonuses.append(
                    (config.extended_failed_repeat_capacity - config.capacity_for(term))
                    * repeat_activation
                )
            if final_two_semesters:
                final_activation = model.NewBoolVar(f"final_two_semester_allowance_{ti}")
                final_load_activations.append(final_activation)
                later_regular = [
                    index for index in range(ti + 1, len(terms))
                    if terms[index].is_regular
                ]
                if len(later_regular) > 1:
                    model.Add(graduation_index < later_regular[1]).OnlyEnforceIf(
                        final_activation
                    )
                model.Add(graduation_index >= ti).OnlyEnforceIf(final_activation)
                bonuses.append(
                    (config.final_two_semester_graduation_capacity
                     - config.capacity_for(term)) * final_activation
                )
            if bonuses:
                maximum_bonus = max(
                    config.extended_failed_repeat_capacity,
                    config.final_two_semester_graduation_capacity,
                ) - config.capacity_for(term)
                capacity_bonus = model.NewIntVar(
                    0, max(0, maximum_bonus), f"capacity_bonus_{ti}"
                )
                model.AddMaxEquality(capacity_bonus, bonuses)
                model.Add(selected_credits <= config.capacity_for(term) + capacity_bonus)
            else:
                capacity = self.credit_policy.capacity(
                    problem.student, term, problem.configuration
                )
                model.Add(selected_credits <= capacity)

        for course_id in planning_courses:
            for prerequisite in prereq_map.get(course_id, frozenset()):
                if prerequisite in completed:
                    continue
                if prerequisite not in course_pool:
                    for ti in range(len(terms)):
                        if (
                            problem.configuration.authoritative_course_terms.get(course_id)
                            != terms[ti]
                        ):
                            model.Add(x[course_id, ti] == 0)
                    continue
                for ti in range(len(terms)):
                    if (
                        problem.configuration.authoritative_course_terms.get(course_id)
                        == terms[ti]
                    ):
                        continue
                    model.Add(x[course_id, ti] <= sum(x[prerequisite, earlier] for earlier in range(ti)))

        term_indexes = {term: index for index, term in enumerate(terms)}
        for course_id, forced_term in problem.configuration.forced_course_terms.items():
            if course_id not in course_pool or forced_term not in term_indexes:
                return GraduationPlan(
                    SolverStatus.INFEASIBLE,
                    explanations=(
                        f"forced assignment is unavailable: {course_id} in {forced_term.label()}",
                    ),
                )
            model.Add(x[course_id, term_indexes[forced_term]] == 1)

        training_ids = (
            problem.curriculum.training_requirement_ids
            & set(mandatory_requirements)
        )
        first_academic_year = terms[0].academic_year_start
        training_delay_terms = []
        for course_id in training_ids:
            course = problem.courses[course_id]
            normal_year = first_academic_year + course.reference_year - problem.student.nominal_year
            training_kinds = {
                offering.term.kind
                for offering in problem.offerings
                if offering.course_id == course_id
                and offering.term.kind in {TermKind.TRAINING_1, TermKind.TRAINING_2}
            }
            for ti, term in enumerate(terms):
                delay_years = term.academic_year_start - normal_year
                if term.kind not in training_kinds or delay_years < 0:
                    model.Add(x[course_id, ti] == 0)
                    continue
                if not problem.configuration.allow_training_postponement and delay_years != 0:
                    model.Add(x[course_id, ti] == 0)
                    continue
                maximum = problem.configuration.max_training_delay_years
                if maximum is not None and delay_years > maximum:
                    model.Add(x[course_id, ti] == 0)
                    continue
                training_delay_terms.append(
                    delay_years * problem.configuration.training_delay_penalty * x[course_id, ti]
                )

        # Exact current-term bundle choice; every selected course gets exactly one complete bundle.
        bundle_vars: dict[str, cp_model.IntVar] = {}
        current = terms[0]
        current_bundles = []
        for course_id in planning_courses:
            offering = offering_map.get((course_id, current))
            bundles = offering.bundles if offering else ()
            if not bundles:
                model.Add(x[course_id, 0] == 0)
                continue
            variables = []
            for bundle in bundles:
                bv = model.NewBoolVar(f"bundle_{bundle.id}")
                bundle_vars[bundle.id] = bv
                variables.append(bv)
                current_bundles.append(bundle)
            model.Add(sum(variables) == x[course_id, 0])
        for i, left in enumerate(current_bundles):
            for right in current_bundles[i + 1:]:
                if bundles_conflict(left, right):
                    model.Add(bundle_vars[left.id] + bundle_vars[right.id] <= 1)

        day_vars = []
        for weekday in range(7):
            using_day = [
                bundle_vars[bundle.id]
                for bundle in current_bundles
                if any(int(meeting.weekday) == weekday for section in bundle.sections for meeting in section.meetings)
            ]
            if using_day:
                day_var = model.NewBoolVar(f"current_day_{weekday}")
                for bundle_var in using_day:
                    model.Add(day_var >= bundle_var)
                model.Add(day_var <= sum(using_day))
                day_vars.append(day_var)

        # Lexicographic objectives are solved sequentially and each proven value
        # is fixed before the next preference is introduced.
        # Graduation is the last period containing any selected course needed by
        # the degree plan.  Minimizing this variable makes the inequalities exact
        # without preventing optional credits from extending beyond the last
        # mandatory course.
        for course_id in planning_courses:
            for ti in range(len(terms)):
                model.Add(graduation_index >= ti * x[course_id, ti])
        graduation_credit_expression = sum(
            problem.courses[c].credits * x[c, ti]
            for c in set(mandatory_delivery_ids) | set(optional)
            for ti in range(len(terms))
        )
        accepted_credit_expression = (
            graduation_credit_expression + adjustment_amount
        )
        model.Add(accepted_credit_expression >= credits_needed)
        # With the accepted-credit footprint fixed, prefer combinations
        # containing larger-credit courses. Squared credits distinguish, for
        # example, 4+3+1 from 3+3+2 without weakening prerequisite constraints;
        # a smaller prerequisite is still selected whenever it unlocks the
        # preferred larger course.
        optional_credit_priority = sum(
            problem.courses[c].credits ** 2 * x[c, ti]
            for c in optional for ti in range(len(terms))
        )
        current_mandatory_credits = sum(
            problem.courses[c].credits * x[c, 0]
            for c in mandatory_delivery_ids
        )
        scarce_current_mandatory_credits = 0
        failed_current_mandatory_credits = 0
        backlog_current_mandatory_priority = 0
        for requirement_id, course_ids in delivery_options.items():
            has_verified_later_delivery = any(
                offering_map.get((course_id, term)) is not None
                and offering_map[course_id, term].availability_verified
                and self.rollout_policy.permits(
                    problem.courses[course_id], term
                ).permitted
                and self.registration_policy.rejection_reason(
                    problem.student, problem.courses[course_id], term
                ) is None
                for course_id in course_ids
                for term in terms[1:]
            )
            current_delivery_credits = sum(
                problem.courses[course_id].credits * x[course_id, 0]
                for course_id in course_ids
            )
            if not has_verified_later_delivery:
                scarce_current_mandatory_credits += current_delivery_credits
            if requirement_id in failed_repeat_ids:
                failed_current_mandatory_credits += current_delivery_credits
            requirement_course = problem.courses.get(requirement_id)
            reference_year = (
                requirement_course.reference_year
                if requirement_course is not None
                else min(problem.courses[c].reference_year for c in course_ids)
            )
            backlog_gap = max(
                0, problem.student.nominal_year - reference_year
            )
            backlog_current_mandatory_priority += (
                backlog_gap * current_delivery_credits
            )
        current_credit_expression = sum(
            problem.courses[c].credits * x[c, 0]
            for c in planning_courses
        )
        alignment_terms = []
        current_alignment_terms = []
        productive_terms = []
        for course_id in planning_courses:
            course = problem.courses[course_id]
            for ti, term in enumerate(terms):
                projected_year = problem.student.nominal_year + (
                    term.academic_year_start - first_academic_year
                )
                year_deviation = abs(course.reference_year - projected_year)
                semester_deviation = (
                    0
                    if course_id in training_ids or term.kind is course.reference_semester
                    else 1
                )
                alignment_penalty = (
                    problem.configuration.academic_year_deviation_weight * year_deviation
                    + problem.configuration.reference_semester_deviation_weight * semester_deviation
                ) * x[course_id, ti]
                alignment_terms.append(alignment_penalty)
                if ti == 0:
                    current_alignment_terms.append(alignment_penalty)
                productive_terms.append(problem.courses[course_id].credits * (len(terms) - ti) * x[course_id, ti])
        mandatory_productive_terms = sum(
            problem.courses[c].credits * (len(terms) - ti) * x[c, ti]
            for c in mandatory_delivery_ids
            for ti in range(len(terms))
        )
        mandatory_cross_system_selection = sum(
            x[course_id, ti]
            for course_id in mandatory_delivery_ids
            if problem.courses[course_id].curriculum_version
            is not problem.curriculum.version
            for ti in range(len(terms))
        )
        alternate_track_bundles = [
            bundle_vars[bundle.id]
            for bundle in current_bundles
            if any(section.teaching_language is not None
                   and section.teaching_language is not problem.student.language_track
                   for section in bundle.sections)
        ]
        objective_stages = [
            # Administrative adjustments are a last-resort way to close an
            # otherwise unfillable numerical deficit.  First avoid excess
            # accepted credit, then prefer real coursework for an exact fit.
            # This selects a real 2-ECTS course at 298/300, but proposes a
            # 1-ECTS adjustment at 299/300 instead of forcing 2 excess ECTS.
            ("min", accepted_credit_expression),
            ("min", adjustment_amount),
            ("min", graduation_index),
            # The IUL final-two-semester allowance is used only when it improves
            # the already-prioritized graduation date.
            ("min", sum(final_load_activations)),
            # A confirmed current opportunity is safer than an unverified
            # future assumption.  This is evaluated per requirement across all
            # accepted delivery equivalents, not per legacy course code.
            ("max", scarce_current_mandatory_credits),
            # Failed and earlier-year backlog choose among mandatory work
            # without overriding graduation speed or a genuinely scarce
            # requirement opportunity. Mandatory credit then precedes optional
            # credit when those academic distinctions are equal.
            ("max", failed_current_mandatory_credits),
            ("max", backlog_current_mandatory_priority),
            ("max", current_mandatory_credits),
            ("max", mandatory_productive_terms),
            ("min", sum(training_delay_terms)),
            # Governing-curriculum preference applies only when choosing how to
            # deliver a mandatory requirement. It cannot promote an OLD
            # optional course ahead of mandatory backlog.
            ("min", mandatory_cross_system_selection),
            ("max", optional_credit_priority),
            # Nominal year and semester are tie-breakers, never reasons to defer
            # mandatory, prerequisite-enabling, or backlog work.
            ("min", sum(current_alignment_terms)),
            ("min", sum(alignment_terms)),
            # Load is a capacity, not a degree objective. Fill it only after the
            # academic priorities above are fixed.
            ("max", current_credit_expression),
            ("max", sum(productive_terms)),
            ("min", sum(
                x[c, ti]
                for c in optional + auxiliary for ti in range(len(terms))
            )),
        ]
        if problem.configuration.prefer_own_track_sections:
            objective_stages.append(("min", sum(alternate_track_bundles)))
        objective_stages.append(("min", sum(day_vars)))
        solver = cp_model.CpSolver()
        # Repeatable plans matter for review and import comparisons. A single
        # deterministic worker prevents equally optimal schedules from changing
        # merely because parallel search completed in a different order.
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        solve_started = monotonic()
        all_stages_optimal = True
        result = cp_model.UNKNOWN
        last_feasible_values: dict[int, int] | None = None
        response_variables = [
            *x.values(), *bundle_vars.values(), graduation_index, adjustment_amount,
        ]
        for stage_index, (direction, expression) in enumerate(objective_stages):
            remaining_seconds = problem.configuration.time_limit_seconds - (monotonic() - solve_started)
            if remaining_seconds <= 0:
                all_stages_optimal = False
                break
            solver.parameters.max_time_in_seconds = remaining_seconds
            if direction == "min":
                model.Minimize(expression)
            else:
                model.Maximize(expression)
            result = solver.Solve(model)
            if result not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
                break
            if result != cp_model.OPTIMAL:
                all_stages_optimal = False
            value = solver.Value(expression)
            last_feasible_values = {
                variable.Index(): solver.Value(variable)
                for variable in response_variables
            }
            if stage_index < len(objective_stages) - 1:
                model.Add(expression == value)
        use_saved_incumbent = (
            result == cp_model.UNKNOWN and last_feasible_values is not None
        )
        status = (
            SolverStatus.OPTIMAL
            if result == cp_model.OPTIMAL and all_stages_optimal
            else SolverStatus.FEASIBLE_NOT_PROVEN_OPTIMAL
            if result in {cp_model.OPTIMAL, cp_model.FEASIBLE} or use_saved_incumbent
            else SolverStatus.INFEASIBLE
            if result == cp_model.INFEASIBLE
            else SolverStatus.UNKNOWN
        )
        if status in {SolverStatus.INFEASIBLE, SolverStatus.UNKNOWN}:
            details = ["no plan satisfies all requirements within the supplied horizon"]
            if unavailable:
                details.append(f"no offering supplied in horizon: {', '.join(unavailable)}")
            return GraduationPlan(status, explanations=tuple(details))

        def solution_value(variable: cp_model.IntVar) -> int:
            if use_saved_incumbent:
                assert last_feasible_values is not None
                return last_feasible_values[variable.Index()]
            return solver.Value(variable)

        scheduled: list[ScheduledTerm] = []
        for ti, term in enumerate(terms):
            chosen = tuple(c for c in planning_courses if solution_value(x[c, ti]))
            chosen_bundles = tuple(
                b.id for b in current_bundles
                if ti == 0 and solution_value(bundle_vars[b.id])
            )
            scheduled.append(ScheduledTerm(term, chosen, chosen_bundles))
        graduation_term = terms[solution_value(graduation_index)]
        warnings = []
        if use_saved_incumbent:
            warnings.append(
                "The solver time limit was reached during a lower-priority "
                "optimization stage; the last verified feasible plan was retained."
            )
        if blocked_course_ids:
            warnings.append(
                "Courses awaiting results or confirmed as still in progress were "
                "kept unearned and were not scheduled again: "
                + ", ".join(sorted(blocked_course_ids))
                + "."
            )
        adjustment_credits = solution_value(adjustment_amount)
        adjustment_term = graduation_term if adjustment_credits else None
        adjustment_proposal = (
            CreditAdjustmentProposal(
                adjustment_credits,
                adjustment_term,
                "No approved real-course combination reaches the graduation-credit "
                "target exactly; this closes only the residual numerical deficit.",
            )
            if adjustment_credits and adjustment_term is not None
            else None
        )
        if adjustment_proposal:
            warnings.append(
                f"A provisional {adjustment_credits}-ECTS administrative credit adjustment "
                f"is proposed in {adjustment_term.label()}; academic approval is required."
            )
        selected_bundle_ids = {bundle_id for term in scheduled for bundle_id in term.bundle_ids}
        used_alternate_track = any(
            bundle.id in selected_bundle_ids
            and any(section.teaching_language is not None
                    and section.teaching_language is not problem.student.language_track
                    for section in bundle.sections)
            for bundle in current_bundles
        )
        if used_alternate_track:
            warnings.append(
                "Permitted alternate-track section selected; current timetable is conflict-free. "
                "Institutional permission is an unverified configured assumption."
            )
        if any(bundle.id in selected_bundle_ids and any(
                section.provenance.value in {"SYNTHETIC_UNVERIFIED", "SYNTHETIC_PLACEHOLDER"}
                for section in bundle.sections) for bundle in current_bundles):
            warnings.append(
                "Current registration uses synthetic or otherwise unverified timetable data."
            )
        used_unverified = [o for o in problem.offerings if not o.availability_verified and any(o.course_id in s.course_ids and o.term == s.term for s in scheduled)]
        if used_unverified:
            warnings.append("graduation date relies on unverified future offering assumptions")
        selected_optional_ids = tuple(
            c for c in optional
            if any(solution_value(x[c, ti]) for ti in range(len(terms)))
        )
        hypothetical = problem.exploratory and any(
            optional_approvals[c].status is ApprovalStatus.UNVERIFIED
            for c in selected_optional_ids
        )
        if hypothetical:
            warnings.append(
                "This hypothetical plan depends on unverified optional-credit approval(s) "
                "and is not an official graduation-ready plan."
            )
        credit_usages = []
        outstanding_set = frozenset(mandatory_requirements)
        for scheduled_term in scheduled:
            selected_ids = frozenset(scheduled_term.course_ids)
            decision = effective_credit_capacity(
                problem.student,
                scheduled_term.term,
                problem.configuration,
                outstanding_set,
                selected_ids,
                selected_credits=sum(problem.courses[c].credits for c in selected_ids),
                graduation_term=graduation_term,
                planning_horizon=problem.configuration.planning_horizon,
            )
            credit_usages.append(TermCreditUsage(
                scheduled_term.term,
                sum(problem.courses[c].credits for c in selected_ids),
                decision.capacity,
                decision.reason,
                decision.repeated_course_ids,
            ))
        return GraduationPlan(
            status,
            tuple(scheduled),
            graduation_term,
            ("lexicographic optimality is relative to the supplied horizon and offerings",),
            tuple(warnings),
            tuple(credit_usages),
            selected_optional_ids,
            hypothetical,
            adjustment_proposal,
        )

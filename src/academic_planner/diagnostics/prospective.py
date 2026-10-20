from __future__ import annotations

from dataclasses import dataclass, replace

from academic_planner.domain.models import (
    PrerequisiteRule, SolverStatus,
)
from academic_planner.fixtures import build_scenario
from academic_planner.optimization import GlobalPlanner, PlanningProblem
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy,
    ProgressiveRolloutPolicy,
)
from academic_planner.reconciliation import ReconciliationService
from academic_planner.validation import validate_plan


@dataclass(frozen=True)
class ProspectiveEquivalencyApproval:
    registration_course_id: str
    target_requirement_id: str
    requirement_equivalency_id: str
    prerequisite_equivalency_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProspectiveEquivalencyExperimentResult:
    baseline_graduation_term: str | None
    optional_experiment_graduation_term: str | None
    forced_substitution_graduation_term: str | None
    baseline_solver_status: str
    forced_substitution_solver_status: str
    optional_selected_registration_course: bool
    forced_registration_term: str | None
    forced_selected_current_credits: int
    forced_selected_bundle_components: tuple[str, ...]
    curriculum_credit_total: int
    validation_issue_codes: tuple[str, ...]
    scheduled_registration_count: int
    scheduled_native_target_count: int


ELBC901_CCE640_APPROVAL = ProspectiveEquivalencyApproval(
    registration_course_id="OLD:ELBC901",
    target_requirement_id="NEW:CCE640",
    requirement_equivalency_id="SYN:ELBC901:CCE640:O2N",
    prerequisite_equivalency_ids=("SYN:ELBC504:CCE450:N2O",),
)


def apply_prospective_equivalency(
    problem: PlanningProblem, approval: ProspectiveEquivalencyApproval
) -> PlanningProblem:
    """Build an isolated curriculum view for one explicitly approved substitution."""
    reconciliation = ReconciliationService().reconcile(
        problem.student, problem.curriculum, problem.equivalencies
    )
    if approval.target_requirement_id not in reconciliation.outstanding_requirement_ids:
        raise ValueError(
            f"target requirement is not outstanding: {approval.target_requirement_id}"
        )
    if approval.registration_course_id in problem.curriculum.requirement_ids:
        raise ValueError("registration course is already a curriculum requirement")

    equivalencies = {item.id: item for item in problem.equivalencies}
    requirement_equivalency = equivalencies.get(approval.requirement_equivalency_id)
    if requirement_equivalency is None:
        raise ValueError(
            f"unknown requirement equivalency: {approval.requirement_equivalency_id}"
        )
    if (
        approval.registration_course_id not in requirement_equivalency.source_course_ids
        or approval.target_requirement_id
        not in requirement_equivalency.target_requirement_ids
    ):
        raise ValueError("requirement equivalency does not approve the requested substitution")

    prerequisite_map = {
        rule.course_id: rule for rule in problem.prerequisites
    }
    registration_prerequisites = prerequisite_map.get(
        approval.registration_course_id,
        PrerequisiteRule(approval.registration_course_id),
    ).all_of
    approved_prerequisite_sources: set[str] = set()
    covered_registration_prerequisites: set[str] = set()
    for equivalency_id in approval.prerequisite_equivalency_ids:
        equivalency = equivalencies.get(equivalency_id)
        if equivalency is None:
            raise ValueError(f"unknown prerequisite equivalency: {equivalency_id}")
        matched_targets = registration_prerequisites & equivalency.target_requirement_ids
        if not matched_targets:
            raise ValueError(
                f"equivalency {equivalency_id} does not satisfy a registration prerequisite"
            )
        completed_sources = (
            equivalency.source_course_ids
            & reconciliation.satisfied_requirement_ids
        )
        if not completed_sources:
            raise ValueError(
                f"approved prerequisite source is not satisfied: {equivalency_id}"
            )
        covered_registration_prerequisites.update(matched_targets)
        approved_prerequisite_sources.update(completed_sources)
    uncovered = registration_prerequisites - covered_registration_prerequisites
    if uncovered:
        raise ValueError(
            "registration prerequisites lack explicit prospective approval: "
            + ", ".join(sorted(uncovered))
        )

    target_course = problem.courses[approval.target_requirement_id]
    registration_course = problem.courses[approval.registration_course_id]
    if target_course.credits != registration_course.credits:
        raise ValueError(
            "prospective substitution must preserve requirement credits to avoid double counting"
        )

    requirements = (
        problem.curriculum.requirement_ids - {approval.target_requirement_id}
    ) | {approval.registration_course_id}
    curriculum = replace(problem.curriculum, requirement_ids=frozenset(requirements))
    prerequisites = tuple(
        rule for rule in problem.prerequisites
        if rule.course_id != approval.registration_course_id
    ) + (
        PrerequisiteRule(
            approval.registration_course_id,
            frozenset(approved_prerequisite_sources),
            registration_course.provenance,
        ),
    )
    return replace(problem, curriculum=curriculum, prerequisites=prerequisites)


def run_elbc901_cce640_experiment() -> ProspectiveEquivalencyExperimentResult:
    scenario = build_scenario("failed-fourth")
    base_problem = scenario.data.demo_problem()
    conditional_config = replace(
        base_problem.configuration,
        allow_extended_load_when_repeating_failed_course=True,
    )
    baseline_problem = replace(base_problem, configuration=conditional_config)
    prospective_problem = apply_prospective_equivalency(
        baseline_problem, ELBC901_CCE640_APPROVAL
    )
    planner = GlobalPlanner(
        ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(),
        AllowAllRegistrationPolicy(),
    )
    baseline = planner.plan(baseline_problem)
    forced_substitution = planner.plan(prospective_problem)
    if (
        baseline.graduation_term is None
        or forced_substitution.graduation_term is None
    ):
        raise ValueError("both prospective-equivalency branches must be feasible")
    optional_selected_registration_course = (
        forced_substitution.graduation_term < baseline.graduation_term
    )
    optional_plan = forced_substitution if optional_selected_registration_course else baseline
    registration_terms = [
        scheduled for scheduled in forced_substitution.scheduled_terms
        if ELBC901_CCE640_APPROVAL.registration_course_id in scheduled.course_ids
    ]
    native_target_count = sum(
        ELBC901_CCE640_APPROVAL.target_requirement_id in scheduled.course_ids
        for scheduled in forced_substitution.scheduled_terms
    )
    current = (
        forced_substitution.scheduled_terms[0]
        if forced_substitution.scheduled_terms else None
    )
    bundle_map = {
        bundle.id: bundle
        for offering in prospective_problem.offerings for bundle in offering.bundles
    }
    selected_elbc901_bundle = next((
        bundle_map[bundle_id]
        for bundle_id in (current.bundle_ids if current else ())
        if bundle_map[bundle_id].course_id
        == ELBC901_CCE640_APPROVAL.registration_course_id
    ), None)
    validation_issues = validate_plan(forced_substitution, prospective_problem)
    return ProspectiveEquivalencyExperimentResult(
        baseline_graduation_term=(
            baseline.graduation_term.label() if baseline.graduation_term else None
        ),
        optional_experiment_graduation_term=(
            optional_plan.graduation_term.label()
            if optional_plan.graduation_term else None
        ),
        forced_substitution_graduation_term=(
            forced_substitution.graduation_term.label()
            if forced_substitution.graduation_term else None
        ),
        baseline_solver_status=baseline.status.value,
        forced_substitution_solver_status=forced_substitution.status.value,
        optional_selected_registration_course=optional_selected_registration_course,
        forced_registration_term=(
            registration_terms[0].term.label() if registration_terms else None
        ),
        forced_selected_current_credits=(
            forced_substitution.credit_usages[0].selected_credits
            if forced_substitution.credit_usages else 0
        ),
        forced_selected_bundle_components=(
            tuple(section.component for section in selected_elbc901_bundle.sections)
            if selected_elbc901_bundle else ()
        ),
        curriculum_credit_total=sum(
            prospective_problem.courses[item].credits
            for item in prospective_problem.curriculum.requirement_ids
        ),
        validation_issue_codes=tuple(issue.code for issue in validation_issues),
        scheduled_registration_count=len(registration_terms),
        scheduled_native_target_count=native_target_count,
    )

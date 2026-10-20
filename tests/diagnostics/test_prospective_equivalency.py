from dataclasses import replace

import pytest

from academic_planner.diagnostics import (
    ELBC901_CCE640_APPROVAL, ProspectiveEquivalencyApproval,
    apply_prospective_equivalency, run_elbc901_cce640_experiment,
)
from academic_planner.fixtures import build_scenario
from academic_planner.reconciliation import ReconciliationService


def _conditional_problem():
    problem = build_scenario("failed-fourth").data.demo_problem()
    return replace(
        problem,
        configuration=replace(
            problem.configuration,
            allow_extended_load_when_repeating_failed_course=True,
        ),
    )


def test_prospective_substitution_requires_explicit_prerequisite_approval():
    incomplete = ProspectiveEquivalencyApproval(
        registration_course_id="OLD:ELBC901",
        target_requirement_id="NEW:CCE640",
        requirement_equivalency_id="SYN:ELBC901:CCE640:O2N",
    )
    with pytest.raises(ValueError, match="lack explicit prospective approval"):
        apply_prospective_equivalency(_conditional_problem(), incomplete)


def test_only_the_explicitly_approved_requirement_is_substituted():
    base = _conditional_problem()
    prospective = apply_prospective_equivalency(
        base, ELBC901_CCE640_APPROVAL
    )
    requirements = prospective.curriculum.requirement_ids
    assert "NEW:CCE640" not in requirements
    assert "OLD:ELBC901" in requirements
    assert "OLD:ELCC711" not in requirements
    assert len(requirements) == len(base.curriculum.requirement_ids)
    assert sum(prospective.courses[item].credits for item in requirements) == 300

    rules = {rule.course_id: rule.all_of for rule in prospective.prerequisites}
    assert rules["OLD:ELBC901"] == {"NEW:CCE450"}
    reconciled = ReconciliationService().reconcile(
        prospective.student, prospective.curriculum, prospective.equivalencies
    )
    assert "NEW:CCE450" in reconciled.satisfied_requirement_ids


def test_optional_prospective_registration_improves_earliest_graduation():
    result = run_elbc901_cce640_experiment()
    assert result.baseline_solver_status == "OPTIMAL"
    assert result.forced_substitution_solver_status == "OPTIMAL"
    assert result.baseline_graduation_term == "2028-2029 SPRING"
    assert result.optional_experiment_graduation_term == "2028-2029 FALL"
    assert result.forced_substitution_graduation_term == "2028-2029 FALL"
    assert result.optional_selected_registration_course
    assert result.forced_registration_term == "2026-2027 FALL"


def test_elbc901_is_counted_once_and_preserves_mandatory_lab_bundle():
    result = run_elbc901_cce640_experiment()
    assert result.curriculum_credit_total == 300
    assert result.scheduled_registration_count == 1
    assert result.scheduled_native_target_count == 0
    assert result.forced_selected_bundle_components == (
        "LECTURE", "LAB:ELBC901L"
    )
    assert result.forced_selected_current_credits == 29
    assert result.validation_issue_codes == ()


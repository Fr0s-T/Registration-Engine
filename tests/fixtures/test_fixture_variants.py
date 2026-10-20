import pytest

from academic_planner.domain.models import DataProvenance, SolverStatus
from academic_planner.fixtures import (
    BASELINE_FIXTURE, RELAXED_FIXTURE, SyntheticFixtureLoader, build_scenario,
    compare_struggling_fixture_variants,
)
from academic_planner.optimization import GlobalPlanner
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy,
    ProgressiveRolloutPolicy,
)
from academic_planner.scheduling.conflicts import bundles_conflict
from academic_planner.validation import validate_plan


def _planner():
    return GlobalPlanner(
        ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(),
        AllowAllRegistrationPolicy(),
    )


def _rules(data):
    return {rule.course_id: rule.all_of for rule in data.prerequisites}


def _offering(data, course_id):
    current = data.demo_configuration.planning_horizon[0]
    return next(
        offering for offering in data.offerings
        if offering.course_id == course_id and offering.term == current
    )


def test_baseline_is_unchanged_and_relaxed_prerequisite_delta_is_minimal():
    baseline = SyntheticFixtureLoader().load(configuration=BASELINE_FIXTURE)
    relaxed = SyntheticFixtureLoader().load(configuration=RELAXED_FIXTURE)
    baseline_rules = _rules(baseline)
    relaxed_rules = _rules(relaxed)

    changed = {
        course_id for course_id in baseline_rules
        if baseline_rules[course_id] != relaxed_rules[course_id]
    }
    assert changed == {"NEW:CCE561", "NEW:CCE650"}
    assert baseline_rules["NEW:CCE561"] == {"NEW:CSC437"}
    assert relaxed_rules["NEW:CCE561"] == {"NEW:CSC333"}
    assert baseline_rules["NEW:CCE650"] == {"NEW:CCE561"}
    assert relaxed_rules["NEW:CCE650"] == {"NEW:CCE443"}

    # Foundational dependencies explicitly requested for preservation.
    assert relaxed_rules["NEW:MAT231"] == {"NEW:MAT230"}
    assert relaxed_rules["NEW:CSC333"] == {"NEW:CSC320"}
    assert relaxed_rules["NEW:CCE451"] == {"NEW:CCE341"}
    assert relaxed_rules["NEW:CCE550"] == {"NEW:CCE443"}
    assert all(
        rule.provenance is DataProvenance.SYNTHETIC_UNVERIFIED
        for rule in relaxed.prerequisites
    )


def test_relaxed_fixture_is_the_only_implicit_runtime_default():
    loaded = SyntheticFixtureLoader().load()
    scenario = build_scenario("struggling-third")
    assert loaded.fixture_configuration == RELAXED_FIXTURE
    assert scenario.data.fixture_configuration == RELAXED_FIXTURE


def test_relaxed_timetable_adds_without_overwriting_baseline_sections():
    baseline = SyntheticFixtureLoader().load(configuration=BASELINE_FIXTURE)
    relaxed = SyntheticFixtureLoader().load(configuration=RELAXED_FIXTURE)
    for course_id in baseline.courses:
        baseline_offerings = [
            offering for offering in baseline.offerings
            if offering.course_id == course_id
            and offering.term == baseline.demo_configuration.planning_horizon[0]
        ]
        relaxed_offerings = [
            offering for offering in relaxed.offerings
            if offering.course_id == course_id
            and offering.term == relaxed.demo_configuration.planning_horizon[0]
        ]
        if not baseline_offerings:
            continue
        baseline_bundles = baseline_offerings[0].bundles
        relaxed_bundles = relaxed_offerings[0].bundles
        assert relaxed_bundles[:len(baseline_bundles)] == baseline_bundles

    baseline_cce431 = _offering(baseline, "NEW:CCE431")
    relaxed_cce431 = _offering(relaxed, "NEW:CCE431")
    assert len(baseline_cce431.bundles) == 2
    assert len(relaxed_cce431.bundles) == 3
    extra_meeting = relaxed_cce431.bundles[-1].sections[0].meetings[0]
    assert extra_meeting.weekday.name == "THURSDAY"

    # Genuine conflicts remain elsewhere in the relaxed timetable.
    cce420 = _offering(relaxed, "NEW:CCE420")
    cce331 = _offering(relaxed, "NEW:CCE331")
    assert bundles_conflict(cce420.bundles[0], cce331.bundles[0])

    # Mandatory lecture/lab pairing remains intact in every relaxed bundle.
    image = _offering(relaxed, "OLD:ELBC901")
    assert all(
        [section.component for section in bundle.sections]
        == ["LECTURE", "LAB:ELBC901L"]
        for bundle in image.bundles
    )


def test_controlled_experiment_outcomes_are_deterministic_and_valid():
    results = compare_struggling_fixture_variants()
    assert len(results) == 8
    by_key = {
        (result.experiment, result.conditional_repeat_allowance): result
        for result in results
    }
    for result in results:
        assert result.solver_status == SolverStatus.OPTIMAL.value
        assert not validate_plan(result.plan, result.problem)
        assert (result.eligible_course_count, result.eligible_credits) == (5, 20)
        assert result.graduation_term == "2029-2030 FALL"
        assert result.remaining_regular_semesters == 7
        assert result.fall_reference_outstanding_credits == 94

    for experiment in ("A", "C"):
        assert by_key[experiment, False].maximum_schedulable_credits == 17
        assert by_key[experiment, False].selected_current_credits == 17
    for experiment in ("B", "D"):
        assert by_key[experiment, False].maximum_schedulable_credits == 20
        assert by_key[experiment, False].selected_current_credits == 20

    # Pool construction is independent of timetable and credit-capacity policy.
    assert {
        (result.eligible_course_count, result.eligible_credits)
        for result in results
    } == {(5, 20)}
    for experiment in "ABCD":
        normal = by_key[experiment, False]
        conditional = by_key[experiment, True]
        assert normal.maximum_schedulable_credits == conditional.maximum_schedulable_credits
        assert normal.selected_current_credits == conditional.selected_current_credits
        assert normal.graduation_term == conditional.graduation_term
        assert normal.current_effective_capacity == 30
        assert conditional.current_effective_capacity == 36

    # The relaxed prerequisite changes advance CCE561 in experiment C, but the
    # Fall-only credit volume still prevents an earlier graduation.
    def scheduled_label(result, course_id):
        return next(
            item.term.label() for item in result.plan.scheduled_terms
            if course_id in item.course_ids
        )

    assert scheduled_label(by_key["A", False], "NEW:CCE561") == "2028-2029 FALL"
    assert scheduled_label(by_key["C", False], "NEW:CCE561") == "2027-2028 FALL"
    assert by_key["A", False].graduation_term == by_key["C", False].graduation_term


@pytest.mark.parametrize("fixture_configuration", [BASELINE_FIXTURE, RELAXED_FIXTURE])
@pytest.mark.parametrize("scenario_id", ["fresh", "regular-fourth", "failed-fourth"])
def test_golden_path_scenarios_remain_valid(scenario_id, fixture_configuration):
    scenario = build_scenario(
        scenario_id, fixture_configuration=fixture_configuration
    )
    problem = scenario.data.demo_problem()
    plan = _planner().plan(problem)
    assert plan.status is SolverStatus.OPTIMAL
    assert not validate_plan(plan, problem)
    assert plan.graduation_term is not None

    scheduled_index = {
        course_id: index
        for index, term in enumerate(plan.scheduled_terms)
        for course_id in term.course_ids
    }
    for rule in problem.prerequisites:
        if rule.course_id not in scheduled_index:
            continue
        for prerequisite in rule.all_of:
            if prerequisite in scheduled_index:
                assert scheduled_index[prerequisite] < scheduled_index[rule.course_id]

    if scenario_id == "fresh":
        for scheduled in plan.scheduled_terms:
            for course_id in scheduled.course_ids:
                if course_id not in problem.curriculum.training_requirement_ids:
                    assert problem.courses[course_id].reference_semester is scheduled.term.kind

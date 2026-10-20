from academic_planner.domain.models import CurriculumVersion, DataProvenance, SolverStatus, TermKind
from academic_planner.domain.validation import validate_catalog
from academic_planner.fixtures import SyntheticFixtureLoader
from academic_planner.optimization import GlobalPlanner
from academic_planner.policies import AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy
from academic_planner.validation import validate_plan


def seeded_plan():
    data = SyntheticFixtureLoader().load()
    planner = GlobalPlanner(ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(), AllowAllRegistrationPolicy())
    return data, planner.plan(data.demo_problem())


def test_seeded_curricula_each_total_300_ects():
    data = SyntheticFixtureLoader().load()
    for version, curriculum in data.curricula.items():
        assert sum(data.courses[c].credits for c in curriculum.requirement_ids) == 300, version


def test_seeded_assumptions_are_explicitly_unverified_and_catalog_is_valid():
    data = SyntheticFixtureLoader().load()
    assert all(c.provenance is DataProvenance.SYNTHETIC_UNVERIFIED for c in data.courses.values())
    assert all(r.provenance is DataProvenance.SYNTHETIC_UNVERIFIED for r in data.prerequisites)
    assert all(e.provenance is DataProvenance.SYNTHETIC_UNVERIFIED for e in data.equivalencies)
    assert all(o.provenance is DataProvenance.SYNTHETIC_UNVERIFIED for o in data.offerings)
    validate_catalog(data.courses, data.prerequisites, data.equivalencies)


def test_prerequisites_are_explicit_sparse_mappings_not_semester_anchors():
    data = SyntheticFixtureLoader().load()
    rules = {rule.course_id: rule.all_of for rule in data.prerequisites}
    assert len(rules) == 88
    assert rules["NEW:MAT231"] == {"NEW:MAT230"}
    assert rules["NEW:CCE550"] == {"NEW:CCE443"}
    assert rules["NEW:CCE690"] == {"NEW:CCE431", "NEW:CSC437"}
    assert rules["OLD:ELBC503"] == {"OLD:ELBC403"}
    assert "NEW:DRH310" not in rules
    assert "OLD:ART320" not in rules


def test_new_english_student_receives_reference_plan():
    data, plan = seeded_plan()
    assert plan.status is SolverStatus.OPTIMAL
    assert not validate_plan(plan, data.demo_problem())
    assert sum(data.courses[c].credits for scheduled in plan.scheduled_terms for c in scheduled.course_ids) == 300
    assert len({c for scheduled in plan.scheduled_terms for c in scheduled.course_ids}) == len(data.curricula[CurriculumVersion.NEW].requirement_ids)
    assert plan.scheduled_terms[6].term.kind is TermKind.TRAINING_1
    assert plan.scheduled_terms[9].term.kind is TermKind.TRAINING_2
    assert plan.graduation_term == plan.scheduled_terms[-1].term
    assert plan.warnings


def test_version_qualified_ids_keep_shared_codes_distinct():
    data = SyntheticFixtureLoader().load()
    assert data.courses["NEW:DRH310"].code == data.courses["OLD:DRH310"].code
    assert data.courses["NEW:DRH310"].curriculum_version is CurriculumVersion.NEW
    assert data.courses["OLD:DRH310"].curriculum_version is CurriculumVersion.OLD


def test_image_processing_lab_is_a_mandatory_zero_credit_component():
    data = SyntheticFixtureLoader().load()
    offering = next(o for o in data.offerings if o.course_id == "OLD:ELBC901" and o.term == data.demo_configuration.planning_horizon[0])
    assert len(offering.bundles) == 2
    assert all([s.component for s in bundle.sections] == ["LECTURE", "LAB:ELBC901L"] for bundle in offering.bundles)
    assert data.courses["OLD:ELBC901"].credits == 5

from academic_planner.eligibility import EligibilityEngine
from academic_planner.optimization import GlobalPlanner
from academic_planner.policies import AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy
from academic_planner.reconciliation import ReconciliationService


def planner() -> GlobalPlanner:
    return GlobalPlanner(
        ConfiguredCreditLimitPolicy(), ProgressiveRolloutPolicy(), AllowAllRegistrationPolicy()
    )


def reconcile(scenario):
    problem = scenario.data.demo_problem()
    return ReconciliationService().reconcile(
        problem.student, problem.curriculum, problem.equivalencies
    )


def build_pool(scenario, term, completed=None):
    problem = scenario.data.demo_problem()
    result = reconcile(scenario)
    applicable = {
        cid: problem.courses[cid]
        for cid in problem.curriculum.resolved_requirements(problem.student.language_track)
    }
    return EligibilityEngine(
        ProgressiveRolloutPolicy(), AllowAllRegistrationPolicy()
    ).build_pool(
        problem.student,
        term,
        applicable,
        result.outstanding_requirement_ids,
        result.satisfied_requirement_ids if completed is None else frozenset(completed),
        problem.prerequisites,
        problem.offerings,
    )


def scheduled_index(plan, course_id: str) -> int:
    return next(
        index for index, scheduled in enumerate(plan.scheduled_terms)
        if course_id in scheduled.course_ids
    )

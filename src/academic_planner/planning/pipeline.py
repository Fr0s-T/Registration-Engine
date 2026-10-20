"""Application-level planning pipeline.

This module is the single orchestration boundary between student/curriculum
reconciliation and optimization.  Academic facts are reconciled once, then the
same immutable audit is consumed by the solver and presentation layers.
"""
from __future__ import annotations

from dataclasses import dataclass

from academic_planner.domain.models import GraduationPlan
from academic_planner.optimization import GlobalPlanner, PlanningProblem
from academic_planner.reconciliation import ReconciliationResult, ReconciliationService


@dataclass(frozen=True)
class PlanningRun:
    """The complete output of one planning request."""

    audit: ReconciliationResult
    plan: GraduationPlan


class AcademicPlanningEngine:
    """Reconcile once and optimize from that exact academic audit."""

    def __init__(
        self,
        planner: GlobalPlanner,
        reconciliation_service: ReconciliationService | None = None,
    ) -> None:
        self.planner = planner
        self.reconciliation_service = reconciliation_service or ReconciliationService()

    def run(
        self,
        problem: PlanningProblem,
        *,
        registration_course_ids: frozenset[str] = frozenset(),
        review_course_ids: frozenset[str] = frozenset(),
    ) -> PlanningRun:
        audit = self.reconciliation_service.reconcile(
            problem.student,
            problem.curriculum,
            problem.equivalencies,
            courses=problem.courses,
            optional_approvals=problem.optional_credit_approvals,
            registration_course_ids=registration_course_ids,
            review_course_ids=review_course_ids,
        )
        return PlanningRun(audit=audit, plan=self.planner.plan(problem, audit=audit))

"""Reconcile recorded academic history with one governing graduation contract."""

from dataclasses import dataclass

from academic_planner.domain.models import (
    ApprovalStatus,
    Course,
    CourseAttempt,
    CourseEquivalency,
    Curriculum,
    CurriculumVersion,
    OptionalCreditApproval,
    RequirementClassification,
    StudentAcademicState,
)


@dataclass(frozen=True)
class ClassifiedRequirement:
    """One student-specific requirement or course classification."""

    course_id: str
    classification: RequirementClassification
    explanation: str
    category: str | None = None
    approval_status: ApprovalStatus | None = None


@dataclass(frozen=True)
class ReconciliationResult:
    """Immutable academic audit consumed by planning and presentation."""

    satisfied_requirement_ids: frozenset[str]
    outstanding_requirement_ids: frozenset[str]
    official_earned_credits: int
    allocations: tuple[tuple[str, str], ...]
    prerequisite_completion_ids: frozenset[str]
    classifications: tuple[ClassifiedRequirement, ...] = ()
    unresolved_credit_difference: int = 0


class ReconciliationService:
    """Resolve completion, credit, and classifications without mutating inputs."""

    def reconcile(
        self,
        student: StudentAcademicState,
        curriculum: Curriculum,
        equivalencies: tuple[CourseEquivalency, ...],
        *,
        courses: dict[str, Course] | None = None,
        optional_approvals: tuple[OptionalCreditApproval, ...] = (),
        registration_course_ids: frozenset[str] = frozenset(),
        review_course_ids: frozenset[str] = frozenset(),
    ) -> ReconciliationResult:
        """Reconcile ``student`` against ``curriculum`` exactly once.

        Completed attempts are allocated one-to-one to governing requirements.
        Recorded earned ECTS are deduplicated by stable credit identity and remain
        independent of the target course's credit value. Optional and registration
        classifications are reporting/authorization facts; they never rewrite the
        governing requirement set.
        """
        requirements = curriculum.resolved_requirements(student.language_track)
        satisfied = set(student.completed_requirement_ids & requirements)
        prerequisite_completions = set(student.completed_requirement_ids)
        allocations: list[tuple[str, str]] = []
        equivalent_requirements: dict[str, list[str]] = {}
        for eq in equivalencies:
            if curriculum.version is CurriculumVersion.OLD:
                for completed in sorted(eq.target_requirement_ids):
                    equivalent_requirements.setdefault(completed, []).extend(
                        sorted(eq.source_course_ids)
                    )
            else:
                for completed in sorted(eq.source_course_ids):
                    equivalent_requirements.setdefault(completed, []).extend(
                        sorted(eq.target_requirement_ids)
                    )
        completed_attempts: list[CourseAttempt] = [
            attempt
            for attempt in student.attempts
            if attempt.status.satisfies_requirement
        ]
        prerequisite_completions.update(a.course_id for a in completed_attempts)
        for attempt in completed_attempts:
            prerequisite_completions.update(
                equivalent_requirements.get(attempt.course_id, [])
            )
        # Deterministic one-to-one allocation prevents one completion satisfying two requirements.
        for attempt in completed_attempts:
            candidates = (
                [attempt.course_id] if attempt.course_id in requirements else []
            ) + equivalent_requirements.get(attempt.course_id, [])
            target = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate in requirements and candidate not in satisfied
                ),
                None,
            )
            if target:
                satisfied.add(target)
                allocations.append((attempt.course_id, target))
        # Transcript accounting uses recorded earned credits, once per course. This
        # prevents repeated attempts from earning the same accepted credits twice.
        earned_by_course: dict[str, int] = {}
        for attempt in completed_attempts:
            credit_identity = attempt.credit_identity or attempt.course_id
            earned_by_course[credit_identity] = max(
                earned_by_course.get(credit_identity, 0), attempt.earned_credits
            )
        official = student.earned_credits + sum(earned_by_course.values())
        mandatory_credits = sum(
            courses[cid].credits
            for cid in requirements - satisfied
            if courses is not None and cid in courses
        )
        unresolved = max(0, curriculum.accepted_credit_target - official - mandatory_credits)
        classification_by_id: dict[str, ClassifiedRequirement] = {}
        for cid in sorted(satisfied):
            classification_by_id[cid] = ClassifiedRequirement(
                cid, RequirementClassification.SATISFIED,
                "completed directly or fulfilled by an accepted recognition",
            )
        for cid in sorted(requirements - satisfied):
            classification_by_id[cid] = ClassifiedRequirement(
                cid, RequirementClassification.MANDATORY_OUTSTANDING,
                "explicit unsatisfied requirement in the student's graduation contract",
            )
        completed_course_ids = {attempt.course_id for attempt in completed_attempts}
        for approval in sorted(
            optional_approvals,
            key=lambda item: (item.course_id, item.category),
        ):
            if approval.course_id in classification_by_id:
                continue
            if approval.course_id in completed_course_ids:
                classification = RequirementClassification.SATISFIED
                explanation = "completed course already included in accepted transcript credit"
            elif (
                approval.status is ApprovalStatus.APPROVED
                and approval.sufficiently_documented
            ):
                classification = RequirementClassification.APPROVED_OPTIONAL
                explanation = "authorized member of the student's optional-credit pool"
            elif approval.status is ApprovalStatus.REJECTED:
                classification = RequirementClassification.REGISTRATION_ONLY
                explanation = "optional graduation credit was explicitly rejected"
            else:
                classification = RequirementClassification.NEEDS_REVIEW
                explanation = "optional-credit evidence is unverified or lacks authority/source"
            classification_by_id[approval.course_id] = ClassifiedRequirement(
                approval.course_id,
                classification,
                explanation,
                approval.category,
                approval.status,
            )
        for cid in sorted(review_course_ids):
            classification_by_id.setdefault(
                cid,
                ClassifiedRequirement(
                    cid,
                    RequirementClassification.NEEDS_REVIEW,
                    "completed course has no applicable authorized requirement recognition",
                ),
            )
        for cid in sorted(registration_course_ids):
            classification_by_id.setdefault(
                cid,
                ClassifiedRequirement(
                    cid,
                    RequirementClassification.REGISTRATION_ONLY,
                    "registration eligible but not established as a graduation requirement",
                ),
            )
        return ReconciliationResult(
            frozenset(satisfied),
            frozenset(requirements - satisfied),
            official,
            tuple(allocations),
            frozenset(prerequisite_completions),
            tuple(classification_by_id[cid] for cid in sorted(classification_by_id)),
            unresolved,
        )

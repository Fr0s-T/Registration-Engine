"""Build the explainable current-term registration eligibility view."""

from dataclasses import dataclass
from enum import Enum

from academic_planner.domain.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    PrerequisiteRule,
    StudentAcademicState,
)
from academic_planner.policies.registration import AcademicRegistrationPolicy
from academic_planner.policies.rollout import ProgressiveRolloutPolicy


class RejectionCode(str, Enum):
    ALREADY_SATISFIED = "ALREADY_SATISFIED"
    PREREQUISITE = "PREREQUISITE"
    NOT_OFFERED = "NOT_OFFERED"
    ROLLOUT = "ROLLOUT"
    REGISTRATION_POLICY = "REGISTRATION_POLICY"


@dataclass(frozen=True)
class Rejection:
    course_id: str
    code: RejectionCode
    detail: str


@dataclass(frozen=True)
class EligibleCoursePool:
    """Accepted current-term courses, matching offerings, and all rejections."""

    term: AcademicTerm
    courses: tuple[Course, ...]
    offerings: tuple[CourseOffering, ...]
    rejections: tuple[Rejection, ...]


class EligibilityEngine:
    """Apply prerequisite, offering, rollout, and registration filters in order."""

    def __init__(
        self,
        rollout: ProgressiveRolloutPolicy,
        registration: AcademicRegistrationPolicy,
    ) -> None:
        self.rollout = rollout
        self.registration = registration

    def build_pool(
        self,
        student: StudentAcademicState,
        term: AcademicTerm,
        courses: dict[str, Course],
        outstanding: frozenset[str],
        completed_before_term: frozenset[str],
        prerequisites: tuple[PrerequisiteRule, ...],
        offerings: tuple[CourseOffering, ...],
    ) -> EligibleCoursePool:
        """Return the current eligibility view without changing graduation roles."""
        by_course = {o.course_id: o for o in offerings if o.term == term}
        prereq = {r.course_id: r.all_of for r in prerequisites}
        accepted: list[Course] = []
        accepted_offerings: list[CourseOffering] = []
        rejected: list[Rejection] = []
        for course in courses.values():
            if course.id not in outstanding:
                rejected.append(Rejection(
                    course.id,
                    RejectionCode.ALREADY_SATISFIED,
                    "requirement already satisfied or not applicable",
                ))
                continue
            missing = prereq.get(course.id, frozenset()) - completed_before_term
            if missing:
                rejected.append(Rejection(
                    course.id,
                    RejectionCode.PREREQUISITE,
                    f"missing: {', '.join(sorted(missing))}",
                ))
                continue
            offering = by_course.get(course.id)
            if offering is None:
                rejected.append(Rejection(
                    course.id,
                    RejectionCode.NOT_OFFERED,
                    "no offering supplied for term",
                ))
                continue
            rollout = self.rollout.permits(course, term)
            if not rollout.permitted:
                rejected.append(Rejection(
                    course.id,
                    RejectionCode.ROLLOUT,
                    rollout.reason,
                ))
                continue
            policy_reason = self.registration.rejection_reason(student, course, term)
            if policy_reason:
                rejected.append(Rejection(
                    course.id,
                    RejectionCode.REGISTRATION_POLICY,
                    policy_reason,
                ))
                continue
            accepted.append(course)
            accepted_offerings.append(offering)
        return EligibleCoursePool(
            term,
            tuple(accepted),
            tuple(accepted_offerings),
            tuple(rejected),
        )


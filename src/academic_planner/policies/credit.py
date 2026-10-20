from typing import Protocol

from dataclasses import dataclass

from academic_planner.domain.models import (
    AcademicTerm, AttemptStatus, PlanningConfiguration, StudentAcademicState,
)


class CreditLimitPolicy(Protocol):
    def capacity(self, student: StudentAcademicState, term: AcademicTerm, config: PlanningConfiguration) -> int: ...


class ConfiguredCreditLimitPolicy:
    """Uses explicit capacities; it never interprets failure as administrative approval."""

    def capacity(self, student: StudentAcademicState, term: AcademicTerm, config: PlanningConfiguration) -> int:
        return config.capacity_for(term)


@dataclass(frozen=True)
class EffectiveCreditCapacity:
    capacity: int
    reason: str
    repeated_course_ids: tuple[str, ...] = ()


def has_explicit_capacity_override(
    config: PlanningConfiguration, term: AcademicTerm
) -> bool:
    """Recognize both marked overrides and legacy non-default per-term caps."""
    return (
        term in config.explicit_capacity_override_terms
        or (
            term in config.term_credit_capacities
            and config.term_credit_capacities[term] != config.default_credit_capacity
        )
    )


def unresolved_failed_course_ids(
    student: StudentAcademicState, outstanding_requirement_ids: set[str] | frozenset[str]
) -> frozenset[str]:
    failed = {
        attempt.course_id for attempt in student.attempts
        if attempt.status is AttemptStatus.FAILED
    }
    return frozenset(failed & set(outstanding_requirement_ids))


def effective_credit_capacity(
    student: StudentAcademicState,
    term: AcademicTerm,
    config: PlanningConfiguration,
    outstanding_requirement_ids: set[str] | frozenset[str],
    selected_course_ids: set[str] | frozenset[str],
    *,
    selected_credits: int | None = None,
    graduation_term: AcademicTerm | None = None,
    planning_horizon: tuple[AcademicTerm, ...] = (),
) -> EffectiveCreditCapacity:
    base = config.capacity_for(term)
    if not term.is_regular:
        return EffectiveCreditCapacity(base, "TRAINING_PERIOD_CAP")
    if has_explicit_capacity_override(config, term):
        return EffectiveCreditCapacity(base, "EXPLICIT_TERM_OVERRIDE")
    repeats = tuple(sorted(
        unresolved_failed_course_ids(student, outstanding_requirement_ids)
        & set(selected_course_ids)
    ))
    if config.allow_extended_load_when_repeating_failed_course and repeats:
        return EffectiveCreditCapacity(
            config.extended_failed_repeat_capacity,
            "FAILED_COURSE_REPEAT_ALLOWANCE", repeats,
        )
    if (
        config.allow_final_two_semester_graduation_load
        and selected_credits is not None
        and selected_credits > base
        and graduation_term is not None
        and _within_final_two_regular_semesters(term, graduation_term, planning_horizon)
    ):
        return EffectiveCreditCapacity(
            config.final_two_semester_graduation_capacity,
            "FINAL_TWO_SEMESTER_GRADUATION_ALLOWANCE",
        )
    return EffectiveCreditCapacity(base, "NORMAL_REGULAR_CAPACITY")


def _within_final_two_regular_semesters(
    term: AcademicTerm,
    graduation_term: AcademicTerm,
    planning_horizon: tuple[AcademicTerm, ...],
) -> bool:
    """True when graduation occurs before a third later regular semester."""
    if not term.is_regular or not planning_horizon:
        return False
    try:
        term_index = planning_horizon.index(term)
        graduation_index = planning_horizon.index(graduation_term)
    except ValueError:
        return False
    if graduation_index < term_index:
        return False
    later_regular = [
        index for index in range(term_index + 1, len(planning_horizon))
        if planning_horizon[index].is_regular
    ]
    third_regular_index = later_regular[1] if len(later_regular) > 1 else None
    return third_regular_index is None or graduation_index < third_regular_index

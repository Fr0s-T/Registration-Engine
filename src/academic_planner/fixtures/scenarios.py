from __future__ import annotations

from dataclasses import dataclass, replace

from academic_planner.domain.models import (
    AcademicTerm, AttemptStatus, Course, CourseAttempt, CurriculumVersion,
    LanguageTrack, PlanningConfiguration, StudentAcademicState, TermKind,
)
from academic_planner.fixtures.synthetic import (
    RELAXED_FIXTURE, SeededPlanningData, SyntheticFixtureConfiguration,
    SyntheticFixtureLoader,
)


@dataclass(frozen=True)
class StudentScenario:
    identifier: str
    description: str
    data: SeededPlanningData

    @property
    def starting_term(self) -> AcademicTerm:
        return self.data.demo_configuration.planning_horizon[0]


SCENARIO_DESCRIPTIONS = {
    "fresh": "New English-track first-year student with no prior attempts",
    "struggling-third": (
        "Third-year student balancing failed prerequisite retakes, current courses, "
        "and recognized transfer/exemption credit"
    ),
    "regular-fourth": "On-track English-track fourth-year student",
    "failed-fourth": "Fourth-year student repeating failed Network Essentials",
}


def list_scenarios() -> dict[str, str]:
    return dict(SCENARIO_DESCRIPTIONS)


def build_scenario(
    identifier: str,
    regular_credit_capacity: int | None = None,
    fixture_configuration: SyntheticFixtureConfiguration = RELAXED_FIXTURE,
) -> StudentScenario:
    if identifier not in SCENARIO_DESCRIPTIONS:
        raise ValueError(f"unknown scenario: {identifier}")
    base = SyntheticFixtureLoader().load(
        entry_year=2026, configuration=fixture_configuration
    )
    if identifier == "fresh":
        if regular_credit_capacity is None or regular_credit_capacity == 30:
            data = base
        else:
            config = _configuration(base.demo_configuration.planning_horizon, regular_credit_capacity)
            data = replace(base, demo_configuration=config)
        return StudentScenario(identifier, SCENARIO_DESCRIPTIONS[identifier], data)

    if identifier == "struggling-third":
        capacity = regular_credit_capacity if regular_credit_capacity is not None else 30
        student = _struggling_third_year_student(base.courses)
        data = replace(
            base,
            demo_student=student,
            demo_configuration=_configuration(_third_year_horizon(), capacity),
        )
        return StudentScenario(identifier, SCENARIO_DESCRIPTIONS[identifier], data)

    failed = identifier == "failed-fourth"
    attempts = list(_completed_first_three_years(base.courses, failed))
    if failed:
        attempts.append(CourseAttempt(
            "NEW:CCE443", AcademicTerm(2025, TermKind.SPRING), AttemptStatus.FAILED,
            grade=None, earned_credits=0,
        ))
    student = StudentAcademicState(4, base.demo_student.language_track, tuple(attempts))
    horizon = _fourth_year_horizon()
    capacity = regular_credit_capacity if regular_credit_capacity is not None else 30
    data = replace(
        base,
        demo_student=student,
        demo_configuration=_configuration(horizon, capacity),
    )
    return StudentScenario(identifier, SCENARIO_DESCRIPTIONS[identifier], data)


def _completed_first_three_years(
    courses: dict[str, Course], exclude_network_essentials: bool
) -> tuple[CourseAttempt, ...]:
    attempts: list[CourseAttempt] = []
    for course in courses.values():
        if course.curriculum_version is not CurriculumVersion.NEW or course.reference_year > 3:
            continue
        if exclude_network_essentials and course.code == "CCE443":
            continue
        if course.code == "CCE471":
            term = AcademicTerm(2025, TermKind.TRAINING_1)
        else:
            term = AcademicTerm(2023 + course.reference_year - 1, course.reference_semester)
        attempts.append(CourseAttempt(
            course.id, term, AttemptStatus.PASSED, grade=None, earned_credits=course.credits
        ))
    return tuple(sorted(attempts, key=lambda attempt: (attempt.term.academic_year_start, attempt.term.kind.value, attempt.course_id)))


def _fourth_year_horizon() -> tuple[AcademicTerm, ...]:
    terms: list[AcademicTerm] = []
    for year in range(2026, 2036):
        terms.extend((AcademicTerm(year, TermKind.FALL), AcademicTerm(year, TermKind.SPRING)))
        terms.append(AcademicTerm(year, TermKind.TRAINING_2))
    return tuple(terms)


def _third_year_horizon() -> tuple[AcademicTerm, ...]:
    terms: list[AcademicTerm] = []
    for year in range(2026, 2036):
        terms.extend((AcademicTerm(year, TermKind.FALL), AcademicTerm(year, TermKind.SPRING)))
        if year >= 2026:
            terms.append(AcademicTerm(year, TermKind.TRAINING_1))
        if year >= 2027:
            terms.append(AcademicTerm(year, TermKind.TRAINING_2))
    return tuple(terms)


def _struggling_third_year_student(courses: dict[str, Course]) -> StudentAcademicState:
    failed_codes = {"CCE340", "CCE341", "CSC333"}
    attempts: list[CourseAttempt] = []
    for course in courses.values():
        if course.curriculum_version is not CurriculumVersion.NEW:
            continue
        if course.reference_year <= 2 and course.code not in failed_codes:
            term = AcademicTerm(2024 + course.reference_year - 1, course.reference_semester)
            attempts.append(CourseAttempt(
                course.id, term, AttemptStatus.PASSED,
                grade=None, earned_credits=course.credits,
            ))
    for code in sorted(failed_codes):
        course = courses[f"NEW:{code}"]
        attempts.append(CourseAttempt(
            course.id,
            AcademicTerm(2025, course.reference_semester),
            AttemptStatus.FAILED,
            grade=None,
            earned_credits=0,
        ))
    attempts.extend((
        CourseAttempt(
            "NEW:CCE653", AcademicTerm(2025, TermKind.SPRING),
            AttemptStatus.TRANSFERRED, earned_credits=courses["NEW:CCE653"].credits,
        ),
        CourseAttempt(
            "NEW:CCE660", AcademicTerm(2025, TermKind.SPRING),
            AttemptStatus.EXEMPTED, earned_credits=courses["NEW:CCE660"].credits,
        ),
    ))
    return StudentAcademicState(
        nominal_year=3,
        language_track=LanguageTrack.EN,
        attempts=tuple(sorted(
            attempts,
            key=lambda attempt: (
                attempt.term.academic_year_start,
                attempt.term.kind.value,
                attempt.course_id,
                attempt.status.value,
            ),
        )),
    )


def _configuration(horizon: tuple[AcademicTerm, ...], regular_capacity: int) -> PlanningConfiguration:
    capacities = {
        term: (5 if term.kind in {TermKind.TRAINING_1, TermKind.TRAINING_2} else regular_capacity)
        for term in horizon
    }
    return PlanningConfiguration(
        term_credit_capacities=capacities,
        default_credit_capacity=regular_capacity,
        planning_horizon=horizon,
    )

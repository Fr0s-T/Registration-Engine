"""Normalize source transcript rows before they enter academic planning."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from academic_planner.domain.models import AcademicTerm, AttemptStatus, CourseAttempt


class TranscriptRow(Protocol):
    course_id: object | None
    source_code: str
    source_term: str
    status: str
    grade: float | None
    ects: int
    earned_credits: int
    counts_toward_degree_credit: bool


@dataclass(frozen=True)
class NormalizedTranscript:
    """Planning-ready attempts plus source rows that remain unresolved."""

    attempts: tuple[CourseAttempt, ...]
    unresolved_earned_credits: int
    completed_credits: int
    unknown_codes: tuple[str, ...]
    component_codes: tuple[str, ...]


def normalize_attempt_rows(
    source_rows: Iterable[TranscriptRow],
    term_parser: Callable[[str], AcademicTerm],
    *,
    course_id_by_source_code: dict[str, object] | None = None,
    credit_identity_by_course_id: dict[object, str] | None = None,
    separate_source_identity_codes: frozenset[str] = frozenset(),
    recognized_non_degree_codes: frozenset[str] = frozenset(),
) -> NormalizedTranscript:
    rows = tuple(source_rows)
    course_id_by_source_code = {
        code.upper(): course_id
        for code, course_id in (course_id_by_source_code or {}).items()
    }
    credit_identity_by_course_id = credit_identity_by_course_id or {}
    separate_source_identity_codes = frozenset(
        code.upper() for code in separate_source_identity_codes
    )
    recognized_non_degree_codes = frozenset(
        code.upper() for code in recognized_non_degree_codes
    )
    resolved_course_id = {
        id(row): row.course_id or course_id_by_source_code.get(row.source_code.upper())
        for row in rows
    }
    transcript_codes = {row.source_code.upper() for row in rows}
    component_codes = {
        row.source_code
        for row in rows
        if resolved_course_id[id(row)] is None
        and row.ects == 0
        and row.source_code.upper().endswith("L")
        and (
            row.source_code.upper()[:-1] in transcript_codes
            or not row.counts_toward_degree_credit
        )
    }
    planning_rows = tuple(row for row in rows if row.source_code not in component_codes)
    credit_identity = {
        id(row): (
            getattr(row, "credit_identity", None)
            or (
                credit_identity_by_course_id.get(row.course_id)
                if row.course_id is not None
                and row.source_code.upper() not in separate_source_identity_codes
                else None
            )
            or f"source:{row.source_code.upper()}"
        )
        for row in planning_rows
    }
    attempts = tuple(
        CourseAttempt(
            str(resolved_course_id[id(row)]),
            term_parser(row.source_term),
            AttemptStatus(row.status),
            row.grade,
            row.earned_credits if row.counts_toward_degree_credit else 0,
            credit_identity[id(row)],
        )
        for row in planning_rows
        if resolved_course_id[id(row)] is not None
    )
    unresolved_by_identity: dict[str, int] = {}
    completed_by_identity: dict[str, int] = {}
    for row in planning_rows:
        if (
            not row.counts_toward_degree_credit
            or not AttemptStatus(row.status).satisfies_requirement
        ):
            continue
        identity = credit_identity[id(row)]
        completed_by_identity[identity] = max(
            completed_by_identity.get(identity, 0), row.earned_credits
        )
        if (
            resolved_course_id[id(row)] is None
            and row.source_code.upper() not in recognized_non_degree_codes
        ):
            unresolved_by_identity[identity] = max(
                unresolved_by_identity.get(identity, 0), row.earned_credits
            )
    unresolved_earned_credits = sum(unresolved_by_identity.values())
    completed_credits = sum(completed_by_identity.values())
    unknown_codes = tuple(sorted(
        row.source_code
        for row in planning_rows
        if resolved_course_id[id(row)] is None
        and row.source_code.upper() not in recognized_non_degree_codes
    ))
    return NormalizedTranscript(
        attempts=attempts,
        unresolved_earned_credits=unresolved_earned_credits,
        completed_credits=completed_credits,
        unknown_codes=unknown_codes,
        component_codes=tuple(sorted(component_codes)),
    )

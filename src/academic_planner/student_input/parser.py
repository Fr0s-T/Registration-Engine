"""Parse copied portal contract-sheet text without touching persistence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import html
import re

from .schemas import (
    AttemptPreview, CategoryPreview, ComponentPreview, ReviewIssuePreview,
    StudentIdentityPreview,
)


TERM_RE = re.compile(r"^(FALL|SPRING|SUMMERII|SUMMERI|SUMMER)\d{4}$", re.IGNORECASE)
GRADE_RE = re.compile(r"^(.*?)\s*-\s*(\d+(?:\.\d+)?)\s*(.*)$")
COURSE_HEADER_RE = re.compile(r"^#\s+Course Code\s+Course Title\s+Credits\s+Semester\s+Grade$", re.IGNORECASE)
SUMMARY_RE = re.compile(
    r"Required Credits!\s*(\d+)\s+Earned Credits!\s*(\d+)(?:\s+Passing Grade!\s*(\d+))?",
    re.IGNORECASE,
)
OUTSIDE_SECTION = "Courses Not in Contract Sheet"
COMMON_CORE_SECTION = "Common Core"
COMMON_CORE_PASSING_GRADE = 50


def _course_label(title: str, code: str) -> str:
    return f"{title.strip()} ({code})"


@dataclass
class ParsedStudentContract:
    identity: StudentIdentityPreview
    categories: list[CategoryPreview]
    attempts: list[AttemptPreview]
    components: list[ComponentPreview]
    issues: list[ReviewIssuePreview]
    duplicate_attempts_merged: int


def _clean_lines(text: str) -> list[str]:
    value = html.unescape(text).replace("\ufeff", "").replace("\xa0", " ")
    return [re.sub(r"[ \t]+$", "", line).strip() for line in value.splitlines()]


def _previous_nonempty(lines: list[str], index: int) -> str:
    for line in reversed(lines[:index]):
        if line:
            return line
    return "Unclassified"


def _course_row(line: str) -> tuple[str, str, int, str | None] | None:
    parts = [part.strip() for part in re.split(r"\t+| {2,}", line.strip()) if part.strip()]
    if len(parts) >= 4 and parts[0].isdigit() and re.fullmatch(r"[A-Z][A-Z0-9]*", parts[1]):
        possible_term = parts[-1].upper() if TERM_RE.fullmatch(parts[-1]) else None
        ects_index = -2 if possible_term else -1
        if parts[ects_index].isdigit():
            return parts[1].upper(), " ".join(parts[2:ects_index]), int(parts[ects_index]), possible_term
    fallback = re.match(
        r"^\d+\s+([A-Z][A-Z0-9]*)\s+(.+?)\s+(\d+)"
        r"(?:\s+((?:FALL|SPRING|SUMMERII|SUMMERI|SUMMER)\d{4}))?$",
        line.strip(), re.IGNORECASE,
    )
    if fallback:
        return (
            fallback.group(1).upper(), fallback.group(2).strip(),
            int(fallback.group(3)), fallback.group(4).upper() if fallback.group(4) else None,
        )
    return None


def _term_key(term: str) -> tuple[int, int]:
    match = re.fullmatch(r"(FALL|SPRING|SUMMERII|SUMMERI|SUMMER)(\d{4})", term.upper())
    if not match:
        return 9999, 9
    kind, raw_year = match.group(1), int(match.group(2))
    if kind == "FALL":
        return raw_year, 0
    order = {"SPRING": 1, "SUMMER": 2, "SUMMERI": 2, "SUMMERII": 3}[kind]
    return raw_year - 1, order


def _status(
    token: str, grade: float | None, note: str | None, passing_grade: int,
    term: str, current_term: str,
) -> str:
    token = token.upper().strip()
    note_value = (note or "").casefold()
    if "to be repeated" in note_value:
        return "FAILED"
    if token in {"W", "WD", "WITHDRAWN"}:
        return "WITHDRAWN"
    if token in {"T", "TR", "TRANSFER", "TRANSFERRED"}:
        return "TRANSFERRED"
    if token in {"F", "FAIL", "FAILED"}:
        return "FAILED"
    if token in {"IP", "IN PROGRESS"}:
        return "IN_PROGRESS"
    if token in {"", "-"}:
        return "REGISTERED" if _term_key(term) >= _term_key(current_term) else "NEEDS_REVIEW"
    if token in {"S", "P", "PASS", "PASSED"}:
        return "PASSED"
    if grade is not None:
        return "PASSED" if grade >= passing_grade else "FAILED"
    return "NEEDS_REVIEW"


def _identity(text: str) -> StudentIdentityPreview:
    student = re.search(r"Contract Sheet\s*\|\s*([^\s|]+)\s*-\s*([^\r\n]+)", text, re.IGNORECASE)
    program = re.search(
        r"^\s*([A-Z]{2,}[A-Z0-9]*)\s+-\s+(.+?)\s+-\s+Bachelor Degree(?:\s+(\d{4}-\d{2}-\d{2}))?\s*$",
        text, re.IGNORECASE | re.MULTILINE,
    )
    reported = re.search(r"Total Earned Credits\s*:\s*(\d+)\s*Credits", text, re.IGNORECASE)
    target = re.search(r"total number of credits needed to graduate is\s*(\d+)", text, re.IGNORECASE)
    passing = re.search(r"Passing Grade.*?is\s*(\d+)\s*/\s*100", text, re.IGNORECASE)
    track = re.search(r"(?:^|\n)\s*(EN|FR)\s*(?:\n|$)", text, re.IGNORECASE)
    return StudentIdentityPreview(
        student_id=student.group(1).strip() if student else None,
        name=student.group(2).strip() if student else None,
        program_code=program.group(1).upper() if program else None,
        program_title=program.group(2).strip() if program else None,
        date_of_birth=program.group(3) if program else None,
        language_track=track.group(1).upper() if track else None,
        reported_earned_credits=int(reported.group(1)) if reported else None,
        graduation_target=int(target.group(1)) if target else None,
        passing_grade=int(passing.group(1)) if passing else 60,
    )


def parse_student_contract(text: str, current_term: str) -> ParsedStudentContract:
    """Parse one copied contract sheet into attempts, components, and source checks."""
    lines = _clean_lines(text)
    identity = _identity(text)
    issues: list[ReviewIssuePreview] = []
    headers = [index for index, line in enumerate(lines) if COURSE_HEADER_RE.fullmatch(line)]
    categories: list[CategoryPreview] = []
    raw_attempts: list[AttemptPreview] = []
    issue_number = 0

    def add_issue(code: str, message: str, question: str | None = None, *, severity: str = "REVIEW", attempt_id: str | None = None, options: list[str] | None = None) -> None:
        nonlocal issue_number
        issue_number += 1
        issues.append(ReviewIssuePreview(
            id=f"issue-{issue_number}", severity=severity, code=code, message=message,
            question=question, attempt_id=attempt_id, options=options or [],
        ))

    if not headers:
        add_issue(
            "NO_COURSE_TABLES", "No portal course tables were found in the pasted text.",
            "Was the complete Contract Sheet page copied?", severity="BLOCKING",
        )

    for position, header_index in enumerate(headers):
        end = headers[position + 1] if position + 1 < len(headers) else len(lines)
        section = _previous_nonempty(lines, header_index)
        category = CategoryPreview(label=section)
        categories.append(category)
        current_row: tuple[str, str, int, str | None] | None = None
        payload: list[str] = []

        def flush_row() -> None:
            nonlocal current_row, payload
            if current_row is None:
                payload = []
                return
            code, title, ects, inline_term = current_row
            terms = ([inline_term] if inline_term else []) + [
                item.upper() for item in payload if TERM_RE.fullmatch(item)
            ]
            grades: list[tuple[str, float | None, str | None]] = []
            for item in payload:
                match = GRADE_RE.fullmatch(item)
                if not match:
                    continue
                token = match.group(1).strip().upper() or "-"
                grade_value = float(match.group(2))
                note = match.group(3).strip() or None
                grades.append((token, grade_value, note))
            if grades and not terms:
                add_issue(
                    "GRADE_WITHOUT_TERM",
                    f"{_course_label(title, code)} has grade information but no semester.",
                    "Which semester belongs to this grade?", severity="BLOCKING",
                    options=[
                        "Choose the correct semester — keep the grade on this attempt",
                        "Remove the grade — keep the course as ungraded",
                        "Ignore this row as a portal error — no credit or GPA effect",
                        "Leave unresolved — block import until corrected",
                    ],
                )
            if len(grades) > len(terms):
                add_issue(
                    "ATTEMPT_PAIRING",
                    f"{_course_label(title, code)} has {len(grades)} grades but only {len(terms)} semesters.",
                    "Please confirm how these grades pair with semesters.", severity="BLOCKING",
                    options=[
                        "Pair each grade with a semester — preserve every valid attempt",
                        "Remove the extra grade — exclude that record from credit and GPA",
                        "Leave unresolved — block import until corrected",
                    ],
                )
            for attempt_index, term in enumerate(terms):
                token, grade_value, note = grades[attempt_index] if attempt_index < len(grades) else ("-", None, None)
                passing_grade = (
                    COMMON_CORE_PASSING_GRADE
                    if section == COMMON_CORE_SECTION
                    else identity.passing_grade
                )
                status = _status(token, grade_value, note, passing_grade, term, current_term)
                excluded_from_gpa = "excluded from gpa" in (note or "").casefold()
                raw_attempts.append(AttemptPreview(
                    source_code=code, source_title=title, ects=ects, term=term,
                    grade_token=token, grade_value=grade_value, note=note, status=status,
                    passing_grade=passing_grade,
                    source_sections=[section],
                    counts_toward_degree_credit=not excluded_from_gpa,
                    counts_toward_gpa=not excluded_from_gpa,
                    counts_toward_source_subtotal=not excluded_from_gpa,
                    earned_ects=(
                        ects
                        if status in {"PASSED", "TRANSFERRED", "EXEMPTED"}
                        and not excluded_from_gpa
                        else 0
                    ),
                ))
            current_row = None
            payload = []

        for line in lines[header_index + 1:end]:
            summary = SUMMARY_RE.search(line)
            if summary:
                flush_row()
                category.required_ects = int(summary.group(1))
                category.reported_earned_ects = int(summary.group(2))
                if summary.group(3):
                    identity.passing_grade = int(summary.group(3))
                continue
            if section == OUTSIDE_SECTION:
                outside_total = re.fullmatch(r"Earned Credits!\s*(\d+)", line, re.IGNORECASE)
                if outside_total:
                    flush_row()
                    category.reported_earned_ects = int(outside_total.group(1))
                    continue
            row = _course_row(line)
            if row:
                flush_row()
                current_row = row
            elif current_row is not None and line:
                payload.append(line)
        flush_row()

    deduplicated: dict[tuple[object, ...], AttemptPreview] = {}
    duplicate_count = 0
    for attempt in raw_attempts:
        key = (
            attempt.source_code, attempt.term, attempt.grade_token,
            attempt.grade_value, (attempt.note or "").casefold(), attempt.ects,
        )
        existing = deduplicated.get(key)
        if existing is None:
            deduplicated[key] = attempt
            continue
        duplicate_count += 1
        existing.duplicate_occurrences += 1
        existing.source_sections = sorted(set(existing.source_sections + attempt.source_sections))

    attempts = list(deduplicated.values())
    for index, attempt in enumerate(attempts, start=1):
        attempt.id = f"attempt-{index}"

    components: list[ComponentPreview] = []
    planning_attempts: list[AttemptPreview] = []
    by_code_term: dict[tuple[str, str], list[AttemptPreview]] = defaultdict(list)
    for attempt in attempts:
        if not (attempt.ects == 0 and attempt.source_code.endswith("L")):
            by_code_term[attempt.source_code, attempt.term].append(attempt)
            planning_attempts.append(attempt)
    for attempt in attempts:
        if not (attempt.ects == 0 and attempt.source_code.endswith("L")):
            continue
        parent_code = attempt.source_code[:-1]
        parents = by_code_term.get((parent_code, attempt.term), [])
        parent = parents[0] if len(parents) == 1 else None
        component = ComponentPreview(
            id=f"component-{len(components) + 1}", source_code=attempt.source_code,
            source_title=attempt.source_title, term=attempt.term, status=attempt.status,
            note=attempt.note, parent_code=parent_code,
            parent_attempt_id=parent.id if parent else None,
            source_sections=attempt.source_sections,
        )
        components.append(component)
        if parent is None:
            parent_title = re.sub(r"\s+lab(?:oratory)?\s*$", "", attempt.source_title, flags=re.IGNORECASE).strip()
            add_issue(
                "LAB_PARENT_MISSING",
                f"{_course_label(attempt.source_title, attempt.source_code)} is a zero-credit lab, but no unique "
                f"{_course_label(parent_title, parent_code)} attempt exists in {attempt.term}.",
                f"What should happen to {_course_label(attempt.source_title, attempt.source_code)}?",
                severity="BLOCKING", attempt_id=component.id,
                options=[
                    f"Attach it to the correct {_course_label(parent_title, parent_code)} attempt — keep it as a zero-credit component",
                    "Keep it for transcript audit only — no credit, GPA, or requirement effect",
                    "Ignore this row as a portal error — remove it from the import",
                    "Leave unresolved — block import until corrected",
                ],
            )

    for attempt in planning_attempts:
        if attempt.status == "NEEDS_REVIEW":
            label = _course_label(attempt.source_title, attempt.source_code)
            add_issue(
                "PAST_UNGRADED_ATTEMPT",
                f"{label} in {attempt.term} has no released grade even though the term is before {current_term}.",
                f"What happened to {label}?", attempt_id=attempt.id,
                options=[
                    "Enter the final grade — use it to determine pass/fail, earned credit, GPA, and retake status",
                    "Completed; grade still pending — do not schedule it again, but add no earned credit or GPA yet",
                    "Withdrawn — add no earned credit or GPA; keep the requirement outstanding",
                    "Still in progress — treat it as active and do not schedule it again; add no earned credit or GPA yet",
                    "Not taken / portal error — ignore this row; add no credit or GPA",
                    "Leave unresolved — block import until corrected",
                ],
            )

    conflicts: dict[tuple[str, str], set[tuple[str, float | None]]] = defaultdict(set)
    for attempt in planning_attempts:
        conflicts[attempt.source_code, attempt.term].add((attempt.status, attempt.grade_value))
    for (code, term), values in conflicts.items():
        if len(values) > 1:
            attempt = next(item for item in planning_attempts if item.source_code == code and item.term == term)
            label = _course_label(attempt.source_title, code)
            add_issue(
                "CONFLICTING_ATTEMPT", f"{label} has conflicting records in {term}.",
                f"Which {label} record is authoritative?", severity="BLOCKING",
                options=[
                    "Keep the correct record — use only its grade, credit, GPA, and status",
                    "Keep both as separate attempts — only if both attempts genuinely occurred",
                    "Leave unresolved — block import until corrected",
                ],
            )

    if identity.student_id is None or identity.name is None:
        add_issue(
            "IDENTITY_MISSING", "The student identifier or name could not be detected.",
            "Was the Contract Sheet heading included?", severity="BLOCKING",
        )
    if identity.reported_earned_credits is None:
        add_issue(
            "REPORTED_TOTAL_MISSING", "The portal's total earned credits could not be detected.",
            "Please include the Total Earned Credits line.", severity="BLOCKING",
        )

    return ParsedStudentContract(
        identity=identity, categories=categories, attempts=planning_attempts,
        components=components, issues=issues,
        duplicate_attempts_merged=duplicate_count,
    )

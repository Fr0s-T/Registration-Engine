"""Resolve parsed contract text against both active curricula and verify totals."""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from hashlib import sha256
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from academic_planner.database.models import (
    CourseRecord, CurriculumRevision, Equivalency, TranscriptCodeMapping,
)
from academic_planner.transcripts import canonical_course_credit_identities

from .parser import OUTSIDE_SECTION, parse_student_contract
from .schemas import (
    AppliedReviewDecisionPreview, CatalogMatchPreview, CourseGroupPreview,
    CreditCheckPreview, ReviewDecisionInput, ReviewIssuePreview,
    StudentInputPreviewResponse,
)


VERIFIED_EQUIVALENCY_STATUSES = {
    "AUTO_MATCHED", "HUMAN_VERIFIED", "OFFICIALLY_DOCUMENTED", "VERIFIED",
}
COMPLETED_STATUSES = {"PASSED", "TRANSFERRED", "EXEMPTED"}
REVIEW_ACTIONS_BY_ISSUE = {
    "LAB_PARENT_MISSING": {
        "ATTACH_LAB_TO_PARENT", "KEEP_LAB_FOR_AUDIT", "IGNORE_LAB_ROW",
        "LEAVE_UNRESOLVED",
    },
    "PAST_UNGRADED_ATTEMPT": {
        "ENTER_FINAL_GRADE", "COMPLETED_GRADE_PENDING", "WITHDRAWN",
        "STILL_IN_PROGRESS", "NOT_TAKEN", "LEAVE_UNRESOLVED",
    },
    "CATEGORY_TOTAL_MISMATCH": {
        "ACCEPT_PARSED_CATEGORY_TOTAL", "LEAVE_UNRESOLVED",
    },
    "CREDIT_TOTAL_MISMATCH": {
        "ACCEPT_PARSED_CREDIT_TOTAL", "LEAVE_UNRESOLVED",
    },
}


def _course_label(title: str, code: str) -> str:
    return f"{title.strip()} ({code})"


def _normalized_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _preferred_version(sections: list[str]) -> str:
    return "NEW" if any(section != OUTSIDE_SECTION for section in sections) else "OLD"


def _source_section_credits(attempts, section: str) -> int:
    earned: dict[str, int] = {}
    for attempt in attempts:
        if section not in attempt.source_sections or attempt.status not in COMPLETED_STATUSES:
            continue
        if not attempt.counts_toward_source_subtotal:
            continue
        earned[attempt.source_code] = max(earned.get(attempt.source_code, 0), attempt.ects)
    return sum(earned.values())


def student_input_preview_token(text: str, current_term: str) -> str:
    """Bind review decisions to the exact source snapshot that was previewed."""

    return sha256(f"{current_term}\0{text}".encode("utf-8")).hexdigest()


def _validate_review_action(issue_code: str, decision: ReviewDecisionInput) -> None:
    allowed = REVIEW_ACTIONS_BY_ISSUE.get(issue_code, {"LEAVE_UNRESOLVED"})
    if decision.action not in allowed:
        raise ValueError(
            f"{decision.action} is not valid for review issue {issue_code}."
        )


def _apply_review_decisions(parsed, decisions: list[ReviewDecisionInput]):
    keys = [(decision.issue_code, decision.attempt_id) for decision in decisions]
    if len(keys) != len(set(keys)):
        raise ValueError("Only one decision may be supplied for each review issue.")
    decision_by_key = {
        (decision.issue_code, decision.attempt_id): decision
        for decision in decisions
    }
    attempts_by_id = {attempt.id: attempt for attempt in parsed.attempts}
    components_by_id = {component.id: component for component in parsed.components}
    resolved_issue_ids: set[str] = set()
    removed_attempt_ids: set[str] = set()
    removed_component_ids: set[str] = set()
    credit_adjustment = 0
    category_adjustments: dict[str, int] = defaultdict(int)
    applied: list[AppliedReviewDecisionPreview] = []
    consumed_keys: set[tuple[str, str]] = set()

    for issue in parsed.issues:
        if issue.attempt_id is None:
            continue
        decision = decision_by_key.get((issue.code, issue.attempt_id))
        if decision is None:
            continue
        _validate_review_action(issue.code, decision)
        consumed_keys.add((issue.code, issue.attempt_id))
        if decision.action == "LEAVE_UNRESOLVED":
            continue
        if issue.code == "LAB_PARENT_MISSING":
            component = components_by_id.get(issue.attempt_id)
            if component is None or decision.action not in {
                "ATTACH_LAB_TO_PARENT", "KEEP_LAB_FOR_AUDIT", "IGNORE_LAB_ROW",
            }:
                continue
            label = _course_label(component.source_title, component.source_code)
            parent_title = re.sub(
                r"\s+lab(?:oratory)?\s*$", "", component.source_title,
                flags=re.IGNORECASE,
            ).strip()
            parent_label = _course_label(parent_title, component.parent_code)
            if decision.action == "ATTACH_LAB_TO_PARENT":
                component.review_disposition = "ATTACH_TO_CATALOG_PARENT"
                summary = (
                    f"Attach to {parent_label} as a zero-credit component; "
                    "it has no separate credit or GPA effect."
                )
            elif decision.action == "KEEP_LAB_FOR_AUDIT":
                component.review_disposition = "AUDIT_ONLY"
                summary = "Kept for transcript audit only, with no credit, GPA, or requirement effect."
            else:
                removed_component_ids.add(component.id)
                summary = "Removed as a portal error; it has no credit, GPA, or planning effect."
            resolved_issue_ids.add(issue.id)
            applied.append(AppliedReviewDecisionPreview(
                issue_code=issue.code,
                attempt_id=component.id,
                action=decision.action,
                course_label=label,
                summary=summary,
            ))
            continue
        if issue.code != "PAST_UNGRADED_ATTEMPT":
            continue
        attempt = attempts_by_id.get(issue.attempt_id)
        if attempt is None:
            continue

        label = _course_label(attempt.source_title, attempt.source_code)
        action = decision.action
        if action == "ENTER_FINAL_GRADE":
            grade = float(decision.grade_value)
            passed = grade >= attempt.passing_grade
            attempt.grade_token = "FINAL"
            attempt.grade_value = grade
            attempt.status = "PASSED" if passed else "FAILED"
            attempt.earned_ects = attempt.ects if passed else 0
            attempt.note = "Final grade entered during review"
            if passed:
                credit_adjustment += attempt.ects
                for section in attempt.source_sections:
                    category_adjustments[section] += attempt.ects
            summary = (
                f"Final grade {grade:g}: {'passed' if passed else 'failed'}; "
                f"{attempt.ects if passed else 0} ECTS added and retake status recalculated."
            )
        elif action == "COMPLETED_GRADE_PENDING":
            attempt.status = "RESULT_PENDING"
            attempt.note = "Reviewer confirmed completion; final grade is pending"
            summary = "Completion confirmed; no earned credit or GPA is added until the grade arrives."
        elif action == "WITHDRAWN":
            attempt.status = "WITHDRAWN"
            attempt.grade_token = "W"
            attempt.grade_value = None
            attempt.earned_ects = 0
            attempt.counts_toward_gpa = False
            attempt.note = "Reviewer confirmed withdrawal"
            summary = "Marked withdrawn; no earned credit or GPA, and the requirement remains outstanding."
        elif action == "STILL_IN_PROGRESS":
            attempt.status = "IN_PROGRESS"
            attempt.grade_token = "IP"
            attempt.grade_value = None
            attempt.earned_ects = 0
            attempt.note = "Reviewer confirmed the course is still in progress"
            summary = "Kept in progress; it will not be scheduled again and has no earned credit or GPA yet."
        elif action == "NOT_TAKEN":
            removed_attempt_ids.add(attempt.id)
            summary = "Removed as a portal error; it has no credit, GPA, or planning effect."
        else:  # Defensive: every accepted action must be handled explicitly above.
            raise ValueError(f"Unsupported review action: {action}")

        resolved_issue_ids.add(issue.id)
        applied.append(AppliedReviewDecisionPreview(
            issue_code=issue.code,
            attempt_id=attempt.id,
            action=action,
            course_label=label,
            summary=summary,
        ))

    parsed.issues = [
        issue for issue in parsed.issues if issue.id not in resolved_issue_ids
    ]
    if removed_attempt_ids:
        parsed.attempts = [
            attempt for attempt in parsed.attempts if attempt.id not in removed_attempt_ids
        ]
        parsed.components = [
            component for component in parsed.components
            if component.parent_attempt_id not in removed_attempt_ids
        ]
    if removed_component_ids:
        parsed.components = [
            component for component in parsed.components
            if component.id not in removed_component_ids
        ]
    return applied, credit_adjustment, category_adjustments, consumed_keys


def preview_student_input(
    session: Session, text: str, current_term: str,
    decisions: list[ReviewDecisionInput] | None = None,
) -> StudentInputPreviewResponse:
    parsed = parse_student_contract(text, current_term)
    (
        applied_decisions, credit_adjustment, category_adjustments,
        consumed_decision_keys,
    ) = _apply_review_decisions(
        parsed, decisions or [],
    )
    decision_by_key = {
        (decision.issue_code, decision.attempt_id): decision
        for decision in (decisions or [])
    }
    courses = list(session.scalars(
        select(CourseRecord)
        .join(CurriculumRevision)
        .where(CurriculumRevision.active.is_(True))
        .options(selectinload(CourseRecord.curriculum))
    ))
    course_by_id = {course.id: course for course in courses}
    by_code: dict[str, list[CourseRecord]] = defaultdict(list)
    for course in courses:
        by_code[course.code.upper()].append(course)
    mappings = {
        row.source_code.upper(): row
        for row in session.scalars(select(TranscriptCodeMapping)).all()
    }
    equivalencies = list(session.scalars(select(Equivalency).where(
        Equivalency.recognizes_history.is_(True),
        Equivalency.verification_status.in_(VERIFIED_EQUIVALENCY_STATUSES),
    )))
    target_by_source: dict[int, int] = {}
    for equivalency in equivalencies:
        target_by_source[equivalency.source_course_id] = equivalency.target_course_id
    credit_identity_by_course = canonical_course_credit_identities(
        {
            course.id: (course.curriculum.version, course.code)
            for course in courses
        },
        (
            (equivalency.source_course_id, equivalency.target_course_id)
            for equivalency in equivalencies
        ),
    )

    issues = list(parsed.issues)
    issue_counter = len(issues)

    def add_issue(code: str, message: str, question: str, *, attempt_id: str | None = None, options: list[str] | None = None, severity: str = "REVIEW") -> None:
        nonlocal issue_counter
        issue_counter += 1
        issues.append(ReviewIssuePreview(
            id=f"issue-{issue_counter}", severity=severity, code=code,
            message=message, question=question, attempt_id=attempt_id,
            options=options or [],
        ))

    for attempt in parsed.attempts:
        code = attempt.source_code.upper()
        exact = by_code.get(code, [])
        mapping = mappings.get(code)
        if not attempt.counts_toward_degree_credit:
            attempt.match_status = "TRANSCRIPT_EXCLUDED"
            attempt.earned_ects = 0
            attempt.logical_key = f"transcript-excluded:{code}"
            attempt.credit_identity = f"transcript-excluded:{code}"
            continue
        if mapping is not None and mapping.mapping_kind == "NON_DEGREE":
            attempt.match_status = "NON_DEGREE"
            attempt.counts_toward_degree_credit = False
            attempt.earned_ects = 0
            attempt.logical_key = f"non-degree:{code}"
            attempt.credit_identity = f"non-degree:{code}"
            continue
        selected: CourseRecord | None = None
        match_kind = "EXACT_CODE"
        if exact:
            preferred = _preferred_version(attempt.source_sections)
            selected = next(
                (course for course in exact if course.curriculum.version == preferred),
                exact[0] if len(exact) == 1 else None,
            )
        elif mapping is not None and mapping.mapping_kind == "COURSE_ALIAS":
            selected = course_by_id.get(mapping.target_course_id)
            match_kind = "VERIFIED_ALIAS"
        attempt.catalog_matches = [
            CatalogMatchPreview(
                course_id=course.id, version=course.curriculum.version,
                code=course.code, title=course.title, ects=course.ects,
                match_kind=match_kind, selected=selected is not None and course.id == selected.id,
            )
            for course in (exact if exact else ([selected] if selected else []))
        ]
        if selected is None:
            unresolved_status = "AMBIGUOUS" if exact else "UNKNOWN"
            # Preserve passed historical rows as distinct earned-credit identities.
            # They count toward the reconciled total but do not satisfy a named
            # curriculum requirement without a verified mapping.
            if attempt.status in COMPLETED_STATUSES and not exact:
                attempt.match_status = "HISTORICAL_UNMAPPED"
                attempt.logical_key = f"historical:{code}"
                attempt.credit_identity = f"source:{code}"
                continue
            attempt.match_status = unresolved_status
            suggestions = sorted(
                (
                    (SequenceMatcher(None, _normalized_title(attempt.source_title), _normalized_title(course.title)).ratio(), course)
                    for course in courses if course.ects == attempt.ects
                ),
                key=lambda item: item[0], reverse=True,
            )[:3]
            options = [
                f"Map to {_course_label(course.title, course.code)} in the {course.curriculum.version} curriculum — use its requirement and retake identity"
                for score, course in suggestions if score >= .58
            ]
            options.extend([
                "Search both curricula for another course — choose its requirement and retake identity",
                "Keep as a separate unmapped transcript course — preserve it for audit but satisfy no named requirement",
                "Mark as non-degree — exclude it from earned degree credit, GPA, and curriculum requirements",
                "Leave unresolved — block import until corrected",
            ])
            label = _course_label(attempt.source_title, attempt.source_code)
            add_issue(
                "COURSE_MATCH_REQUIRED",
                f"{label} was not resolved to one course in the active OLD or NEW curriculum.",
                f"How should {label} be represented?",
                attempt_id=attempt.id, options=options,
                severity="BLOCKING",
            )
            attempt.logical_key = f"unresolved:{code}"
            attempt.credit_identity = f"source:{code}"
            continue
        attempt.match_status = match_kind
        attempt.selected_course_id = selected.id
        attempt.selected_course_code = selected.code
        attempt.selected_curriculum_version = selected.curriculum.version
        stable_identity = credit_identity_by_course[selected.id]
        attempt.logical_key = stable_identity
        # Verified OLD/NEW course equivalencies are one retake identity. Transcript
        # aliases remain source identities because several aliases may contribute credit.
        attempt.credit_identity = (
            f"source:{code}" if match_kind == "VERIFIED_ALIAS"
            else stable_identity
        )

    attempts_by_id = {attempt.id: attempt for attempt in parsed.attempts}
    for component in parsed.components:
        parent = attempts_by_id.get(component.parent_attempt_id or "")
        if parent is not None:
            component.logical_key = parent.logical_key
            continue
        if component.review_disposition != "ATTACH_TO_CATALOG_PARENT":
            continue
        candidates = [
            attempt for attempt in parsed.attempts
            if attempt.logical_key
            and (
                attempt.source_code == component.parent_code
                or attempt.selected_course_code == component.parent_code
                or (
                    attempt.selected_course_id in target_by_source
                    and target_by_source[attempt.selected_course_id] in course_by_id
                    and course_by_id[target_by_source[attempt.selected_course_id]].code
                    == component.parent_code
                )
            )
        ]
        candidate_keys = {attempt.logical_key for attempt in candidates}
        if len(candidate_keys) == 1:
            parent = next(
                (attempt for attempt in candidates if attempt.term == component.term),
                candidates[0],
            )
            component.parent_attempt_id = parent.id
            component.logical_key = parent.logical_key
            for decision in applied_decisions:
                if (
                    decision.issue_code == "LAB_PARENT_MISSING"
                    and decision.attempt_id == component.id
                ):
                    selected_parent = course_by_id.get(
                        parent.selected_course_id or -1,
                    )
                    resolved_parent = course_by_id.get(
                        target_by_source.get(parent.selected_course_id or -1, -1),
                    ) or selected_parent
                    parent_label = _course_label(
                        resolved_parent.title, resolved_parent.code,
                    ) if resolved_parent else _course_label(
                        parent.source_title, parent.source_code,
                    )
                    source_note = (
                        f", using transcript parent "
                        f"{_course_label(parent.source_title, parent.source_code)}"
                        if resolved_parent and parent.source_code != resolved_parent.code
                        else ""
                    )
                    decision.summary = (
                        f"Attached to {parent_label}{source_note} as a zero-credit component; "
                        "it has no separate credit or GPA effect."
                    )
                    break
            continue
        component.review_disposition = None
        applied_decisions[:] = [
            decision for decision in applied_decisions
            if not (
                decision.issue_code == "LAB_PARENT_MISSING"
                and decision.attempt_id == component.id
            )
        ]
        parent_title = re.sub(
            r"\s+lab(?:oratory)?\s*$", "", component.source_title,
            flags=re.IGNORECASE,
        ).strip()
        parent_label = _course_label(parent_title, component.parent_code)
        component_label = _course_label(
            component.source_title, component.source_code,
        )
        add_issue(
            "LAB_PARENT_MISSING",
            f"{component_label} could not be attached because exactly one "
            f"{parent_label} course group was not found.",
            f"What should happen to {component_label}?",
            attempt_id=component.id,
            severity="BLOCKING",
            options=[
                f"Attach it to the correct {parent_label} attempt â€” keep it as a zero-credit component",
                "Keep it for transcript audit only â€” no credit, GPA, or requirement effect",
                "Ignore this row as a portal error â€” remove it from the import",
                "Leave unresolved â€” block import until corrected",
            ],
        )

    grouped: dict[str, list] = defaultdict(list)
    for attempt in parsed.attempts:
        grouped[attempt.logical_key or f"unresolved:{attempt.source_code}"].append(attempt)
    components_by_group: dict[str, list] = defaultdict(list)
    for component in parsed.components:
        components_by_group[component.logical_key or f"component:{component.parent_code}"].append(component)

    course_groups: list[CourseGroupPreview] = []
    for key, attempts in grouped.items():
        statuses = {attempt.status for attempt in attempts}
        completed = bool(statuses & COMPLETED_STATUSES)
        failed = "FAILED" in statuses and not completed
        registered = bool(statuses & {"REGISTERED", "IN_PROGRESS"})
        result_pending = "RESULT_PENDING" in statuses
        needs_review = "NEEDS_REVIEW" in statuses or any(
            attempt.match_status in {"UNKNOWN", "AMBIGUOUS"} for attempt in attempts
        )
        if completed:
            effective = "COMPLETED"
        elif needs_review:
            effective = "NEEDS_REVIEW"
        elif failed:
            effective = "FAILED_OUTSTANDING"
        elif result_pending:
            effective = "RESULT_PENDING"
        elif registered:
            effective = "ACTIVE_OUTSTANDING"
        else:
            effective = "WITHDRAWN_OUTSTANDING"
        selected = next((attempt for attempt in attempts if attempt.selected_course_id), attempts[0])
        selected_course = course_by_id.get(selected.selected_course_id) if selected.selected_course_id else None
        target = course_by_id.get(target_by_source.get(selected.selected_course_id)) if selected.selected_course_id else None
        display_code = target.code if target else (selected_course.code if selected_course else selected.source_code)
        title = target.title if target else (selected_course.title if selected_course else selected.source_title)
        match_statuses = {attempt.match_status for attempt in attempts}
        if match_statuses & {"UNKNOWN", "AMBIGUOUS"}:
            mapping_status = "NEEDS_REVIEW"
        elif "HISTORICAL_UNMAPPED" in match_statuses:
            mapping_status = "HISTORICAL_UNMAPPED"
        elif match_statuses == {"TRANSCRIPT_EXCLUDED"}:
            mapping_status = "TRANSCRIPT_EXCLUDED"
        elif match_statuses == {"NON_DEGREE"}:
            mapping_status = "NON_DEGREE"
        else:
            mapping_status = "RESOLVED"
        course_groups.append(CourseGroupPreview(
            key=key, display_code=display_code, title=title,
            codes=sorted({attempt.source_code for attempt in attempts}),
            effective_status=effective, mapping_status=mapping_status, completed=completed,
            unresolved_failed=failed, currently_registered=registered,
            attempts=sorted(attempts, key=lambda item: (item.term, item.source_code)),
            components=components_by_group.get(key, []),
        ))

    # Components without a matched parent still appear as their own audit group.
    known_component_ids = {
        component.id for group in course_groups for component in group.components
    }
    for component in parsed.components:
        if component.id in known_component_ids:
            continue
        parent_title = re.sub(
            r"\s*(?:-|–)?\s*lab(?:oratory)?\s*$", "", component.source_title,
            flags=re.IGNORECASE,
        ).strip()
        course_groups.append(CourseGroupPreview(
            key=component.logical_key or f"component:{component.parent_code}",
            display_code=component.parent_code, title=parent_title,
            codes=[component.parent_code],
            effective_status=(
                "AUDIT_ONLY"
                if component.review_disposition == "AUDIT_ONLY"
                else "NEEDS_REVIEW"
            ),
            mapping_status=(
                "TRANSCRIPT_AUDIT"
                if component.review_disposition == "AUDIT_ONLY"
                else "NEEDS_REVIEW"
            ),
            completed=False, unresolved_failed=False, currently_registered=False,
            attempts=[], components=[component],
        ))

    for category in parsed.categories:
        category.parsed_earned_ects = _source_section_credits(parsed.attempts, category.label)
        if category.reported_earned_ects is None:
            category.validation_status = "NOT_CHECKED"
        elif category.parsed_earned_ects == category.reported_earned_ects:
            category.validation_status = "MATCH"
        elif (
            category.parsed_earned_ects - category.reported_earned_ects
            == category_adjustments.get(category.label, 0)
        ):
            category.validation_status = "ADJUSTED"
        else:
            decision_key = f"category:{category.label}"
            decision = decision_by_key.get(("CATEGORY_TOTAL_MISMATCH", decision_key))
            if decision:
                _validate_review_action("CATEGORY_TOTAL_MISMATCH", decision)
                consumed_decision_keys.add(("CATEGORY_TOTAL_MISMATCH", decision_key))
            if decision and decision.action == "ACCEPT_PARSED_CATEGORY_TOTAL":
                source_total = category.reported_earned_ects
                category.reported_earned_ects = category.parsed_earned_ects
                category.validation_status = "ADJUSTED"
                applied_decisions.append(AppliedReviewDecisionPreview(
                    issue_code="CATEGORY_TOTAL_MISMATCH",
                    attempt_id=decision_key,
                    action=decision.action,
                    course_label=f"{category.label} subtotal",
                    summary=(
                        f"Corrected the reported subtotal from {source_total} to "
                        f"{category.parsed_earned_ects} ECTS; parsed courses are unchanged."
                    ),
                ))
            else:
                category.validation_status = "MISMATCH"
                add_issue(
                    "CATEGORY_TOTAL_MISMATCH",
                    f"{category.label} reports {category.reported_earned_ects} earned ECTS, "
                    f"but its parsed attempts produce {category.parsed_earned_ects} ECTS.",
                    "Should the reported category subtotal be corrected to match the parsed courses?",
                    attempt_id=decision_key,
                    severity="REVIEW",
                    options=[
                        f"Use {category.parsed_earned_ects} ECTS as the corrected {category.label} subtotal — keep the parsed courses unchanged",
                        "Leave unresolved — correct the course rows or source subtotal before saving",
                    ],
                )

    earned_by_identity: dict[str, int] = {}
    for attempt in parsed.attempts:
        if attempt.status not in COMPLETED_STATUSES or not attempt.counts_toward_degree_credit:
            continue
        identity = attempt.credit_identity or f"source:{attempt.source_code}"
        earned_by_identity[identity] = max(earned_by_identity.get(identity, 0), attempt.ects)
    parsed_earned = sum(earned_by_identity.values())
    reported = parsed.identity.reported_earned_credits
    difference = parsed_earned - reported if reported is not None else None
    if reported is None:
        credit_status = "NOT_CHECKED"
        explanation = "The portal total was not available for comparison."
    elif difference == 0:
        credit_status = "MATCH"
        explanation = "Unique completed degree-credit attempts reconcile exactly with the portal total."
    elif difference == credit_adjustment:
        credit_status = "ADJUSTED"
        explanation = (
            f"The portal snapshot reports {reported} ECTS; reviewer-confirmed results add "
            f"{credit_adjustment} ECTS, producing {parsed_earned} ECTS."
        )
    else:
        decision_key = "credit-ledger"
        decision = decision_by_key.get(("CREDIT_TOTAL_MISMATCH", decision_key))
        if decision:
            _validate_review_action("CREDIT_TOTAL_MISMATCH", decision)
            consumed_decision_keys.add(("CREDIT_TOTAL_MISMATCH", decision_key))
        if decision and decision.action == "ACCEPT_PARSED_CREDIT_TOTAL":
            source_total = reported
            parsed.identity.reported_earned_credits = parsed_earned
            reported = parsed_earned
            difference = 0
            credit_status = "ADJUSTED"
            explanation = (
                f"The reviewer corrected the reported total from {source_total} to "
                f"{parsed_earned} ECTS; parsed course records are unchanged."
            )
            applied_decisions.append(AppliedReviewDecisionPreview(
                issue_code="CREDIT_TOTAL_MISMATCH",
                attempt_id=decision_key,
                action=decision.action,
                course_label="Overall earned-credit total",
                summary=explanation,
            ))
        else:
            credit_status = "MISMATCH"
            explanation = (
                f"Parsed degree credit is {abs(difference)} ECTS "
                f"{'above' if difference > 0 else 'below'} the portal total."
            )
            add_issue(
                "CREDIT_TOTAL_MISMATCH", explanation,
                "Should the reported overall total be corrected to match the parsed courses?",
                attempt_id=decision_key,
                severity="BLOCKING",
                options=[
                    f"Use {parsed_earned} ECTS as the corrected overall total — keep the parsed courses unchanged",
                    "Leave unresolved — correct the course rows or reported total before saving",
                ],
            )

    unconsumed = set(decision_by_key) - consumed_decision_keys
    if unconsumed:
        details = ", ".join(f"{code}/{attempt_id}" for code, attempt_id in sorted(unconsumed))
        raise ValueError(
            f"Review decisions do not match the current preview: {details}."
        )

    course_groups.sort(key=lambda group: (
        group.effective_status not in {"NEEDS_REVIEW", "FAILED_OUTSTANDING"},
        group.display_code,
    ))
    blocking = any(issue.severity in {"BLOCKING", "REVIEW"} for issue in issues)
    return StudentInputPreviewResponse(
        current_term=current_term,
        preview_token=student_input_preview_token(text, current_term),
        identity=parsed.identity, categories=parsed.categories,
        course_groups=course_groups,
        credit_check=CreditCheckPreview(
            reported_earned_ects=reported, parsed_degree_earned_ects=parsed_earned,
            difference=difference, status=credit_status, explanation=explanation,
        ),
        review_issues=issues, applied_decisions=applied_decisions,
        attempts_parsed=len(parsed.attempts),
        duplicate_attempts_merged=parsed.duplicate_attempts_merged,
        lab_components=len(parsed.components),
        completed_courses=sum(group.completed for group in course_groups),
        failed_outstanding_courses=sum(group.unresolved_failed for group in course_groups),
        currently_registered_courses=sum(group.currently_registered for group in course_groups),
        can_continue_without_review=not blocking,
    )

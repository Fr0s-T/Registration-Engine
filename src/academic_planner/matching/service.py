"""Conservative OLD/NEW course matching with durable review decisions."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
import re
import unicodedata

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from academic_planner.database.models import (
    CourseRecord, CurriculumRevision, Equivalency, EquivalencyMatch,
    TransitionCourseDisposition,
)


def _utc_now() -> datetime:
    """Return naive UTC for the existing timezone-naive persistence columns."""
    return datetime.now(UTC).replace(tzinfo=None)


SIMILARITY_THRESHOLD = 0.84


def normalize_course_title(value: str) -> str:
    """Normalize typography without erasing academically meaningful words."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"\bintro\.?(?=\s|$)", "introduction", value)
    value = re.sub(r"\bentrepreneurial\s+ship\b", "entrepreneurship", value)
    value = re.sub(r"(?<!\w)\+(?!\w)", " ", value)
    value = "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in value)
    return " ".join(value.split())


def _similarity(left: str, right: str) -> float:
    a, b = normalize_course_title(left), normalize_course_title(right)
    if not a or not b:
        return 0.0
    tokens_a, tokens_b = set(a.split()), set(b.split())
    if not (tokens_a & tokens_b):
        return 0.0
    # These qualifiers change academic scope and must never be smoothed over by
    # a high character-level score.
    roman = {"i", "ii", "iii", "iv", "v"}
    if (tokens_a & roman) != (tokens_b & roman):
        return 0.0
    protected = {"advanced", "introduction", "introductory", "analog", "digital"}
    if (tokens_a & protected) != (tokens_b & protected):
        return 0.0
    score = SequenceMatcher(None, a, b, autojunk=False).ratio()
    # Catalogs sometimes add a generic scope prefix. This is review-worthy,
    # never automatic, but a long shared core remains a credible suggestion.
    generic = {"foundations", "foundation", "of", "the"}
    core_a, core_b = tokens_a - generic, tokens_b - generic
    if core_a == core_b and any(len(token) >= 10 for token in core_a):
        score = max(score, 0.86)
    return score


def _differences(old: CourseRecord, new: CourseRecord, similar: bool = False) -> list[str]:
    reasons = ["TITLE_SIMILAR"] if similar else []
    if old.ects != new.ects:
        reasons.append("ECTS_CHANGED")
    if old.reference_year != new.reference_year:
        reasons.append("REFERENCE_YEAR_CHANGED")
    if old.reference_semester != new.reference_semester:
        reasons.append("REFERENCE_SEMESTER_CHANGED")
    return reasons


def _explanation(old: CourseRecord, new: CourseRecord, reasons: list[str]) -> str:
    if not reasons:
        return "Unique normalized title, ECTS, reference year, and semester match."
    messages = {
        "TITLE_SIMILAR": f"Titles are similar: {old.title!r} and {new.title!r}.",
        "ECTS_CHANGED": f"ECTS changed from {old.ects} to {new.ects}.",
        "REFERENCE_YEAR_CHANGED": (
            f"Reference year changed from Year {old.reference_year} to Year {new.reference_year}."
        ),
        "REFERENCE_SEMESTER_CHANGED": (
            f"Reference semester changed from {old.reference_semester} to {new.reference_semester}."
        ),
        "MULTIPLE_CANDIDATES": "More than one plausible candidate exists; no automatic choice was made.",
        "CONFLICTING_ACCEPTED_EQUIVALENCY": "A course is already part of an accepted equivalency.",
    }
    return " ".join(messages[item] for item in reasons)


class EquivalencyMatchingService:
    def run(self, session: Session) -> dict:
        revisions = session.scalars(select(CurriculumRevision).where(
            CurriculumRevision.active.is_(True)
        )).all()
        old_revision = next((row for row in revisions if row.version == "OLD"), None)
        new_revision = next((row for row in revisions if row.version == "NEW"), None)
        if old_revision is None or new_revision is None:
            raise ValueError("Active OLD and NEW curriculum revisions are required")
        old = list(session.scalars(select(CourseRecord).where(
            CourseRecord.curriculum_id == old_revision.id).order_by(CourseRecord.code)))
        new = list(session.scalars(select(CourseRecord).where(
            CourseRecord.curriculum_id == new_revision.id).order_by(CourseRecord.code)))
        explicitly_disposed = set(session.scalars(select(
            TransitionCourseDisposition.old_course_id
        )))
        matchable_old = [row for row in old if row.id not in explicitly_disposed]

        decisions = list(session.scalars(select(EquivalencyMatch)))
        preserved = [row for row in decisions if row.status in {"HUMAN_VERIFIED", "REJECTED"}]
        rejected_pairs = {(row.old_course_id, row.new_course_id) for row in preserved
                          if row.status == "REJECTED"}
        reserved = {course_id for row in preserved if row.status == "HUMAN_VERIFIED"
                    for course_id in (row.old_course_id, row.new_course_id)}
        algorithm_equivalency_ids = {row.equivalency_id for row in decisions
                                     if row.status == "AUTO_MATCHED" and row.equivalency_id}
        accepted = session.scalars(select(Equivalency).where(
            Equivalency.recognizes_history.is_(True),
            ~Equivalency.id.in_(algorithm_equivalency_ids) if algorithm_equivalency_ids else True,
        )).all()
        reserved.update(course_id for row in accepted
                        for course_id in (row.source_course_id, row.target_course_id))

        old_by_name, new_by_name = defaultdict(list), defaultdict(list)
        for row in matchable_old: old_by_name[normalize_course_title(row.title)].append(row)
        for row in new: new_by_name[normalize_course_title(row.title)].append(row)
        proposed: dict[tuple[int, int], tuple[str, str, list[str], str]] = {}
        considered_old, considered_new = set(), set()

        for title in sorted(old_by_name.keys() & new_by_name.keys()):
            olds, news = old_by_name[title], new_by_name[title]
            ambiguous = len(olds) != 1 or len(news) != 1
            for left in olds:
                for right in news:
                    pair = (left.id, right.id)
                    considered_old.add(left.id); considered_new.add(right.id)
                    if pair in rejected_pairs:
                        continue
                    reasons = _differences(left, right)
                    if ambiguous:
                        reasons.append("MULTIPLE_CANDIDATES")
                    if left.id in reserved or right.id in reserved:
                        reasons.append("CONFLICTING_ACCEPTED_EQUIVALENCY")
                    status = "AUTO_MATCHED" if not reasons else "NEEDS_REVIEW"
                    proposed[pair] = (status, "EXACT_NORMALIZED_TITLE", reasons,
                                      _explanation(left, right, reasons))

        # Only courses without an exact-title candidate enter conservative fuzzy matching.
        fuzzy: dict[int, list[tuple[CourseRecord, float]]] = defaultdict(list)
        reverse: dict[int, list[tuple[CourseRecord, float]]] = defaultdict(list)
        for left in matchable_old:
            if left.id in considered_old:
                continue
            for right in new:
                if right.id in considered_new:
                    continue
                score = _similarity(left.title, right.title)
                if score >= SIMILARITY_THRESHOLD:
                    fuzzy[left.id].append((right, score)); reverse[right.id].append((left, score))
        old_map = {row.id: row for row in old}
        for old_id, candidates in sorted(fuzzy.items()):
            left = old_map[old_id]
            for right, score in sorted(candidates, key=lambda item: (-item[1], item[0].code)):
                pair = (left.id, right.id)
                if pair in rejected_pairs:
                    continue
                reasons = _differences(left, right, similar=True)
                if len(candidates) > 1 or len(reverse[right.id]) > 1:
                    reasons.append("MULTIPLE_CANDIDATES")
                if left.id in reserved or right.id in reserved:
                    reasons.append("CONFLICTING_ACCEPTED_EQUIVALENCY")
                proposed[pair] = ("NEEDS_REVIEW", "TITLE_SIMILARITY", reasons,
                                  f"Title similarity {score:.0%}. " + _explanation(left, right, reasons))

        existing = {(row.old_course_id, row.new_course_id): row for row in decisions}
        for pair, (status, method, reasons, explanation) in proposed.items():
            row = existing.get(pair)
            if row and row.status in {"HUMAN_VERIFIED", "REJECTED"}:
                continue
            if row is None:
                row = EquivalencyMatch(old_course_id=pair[0], new_course_id=pair[1],
                                       status=status, method=method, review_reasons=reasons,
                                       explanation=explanation)
                session.add(row); session.flush(); existing[pair] = row
            else:
                row.status, row.method = status, method
                row.review_reasons, row.explanation = reasons, explanation
                row.updated_at = _utc_now()
            if status == "AUTO_MATCHED":
                eq = session.get(Equivalency, row.equivalency_id) if row.equivalency_id else None
                if eq is None:
                    eq = Equivalency(
                        source_course_id=pair[0], target_course_id=pair[1]
                    )
                    session.add(eq); session.flush(); row.equivalency_id = eq.id
                eq.recognizes_history = True
                eq.prospective_registration_allowed = None
                eq.verification_status = "AUTO_MATCHED"
                eq.provenance = "ALGORITHMIC_MATCH"
                eq.notes = (
                    "Automatically accepted high-confidence historical equivalency; "
                    "an administrator may unverify or replace it."
                )
            elif status != "AUTO_MATCHED" and row.equivalency_id:
                session.execute(delete(Equivalency).where(Equivalency.id == row.equivalency_id))
                row.equivalency_id = None

        for pair, row in existing.items():
            if row.status not in {"HUMAN_VERIFIED", "REJECTED"} and pair not in proposed:
                if row.equivalency_id:
                    session.execute(delete(Equivalency).where(Equivalency.id == row.equivalency_id))
                session.delete(row)
        session.flush()
        return self.summary(session, old, new)

    def verify(self, session: Session, match_id: int, *, old_course_id: int | None = None,
               new_course_id: int | None = None, verified_by: str = "LOCAL_ADMIN") -> EquivalencyMatch:
        original = session.get(EquivalencyMatch, match_id)
        if original is None:
            raise ValueError("Match suggestion not found")
        old_id, new_id = old_course_id or original.old_course_id, new_course_id or original.new_course_id
        self._validate_pair(session, old_id, new_id)
        row = original
        if (old_id, new_id) != (original.old_course_id, original.new_course_id):
            if original.equivalency_id:
                session.execute(delete(Equivalency).where(
                    Equivalency.id == original.equivalency_id
                ))
                original.equivalency_id = None
            original.status, original.decided_at = "REJECTED", _utc_now()
            original.verified_by = verified_by
            row = session.scalar(select(EquivalencyMatch).where(
                EquivalencyMatch.old_course_id == old_id, EquivalencyMatch.new_course_id == new_id))
            if row and row.status == "REJECTED":
                raise ValueError("The selected pair was previously rejected")
            if row is None:
                row = EquivalencyMatch(old_course_id=old_id, new_course_id=new_id,
                    status="NEEDS_REVIEW", method="MANUAL_SELECTION", review_reasons=[],
                    explanation="Administrator selected a different course pair.")
                session.add(row); session.flush()
        conflicts = session.scalars(select(EquivalencyMatch).where(
            EquivalencyMatch.status == "HUMAN_VERIFIED", EquivalencyMatch.id != row.id,
            or_(EquivalencyMatch.old_course_id == old_id,
                EquivalencyMatch.new_course_id == new_id))).all()
        if conflicts:
            raise ValueError("A selected course already has a human-verified match")
        eq = session.get(Equivalency, row.equivalency_id) if row.equivalency_id else None
        if eq is None:
            eq = session.scalar(select(Equivalency).where(
                Equivalency.source_course_id == old_id, Equivalency.target_course_id == new_id))
        if eq is None:
            eq = Equivalency(source_course_id=old_id, target_course_id=new_id)
            session.add(eq); session.flush()
        session.execute(delete(TransitionCourseDisposition).where(
            TransitionCourseDisposition.old_course_id == old_id
        ))
        eq.recognizes_history = True
        eq.prospective_registration_allowed = None
        eq.verification_status = "HUMAN_VERIFIED"
        eq.provenance = "LOCAL_HUMAN_VERIFICATION"
        eq.notes = "Locally verified correspondence; not documented as official university approval."
        row.equivalency_id, row.status, row.method = eq.id, "HUMAN_VERIFIED", "HUMAN_VERIFICATION"
        now = _utc_now()
        row.verified_by, row.decided_at, row.updated_at = verified_by, now, now
        return row

    def reject(self, session: Session, match_id: int, rejected_by: str = "LOCAL_ADMIN") -> EquivalencyMatch:
        row = session.get(EquivalencyMatch, match_id)
        if row is None:
            raise ValueError("Match suggestion not found")
        if row.equivalency_id:
            session.execute(delete(Equivalency).where(Equivalency.id == row.equivalency_id))
            row.equivalency_id = None
        row.status, row.verified_by = "REJECTED", rejected_by
        row.decided_at = row.updated_at = _utc_now()
        return row

    @staticmethod
    def _validate_pair(session: Session, old_id: int, new_id: int) -> None:
        old, new = session.get(CourseRecord, old_id), session.get(CourseRecord, new_id)
        if not old or not new or old.curriculum.version != "OLD" or new.curriculum.version != "NEW":
            raise ValueError("A match must pair an OLD course with a NEW course")

    @staticmethod
    def summary(session: Session, old=None, new=None) -> dict:
        rows = list(session.scalars(select(EquivalencyMatch)))
        if old is None or new is None:
            courses = list(session.scalars(select(CourseRecord).where(
                CourseRecord.curriculum.has(CurriculumRevision.active.is_(True)))))
            old = [c for c in courses if c.curriculum.version == "OLD"]
            new = [c for c in courses if c.curriculum.version == "NEW"]
        active_rows = [r for r in rows if r.status != "REJECTED"]
        dispositions = list(session.scalars(select(TransitionCourseDisposition)))
        disposed_old = {row.old_course_id for row in dispositions}
        accepted = list(session.scalars(select(Equivalency)))
        matched_old = (
            {r.old_course_id for r in active_rows}
            | disposed_old
            | {row.source_course_id for row in accepted}
        )
        matched_new = (
            {r.new_course_id for r in active_rows}
            | {row.target_course_id for row in accepted}
        )
        ambiguous = sum("MULTIPLE_CANDIDATES" in (r.review_reasons or [])
                        for r in active_rows)
        return {
            "automatic_matches": sum(r.status == "AUTO_MATCHED" for r in rows),
            "needs_review": sum(r.status == "NEEDS_REVIEW" for r in rows),
            "verified": sum(r.status == "HUMAN_VERIFIED" for r in rows),
            "rejected": sum(r.status == "REJECTED" for r in rows),
            "legacy_only": sum(
                row.disposition == "LEGACY_CREDIT_ONLY" for row in dispositions
            ),
            "unmatched_old": sum(c.id not in matched_old for c in old),
            "unmatched_new": sum(c.id not in matched_new for c in new),
            "ambiguous_candidates": ambiguous,
        }

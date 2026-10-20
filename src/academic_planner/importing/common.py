from __future__ import annotations

import re
from pathlib import Path

COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,6}\s*[- ]?\s*\d{3,4}[A-Z]?)\b", re.I)


def normalize_code(value: object) -> str:
    text = str(value or "").strip().upper()
    match = COURSE_CODE_RE.search(text)
    return re.sub(r"[\s-]+", "", match.group(1)) if match else ""


def parse_ects(value: object) -> int | None:
    if isinstance(value, (int, float)) and float(value).is_integer():
        return int(value)
    match = re.search(r"(?<!\d)(\d{1,2})(?:\.0)?(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


def revision_for(path: Path, digest: str | None = None) -> str:
    return f"{path.stem}:{(digest or '')[:12]}".rstrip(":")[:60]


def classify_course(title: str, code: str) -> tuple[str, bool]:
    value = f"{title} {code}".lower()
    if "training" in value or "internship" in value:
        return "TRAINING", False
    if "final project" in value or "final year project" in value or re.search(r"\bfyp\b", value):
        return "FINAL_PROJECT", True
    if re.search(r"(?:\+|with)\s*(?:laboratory|lab)\b", value):
        return "COURSE_WITH_LAB", False
    if "laboratory" in value or re.search(r"\blab\b", value):
        return "LAB", False
    if "language" in value or "anglais" in value or "fran[cç]ais" in value:
        return "LANGUAGE", False
    return "COURSE", False


def training_semester(title: str) -> str | None:
    value = title.lower()
    if not ("training" in value or "internship" in value): return None
    if re.search(r"\b(?:ii|2)\b", value): return "TRAINING_2"
    return "TRAINING_1"


def language_track(title: str) -> str | None:
    value = title.lower()
    if re.search(r"\b(english|anglais)\b", value): return "EN"
    if re.search(r"\b(french|fran[cç]ais|francaise?)\b", value): return "FR"
    return None


def parse_prerequisite_text(text: str) -> tuple[tuple[str, ...], str, bool]:
    raw = " ".join(str(text or "").split())
    if not raw or raw.lower() in {"none", "nil", "n/a", "-", "—"}:
        return (), "AND", False
    codes = tuple(dict.fromkeys(normalize_code(m.group(1)) for m in COURSE_CODE_RE.finditer(raw)))
    has_or = bool(re.search(r"\b(or|ou)\b|/", raw, re.I))
    has_and = bool(re.search(r"\b(and|et)\b|[,+&]", raw, re.I))
    logic = "OR" if has_or and not has_and else "AND"
    residue = COURSE_CODE_RE.sub("", raw)
    residue = re.sub(r"\b(pre[- ]?requisite|prerequisite|pr)\b|[()\[\]:;,/+&-]", " ", residue, flags=re.I)
    residue = re.sub(r"\b(and|or|et|ou)\b", " ", residue, flags=re.I)
    review_words = bool(re.search(r"\b(approval|permission|equivalent|minimum|department)\b", residue, re.I))
    # A title followed by one explicit code is safely resolvable. Several codes
    # without a documented connector remain ambiguous; they may be alternatives
    # grouped by department rather than an implicit all-of rule.
    ambiguous = ((has_or and has_and) or not codes or review_words
                 or (len(codes) > 1 and not has_and and not has_or))
    return codes, logic, ambiguous

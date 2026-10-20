from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pypdf import PdfReader

from .common import COURSE_CODE_RE, classify_course, language_track, normalize_code, parse_prerequisite_text, revision_for, training_semester
from .models import ParsedCourse, ParsedCurriculum, ParsedLabRelationship, ParsedPrerequisite, SourceReference
from academic_planner.policies.graduation_role import graduation_role_for

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


def term_to_placement(term: int) -> tuple[int, str]:
    if term not in range(1, 11): raise ValueError("reference term must be I through X")
    return (term + 1) // 2, "FALL" if term % 2 else "SPRING"


class NewCurriculumPdfParser:
    def parse(self, file_path: str | Path) -> ParsedCurriculum:
        path = Path(file_path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result = ParsedCurriculum("NEW", path.name, revision_for(path, digest))
        reader = PdfReader(path)
        stated_terms: dict[int, int] = {}
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text(extraction_mode="layout") or page.extract_text() or ""
            for roman, credits in re.findall(r"\bTerm\s+([IVX]+)\s*,\s*(\d+)\s*c(?:r)?\b", text, re.I):
                if roman.upper() in ROMAN: stated_terms[ROMAN[roman.upper()]] = int(credits)
            raw_lines = text.splitlines()
            split_at = self._column_split(raw_lines)
            columns = ([line[:split_at] for line in raw_lines],
                       [line[split_at:] for line in raw_lines]) if split_at else (raw_lines,)
            for column_number, column in enumerate(columns, 1):
                current_term: int | None = None
                pending: tuple[str, int, int] | None = None
                def flush():
                    nonlocal pending
                    if pending is None: return
                    line, line_number, term = pending
                    parsed = self._course_line(line, term, result.source_document,
                                               page_number, line_number)
                    pending = None
                    if parsed is None: return
                    courses, prerequisites = parsed
                    result.courses.extend(courses)
                    result.prerequisite_rules.extend(prerequisites)
                    lab = re.search(r"\b(?:mandatory\s+)?Lab\s*\(\s*([A-Z]{2,6}\s*[- ]?\s*\d{3,4}[A-Z]?)\s*\)", line, re.I)
                    if lab:
                        for course in courses:
                            result.lab_relationships.append(ParsedLabRelationship(
                                course.code, normalize_code(lab.group(1)), True, course.source))
                for line_number, raw in enumerate(column, 1):
                    line = " ".join(raw.split())
                    if not line: continue
                    heading = self._term_heading(line)
                    if heading is not None:
                        flush(); current_term = heading; continue
                    if self._starts_course(line):
                        flush()
                        if current_term is not None: pending = (line, line_number, current_term)
                    elif pending is not None:
                        previous, first_line, term = pending
                        if (not re.search(r"\d+\s*c\s*r\b", previous, re.I)
                                or previous.count("(") > previous.count(")")
                                or re.match(r"^Pr\s*\(", line, re.I)):
                            pending = (previous + " " + line, first_line, term)
                flush()
            stated = re.search(r"(?:total|curriculum)\s*(?:credits|ects)?\s*[:=]?\s*(\d{2,3})\s*(?:ects|credits)?", text, re.I)
            if stated: result.stated_total_ects = int(stated.group(1))
        if len(stated_terms) == 10: result.stated_total_ects = sum(stated_terms.values())
        result.degree_requirements = [
            course.code for course in result.courses
            if graduation_role_for(
                course.ects, course.is_fyp, course.course_type
            ) == "MANDATORY"
        ]
        return result

    @staticmethod
    def _column_split(lines: list[str]) -> int | None:
        for line in lines:
            matches = list(re.finditer(r"\bTerm\s+(?:I{1,3}|IV|V|VI{0,3}|IX|X)\b", line, re.I))
            if len(matches) >= 2: return matches[1].start()
        return None

    @staticmethod
    def _starts_course(line: str) -> bool:
        return bool(re.match(
            r"^[A-Z]{2,6}\s*\d{3,4}(?:\s*/\s*[A-Z]{2,6}\s*\d{3,4})?"
            r"(?:\s*[-,\u2013\u2014\ufffd]|(?=\s+[A-Za-z]))",
            line, re.I))

    @staticmethod
    def _term_heading(line: str) -> int | None:
        match = re.search(r"\b(?:term|semester|semestre)\s*(I{1,3}|IV|V|VI{0,3}|IX|X|10|[1-9])\b", line, re.I)
        if not match: return None
        token = match.group(1).upper()
        return int(token) if token.isdigit() else ROMAN.get(token)

    def _course_line(self, line: str, term: int | None, document: str, page: int, line_number: int):
        composite = re.match(
            r"^([A-Z]{2,6}\s*\d{3,4})\s*/\s*([A-Z]{2,6}\s*\d{3,4})\s*[-,]",
            line, re.I)
        if composite:
            code_matches = [composite.group(1), composite.group(2)]
            match_start, match_end = composite.start(), composite.end() - 1
        else:
            match = COURSE_CODE_RE.search(line)
            if not match: return None
            code_matches = [match.group(1)]
            match_start, match_end = match.start(), match.end()
        # Header examples such as "Course Code" cannot match the required 3 digits.
        before, after = line[:match_start].strip(" |-,\u2013\u2014\ufffd"), line[match_end:].strip(" |-,\u2013\u2014\ufffd")
        prereq_match = re.search(r"\bPr\s*\(([^)]*)\)", line, re.I)
        prereq_text = prereq_match.group(0) if prereq_match else ""
        clean_after = re.sub(r"\bPr\s*\([^)]*\)", "", after, flags=re.I).strip(" |-")
        clean_before = re.sub(r"\bPr\s*\([^)]*\)", "", before, flags=re.I).strip(" |-")
        clean_after = re.sub(r"\b(?:mandatory\s+)?Lab\s*\([^)]*\)", "", clean_after, flags=re.I).strip(" |-")
        clean_before = re.sub(r"\b(?:mandatory\s+)?Lab\s*\([^)]*\)", "", clean_before, flags=re.I).strip(" |-")
        numbers = list(re.finditer(r"(?<!\d)(\d{1,2})(?:\.0)?(?!\d)", clean_after))
        ects_match = next((item for item in reversed(numbers) if 0 <= int(item.group(1)) <= 30), None)
        if ects_match:
            ects = int(ects_match.group(1)); title_after = clean_after[:ects_match.start()].strip(" |-:,\u2013\u2014\ufffd")
        else:
            numbers = list(re.finditer(r"(?<!\d)(\d{1,2})(?:\.0)?(?!\d)", clean_before))
            ects_match = next((item for item in reversed(numbers) if 0 <= int(item.group(1)) <= 30), None)
            if not ects_match: return None
            ects = int(ects_match.group(1)); clean_before = clean_before[:ects_match.start()].strip()
            title_after = ""
        title = title_after or clean_before
        title = re.sub(r"^(?:mandatory|elective)\s+", "", title, flags=re.I).strip(" |-:,\u2013\u2014\ufffd")
        if not title: return None
        special = training_semester(title)
        if special:
            semester = special
            # Training headings are sometimes outside Terms I-X. Preserve a documented
            # adjacent term year, but never fabricate one when there is no context.
            if term is None: return None
            year, _ = term_to_placement(term)
        else:
            if term is None: return None
            year, semester = term_to_placement(term)
        source = SourceReference(document, f"page {page}, extracted line {line_number}")
        normalized_codes = [normalize_code(value) for value in code_matches]
        course_type, is_fyp = classify_course(title, normalized_codes[0])
        explicit_tracks: list[str | None] = [None] * len(normalized_codes)
        if len(normalized_codes) == 2 and "english" in title.lower() and "french" in title.lower():
            explicit_tracks = ["EN", "FR"]
        courses = [ParsedCourse(code, title, ects, year, semester, source,
            course_type, is_fyp, explicit_tracks[index] or language_track(title))
            for index, code in enumerate(normalized_codes)]
        prerequisites = []
        if prereq_text:
            codes, logic, ambiguous = parse_prerequisite_text(prereq_text)
            prerequisites = [ParsedPrerequisite(code, codes, logic, prereq_text, source, ambiguous)
                             for code in normalized_codes]
        return courses, prerequisites

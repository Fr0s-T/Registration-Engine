from __future__ import annotations

import hashlib
import re
from pathlib import Path

from openpyxl import load_workbook

from .common import classify_course, language_track, normalize_code, parse_ects, parse_prerequisite_text, revision_for, training_semester
from .models import ParsedCourse, ParsedCurriculum, ParsedPrerequisite, SourceReference
from academic_planner.policies.graduation_role import graduation_role_for


class OldCurriculumExcelParser:
    """Header-driven parser for the OLD curriculum workbook.

    It intentionally refuses to infer academic facts from titles when the workbook has
    not established a year/semester context.
    """
    HEADER_ALIASES = {
        "code": ("course code", "code", "course no", "course number"),
        "title": ("course title", "course name", "title", "subject"),
        "ects": ("ects", "credits", "credit", "crdts", "crd", "cr."),
        "prerequisite": ("pre-requisite", "prerequisite", "pre requisite", "prerequisites"),
        "year": ("academic year", "year"),
        "semester": ("semester",),
        "term": ("term", "reference term"),
        "lab": ("associated lab", "lab", "laboratory"),
    }

    def parse(self, file_path: str | Path) -> ParsedCurriculum:
        path = Path(file_path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result = ParsedCurriculum("OLD", path.name, revision_for(path, digest))
        workbook = load_workbook(path, data_only=True, read_only=True)
        for sheet in workbook.worksheets:
            self._parse_sheet(sheet, result)
        result.degree_requirements = [
            course.code for course in result.courses
            if graduation_role_for(
                course.ects, course.is_fyp, course.course_type
            ) == "MANDATORY"
        ]
        return result

    def _parse_sheet(self, sheet, result: ParsedCurriculum) -> None:
        rows = list(sheet.iter_rows(values_only=True))
        header_index, columns = self._find_header(rows)
        if header_index is None:
            if any(normalize_code(cell) for row in rows for cell in row):
                result.validation_warnings.append(f"Sheet {sheet.title!r} contains course-like codes but no recognized header row.")
            return
        context_year = self._context_year(sheet.title)
        context_semester = self._context_semester(sheet.title)
        for row_number, values in enumerate(rows[header_index + 1:], header_index + 2):
            joined = " ".join(str(v) for v in values if v is not None)
            context_year = self._context_year(joined) or context_year
            context_semester = self._context_semester(joined) or context_semester
            raw_code = str(self._cell(values, columns.get("code")) or "").strip()
            codes = self._course_codes(raw_code)
            if not codes:
                if re.search(r"total\s+(?:credits|ects)", joined, re.I):
                    numbers = [parse_ects(value) for value in values]
                    result.stated_total_ects = next((number for number in reversed(numbers) if number is not None), result.stated_total_ects)
                continue
            title = str(self._cell(values, columns.get("title")) or "").strip()
            ects = parse_ects(self._cell(values, columns.get("ects")))
            term = self._parse_term(self._cell(values, columns.get("term")))
            year = self._parse_year(self._cell(values, columns.get("year"))) or (
                (term + 1) // 2 if term else context_year)
            semester = self._parse_semester(self._cell(values, columns.get("semester"))) or (
                "FALL" if term and term % 2 else "SPRING" if term else context_semester)
            special = training_semester(title)
            semester = special or semester
            source = SourceReference(result.source_document, f"sheet {sheet.title}, row {row_number}")
            missing = []
            if not title: missing.append("title")
            if ects is None: missing.append("ECTS")
            if year is None: missing.append("reference year")
            if semester is None: missing.append("semester")
            if missing:
                result.unresolved_items.append(f"{source.location}: {raw_code} is missing {', '.join(missing)}; row was not imported.")
                continue
            course_type, is_fyp = classify_course(title, codes[0][0])
            for code, track in codes:
                result.courses.append(ParsedCourse(code, title, ects, year, semester, source,
                    course_type, is_fyp, track or language_track(title)))
            raw_prereq = str(self._cell(values, columns.get("prerequisite")) or "").strip()
            prereq_codes, logic, ambiguous = parse_prerequisite_text(raw_prereq)
            if raw_prereq and raw_prereq.lower() not in {"none", "nil", "n/a", "-", "—"}:
                for code, _track in codes:
                    result.prerequisite_rules.append(ParsedPrerequisite(code, prereq_codes, logic, raw_prereq, source, ambiguous))
            raw_lab = str(self._cell(values, columns.get("lab")) or "").strip()
            lab_code = normalize_code(raw_lab)
            if raw_lab and not lab_code:
                result.unresolved_items.append(f"{source.location}: lab association for {codes[0][0]} is ambiguous: {raw_lab}")
            elif lab_code:
                from .models import ParsedLabRelationship
                result.lab_relationships.append(ParsedLabRelationship(codes[0][0], lab_code, True, source))

    def _find_header(self, rows):
        best = (None, {})
        for index, row in enumerate(rows[:50]):
            mapping = {}
            for column, cell in enumerate(row):
                text = re.sub(r"\s+", " ", str(cell or "").strip().lower())
                for key, aliases in self.HEADER_ALIASES.items():
                    if text in aliases or any(alias in text for alias in aliases if len(alias) > 5):
                        mapping.setdefault(key, column)
            if "code" in mapping and "title" in mapping and "ects" in mapping:
                return index, mapping
            if len(mapping) > len(best[1]): best = (index, mapping)
        return (None, {})

    @staticmethod
    def _cell(row, index): return row[index] if index is not None and index < len(row) else None

    @staticmethod
    def _context_year(value: str) -> int | None:
        match = re.search(r"(?:year|année|annee)\s*([1-5]|I{1,3}|IV|V)\b", str(value), re.I)
        if not match: return None
        token = match.group(1).upper()
        return {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}.get(token, int(token) if token.isdigit() else None)

    @staticmethod
    def _context_semester(value: str) -> str | None:
        text = str(value).lower()
        if re.search(r"\b(fall|autumn|semester\s*1|semestre\s*1)\b", text): return "FALL"
        if re.search(r"\b(spring|semester\s*2|semestre\s*2)\b", text): return "SPRING"
        return None

    def _parse_year(self, value) -> int | None:
        if isinstance(value, (int, float)) and int(value) in range(1, 6): return int(value)
        return self._context_year(str(value or ""))

    def _parse_semester(self, value) -> str | None:
        text = str(value or "").strip()
        if text in {"1", "1.0"}: return "FALL"
        if text in {"2", "2.0"}: return "SPRING"
        return self._context_semester(text)

    @staticmethod
    def _parse_term(value) -> int | None:
        if isinstance(value, (int, float)) and int(value) in range(1, 11): return int(value)
        match = re.fullmatch(r"\s*(10|[1-9])\s*", str(value or ""))
        return int(match.group(1)) if match else None

    @staticmethod
    def _course_codes(value: str) -> list[tuple[str, str | None]]:
        compact = re.sub(r"\s+", "", value.upper())
        alternative = re.fullmatch(r"([A-Z]{2,6})/([A-Z]{2,6})(\d{3,4}[A-Z]?)", compact)
        if alternative:
            left, right, suffix = alternative.groups()
            tracks = {"CLEN": "EN", "CLFR": "FR"}
            return [(left + suffix, tracks.get(left)), (right + suffix, tracks.get(right))]
        code = normalize_code(compact)
        return [(code, None)] if code else []

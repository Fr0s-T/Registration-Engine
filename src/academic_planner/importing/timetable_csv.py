from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from academic_planner.database.models import (
    ActiveTerm, CourseRecord, CurriculumRevision, MeetingRecord, Offering,
    SectionRecord, SourceDocument,
)


WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
LANGUAGES = {"english": "EN", "french": "FR"}

# The 2026–27 rollout uses NEW requirements for Years 3–4 and OLD for Year 5.
COURSE_MAPPING = {
    (3, "analog electronics ii"): ("NEW", "CCE451"),
    (3, "computer architecture"): ("NEW", "CCE441"),
    (3, "data communication"): ("NEW", "CCE430"),
    (3, "database"): ("NEW", "CCE440"),
    (3, "digital signal processing"): ("NEW", "CCE450"),
    (4, "analog communication"): ("NEW", "CCE551"),
    (4, "client side scripting"): ("NEW", "CCE560"),
    (4, "cryptography and network security"): ("NEW", "CCE540"),
    (4, "microprocessors"): ("NEW", "CCE552"),
    (4, "microwaves"): ("NEW", "CCE541"),
    (4, "routing and switching"): ("NEW", "CCE550"),
    (5, "data analytics"): ("OLD", "ELCC923"),
    (5, "fiber optics"): ("OLD", "ELCC919"),
    (5, "image processing"): ("OLD", "ELBC901"),
    (5, "mobile networks"): ("OLD", "ELCC914"),
    (5, "multimedia and qos"): ("OLD", "ELCC916"),
}


def _canonical_title(value: str) -> str:
    value = value.casefold().strip()
    value = value.replace("&", " and ")
    value = re.sub(r"\b(dsp)\b", "digital signal processing", value)
    value = re.sub(r"\blaboratory\b|\blab\b", " ", value)
    value = re.sub(r"\banalog electronics\b(?!\s+ii)", "analog electronics ii", value)
    value = re.sub(r"\banalog communications\b", "analog communication", value)
    value = re.sub(r"\bmicroprocessor\b", "microprocessors", value)
    value = re.sub(r"\bmultimedia\s+and\s+quality\s+of\s+service\b", "multimedia and qos", value)
    value = re.sub(r"[^\w]+", " ", value)
    return " ".join(value.split())


def _minutes(value: str) -> int:
    hours, minutes = (int(part) for part in value.split(":"))
    result = hours * 60 + minutes
    if not 0 <= result <= 1440:
        raise ValueError(f"Invalid timetable time: {value}")
    return result


@dataclass(frozen=True)
class ParsedTimetableMeeting:
    source_page: int
    year: int
    language_track: str
    weekday: int
    start_minute: int
    end_minute: int
    source_course: str
    canonical_course: str
    component: str
    group: str | None
    instructor: str | None
    room: str | None
    notes: str | None


@dataclass(frozen=True)
class TimetableImportResult:
    rows_read: int
    offerings_replaced: int
    offerings_inserted: int
    sections_inserted: int
    meetings_inserted: int
    unresolved_rows: tuple[dict, ...]


class ParsedTimetableCsvImporter:
    required_headers = {
        "source_pdf_page", "year", "language", "day", "start", "end",
        "course", "kind", "group", "instructor", "room", "notes",
    }

    def parse(self, path: str | Path) -> list[ParsedTimetableMeeting]:
        path = Path(path)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = self.required_headers - set(reader.fieldnames or ())
            if missing:
                raise ValueError(f"Timetable CSV is missing columns: {', '.join(sorted(missing))}")
            output = []
            for line_number, row in enumerate(reader, start=2):
                try:
                    year = int(row["year"])
                    language = LANGUAGES[row["language"].strip().casefold()]
                    weekday = WEEKDAYS[row["day"].strip().casefold()]
                    start, end = _minutes(row["start"]), _minutes(row["end"])
                    if year not in {3, 4, 5} or start >= end:
                        raise ValueError("year must be 3–5 and start must precede end")
                    kind = row["kind"].strip().upper()
                    if kind not in {"LECTURE", "LAB"}:
                        raise ValueError("kind must be Lecture or Lab")
                    output.append(ParsedTimetableMeeting(
                        int(row["source_pdf_page"]), year, language, weekday, start, end,
                        row["course"].strip(), _canonical_title(row["course"]), kind,
                        row["group"].strip() or None, row["instructor"].strip() or None,
                        row["room"].strip() or None, row["notes"].strip() or None,
                    ))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid timetable row {line_number}: {exc}") from exc
        if not output:
            raise ValueError("Timetable CSV contains no meeting rows")
        return output

    def replace_years_3_to_5(self, session: Session, path: str | Path) -> TimetableImportResult:
        path = Path(path)
        rows = self.parse(path)
        active = session.get(ActiveTerm, 1)
        if active is None:
            raise ValueError("An active academic term must be configured")

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        document = session.scalar(select(SourceDocument).where(SourceDocument.sha256 == digest))
        if document is None:
            document = SourceDocument(filename=path.name, kind="TIMETABLE", sha256=digest,
                status="VALIDATED", notes="Parsed Year 3–5 timetable source.",
                storage_path=str(path))
            session.add(document); session.flush()

        courses = session.scalars(select(CourseRecord).join(CurriculumRevision).where(
            CurriculumRevision.active.is_(True))).all()
        by_identity = {(row.curriculum.version, row.code.upper()): row for row in courses}
        resolved, unresolved = [], []
        for row in rows:
            mapping = COURSE_MAPPING.get((row.year, row.canonical_course))
            course = by_identity.get(mapping) if mapping else None
            if course is None:
                unresolved.append({
                    "page": row.source_page, "year": row.year,
                    "language_track": row.language_track, "course": row.source_course,
                    "reason": "NO_CATALOG_COURSE_MAPPING",
                })
            else:
                resolved.append((course, row))

        existing_ids = list(session.scalars(select(Offering.id).join(CourseRecord).where(
            Offering.academic_year_start == active.academic_year_start,
            Offering.semester == active.semester,
            CourseRecord.reference_year.in_([3, 4, 5]),
        )))
        replaced = len(existing_ids)
        if existing_ids:
            session.execute(delete(Offering).where(Offering.id.in_(existing_ids)))
            session.flush()

        grouped: dict[tuple[int, str], list[ParsedTimetableMeeting]] = {}
        course_rows: dict[int, CourseRecord] = {}
        for course, row in resolved:
            grouped.setdefault((course.id, row.language_track), []).append(row)
            course_rows[course.id] = course

        section_count = meeting_count = 0
        for (course_id, track), meeting_rows in sorted(grouped.items(),
                key=lambda item: (course_rows[item[0][0]].reference_year,
                                  item[0][1], course_rows[item[0][0]].code)):
            course = course_rows[course_id]
            offering = Offering(course_id=course_id,
                academic_year_start=active.academic_year_start, semester=active.semester,
                language_track=track, provenance="TIMETABLE_CSV_IMPORT",
                verification_status="SOURCE_IMPORTED", source_document_id=document.id)
            session.add(offering); session.flush()
            lectures = [row for row in meeting_rows if row.component == "LECTURE"]
            labs = [row for row in meeting_rows if row.component == "LAB"]
            lab_groups: list[tuple[str, list[ParsedTimetableMeeting]]] = []
            for index, lab in enumerate(labs, start=1):
                # Unlabelled time slots remain separate choices; grouping them would
                # incorrectly require a student to attend both.
                key = lab.group or f"Unspecified {index}"
                existing = next((item for item in lab_groups if item[0] == key), None)
                if existing is None:
                    lab_groups.append((key, [lab]))
                else:
                    existing[1].append(lab)
            bundles = lab_groups or [("A", [])]
            for bundle_index, (group_name, lab_rows) in enumerate(bundles, start=1):
                bundle_key = f"{track}-{bundle_index}"
                if lectures:
                    section_count += 1
                    section = SectionRecord(offering_id=offering.id,
                        code=f"{course.code}-{track}-LEC-{bundle_index}", component="LECTURE",
                        bundle_key=bundle_key, campus="IUL",
                        room=next((row.room for row in lectures if row.room), None),
                        instructor=" / ".join(dict.fromkeys(
                            row.instructor for row in lectures if row.instructor)) or None,
                        notes="; ".join(dict.fromkeys(
                            row.notes for row in lectures if row.notes)) or None)
                    session.add(section); session.flush()
                    for item in lectures:
                        session.add(MeetingRecord(section_id=section.id, weekday=item.weekday,
                            start_minute=item.start_minute, end_minute=item.end_minute))
                        meeting_count += 1
                if lab_rows:
                    section_count += 1
                    section = SectionRecord(offering_id=offering.id,
                        code=f"{course.code}-{track}-LAB-{bundle_index}", component="LAB",
                        bundle_key=bundle_key, campus="IUL",
                        room=next((row.room for row in lab_rows if row.room), None),
                        instructor=" / ".join(dict.fromkeys(
                            row.instructor for row in lab_rows if row.instructor)) or None,
                        notes=(f"Source group: {group_name}. " + "; ".join(dict.fromkeys(
                            row.notes for row in lab_rows if row.notes))).strip())
                    session.add(section); session.flush()
                    for item in lab_rows:
                        session.add(MeetingRecord(section_id=section.id, weekday=item.weekday,
                            start_minute=item.start_minute, end_minute=item.end_minute))
                        meeting_count += 1

        document.status = "IMPORTED"
        document.notes = (f"Active Fall timetable baseline for Years 3–5; "
                          f"{len(grouped)} track-specific offerings imported, "
                          f"{len(unresolved)} source rows unresolved.")
        session.flush()
        return TimetableImportResult(len(rows), replaced, len(grouped), section_count,
                                     meeting_count, tuple(unresolved))

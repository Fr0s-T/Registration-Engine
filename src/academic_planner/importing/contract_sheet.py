"""Parser and importer for the official CCE graduation contract sheet.

The PDF is a four-column layout, so ordinary text extraction interleaves unrelated
rows.  This parser uses the source coordinates to recover course codes and credits,
then assigns rows to the labelled contract sections on the page.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from academic_planner.database.models import (
    CourseRecord, CourseRequirementGroupRecognition, CurriculumRevision,
    DegreeContract, RequirementGroupCourseRecord, RequirementGroupRecord,
    SourceDocument, StudentRecord,
)


@dataclass(frozen=True)
class ParsedMembership:
    course_code: str
    ects: int
    membership_type: str = "REQUIRED"
    language_track: str | None = None
    source_locator: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class ParsedRequirementGroup:
    code: str
    title: str
    required_ects: int
    rule_type: str
    display_order: int
    parent_code: str | None = None
    memberships: tuple[ParsedMembership, ...] = ()


@dataclass(frozen=True)
class ParsedDegreeContract:
    program_code: str
    title: str
    graduation_ects_target: int
    effective_academic_year: str
    groups: tuple[ParsedRequirementGroup, ...]


class CceContractSheetParser:
    """Coordinate-aware parser for the Fall 2026 CCE contract sheet."""

    _code = re.compile(r"^(?:GER|MAT|STA|PHY|GRD|CHM|CSC|CCE)\d{3}$")
    _credit = re.compile(r"^(\d+)\s*cr\.$", re.IGNORECASE)
    _columns = ((14.8, 151.5), (181.4, 318.1), (347.9, 484.6), (514.5, 651.2))
    _title_x = (38.9, 205.5, 372.1, 538.7)

    def parse(self, path: Path) -> ParsedDegreeContract:
        reader = PdfReader(str(path))
        if len(reader.pages) != 1:
            raise ValueError("CCE contract parser expects a one-page contract sheet")
        fragments: list[tuple[float, float, str]] = []

        def visit(text, _cm, tm, _font, _size):
            value = text.strip()
            if value:
                fragments.append((float(tm[4]), float(tm[5]), value))

        page_text = reader.pages[0].extract_text(visitor_text=visit) or ""
        if "total number of credits needed to graduate is 300" not in page_text.lower():
            raise ValueError("contract sheet does not declare the expected 300-ECTS target")

        courses: dict[str, tuple[int, int, float]] = {}
        for column, (code_x, credit_x) in enumerate(self._columns):
            codes = [
                (value, y) for x, y, value in fragments
                if abs(x - code_x) < 1.0 and self._code.fullmatch(value)
            ]
            credits = [
                (int(match.group(1)), y)
                for x, y, value in fragments
                if abs(x - credit_x) < 1.0
                and (match := self._credit.fullmatch(value))
            ]
            for code, y in codes:
                candidates = [(abs(y - cy), credit) for credit, cy in credits if abs(y - cy) <= 5]
                if not candidates:
                    raise ValueError(f"could not locate source credit value for {code}")
                credit = min(candidates)[1]
                if code in courses:
                    raise ValueError(f"duplicate course code in contract sheet: {code}")
                courses[code] = (credit, column, y)

        def members(codes: list[str], *, kind="REQUIRED", tracks=None):
            missing = set(codes) - courses.keys()
            if missing:
                raise ValueError(f"contract sheet is missing expected course(s): {sorted(missing)}")
            tracks = tracks or {}
            return tuple(
                ParsedMembership(
                    code, courses[code][0], kind, tracks.get(code),
                    f"page 1, column {courses[code][1] + 1}, y={courses[code][2]:.1f}",
                    " ".join(
                        value for x, y, value in sorted(fragments)
                        if abs(x - self._title_x[courses[code][1]]) < 1.0
                        and abs(y - courses[code][2]) < 4.5
                        and not value.startswith("(PR:")
                    ) or code,
                )
                for code in codes
            )

        by_column = {
            column: [code for code, (_credit, col, _y) in courses.items() if col == column]
            for column in range(4)
        }
        ger = by_column[0]
        lang = [code for code in ger if courses[code][2] > 390]
        religion = [code for code in ger if 350 < courses[code][2] < 390]
        quantitative = [code for code in ger if 280 < courses[code][2] < 350]
        civic = [code for code in ger if 190 < courses[code][2] < 270]
        entrepreneurship = [code for code in ger if 125 < courses[code][2] < 190]
        health = [code for code in ger if courses[code][2] < 110]
        fundamental = [code for code in by_column[1] if courses[code][2] > 272.8]
        faculty = [code for code in by_column[1] if courses[code][2] < 272.8]
        emphasis = by_column[2]
        common = [code for code in by_column[3] if courses[code][2] > 276.6]
        capstone = [code for code in by_column[3] if courses[code][2] < 276.6]

        groups = (
            ParsedRequirementGroup("GER", "General Education Requirements", 29, "ALL_OF", 10),
            ParsedRequirementGroup("GER_LANGUAGE", "French or English skills", 4, "TRACK_CHOICE", 11, "GER",
                members(lang, kind="CANDIDATE", tracks={"GER221": "EN", "GER222": "FR"})),
            ParsedRequirementGroup("GER_RELIGION_ETHICS", "Religion, Human Rights and Ethics", 5, "ALL_OF", 12, "GER", members(religion)),
            ParsedRequirementGroup("GER_QUANT_CORE", "Quantitative Reasoning mandatory core", 4, "ALL_OF", 13, "GER", members(["CSC230"])),
            ParsedRequirementGroup("GER_QUANT_CHOICE", "Quantitative Reasoning choice", 2, "CREDIT_QUOTA", 14, "GER",
                members([code for code in quantitative if code != "CSC230"], kind="CANDIDATE")),
            ParsedRequirementGroup("GER_CIVIC", "Civic Engagement, culture and social", 4, "CREDIT_QUOTA", 15, "GER", members(civic, kind="CANDIDATE")),
            ParsedRequirementGroup("GER_ENTREPRENEURSHIP", "Entrepreneurship and Innovation", 6, "ALL_OF", 16, "GER", members(entrepreneurship)),
            ParsedRequirementGroup("GER_HEALTH", "Health, well-being and sustainability", 4, "CREDIT_QUOTA", 17, "GER", members(health, kind="CANDIDATE")),
            ParsedRequirementGroup("FUNDAMENTAL", "Fundamental Courses", 61, "ALL_OF", 20, memberships=members(fundamental)),
            ParsedRequirementGroup("FACULTY", "Faculty Requirements", 12, "ALL_OF", 30, memberships=members(faculty)),
            ParsedRequirementGroup("CCE", "Computer & Communication Engineering Emphasis", 135, "ALL_OF", 40, memberships=members(emphasis)),
            ParsedRequirementGroup("COMMON", "Common Emphasis CCE-BME", 45, "ALL_OF", 50, memberships=members(common)),
            ParsedRequirementGroup("CAPSTONE", "Capstone", 18, "PATHWAY", 60, memberships=members(capstone)),
        )
        self._validate(groups, courses)
        return ParsedDegreeContract(
            "CCE", "Bachelor of Engineering in Computer & Communication Engineering",
            300, "2026-2027", groups,
        )

    @staticmethod
    def _validate(groups, courses) -> None:
        roots = [group for group in groups if group.parent_code is None]
        if sum(group.required_ects for group in roots) != 300:
            raise ValueError("top-level contract groups do not total 300 ECTS")
        expected_roots = {"GER": 29, "FUNDAMENTAL": 61, "FACULTY": 12, "CCE": 135, "COMMON": 45, "CAPSTONE": 18}
        if {group.code: group.required_ects for group in roots} != expected_roots:
            raise ValueError("contract section totals differ from the official CCE structure")
        ger_children = [group for group in groups if group.parent_code == "GER"]
        if sum(group.required_ects for group in ger_children) != 29:
            raise ValueError("GER subgroups do not total 29 ECTS")
        fixed_or_path = [g for g in groups if g.rule_type in {"ALL_OF", "PATHWAY"} and g.memberships]
        for group in fixed_or_path:
            if sum(item.ects for item in group.memberships) != group.required_ects:
                raise ValueError(f"fixed group {group.code} does not match its source total")
        parsed_members = {item.course_code for group in groups for item in group.memberships}
        if parsed_members != set(courses):
            raise ValueError(f"unclassified contract courses: {sorted(set(courses) - parsed_members)}")


class DegreeContractImportService:
    """Strict, idempotent import of a parsed contract into the active NEW catalog."""

    def import_pdf(self, session: Session, path: Path, *, assign_active_students=True) -> DegreeContract:
        parsed = CceContractSheetParser().parse(path)
        revision = session.scalar(select(CurriculumRevision).where(
            CurriculumRevision.version == "NEW", CurriculumRevision.active.is_(True)
        ))
        if revision is None:
            raise ValueError("cannot import degree contract without an active NEW curriculum")
        digest = sha256(path.read_bytes()).hexdigest()
        document = session.scalar(select(SourceDocument).where(SourceDocument.sha256 == digest))
        if document is None:
            document = SourceDocument(
                filename=path.name, kind="DEGREE_CONTRACT", sha256=digest,
                status="IMPORTED", storage_path=str(path),
            )
            session.add(document)
            session.flush()
        else:
            document.kind = "DEGREE_CONTRACT"
            document.status = "IMPORTED"

        rows = list(session.scalars(select(CourseRecord).where(CourseRecord.curriculum_id == revision.id)))
        by_code = {row.code: row for row in rows}
        memberships = [item for group in parsed.groups for item in group.memberships]
        # The contract sheet is authoritative for course identity and ECTS.  It
        # is not an offering schedule, so imported missing definitions carry an
        # explicit unverified placement default used only by future projections.
        for item in memberships:
            if item.course_code in by_code:
                continue
            row = CourseRecord(
                curriculum_id=revision.id, code=item.course_code,
                title=item.title or item.course_code, ects=item.ects,
                reference_year=2, reference_semester="FALL", course_type="COURSE",
                is_fyp=False,
                notes=(
                    "Course identity and ECTS imported from the official degree "
                    "contract. Reference year/semester are unverified planning defaults."
                ),
                provenance="SOURCE_CONTRACT", verification_status="SOURCE_IMPORTED",
                source_document_id=document.id, source_locator=item.source_locator,
                graduation_role="NEEDS_REVIEW",
                graduation_role_basis="OFFICIAL_DEGREE_CONTRACT_GROUP",
            )
            session.add(row)
            session.flush()
            by_code[item.course_code] = row
        mismatched = sorted(
            f"{item.course_code} (PDF {item.ects}, DB {by_code[item.course_code].ects})"
            for item in memberships if by_code[item.course_code].ects != item.ects
        )
        if mismatched:
            raise ValueError("contract/catalog credit mismatch: " + "; ".join(mismatched))

        contract = session.scalar(select(DegreeContract).where(
            DegreeContract.curriculum_id == revision.id,
            DegreeContract.program_code == parsed.program_code,
            DegreeContract.effective_academic_year == parsed.effective_academic_year,
        ))
        if contract is None:
            contract = DegreeContract(
                curriculum_id=revision.id, program_code=parsed.program_code,
                title=parsed.title, graduation_ects_target=parsed.graduation_ects_target,
                effective_academic_year=parsed.effective_academic_year,
                source_document_id=document.id, verification_status="SOURCE_IMPORTED",
            )
            session.add(contract)
            session.flush()
        else:
            contract.title = parsed.title
            contract.graduation_ects_target = parsed.graduation_ects_target
            contract.source_document_id = document.id
            session.execute(delete(RequirementGroupRecord).where(
                RequirementGroupRecord.contract_id == contract.id
            ))
            session.flush()

        group_rows: dict[str, RequirementGroupRecord] = {}
        for group in parsed.groups:
            row = RequirementGroupRecord(
                contract_id=contract.id, code=group.code, title=group.title,
                required_ects=group.required_ects, rule_type=group.rule_type,
                display_order=group.display_order, source_locator="page 1",
                verification_status="SOURCE_IMPORTED",
            )
            session.add(row)
            session.flush()
            group_rows[group.code] = row
        for group in parsed.groups:
            row = group_rows[group.code]
            if group.parent_code:
                row.parent_id = group_rows[group.parent_code].id
            for item in group.memberships:
                session.add(RequirementGroupCourseRecord(
                    group_id=row.id, course_id=by_code[item.course_code].id,
                    contribution_ects=item.ects, membership_type=item.membership_type,
                    language_track=item.language_track,
                    source_locator=item.source_locator,
                ))
        session.flush()

        old_courses = list(session.scalars(
            select(CourseRecord).join(CurriculumRevision).where(
                CurriculumRevision.version == "OLD",
                CurriculumRevision.active.is_(True),
            )
        ))
        inferred_roots = {
            course.id: (
                "COMMON" if course.code.upper().startswith("ELBC")
                else "CCE" if course.code.upper().startswith("ELCC")
                else "GER" if course.code.upper().startswith("CLEN")
                else "GER" if course.code.upper() == "ELCM319"
                else None
            )
            for course in old_courses
        }
        for course in old_courses:
            root_code = inferred_roots[course.id]
            if root_code is None:
                continue
            session.add(CourseRequirementGroupRecognition(
                source_course_id=course.id,
                requirement_group_id=group_rows[root_code].id,
                recognition_scope="CATEGORY_CREDIT",
                verification_status="INFERRED_PROGRAM_STRUCTURE",
                provenance="OFFICIAL_CONTRACT_CATEGORY_INFERENCE",
                notes=(
                    "Broad OLD-to-NEW category credit inferred from the official "
                    "contract structure; this is not an exact course equivalency."
                ),
            ))
        if assign_active_students:
            for student in session.scalars(select(StudentRecord).where(
                StudentRecord.active.is_(True),
                StudentRecord.governing_curriculum_version == "NEW",
            )):
                student.degree_contract_id = contract.id
                student.graduation_credit_target = parsed.graduation_ects_target
        session.flush()
        return contract

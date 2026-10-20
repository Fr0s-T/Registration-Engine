from pathlib import Path

from sqlalchemy import func, select

import academic_planner.importing.contract_sheet as contract_sheet_module
from academic_planner.database.models import (
    CourseRecord,
    CourseRequirementGroupRecognition,
    DegreeContract,
    RequirementGroupCourseRecord,
    RequirementGroupRecord,
    StudentAttemptRecord,
)
from academic_planner.database.session import SessionLocal
from academic_planner.importing import CceContractSheetParser, DegreeContractImportService


# Minimal synthetic four-column layout that exercises every requirement group.
# Coordinates match the parser's format contract; no original PDF is required.
_LAYOUT = (
    (0, 410, "GER221", 4, "English Skills"),
    (0, 400, "GER222", 4, "French Skills"),
    (0, 380, "GER310", 3, "Human Rights"),
    (0, 370, "GER312", 2, "Ethics"),
    (0, 330, "CSC230", 4, "Computer Fundamentals"),
    (0, 310, "GER230", 2, "Quantitative Choice"),
    (0, 230, "GER224", 4, "Civic Engagement"),
    (0, 150, "GER225", 6, "Entrepreneurship"),
    (0, 90, "GER300", 4, "Health and Well-being"),
    (1, 400, "MAT901", 61, "Synthetic Fundamental Block"),
    (1, 200, "PHY901", 12, "Synthetic Faculty Block"),
    (2, 400, "CCE901", 135, "Synthetic Emphasis Block"),
    (3, 400, "CCE902", 45, "Synthetic Common Block"),
    (3, 200, "CCE903", 18, "Synthetic Capstone Block"),
)


class _SyntheticContractPage:
    def extract_text(self, visitor_text):
        for column, y, code, ects, title in _LAYOUT:
            code_x, credit_x = CceContractSheetParser._columns[column]
            title_x = CceContractSheetParser._title_x[column]
            visitor_text(code, None, (1, 0, 0, 1, code_x, y), None, 10)
            visitor_text(title, None, (1, 0, 0, 1, title_x, y), None, 10)
            visitor_text(
                f"{ects} cr.", None, (1, 0, 0, 1, credit_x, y), None, 10
            )
        return "The total number of credits needed to graduate is 300 credits (ECTS)."


class _SyntheticContractReader:
    def __init__(self, _path):
        self.pages = [_SyntheticContractPage()]


def _parse_synthetic_contract(monkeypatch):
    monkeypatch.setattr(contract_sheet_module, "PdfReader", _SyntheticContractReader)
    return CceContractSheetParser().parse(Path("synthetic-contract.pdf"))


def _import_synthetic_contract(session, tmp_path, monkeypatch):
    monkeypatch.setattr(contract_sheet_module, "PdfReader", _SyntheticContractReader)
    path = tmp_path / "synthetic-contract.pdf"
    path.write_bytes(b"synthetic parser fixture")
    return DegreeContractImportService().import_pdf(
        session, path, assign_active_students=False
    )


def test_contract_parser_recovers_complete_synthetic_structure(monkeypatch):
    contract = _parse_synthetic_contract(monkeypatch)
    roots = {
        group.code: group.required_ects
        for group in contract.groups
        if group.parent_code is None
    }

    assert contract.graduation_ects_target == 300
    assert roots == {
        "GER": 29,
        "FUNDAMENTAL": 61,
        "FACULTY": 12,
        "CCE": 135,
        "COMMON": 45,
        "CAPSTONE": 18,
    }
    assert sum(roots.values()) == 300
    assert sum(len(group.memberships) for group in contract.groups) == len(_LAYOUT)
    quantitative = next(
        group for group in contract.groups if group.code == "GER_QUANT_CORE"
    )
    assert quantitative.memberships[0].course_code == "CSC230"
    health = next(group for group in contract.groups if group.code == "GER_HEALTH")
    assert {item.course_code for item in health.memberships} == {"GER300"}


def test_imported_contract_is_complete_without_duplicate_memberships(
    tmp_path, monkeypatch
):
    with SessionLocal() as session:
        imported = _import_synthetic_contract(session, tmp_path, monkeypatch)
        contract = session.scalar(
            select(DegreeContract).where(DegreeContract.id == imported.id)
        )
        assert contract is not None
        assert contract.graduation_ects_target == 300
        assert session.scalar(
            select(func.count())
            .select_from(RequirementGroupRecord)
            .where(RequirementGroupRecord.contract_id == contract.id)
        ) == 13
        membership_count = session.scalar(
            select(func.count())
            .select_from(RequirementGroupCourseRecord)
            .join(RequirementGroupRecord)
            .where(RequirementGroupRecord.contract_id == contract.id)
        )
        distinct_memberships = session.scalar(
            select(func.count()).select_from(
                select(
                    RequirementGroupCourseRecord.group_id,
                    RequirementGroupCourseRecord.course_id,
                )
                .join(RequirementGroupRecord)
                .where(RequirementGroupRecord.contract_id == contract.id)
                .distinct()
                .subquery()
            )
        )
        assert membership_count == distinct_memberships == len(_LAYOUT)


def test_candidate_options_are_not_invented_as_transcript_history(
    tmp_path, monkeypatch
):
    candidate_codes = {"GER221", "GER222", "GER230", "GER224", "GER300"}
    with SessionLocal() as session:
        _import_synthetic_contract(session, tmp_path, monkeypatch)
        rows = list(
            session.execute(
                select(
                    CourseRecord.code,
                    RequirementGroupCourseRecord.membership_type,
                )
                .join(
                    RequirementGroupCourseRecord,
                    RequirementGroupCourseRecord.course_id == CourseRecord.id,
                )
                .where(CourseRecord.code.in_(candidate_codes))
            )
        )
        assert {code for code, _kind in rows} == candidate_codes
        assert {kind for _code, kind in rows} == {"CANDIDATE"}
        assert list(
            session.scalars(
                select(StudentAttemptRecord).where(
                    StudentAttemptRecord.source_code.in_(candidate_codes)
                )
            )
        ) == []


def test_broad_legacy_category_inference_is_persisted_and_auditable(
    tmp_path, monkeypatch
):
    with SessionLocal() as session:
        _import_synthetic_contract(session, tmp_path, monkeypatch)
        row = session.execute(
            select(
                CourseRecord.code,
                RequirementGroupRecord.code,
                CourseRequirementGroupRecognition.verification_status,
            )
            .join(
                CourseRequirementGroupRecognition,
                CourseRequirementGroupRecognition.source_course_id
                == CourseRecord.id,
            )
            .join(
                RequirementGroupRecord,
                RequirementGroupRecord.id
                == CourseRequirementGroupRecognition.requirement_group_id,
            )
            .where(CourseRecord.code == "ELBC501")
        ).one()
        assert row == ("ELBC501", "COMMON", "INFERRED_PROGRAM_STRUCTURE")

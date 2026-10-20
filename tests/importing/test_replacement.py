import hashlib

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from academic_planner.database.models import (
    CourseRecord, CourseRequirementGroupRecognition, CurriculumRevision,
    DegreeContract, DegreeRequirement, EngineSetting, Equivalency, Offering,
    PrerequisiteGroup, RequirementGroupCourseRecord, RequirementGroupRecord,
    SourceDocument, StudentAttemptRecord,
    StudentOfferingOverride, StudentRecognitionRecord, StudentRecord,
    StudentOptionalCreditApproval, StudentRequirementRecord,
)
from academic_planner.database.session import Base
from academic_planner.importing import (
    CurriculumImportService, ParsedCourse, ParsedCurriculum, ParsedPrerequisite,
    SourceReference, validate_curriculum,
)
from academic_planner.matching import transition_catalogue_gaps


def database():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine


def parsed(title="Imported One", include_obsolete=False):
    source = SourceReference("old.xlsx", "sheet CCE, row 2")
    courses = [ParsedCourse("ELCM100", title, 5, 1, "FALL", source)]
    rules = []
    if include_obsolete:
        courses.append(ParsedCourse("ELCM200", "Imported Two", 5, 1, "SPRING", source))
        rules.append(ParsedPrerequisite("ELCM200", ("ELCM100",), "AND", "ELCM100", source))
    return ParsedCurriculum("OLD", "old.xlsx", "old:abc", courses,
        [course.code for course in courses], rules)


def seed(session):
    old = CurriculumRevision(version="OLD", revision="before", accepted_credit_target=300)
    new = CurriculumRevision(version="NEW", revision="untouched", accepted_credit_target=300)
    session.add_all([old, new]); session.flush()
    old_course = CourseRecord(curriculum_id=old.id, code="OLD999", title="Manual correction", ects=9,
        reference_year=5, reference_semester="FALL")
    stable_old_course = CourseRecord(curriculum_id=old.id, code="ELCM100", title="Prior title", ects=5,
        reference_year=1, reference_semester="FALL")
    new_course = CourseRecord(curriculum_id=new.id, code="NEW100", title="Keep me", ects=6,
        reference_year=1, reference_semester="FALL")
    session.add_all([old_course, stable_old_course, new_course]); session.flush()
    student = StudentRecord(identifier="transition", display_name="Transition", nominal_year=5,
        language_track="EN", reported_earned_credits=200)
    session.add(student); session.flush()
    session.add_all([
        DegreeRequirement(curriculum_id=old.id, course_id=old_course.id),
        DegreeRequirement(curriculum_id=new.id, course_id=new_course.id),
        Equivalency(source_course_id=old_course.id, target_course_id=new_course.id),
        Offering(course_id=old_course.id, academic_year_start=2026, semester="FALL"),
        EngineSetting(key="preserved", value=42, description="test"),
        StudentAttemptRecord(student_id=student.id, course_id=stable_old_course.id,
            source_code="ELCM100", source_term="FALL2021", ects=5,
            status="PASSED", earned_credits=5),
        StudentRequirementRecord(student_id=student.id, course_id=stable_old_course.id,
            authority="USER_CONFIRMED"),
        StudentRecognitionRecord(student_id=student.id,
            source_course_id=stable_old_course.id, target_course_id=new_course.id,
            authority="USER_CONFIRMED"),
        StudentOfferingOverride(student_id=student.id, course_id=stable_old_course.id,
            academic_year_start=2026, semester="FALL", authority="USER_CONFIRMED"),
        StudentOptionalCreditApproval(
            student_id=student.id, course_id=stable_old_course.id,
            course_code_snapshot="ELCM100", credit_category="PROGRAM_ELECTIVE",
            status="APPROVED", authority="Faculty Council",
            source_reference="decision:test-replacement",
        ),
    ])
    document = SourceDocument(filename="old.xlsx", kind="OLD_CURRICULUM",
        sha256=hashlib.sha256(b"old").hexdigest())
    session.add(document); session.commit()
    return document.id


def test_replacement_is_scoped_invalidates_references_and_is_idempotent():
    engine = database()
    with Session(engine) as session:
        document_id = seed(session)
        result = CurriculumImportService().replace(session, parsed(include_obsolete=True), session.get(SourceDocument, document_id))
        session.commit()
        assert result.equivalencies_invalidated == 1 and result.offerings_invalidated == 1
        assert result.matching_decisions_invalidated == 0
        assert result.student_links_rebound == 5
        assert result.student_links_invalidated == 0
        assert session.scalar(select(EngineSetting).where(EngineSetting.key == "preserved")).value == 42
        assert session.scalar(select(CourseRecord).where(CourseRecord.code == "NEW100")).title == "Keep me"
        assert session.scalar(select(CourseRecord).where(CourseRecord.code == "OLD999")) is None
        assert session.scalar(select(PrerequisiteGroup.id)) is not None
        rebound_course = session.scalar(select(CourseRecord).where(CourseRecord.code == "ELCM100"))
        assert session.scalar(select(StudentAttemptRecord)).course_id == rebound_course.id
        assert session.scalar(select(StudentRequirementRecord)).course_id == rebound_course.id
        assert session.scalar(select(StudentRecognitionRecord)).source_course_id == rebound_course.id
        assert session.scalar(select(StudentOfferingOverride)).course_id == rebound_course.id
        approval = session.scalar(select(StudentOptionalCreditApproval))
        assert approval.course_id == rebound_course.id
        assert approval.status == "UNVERIFIED"
        assert transition_catalogue_gaps(session) == ()

        imported = session.scalar(select(CourseRecord).where(CourseRecord.code == "ELCM100"))
        imported.title = "Manual edit"; session.commit()
        CurriculumImportService().replace(session, parsed(), session.get(SourceDocument, document_id)); session.commit()
        old_codes = set(session.scalars(select(CourseRecord.code).join(CurriculumRevision).where(CurriculumRevision.version == "OLD")))
        assert old_codes == {"ELCM100"}
        assert session.scalar(select(CourseRecord).where(CourseRecord.code == "ELCM100")).title == "Imported One"
        assert session.scalar(select(PrerequisiteGroup.id)) is None
        assert transition_catalogue_gaps(session) == ()

        CurriculumImportService().replace(session, parsed(), session.get(SourceDocument, document_id)); session.commit()
        assert set(session.scalars(select(CourseRecord.code).join(CurriculumRevision).where(CurriculumRevision.version == "OLD"))) == {"ELCM100"}


def test_failed_validation_leaves_previous_catalog_intact():
    engine = database()
    with Session(engine) as session:
        document_id = seed(session)
        bad = parsed(); bad.courses.append(bad.courses[0])
        report = validate_curriculum(bad)
        try:
            CurriculumImportService().replace(session, bad, session.get(SourceDocument, document_id), report)
        except ValueError:
            session.rollback()
        else:
            raise AssertionError("invalid import should fail")
        assert session.scalar(select(CourseRecord).where(CourseRecord.code == "OLD999")) is not None


def test_duplicate_prerequisite_groups_are_rejected_before_publish():
    candidate = parsed(include_obsolete=True)
    candidate.prerequisite_rules.append(candidate.prerequisite_rules[0])

    report = validate_curriculum(candidate)

    assert any(
        issue.code == "DUPLICATE_PREREQUISITE_GROUP"
        and issue.severity == "FATAL"
        for issue in report.issues
    )


def test_new_curriculum_replacement_rebinds_degree_contracts_and_recognitions():
    engine = database()
    with Session(engine) as session:
        old_revision = CurriculumRevision(
            version="OLD", revision="old", accepted_credit_target=300
        )
        new_revision = CurriculumRevision(
            version="NEW", revision="before", accepted_credit_target=300
        )
        session.add_all([old_revision, new_revision])
        session.flush()
        old_course = CourseRecord(
            curriculum_id=old_revision.id, code="ELCC100", title="Legacy",
            ects=5, reference_year=1, reference_semester="FALL",
        )
        new_course = CourseRecord(
            curriculum_id=new_revision.id, code="CCE100", title="Current",
            ects=5, reference_year=1, reference_semester="FALL",
        )
        session.add_all([old_course, new_course])
        session.flush()
        source = SourceDocument(
            filename="contract.pdf", kind="DEGREE_CONTRACT",
            sha256=hashlib.sha256(b"contract").hexdigest(),
        )
        session.add(source)
        session.flush()
        contract = DegreeContract(
            curriculum_id=new_revision.id,
            program_code="CCE",
            title="CCE Contract",
            graduation_ects_target=300,
            effective_academic_year="2026-2027",
            source_document_id=source.id,
        )
        session.add(contract)
        session.flush()
        group = RequirementGroupRecord(
            contract_id=contract.id,
            code="CORE",
            title="Core",
            required_ects=5,
            rule_type="ALL_OF",
        )
        session.add(group)
        session.flush()
        session.add_all([
            RequirementGroupCourseRecord(
                group_id=group.id,
                course_id=new_course.id,
                contribution_ects=5,
                membership_type="REQUIRED",
            ),
            CourseRequirementGroupRecognition(
                source_course_id=old_course.id,
                requirement_group_id=group.id,
            ),
        ])
        student = StudentRecord(
            identifier="contract-student",
            display_name="Contract Student",
            nominal_year=1,
            language_track="EN",
            governing_curriculum_version="NEW",
            reported_earned_credits=0,
            degree_contract_id=contract.id,
        )
        session.add(student)
        import_document = SourceDocument(
            filename="new.xlsx", kind="NEW_CURRICULUM",
            sha256=hashlib.sha256(b"new-curriculum").hexdigest(),
        )
        session.add(import_document)
        session.commit()

        source_ref = SourceReference("new.xlsx", "row 2")
        replacement = ParsedCurriculum(
            "NEW",
            "new.xlsx",
            "new:after",
            [ParsedCourse("CCE100", "Updated Current", 5, 1, "FALL", source_ref)],
            ["CCE100"],
        )
        CurriculumImportService().replace(
            session, replacement, session.get(SourceDocument, import_document.id)
        )
        session.commit()

        rebound_contract = session.scalar(select(DegreeContract))
        rebound_group = session.scalar(select(RequirementGroupRecord))
        rebound_course = session.scalar(
            select(CourseRecord).where(CourseRecord.code == "CCE100")
        )
        rebound_student = session.scalar(
            select(StudentRecord).where(StudentRecord.identifier == "contract-student")
        )
        membership = session.scalar(select(RequirementGroupCourseRecord))
        recognition = session.scalar(select(CourseRequirementGroupRecognition))

        assert rebound_course.title == "Updated Current"
        assert rebound_contract.curriculum_id == rebound_course.curriculum_id
        assert rebound_group.contract_id == rebound_contract.id
        assert membership.course_id == rebound_course.id
        assert rebound_student.degree_contract_id == rebound_contract.id
        assert recognition.source_course_id == old_course.id
        assert recognition.requirement_group_id == rebound_group.id

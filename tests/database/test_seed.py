import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from academic_planner.database.models import (
    CourseRecord,
    CurriculumRevision,
    DegreeRequirement,
    SourceDocument,
    StudentRecord,
)
from academic_planner.database.seed import seed_public_demo
from academic_planner.database.session import Base


def test_public_seed_is_idempotent_synthetic_and_contains_no_students():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first = seed_public_demo(session)
        session.commit()
        second = seed_public_demo(session)
        session.commit()

        assert first == second
        assert first["curricula"] == 2
        assert first["courses"] > 100
        assert first["offerings"] > 0
        assert first["students"] == 0
        assert session.scalar(select(func.count(StudentRecord.id))) == 0
        assert session.scalar(select(func.count(SourceDocument.id))) == 0
        assert session.scalar(
            select(func.count(DegreeRequirement.id))
            .join(CourseRecord)
            .where(CourseRecord.code.like("SYN-%"))
        ) == 0
        eng108 = session.scalar(select(CourseRecord).where(
            CourseRecord.code == "ENG108"
        ))
        assert eng108.graduation_role == "NEEDS_REVIEW"
        assert session.scalar(select(func.count(DegreeRequirement.id)).where(
            DegreeRequirement.course_id == eng108.id
        )) == 0


def test_public_seed_repairs_graduation_policy_from_an_older_seed():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        seed_public_demo(session)
        placeholder = session.scalar(select(CourseRecord).where(
            CourseRecord.code == "SYN-O-REQ01"
        ))
        placeholder.graduation_role = "MANDATORY"
        session.add(DegreeRequirement(
            curriculum_id=placeholder.curriculum_id,
            course_id=placeholder.id,
        ))
        training = session.scalar(select(CourseRecord).where(
            CourseRecord.code == "ELCC819"
        ))
        training.course_type = "COURSE"
        training.graduation_role = "OPTIONAL"
        session.commit()

        seed_public_demo(session)
        session.commit()

        assert placeholder.graduation_role == "NEEDS_REVIEW"
        assert session.scalar(select(func.count(DegreeRequirement.id)).where(
            DegreeRequirement.course_id == placeholder.id
        )) == 0
        assert training.course_type == "TRAINING"
        assert training.graduation_role == "MANDATORY"


def test_public_seed_refuses_to_modify_a_non_synthetic_catalog():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(CurriculumRevision(version="NEW", revision="private-import"))
        session.commit()

        with pytest.raises(RuntimeError, match="new database"):
            seed_public_demo(session)

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from academic_planner.database.models import (
    CurriculumRevision,
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


def test_public_seed_refuses_to_modify_a_non_synthetic_catalog():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(CurriculumRevision(version="NEW", revision="private-import"))
        session.commit()

        with pytest.raises(RuntimeError, match="new database"):
            seed_public_demo(session)

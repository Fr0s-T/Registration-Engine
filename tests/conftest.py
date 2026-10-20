import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

_TEST_DATABASE_DIRECTORY = TemporaryDirectory(prefix="academic-planner-tests-")
_TEST_DATABASE_PATH = Path(_TEST_DATABASE_DIRECTORY.name) / "planner.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DATABASE_PATH.as_posix()}"

from academic_planner.domain.models import *
from academic_planner.database.seed import seed_public_demo
from academic_planner.database.session import engine, initialize_database, session_scope


@pytest.fixture(scope="session", autouse=True)
def isolated_public_demo_database():
    """Run integration tests against a reproducible synthetic database."""
    initialize_database()
    with session_scope() as session:
        seed_public_demo(session)
    yield
    engine.dispose()
    _TEST_DATABASE_DIRECTORY.cleanup()


def term(year: int = 2023, kind: TermKind = TermKind.FALL) -> AcademicTerm:
    return AcademicTerm(year, kind)


def course(cid: str, credits: int = 5, year: int = 1, version: CurriculumVersion = CurriculumVersion.NEW, semester: TermKind = TermKind.FALL) -> Course:
    return Course(cid, cid, cid, credits, version, year, semester)


def bundle(cid: str, suffix: str = "1", day: Weekday = Weekday.MONDAY, start: int = 540, end: int = 600, lab: bool = False) -> RegistrationBundle:
    sections = [Section(f"{cid}-{suffix}-L", cid, "LECTURE", "MAIN", (Meeting(day, start, end),))]
    if lab:
        sections.append(Section(f"{cid}-{suffix}-B", cid, "LAB", "MAIN", (Meeting(Weekday.FRIDAY, start, end),), .2))
    return RegistrationBundle(f"{cid}-{suffix}", cid, tuple(sections))


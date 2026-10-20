"""Create the deterministic, synthetic public demonstration database."""

from __future__ import annotations

import argparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from academic_planner.matching.catalogue import (
    synchronize_transition_catalogue,
    transition_catalogue_coverage,
)

from .models import CourseRecord, CurriculumRevision, Offering, StudentRecord
from .service import seed_defaults, seed_demo_catalog
from .session import initialize_database, session_scope


def seed_public_demo(session: Session) -> dict[str, int]:
    """Idempotently add public demo data without importing local source files."""
    revisions = list(session.scalars(select(CurriculumRevision)))
    if revisions and any(revision.revision != "synthetic-demo" for revision in revisions):
        raise RuntimeError(
            "Refusing to mix the public demo seed into a non-synthetic catalog. "
            "Set DATABASE_URL to a new database."
        )
    seed_defaults(session)
    seed_demo_catalog(session)
    synchronize_transition_catalogue(session)

    coverage = transition_catalogue_coverage(session)
    if not coverage["complete"]:
        raise RuntimeError("Synthetic transition catalogue is incomplete")

    return {
        "curricula": session.scalar(select(func.count(CurriculumRevision.id))) or 0,
        "courses": session.scalar(select(func.count(CourseRecord.id))) or 0,
        "offerings": session.scalar(select(func.count(Offering.id))) or 0,
        "students": session.scalar(select(func.count(StudentRecord.id))) or 0,
    }


def main() -> None:
    """Seed the database configured by DATABASE_URL and report its contents."""
    argparse.ArgumentParser(
        description="Seed a new database with deterministic synthetic demo data."
    ).parse_args()
    initialize_database()
    with session_scope() as session:
        summary = seed_public_demo(session)
    print(
        "Seeded synthetic demo database: "
        + ", ".join(f"{key}={value}" for key, value in summary.items())
    )


if __name__ == "__main__":
    main()

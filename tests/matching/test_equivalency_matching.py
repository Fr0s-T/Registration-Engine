import pytest

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from academic_planner.database.models import (
    CourseRecord, CurriculumRevision, DegreeRequirement, Equivalency, EquivalencyMatch,
    TransitionCourseDisposition, TranscriptCodeMapping,
)
from academic_planner.database.session import Base
from academic_planner.database.loader import DatabasePlanningLoader
from academic_planner.database.service import seed_defaults
from academic_planner.domain.models import (
    AcademicTerm, AttemptStatus, CourseAttempt, LanguageTrack, StudentAcademicState, TermKind,
)
from academic_planner.importing import CurriculumImportService, ParsedCourse, ParsedCurriculum, SourceReference
from academic_planner.matching import (
    EquivalencyMatchingService, normalize_course_title,
    require_complete_transition_catalogue, synchronize_transition_catalogue,
    transition_catalogue_gaps,
)
from academic_planner.reconciliation import ReconciliationService


def database():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine


def seed(session, old_courses, new_courses):
    revisions = {}
    for version in ("OLD", "NEW"):
        revision = CurriculumRevision(version=version, revision="test")
        session.add(revision); session.flush(); revisions[version] = revision
    ids = {}
    for version, rows in (("OLD", old_courses), ("NEW", new_courses)):
        for code, title, ects, year, semester in rows:
            course = CourseRecord(curriculum_id=revisions[version].id, code=code, title=title,
                ects=ects, reference_year=year, reference_semester=semester)
            session.add(course); session.flush(); ids[code] = course.id
            session.add(DegreeRequirement(curriculum_id=revisions[version].id, course_id=course.id))
    session.commit()
    return ids


def test_exact_normalization_auto_matches_but_meaningful_distinctions_do_not():
    engine = database()
    with Session(engine) as session:
        seed(session,
            [("O1", "Image-Processing", 5, 5, "FALL"), ("O2", "Signals I", 5, 2, "FALL")],
            [("N1", " image processing! ", 5, 5, "FALL"), ("N2", "Signals II", 5, 2, "FALL")])
        summary = EquivalencyMatchingService().run(session); session.commit()
        row = session.scalar(select(EquivalencyMatch))
        assert row.status == "AUTO_MATCHED" and row.review_reasons == []
        assert session.get(Equivalency, row.equivalency_id).recognizes_history is True
        assert summary == {"automatic_matches": 1, "needs_review": 0, "verified": 0,
            "rejected": 0, "legacy_only": 0,
            "unmatched_old": 1, "unmatched_new": 1,
            "ambiguous_candidates": 0}
        assert normalize_course_title("Analog I") != normalize_course_title("Analog II")


def test_automatic_match_can_be_unverified():
    engine = database()
    with Session(engine) as session:
        seed(session,
            [("O1", "Data Communication", 5, 3, "FALL")],
            [("N1", "Data Communication", 5, 3, "FALL")])
        EquivalencyMatchingService().run(session)
        row = session.scalar(select(EquivalencyMatch))
        assert session.get(Equivalency, row.equivalency_id).recognizes_history is True
        EquivalencyMatchingService().reject(session, row.id)
        session.flush()
        assert row.status == "REJECTED"
        assert row.equivalency_id is None
        assert session.scalar(select(Equivalency.id)) is None


def test_automatic_match_can_be_replaced_without_leaving_old_recognition():
    engine = database()
    with Session(engine) as session:
        ids = seed(session,
            [("O1", "Networks", 5, 3, "FALL")],
            [("N1", "Networks", 5, 3, "FALL"),
             ("N2", "Network Engineering", 5, 3, "FALL")])
        EquivalencyMatchingService().run(session)
        original = session.scalar(select(EquivalencyMatch).where(
            EquivalencyMatch.status == "AUTO_MATCHED"
        ))
        replacement = EquivalencyMatchingService().verify(
            session, original.id,
            old_course_id=ids["O1"], new_course_id=ids["N2"],
        )
        session.flush()
        pairs = {(row.source_course_id, row.target_course_id)
                 for row in session.scalars(select(Equivalency))}
        assert original.status == "REJECTED"
        assert original.equivalency_id is None
        assert replacement.status == "HUMAN_VERIFIED"
        assert pairs == {(ids["O1"], ids["N2"])}


def test_changed_attributes_and_similar_titles_require_review():
    engine = database()
    with Session(engine) as session:
        seed(session,
            [("O1", "Microprocessors", 6, 4, "FALL"),
             ("O2", "Entrepreneurship", 5, 4, "FALL"),
             ("O3", "Digital Signal Processing", 5, 4, "FALL")],
            [("N1", "Microprocessors", 5, 4, "FALL"),
             ("N2", "Entrepreneurship", 5, 2, "SPRING"),
             ("N3", "Digital Signals Processing", 5, 4, "FALL")])
        result = EquivalencyMatchingService().run(session); session.commit()
        rows = {session.get(CourseRecord, r.old_course_id).code: r
                for r in session.scalars(select(EquivalencyMatch))}
        assert rows["O1"].review_reasons == ["ECTS_CHANGED"]
        assert rows["O2"].review_reasons == ["REFERENCE_YEAR_CHANGED", "REFERENCE_SEMESTER_CHANGED"]
        assert "TITLE_SIMILAR" in rows["O3"].review_reasons
        assert result["needs_review"] == 3
        assert session.scalar(select(Equivalency.id)) is None


def test_ambiguity_prevents_auto_match_and_decisions_survive_reruns_and_restart():
    engine = database()
    with Session(engine) as session:
        ids = seed(session,
            [("O1", "Networks", 5, 3, "FALL"), ("O2", "Networks", 5, 3, "FALL")],
            [("N1", "Networks", 5, 3, "FALL")])
        EquivalencyMatchingService().run(session); session.commit()
        rows = list(session.scalars(select(EquivalencyMatch)))
        assert len(rows) == 2 and all(r.status == "NEEDS_REVIEW" for r in rows)
        assert all("MULTIPLE_CANDIDATES" in r.review_reasons for r in rows)
        EquivalencyMatchingService().verify(session, rows[0].id); session.commit()
        EquivalencyMatchingService().reject(session, rows[1].id); session.commit()
    with Session(engine) as restarted:
        EquivalencyMatchingService().run(restarted); restarted.commit()
        rows = list(restarted.scalars(select(EquivalencyMatch)))
        assert {r.status for r in rows} == {"HUMAN_VERIFIED", "REJECTED"}
        verified = next(r for r in rows if r.status == "HUMAN_VERIFIED")
        eq = restarted.get(Equivalency, verified.equivalency_id)
        assert eq.recognizes_history is True
        assert eq.prospective_registration_allowed is None
        assert len(list(restarted.scalars(select(Equivalency)))) == 1


def test_manual_alternative_rejects_original_and_verifies_selected_pair():
    engine = database()
    with Session(engine) as session:
        ids = seed(session,
            [("O1", "Microprocessors", 6, 4, "FALL"), ("O2", "Embedded Systems", 5, 4, "FALL")],
            [("N1", "Microprocessors", 5, 4, "FALL"), ("N2", "Embedded Design", 5, 4, "FALL")])
        EquivalencyMatchingService().run(session); session.flush()
        original = session.scalar(select(EquivalencyMatch).where(EquivalencyMatch.old_course_id == ids["O1"]))
        chosen = EquivalencyMatchingService().verify(session, original.id,
            old_course_id=ids["O1"], new_course_id=ids["N2"])
        session.commit()
        assert original.status == "REJECTED"
        assert chosen.status == "HUMAN_VERIFIED" and chosen.method == "HUMAN_VERIFICATION"


def test_curriculum_replacement_invalidates_match_decisions():
    engine = database()
    with Session(engine) as session:
        ids = seed(session, [("O1", "Circuits", 5, 1, "FALL")],
                   [("N1", "Circuits", 5, 1, "FALL")])
        EquivalencyMatchingService().run(session); session.commit()
        source = SourceReference("old.xlsx", "row 2")
        parsed = ParsedCurriculum("OLD", "old.xlsx", "replacement",
            [ParsedCourse("O9", "Replacement", 5, 1, "FALL", source)], ["O9"])
        from academic_planner.database.models import SourceDocument
        document = SourceDocument(filename="old.xlsx", kind="OLD_CURRICULUM")
        session.add(document); session.commit()
        result = CurriculumImportService().replace(session, parsed, document); session.commit()
        assert result.matching_decisions_invalidated == 1
        assert session.scalar(select(EquivalencyMatch.id)) is None
        assert session.scalar(select(Equivalency.id)) is None
        assert session.get(CourseRecord, ids["N1"]).title == "Circuits"


def test_solver_loader_ignores_suggestions_and_uses_verified_different_credit_mapping_safely():
    engine = database()
    with Session(engine) as session:
        ids = seed(session, [("O1", "Microprocessors", 6, 4, "FALL")],
                   [("N1", "Microprocessors", 5, 4, "FALL")])
        seed_defaults(session)
        service = EquivalencyMatchingService()
        service.run(session); session.flush()
        student = StudentAcademicState(4, LanguageTrack.EN, (
            CourseAttempt(str(ids["O1"]), AcademicTerm(2025, TermKind.FALL),
                          AttemptStatus.PASSED, earned_credits=6),
        ))
        problem = DatabasePlanningLoader().load_problem(session, student)
        assert problem.equivalencies == ()
        suggestion = session.scalar(select(EquivalencyMatch))
        service.verify(session, suggestion.id); session.flush()
        problem = DatabasePlanningLoader().load_problem(session, student)
        result = ReconciliationService().reconcile(
            student, problem.curriculum, problem.equivalencies)
        assert result.satisfied_requirement_ids == {str(ids["N1"])}
        assert result.official_earned_credits == 6  # actual completion, not target-course ECTS
        assert session.get(Equivalency, suggestion.equivalency_id).prospective_registration_allowed is None


def test_transition_catalogue_sync_maps_known_codes_and_disposes_every_other_old_course():
    engine = database()
    with Session(engine) as session:
        ids = seed(
            session,
            [
                ("ELCM122", "Introduction to Computer + Lab", 5, 1, "FALL"),
                ("LEGACY", "Removed legacy subject", 3, 2, "SPRING"),
            ],
            [
                ("CSC230", "Computer Fundamentals and Applications", 4, 1, "FALL"),
                ("GER312", "Culture, Moral, Religion", 2, 2, "FALL"),
                ("GER333", "Professional Ethics", 2, 2, "FALL"),
            ],
        )

        synchronize_transition_catalogue(session)

        equivalency = session.scalar(select(Equivalency).where(
            Equivalency.source_course_id == ids["ELCM122"],
            Equivalency.target_course_id == ids["CSC230"],
        ))
        disposition = session.scalar(select(TransitionCourseDisposition).where(
            TransitionCourseDisposition.old_course_id == ids["LEGACY"]
        ))
        assert equivalency is not None and equivalency.recognizes_history is True
        assert equivalency.prospective_registration_allowed is True
        assert disposition.disposition == "LEGACY_CREDIT_ONLY"
        aliases = {
            row.source_code: row.target_course_id
            for row in session.scalars(select(TranscriptCodeMapping))
        }
        assert aliases == {
            "REL312": ids["GER312"],
            "DRH320": ids["GER333"],
        }
        assert transition_catalogue_gaps(session) == ()
        require_complete_transition_catalogue(session)

        session.delete(disposition)
        session.flush()
        with pytest.raises(ValueError, match="LEGACY"):
            require_complete_transition_catalogue(session)

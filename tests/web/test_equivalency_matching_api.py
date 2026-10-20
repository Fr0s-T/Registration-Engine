from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from academic_planner.database.models import CourseRecord, CurriculumRevision, EquivalencyMatch
from academic_planner.database.session import Base, get_session
from academic_planner.web.app import app


def test_matching_verify_reject_and_manual_selection_api():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine); factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        old = CurriculumRevision(version="OLD", revision="test")
        new = CurriculumRevision(version="NEW", revision="test")
        session.add_all([old, new]); session.flush()
        session.add_all([
            CourseRecord(curriculum_id=old.id, code="O1", title="Microprocessors", ects=6, reference_year=4, reference_semester="FALL"),
            CourseRecord(curriculum_id=old.id, code="O2", title="Other", ects=5, reference_year=4, reference_semester="FALL"),
            CourseRecord(curriculum_id=new.id, code="N1", title="Microprocessors", ects=5, reference_year=4, reference_semester="FALL"),
            CourseRecord(curriculum_id=new.id, code="N2", title="Different", ects=5, reference_year=4, reference_semester="FALL"),
        ]); session.commit()
    def override():
        with factory() as session: yield session
    app.dependency_overrides[get_session] = override
    try:
        with TestClient(app) as client:
            result = client.post("/api/admin/equivalency-matches/auto-match")
            assert result.status_code == 200 and result.json()["summary"]["needs_review"] == 1
            data = client.get("/api/admin/equivalency-matches").json()
            suggestion = next(row for row in data["entries"] if row["status"] == "NEEDS_REVIEW")
            verified = client.post(f"/api/admin/equivalency-matches/{suggestion['id']}/verify", json={})
            assert verified.status_code == 200
            assert verified.json()["prospective_registration_allowed"] is None
            assert client.post("/api/admin/equivalency-matches/999/reject").status_code == 404
    finally:
        app.dependency_overrides.clear()

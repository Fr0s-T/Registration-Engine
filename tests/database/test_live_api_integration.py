from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from academic_planner.database.models import (
    CourseRecord, CurriculumRevision, DegreeRequirement, MeetingRecord, Offering,
    SectionRecord,
)
from academic_planner.database.service import seed_defaults
from academic_planner.database.session import Base, get_session
from academic_planner.web.admin import router


def add_offering(db, course, day):
    offering = Offering(course_id=course.id, academic_year_start=2026, semester="FALL",
                        language_track="EN", verification_status="VERIFIED")
    db.add(offering); db.flush()
    section = SectionRecord(offering_id=offering.id, code="EN-A",
                            component="LECTURE", bundle_key="A")
    db.add(section); db.flush()
    db.add(MeetingRecord(section_id=section.id, weekday=day,
                         start_minute=510, end_minute=600))


def test_prerequisite_edit_affects_next_api_plan_and_restores_cleanly():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        seed_defaults(db)
        revision = CurriculumRevision(version="NEW", revision="api", accepted_credit_target=10)
        db.add(revision); db.flush()
        courses = []
        for code in ("A", "B"):
            course = CourseRecord(curriculum_id=revision.id, code=code, title=code, ects=5,
                reference_year=1, reference_semester="FALL", academic_track_policy="SHARED",
                permitted_student_tracks=["EN", "FR"])
            db.add(course); db.flush()
            db.add(DegreeRequirement(curriculum_id=revision.id, course_id=course.id))
            courses.append(course)
        add_offering(db, courses[0], 0)
        add_offering(db, courses[1], 1)
        db.commit()

        app = FastAPI()
        app.include_router(router)
        def override_session():
            yield db
        app.dependency_overrides[get_session] = override_session
        payload = {"curriculum_version": "NEW", "nominal_year": 1,
                   "language_track": "EN", "attempts": []}
        with TestClient(app) as client:
            before = client.post("/api/admin/plan", json=payload).json()
            assert len(before["scheduled_terms"][0]["course_ids"]) == 2

            created = client.post(f"/api/admin/courses/{courses[1].id}/prerequisites",
                                  json={"logic": "AND",
                                        "prerequisite_course_ids": [courses[0].id]})
            assert created.status_code == 201
            after = client.post("/api/admin/plan", json=payload).json()
            assert len(after["scheduled_terms"][0]["course_ids"]) == 1
            assert before["graduation_term"] != after["graduation_term"]
            assert after["student_persisted"] is False

            assert client.delete(f"/api/admin/prerequisites/{created.json()['id']}").status_code == 204
            restored = client.post("/api/admin/plan", json=payload).json()
            assert len(restored["scheduled_terms"][0]["course_ids"]) == 2

            assert client.put("/api/admin/settings", json={"values": {
                "allow_cross_track_shared_sections": True}}).status_code == 200

        with TestClient(app) as restarted:
            assert restarted.get("/api/admin/settings").json()["values"][
                "allow_cross_track_shared_sections"] is True

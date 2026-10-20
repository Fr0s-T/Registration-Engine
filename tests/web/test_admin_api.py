from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from academic_planner.database.models import PrerequisiteGroup
from academic_planner.database.session import SessionLocal
from academic_planner.web.app import app


def test_admin_pages_and_database_planning_are_live():
    with TestClient(app) as client:
        for route in ("/courses", "/timetable", "/settings", "/imports"):
            assert client.get(route).status_code == 200
        imports_page = client.get("/imports").text
        assert "from'/static/admin.js'" in imports_page
        assert client.get("/static/admin.js").status_code == 200
        courses = client.get("/api/admin/courses")
        assert courses.status_code == 200
        assert {c["curriculum_version"] for c in courses.json()} == {"OLD", "NEW"}
        planner_page = client.get("/").text
        assert 'id="conditional-repeat-load"' not in planner_page
        assert 'id="prospective-equivalency"' not in planner_page
        assert 'name="capacity"' not in planner_page
        settings = client.get("/api/admin/settings").json()["values"]
        assert settings["training_1_capacity"] == 5
        assert settings["training_2_capacity"] == 5
        result = client.post("/api/admin/plan", json={
            "curriculum_version": "NEW", "nominal_year": 1,
            "language_track": "EN", "attempts": [],
        })
        assert result.status_code == 200
        assert result.json()["student_persisted"] is False


def test_setting_validation_and_persistence():
    with TestClient(app) as client:
        bad = client.put("/api/admin/settings", json={"values": {"solver_time_limit_seconds": 0}})
        assert bad.status_code == 422
        boolean_as_number = client.put(
            "/api/admin/settings",
            json={"values": {"solver_time_limit_seconds": True}},
        )
        assert boolean_as_number.status_code == 422
        saved = client.put("/api/admin/settings", json={"values": {"solver_time_limit_seconds": 19.5}})
        assert saved.status_code == 200
        assert client.get("/api/admin/settings").json()["values"]["solver_time_limit_seconds"] == 19.5
        assert client.get("/api/config").json()["defaults"]["solver_time_limit_seconds"] == 19.5
        app_script = client.get("/static/app.js").text
        assert "state.defaults?.regular_credit_capacity ?? 30" in app_script
        settings_script = client.get("/static/settings.js").text
        assert "value=\"${esc(value ?? '')}\"" in settings_script
        client.post("/api/admin/settings/reset")


def test_active_term_change_requires_confirmation_when_offerings_exist():
    with TestClient(app) as client:
        current = client.get("/api/admin/timetable").json()["active_term"]
        target = {"academic_year_start": current["academic_year_start"] + 1,
                  "semester": current["semester"], "confirm_replace": False}
        if client.get("/api/admin/timetable").json()["offerings"]:
            assert client.put("/api/admin/active-term", json=target).status_code == 409


def test_posting_prerequisites_again_replaces_the_single_group():
    created_course_ids = []
    with TestClient(app) as client:
        curriculum_id = client.get("/api/admin/curricula").json()[0]["id"]

        def create_course(code):
            response = client.post("/api/admin/courses", json={
                "curriculum_id": curriculum_id,
                "code": code,
                "title": f"Prerequisite test {code}",
                "ects": 5,
                "reference_year": 1,
                "reference_semester": "FALL",
            })
            assert response.status_code == 201, response.text
            course_id = response.json()["id"]
            created_course_ids.append(course_id)
            return course_id

        first = create_course("ZZPREREQ1")
        second = create_course("ZZPREREQ2")
        target = create_course("ZZPREREQTARGET")
        try:
            original = client.post(
                f"/api/admin/courses/{target}/prerequisites",
                json={"logic": "AND", "prerequisite_course_ids": [first]},
            )
            replacement = client.post(
                f"/api/admin/courses/{target}/prerequisites",
                json={"logic": "OR", "prerequisite_course_ids": [second]},
            )
            assert original.status_code == replacement.status_code == 201
            assert original.json()["id"] == replacement.json()["id"]

            with SessionLocal() as session:
                groups = list(session.scalars(
                    select(PrerequisiteGroup)
                    .where(PrerequisiteGroup.course_id == target)
                    .options(selectinload(PrerequisiteGroup.items))
                ))
                assert len(groups) == 1
                assert groups[0].logic == "OR"
                assert [item.prerequisite_course_id for item in groups[0].items] == [second]
        finally:
            for course_id in reversed(created_course_ids):
                response = client.delete(f"/api/admin/courses/{course_id}")
                assert response.status_code == 204, response.text

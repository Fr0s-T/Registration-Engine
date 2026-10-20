from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from academic_planner.database.models import CourseRecord, CurriculumRevision, EngineSetting
from academic_planner.database.session import Base, get_session
from academic_planner.web import admin
from academic_planner.web.app import app


def workbook_bytes(title="Imported Circuit"):
    output = BytesIO(); workbook = Workbook(); sheet = workbook.active
    sheet.append(["Code", "Title", "ECTS", "Year", "Semester", "Pre-requisite"])
    sheet.append(["ELCM100", title, 5, 1, "Fall", "-"])
    workbook.save(output)
    return output.getvalue()


def test_preview_requires_confirmation_then_replaces_only_selected_curriculum(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine); factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        old = CurriculumRevision(version="OLD", revision="manual")
        new = CurriculumRevision(version="NEW", revision="keep")
        session.add_all([old, new]); session.flush()
        session.add_all([
            CourseRecord(curriculum_id=old.id, code="OLD999", title="Discard", ects=5, reference_year=1, reference_semester="FALL"),
            CourseRecord(curriculum_id=new.id, code="NEW100", title="Preserve", ects=5, reference_year=1, reference_semester="FALL"),
            EngineSetting(key="kept", value=True, description="test"),
        ]); session.commit()
    def override_session():
        with factory() as session: yield session
    monkeypatch.setattr(admin, "PROJECT_ROOT", tmp_path)
    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            preview = client.post("/api/admin/imports/preview", data={"curriculum_version": "OLD"},
                files={"file": ("CCE Courses Division old.xlsx", workbook_bytes(),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
            assert preview.status_code == 201
            data = preview.json()
            assert data["courses_parsed"] == 1 and data["existing_courses_to_replace"] == 1
            assert client.post(f"/api/admin/imports/{data['batch_id']}/confirm", json={"confirm_replace": False}).status_code == 409
            applied = client.post(f"/api/admin/imports/{data['batch_id']}/confirm", json={"confirm_replace": True})
            assert applied.status_code == 200
        with factory() as session:
            assert set(session.scalars(select(CourseRecord.code))) == {"ELCM100", "NEW100"}
            assert session.get(EngineSetting, "kept").value is True
    finally:
        app.dependency_overrides.clear()

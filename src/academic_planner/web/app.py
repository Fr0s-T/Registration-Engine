"""FastAPI composition root for the local planner and administration UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from academic_planner.database.models import EngineSetting, StudentRecord
from academic_planner.database.service import DEFAULT_SETTINGS, seed_defaults
from academic_planner.database.session import initialize_database, session_scope
from academic_planner.student_input import router as student_input_router
from academic_planner.web.admin import router as admin_router
from academic_planner.web.database_student_service import DatabaseStudentPlanningService
from academic_planner.web.schemas import PlanRequest, PlanResponse, ScenarioResponse
from academic_planner.web.services import (
    InvalidTermOverrideError, PlanningWebService, UnknownScenarioError,
)

STATIC_DIR = Path(__file__).parent / "static"
STUDENT_INPUT_STATIC_DIR = Path(__file__).parents[1] / "student_input" / "static"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize the schema and settings without reading local source files."""
    initialize_database()
    with session_scope() as session:
        seed_defaults(session)
    yield


app = FastAPI(
    title="Academic Planning Engine",
    description="Local dashboard API for synthetic academic planning scenarios.",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount(
    "/student-input-assets",
    StaticFiles(directory=STUDENT_INPUT_STATIC_DIR),
    name="student-input-assets",
)
app.include_router(admin_router)
app.include_router(student_input_router)
service = PlanningWebService()


def _database_student_identifiers() -> list[str]:
    with session_scope() as session:
        return list(session.scalars(
            select(StudentRecord.identifier)
            .where(StudentRecord.active.is_(True))
            .order_by(StudentRecord.identifier)
        ))


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/scenario-lab", include_in_schema=False)
def scenario_lab() -> FileResponse:
    """Keep the former planner available as an explicit scenario sandbox."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/courses", include_in_schema=False)
def courses_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "courses.html")


@app.get("/timetable", include_in_schema=False)
def timetable_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "timetable.html")


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/imports", include_in_schema=False)
def imports_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "imports.html")


@app.get("/student-input", include_in_schema=False)
def student_input_page() -> FileResponse:
    return FileResponse(STUDENT_INPUT_STATIC_DIR / "index.html")


@app.get("/api/scenarios", response_model=list[ScenarioResponse])
def scenarios() -> list[ScenarioResponse]:
    return service.scenario_summaries() + [
        DatabaseStudentPlanningService(identifier).scenario_summary()
        for identifier in _database_student_identifiers()
    ]


@app.get("/api/config")
def configuration() -> dict:
    with session_scope() as session:
        stored = {
            row.key: row.value
            for row in session.scalars(select(EngineSetting)).all()
        }
    engine_defaults = {
        key: stored.get(key, default[0])
        for key, default in DEFAULT_SETTINGS.items()
    }
    return {
        "defaults": {
            "regular_credit_capacity": engine_defaults["default_credit_capacity"],
            "academic_year_deviation_weight": engine_defaults["academic_year_deviation_weight"],
            "reference_semester_deviation_weight": engine_defaults["reference_semester_deviation_weight"],
            "allow_training_postponement": engine_defaults["allow_training_postponement"],
            "training_delay_penalty": engine_defaults["training_delay_penalty"],
            "max_training_delay_years": engine_defaults["max_training_delay_years"],
            "solver_time_limit_seconds": engine_defaults["solver_time_limit_seconds"],
            "initial_horizon_semesters": engine_defaults["initial_horizon_semesters"],
            "max_horizon_semesters": engine_defaults["max_horizon_semesters"],
            "auto_extend_horizon": engine_defaults["auto_extend_horizon"],
            "horizon_extension_step": engine_defaults["horizon_extension_step"],
            "allow_extended_load_when_repeating_failed_course": engine_defaults[
                "allow_extended_load_when_repeating_failed_course"
            ],
            "allow_final_two_semester_graduation_load": engine_defaults[
                "allow_final_two_semester_graduation_load"
            ],
            "enable_course_selection_diagnostics": False,
            "max_diagnostic_courses": 5,
        },
        "options": {
            "regular_credit_capacity": {
                "type": "integer", "minimum": 1, "maximum": 60,
                "suggested_values": [30, 36],
                "description": "Maximum planned ECTS in each regular term.",
            },
            "per_semester_capacity_overrides": {
                "type": "term_to_integer", "minimum": 1, "maximum": 60,
                "description": "Optional capacity replacement for an exact planning term.",
            },
            "academic_year_deviation_weight": {
                "type": "integer", "minimum": 0, "maximum": 1000,
                "description": "Soft preference for the projected curriculum year; zero disables it.",
            },
            "reference_semester_deviation_weight": {
                "type": "integer", "minimum": 0, "maximum": 1000,
                "description": "Soft preference for a course's reference Fall or Spring.",
            },
            "allow_training_postponement": {
                "type": "boolean",
                "description": "Allow training in a later configured training period.",
            },
            "training_delay_penalty": {
                "type": "integer", "minimum": 0, "maximum": 1000,
                "description": "Tie-breaker penalty for each year training is postponed.",
            },
            "max_training_delay_years": {
                "type": "nullable_integer", "minimum": 0, "maximum": 10,
                "description": "Optional maximum postponement; blank means no configured maximum.",
            },
            "solver_time_limit_seconds": {
                "type": "number", "exclusive_minimum": 0, "maximum": 120,
                "description": "Total time budget shared across lexicographic solver stages.",
            },
            "initial_horizon_semesters": {
                "type": "integer", "minimum": 1, "maximum": 40,
                "description": "Initial number of regular Fall/Spring semesters to search.",
            },
            "max_horizon_semesters": {
                "type": "integer", "minimum": 1, "maximum": 40,
                "description": "Bounded maximum regular-semester search horizon.",
            },
            "auto_extend_horizon": {
                "type": "boolean",
                "description": "Extend only after the shorter horizon is proven infeasible.",
            },
            "allow_extended_load_when_repeating_failed_course": {
                "type": "boolean",
                "description": "Allow 36 ECTS only in a regular term that selects an unresolved failed repeat.",
            },
            "allow_final_two_semester_graduation_load": {
                "type": "boolean",
                "description": "Allow up to 36 ECTS in either of the final two regular semesters only when required for an earlier graduation.",
            },
            "enable_course_selection_diagnostics": {
                "type": "boolean",
                "description": "Run bounded counterfactual solves for unselected eligible courses.",
            },
        },
        "fixed_preferences": [
            "Earlier-year backlog clearance is the third lexicographic objective.",
            "Productive credit use is the fourth lexicographic objective.",
            "Current-term campus-day convenience is the fifth objective.",
        ],
    }


@app.post("/api/plan", response_model=PlanResponse)
async def create_plan(request: PlanRequest) -> PlanResponse:
    try:
        if request.scenario_id in _database_student_identifiers():
            return await run_in_threadpool(
                DatabaseStudentPlanningService(request.scenario_id).plan, request
            )
        return await run_in_threadpool(service.plan, request)
    except UnknownScenarioError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTermOverrideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

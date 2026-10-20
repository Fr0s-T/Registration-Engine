"""HTTP boundary for student-input preview and explicit persistence."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from academic_planner.database.models import ActiveTerm
from academic_planner.database.session import get_session

from .persistence import StudentAlreadyExistsError, persist_student_input
from .schemas import (
    StudentInputCommitRequest, StudentInputCommitResponse,
    StudentInputPreviewRequest, StudentInputPreviewResponse,
)
from .service import preview_student_input


router = APIRouter(prefix="/api/student-input", tags=["student input"])


@router.post("/preview", response_model=StudentInputPreviewResponse)
def preview(
    payload: StudentInputPreviewRequest,
    session: Session = Depends(get_session),
) -> StudentInputPreviewResponse:
    active = session.get(ActiveTerm, 1)
    current_term = payload.current_term or (
        f"{active.semester}{active.academic_year_start}" if active else "FALL2026"
    )
    try:
        return preview_student_input(
            session, payload.text, current_term, payload.decisions
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/commit", response_model=StudentInputCommitResponse)
def commit(
    payload: StudentInputCommitRequest,
    session: Session = Depends(get_session),
) -> StudentInputCommitResponse:
    active = session.get(ActiveTerm, 1)
    active_term = (
        f"{active.semester}{active.academic_year_start}" if active else None
    )
    if (
        active_term is not None
        and payload.current_term is not None
        and payload.current_term != active_term
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"The active term changed from {payload.current_term} to "
                f"{active_term}. Parse the portal text again before saving."
            ),
        )
    current_term = active_term or payload.current_term or "FALL2026"
    try:
        result = persist_student_input(session, payload, current_term)
        session.commit()
        return result
    except StudentAlreadyExistsError as exc:
        existing_detail = {
            "identifier": exc.existing.identifier,
            "display_name": exc.existing.display_name,
            "reported_earned_credits": exc.existing.reported_earned_credits,
            "attempts": exc.existing_attempts,
        }
        session.rollback()
        raise HTTPException(status_code=409, detail={
            "code": "STUDENT_EXISTS",
            "message": (
                f"{exc.existing.display_name} is already saved. Review the comparison "
                "before replacing the existing academic record."
            ),
            "existing": existing_detail,
            "incoming": {
                "reported_earned_credits": exc.incoming_credits,
                "attempts": exc.incoming_attempts,
            },
        }) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

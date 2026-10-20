from typing import Protocol

from academic_planner.domain.models import (
    AcademicTerm, AcademicTrackPolicy, Course, StudentAcademicState,
)


class AcademicRegistrationPolicy(Protocol):
    def rejection_reason(self, student: StudentAcademicState, course: Course, term: AcademicTerm) -> str | None: ...


class AllowAllRegistrationPolicy:
    def rejection_reason(self, student: StudentAcademicState, course: Course, term: AcademicTerm) -> str | None:
        return None


class CatalogRegistrationPolicy:
    """Apply catalog-level student-track restrictions to registration."""

    def rejection_reason(
        self, student: StudentAcademicState, course: Course, term: AcademicTerm
    ) -> str | None:
        if (
            course.academic_track_policy is AcademicTrackPolicy.TRACK_SPECIFIC
            and student.language_track not in course.permitted_student_tracks
        ):
            tracks = ", ".join(sorted(
                track.value for track in course.permitted_student_tracks
            ))
            return f"course is restricted to {tracks} students"
        return None

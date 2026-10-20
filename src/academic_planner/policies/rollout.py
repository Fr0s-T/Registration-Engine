from dataclasses import dataclass, field

from academic_planner.domain.models import AcademicTerm, Course, CurriculumVersion


@dataclass(frozen=True)
class RolloutDecision:
    permitted: bool
    reason: str


@dataclass(frozen=True)
class ProgressiveRolloutPolicy:
    """NEW opens one additional reference year each year starting in 2023-24."""

    first_year_start: int = 2023
    explicit_overrides: dict[tuple[str, AcademicTerm], bool] = field(default_factory=dict)

    def new_curriculum_frontier(self, term: AcademicTerm) -> int:
        return max(0, min(5, term.academic_year_start - self.first_year_start + 1))

    def permits(self, course: Course, term: AcademicTerm) -> RolloutDecision:
        override = self.explicit_overrides.get((course.id, term))
        if override is not None:
            return RolloutDecision(override, "explicit offering override")
        new_max_year = self.new_curriculum_frontier(term)
        if course.curriculum_version is CurriculumVersion.NEW:
            allowed = course.reference_year <= new_max_year
            return RolloutDecision(allowed, f"NEW curriculum open through year {new_max_year}")
        allowed = course.reference_year > new_max_year
        return RolloutDecision(allowed, f"OLD curriculum retained above year {new_max_year}")

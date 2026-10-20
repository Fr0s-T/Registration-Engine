from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class SourceReference:
    document: str
    location: str


@dataclass(frozen=True)
class ParsedCourse:
    code: str
    title: str
    ects: int
    reference_year: int
    reference_semester: Literal["FALL", "SPRING", "TRAINING_1", "TRAINING_2"]
    source: SourceReference
    course_type: str = "COURSE"
    is_fyp: bool = False
    language_track: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ParsedPrerequisite:
    course_code: str
    prerequisite_codes: tuple[str, ...]
    logic: Literal["AND", "OR"]
    source_text: str
    source: SourceReference
    ambiguous: bool = False


@dataclass(frozen=True)
class ParsedLabRelationship:
    course_code: str
    lab_code: str
    mandatory: bool
    source: SourceReference


@dataclass
class ParsedCurriculum:
    curriculum_version: Literal["OLD", "NEW"]
    source_document: str
    source_revision: str
    courses: list[ParsedCourse] = field(default_factory=list)
    degree_requirements: list[str] = field(default_factory=list)
    prerequisite_rules: list[ParsedPrerequisite] = field(default_factory=list)
    lab_relationships: list[ParsedLabRelationship] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)
    stated_total_ects: int | None = None

    @property
    def total_ects(self) -> int:
        common = sum(course.ects for course in self.courses if course.language_track is None)
        by_track: dict[str, int] = {}
        for course in self.courses:
            if course.language_track:
                by_track[course.language_track] = by_track.get(course.language_track, 0) + course.ects
        # Language rows are alternative requirements. Count one complete track,
        # never both alternatives, when calculating curriculum totals.
        return common + (max(by_track.values()) if by_track else 0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ParsedCurriculum:
        def source(item: dict[str, Any]) -> SourceReference:
            return SourceReference(**item)
        courses = []
        for item in value.get("courses", []):
            item = dict(item); item["source"] = source(item["source"])
            courses.append(ParsedCourse(**item))
        prerequisites = []
        for item in value.get("prerequisite_rules", []):
            item = dict(item); item["source"] = source(item["source"])
            item["prerequisite_codes"] = tuple(item["prerequisite_codes"])
            prerequisites.append(ParsedPrerequisite(**item))
        labs = []
        for item in value.get("lab_relationships", []):
            item = dict(item); item["source"] = source(item["source"])
            labs.append(ParsedLabRelationship(**item))
        return cls(
            curriculum_version=value["curriculum_version"],
            source_document=value["source_document"],
            source_revision=value["source_revision"], courses=courses,
            degree_requirements=list(value.get("degree_requirements", [])),
            prerequisite_rules=prerequisites, lab_relationships=labs,
            validation_warnings=list(value.get("validation_warnings", [])),
            unresolved_items=list(value.get("unresolved_items", [])),
            stated_total_ects=value.get("stated_total_ects"),
        )


@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["FATAL", "WARNING"]
    code: str
    message: str
    source: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]
    term_totals: dict[str, int]
    total_ects: int

    @property
    def fatal_errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "FATAL")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "WARNING")

    @property
    def publishable(self) -> bool:
        return not self.fatal_errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "publishable": self.publishable,
            "fatal_errors": [asdict(i) for i in self.fatal_errors],
            "warnings": [asdict(i) for i in self.warnings],
            "term_totals": self.term_totals, "total_ects": self.total_ects,
        }

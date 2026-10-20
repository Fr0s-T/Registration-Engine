from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from academic_planner.domain.models import (
    AcademicTerm, Course, CourseEquivalency, CourseOffering, Curriculum,
    CurriculumVersion, DataProvenance, LanguageTrack, Meeting,
    PlanningConfiguration, PrerequisiteRule, RegistrationBundle, Section,
    StudentAcademicState, TermKind, Weekday,
)
from academic_planner.optimization import PlanningProblem

P = DataProvenance.SYNTHETIC_UNVERIFIED


class FixtureVariant(str, Enum):
    BASELINE = "baseline"
    RELAXED = "relaxed"


@dataclass(frozen=True)
class SyntheticFixtureConfiguration:
    prerequisite_variant: FixtureVariant = FixtureVariant.RELAXED
    timetable_variant: FixtureVariant = FixtureVariant.RELAXED

    @property
    def change_descriptions(self) -> tuple[str, ...]:
        changes: list[str] = []
        if self.prerequisite_variant is FixtureVariant.RELAXED:
            changes.extend((
                "CCE561 prerequisite changed from CSC437 to CSC333",
                "CCE650 prerequisite changed from CCE561 to CCE443",
            ))
        if self.timetable_variant is FixtureVariant.RELAXED:
            changes.append(
                "added a synthetic Thursday CCE431 section while preserving all baseline sections"
            )
        return tuple(changes)


BASELINE_FIXTURE = SyntheticFixtureConfiguration(
    FixtureVariant.BASELINE, FixtureVariant.BASELINE
)
RELAXED_FIXTURE = SyntheticFixtureConfiguration()

# code, title, ECTS, reference year, reference semester
NEW_ROWS = (
    ("CCE331", "Graph Theory and Operational Research", 3, 1, "F"),
    ("CHM224", "Chemistry for Engineering", 3, 1, "F"),
    ("CSC230", "Computer Fundamentals and Applications", 4, 1, "F"),
    ("MAT220", "Introduction to Linear Algebra", 5, 1, "F"),
    ("MAT230", "Introductory Calculus", 5, 1, "F"),
    ("PHY224", "Physics", 5, 1, "F"),
    ("PHY234", "Electricity and Magnetism", 5, 1, "F"),
    ("CSC320", "Introduction to Programming", 5, 1, "S"),
    ("DRH310", "Human Rights", 3, 1, "S"),
    ("ENG221", "Oral Expression Techniques", 4, 1, "S"),
    ("ENG222", "Techniques of Written Expression", 4, 1, "S"),
    ("GRD204", "Technical Drawing - CAD", 5, 1, "S"),
    ("MAT224", "Linear Algebra II", 4, 1, "S"),
    ("MAT231", "Calculus II", 5, 1, "S"),
    ("CCE321", "Introduction to Data Sciences", 2, 2, "F"),
    ("CCE340", "Analog Signal Processing", 4, 2, "F"),
    ("CSC340", "Data Structures and Algorithms", 5, 2, "F"),
    ("DRH320", "Ethics of the Profession", 2, 2, "F"),
    ("PHY235", "Engineering Mechanics", 5, 2, "F"),
    ("REL312", "Culture, Moral, Religion", 2, 2, "F"),
    ("SOC221", "Civic Engagement", 2, 2, "F"),
    ("STA222", "Probability and Statistics for Engineers", 4, 2, "F"),
    ("SYN-N-GEN04", "Unverified Unspecified Requirement", 4, 2, "F"),
    ("CCE330", "Logic Design", 5, 2, "S"),
    ("CCE341", "Analog Electronics I", 5, 2, "S"),
    ("CSC333", "Advanced Programming", 5, 2, "S"),
    ("MAT331", "Differential Equation and Vector Analysis", 5, 2, "S"),
    ("MAT343", "Numerical Analysis", 5, 2, "S"),
    ("PHY334", "Electric Circuits", 5, 2, "S"),
    ("CCE420", "Artificial Intelligence", 4, 3, "F"),
    ("CCE431", "Engineering Project Management", 3, 3, "F"),
    ("CCE432", "Operating Systems Engineering", 4, 3, "F"),
    ("CCE440", "Database System Design", 5, 3, "F"),
    ("CCE451", "Analog Electronics II", 5, 3, "F"),
    ("CSC437", "Software Engineering", 5, 3, "F"),
    ("SHM350", "Work Ready Now", 4, 3, "F"),
    ("CCE430", "Data Communication", 5, 3, "S"),
    ("CCE441", "Computer Architecture", 5, 3, "S"),
    ("CCE442", "Java EE", 5, 3, "S"),
    ("CCE443", "Network Essentials", 5, 3, "S"),
    ("CCE450", "Digital Signal Processing", 5, 3, "S"),
    ("CCE471", "Training I", 5, 3, "T1"),
    ("CCE540", "Cryptography and Network Security", 4, 4, "F"),
    ("CCE541", "Microwaves and Transmission Lines", 4, 4, "F"),
    ("CCE554", "Cybersecurity", 4, 4, "F"),
    ("CCE556", "Mobile Applications Development", 4, 4, "F"),
    ("CCE560", "Client Side Scripting", 4, 4, "F"),
    ("CCE561", "Server Side Scripting", 4, 4, "F"),
    ("CCE562", "Embedded System Design", 3, 4, "F"),
    ("CCE563", "Linux and Windows Networks Administration", 3, 4, "F"),
    ("CCE550", "Routing and Switching Concepts", 5, 4, "S"),
    ("CCE551", "Analog Communications", 5, 4, "S"),
    ("CCE552", "Microprocessor and Microcontroller", 5, 4, "S"),
    ("CCE553", "Client Server", 5, 4, "S"),
    ("CCE555", "Digital Communications", 5, 4, "S"),
    ("CCE572", "Training II", 5, 4, "T2"),
    ("CCE650", "Cloud and Internet of Things Applications", 4, 5, "F"),
    ("CCE651", "Multimedia and Quality of Service", 5, 5, "F"),
    ("CCE652", "Machine Learning", 4, 5, "F"),
    ("CCE654", "Telecommunication Systems", 4, 5, "F"),
    ("CCE655", "Fiber Optics Communications", 4, 5, "F"),
    ("CCE656", "Antennas and Waves Propagation", 5, 5, "F"),
    ("CCE657", "Wireless Communications", 4, 5, "F"),
    ("CCE640", "Image Processing", 5, 5, "S"),
    ("CCE653", "Mobile Networks", 4, 5, "S"),
    ("CCE660", "Thematic Seminar", 3, 5, "S"),
    ("CCE690", "Final Project", 18, 5, "S"),
)

OLD_ROWS = (
    ("ELCM119", "Calculus I", 5, 1, "F"), ("ELCM120", "Linear Algebra I", 5, 1, "F"),
    ("ELCM121", "General Physics", 5, 1, "F"), ("ELCM122", "Introduction to Computer", 5, 1, "F"),
    ("ELCM123", "Technical Drawing", 5, 1, "F"), ("SYN-O-REQ01", "Legacy Requirement 01", 5, 1, "F"),
    ("ELCM203", "Linear Algebra II", 4, 1, "S"), ("ELCM211", "Programming I (C)", 5, 1, "S"),
    ("ELCM212", "Calculus II", 5, 1, "S"), ("ELCM215", "Electricity and Magnetism", 4, 1, "S"),
    ("ELCM217", "Chemistry for Engineering", 4, 1, "S"), ("ENG108", "English Level B2", 8, 1, "S"),
    ("ART320", "Theory of Knowledge", 3, 2, "F"), ("DRH310", "Human Rights", 3, 2, "F"),
    ("ELBC403", "Analog Electronics I", 5, 2, "F"), ("ELCM312", "Programming II", 5, 2, "F"),
    ("ELCM317", "Differential Equations and Vector Analysis", 5, 2, "F"),
    ("ELCM319", "Economy for Engineers", 4, 2, "F"), ("ELCM412", "Numerical Analysis", 5, 2, "F"),
    ("ELBC401", "Logic Design", 5, 2, "S"), ("ELCC410", "Data Structures and Algorithms", 5, 2, "S"),
    ("ELCM318", "Probability and Statistics", 5, 2, "S"), ("ELCM320", "Electric Circuits", 5, 2, "S"),
    ("SYN-O-REQ02", "Legacy Requirement 02", 5, 2, "S"), ("SYN-O-REQ03", "Legacy Requirement 03", 5, 2, "S"),
    ("ELBC501", "Computer Organization", 4, 3, "F"), ("ELCC620", "Software Engineering", 4, 3, "F"),
    ("ELCC623", "Network Essentials", 5, 3, "F"), ("ELCC630", "Artificial Intelligence", 4, 3, "F"),
    ("ELCC631", "Operating Systems", 5, 3, "F"), ("ELCC632", "Computer Architecture", 3, 3, "F"),
    ("SYN-O-REQ04", "Legacy Requirement 04", 5, 3, "F"),
    ("ELBC404", "Analog Signal Processing", 4, 3, "S"), ("ELBC503", "Analog Electronics II", 5, 3, "S"),
    ("ELBC504", "Digital Signal Processing", 5, 3, "S"), ("ELCC524", "Database Systems", 5, 3, "S"),
    ("ELCC619", "OOP Using Java", 5, 3, "S"), ("SOC221", "Civic Engagement", 2, 3, "S"),
    ("ELCC608", "Training I", 4, 3, "T1"),
    ("CLEN321", "Advanced English I", 3, 4, "F"), ("ELBC801", "Project Management", 4, 4, "F"),
    ("ELCC712", "Analog Communications", 5, 4, "F"), ("ELCC722", "Microwaves", 3, 4, "F"),
    ("ELCC724", "Client-Side Scripting", 4, 4, "F"), ("ELCC820", "Network Administration Under Unix", 3, 4, "F"),
    ("ELCC822", "Fixed and Mobile Telephony", 4, 4, "F"), ("ELCC823", "Server-Side Scripting", 4, 4, "F"),
    ("CLEN521", "Communication Skills I", 3, 4, "S"), ("ELBC803", "Embedded Systems Design", 3, 4, "S"),
    ("ELCC711", "Routing and Switching Concepts", 5, 4, "S"), ("ELCC812", "Digital Communications", 5, 4, "S"),
    ("ELCC825", "Client/Server Computing", 5, 4, "S"), ("SYN-O-REQ05", "Legacy Requirement 05", 5, 4, "S"),
    ("ELCC819", "Training II", 4, 4, "T2"),
    ("ELBC901", "Image Processing", 5, 5, "F"), ("ELCC914", "Mobile Networks (GSM and UMTS)", 4, 5, "F"),
    ("ELCC916", "Multimedia and Quality of Service", 5, 5, "F"), ("ELCC919", "Fiber Optics Communication", 4, 5, "F"),
    ("ELCC923", "Data Analytics", 4, 5, "F"), ("ELCM900", "Final Project I", 8, 5, "F"),
    ("ELBC701", "Microprocessors and Microcontrollers", 6, 5, "S"), ("ELCC523", "Data Communication", 5, 5, "S"),
    ("SYN-O-FYP2", "Final Project II", 10, 5, "S"), ("SYN-O-REQ06", "Legacy Requirement 06", 5, 5, "S"),
    ("SYN-O-REQ07", "Legacy Requirement 07", 4, 5, "S"),
)

EQUIVALENT_CODES = (
    ("ELCM119", "MAT230"), ("ELCM120", "MAT220"), ("ELCM121", "PHY224"),
    ("ELCM122", "CSC230"), ("ELCM123", "GRD204"), ("ELCM203", "MAT224"),
    ("ELCM211", "CSC320"), ("ELCM212", "MAT231"), ("ELCM215", "PHY234"),
    ("ELCM217", "CHM224"), ("DRH310", "DRH310"), ("ELBC403", "CCE341"),
    ("ELCM312", "CSC333"), ("ELCM317", "MAT331"), ("ELCM412", "MAT343"),
    ("ELBC401", "CCE330"), ("ELCC410", "CSC340"), ("ELCM318", "STA222"),
    ("ELCM320", "PHY334"), ("ELCC620", "CSC437"), ("ELCC623", "CCE443"),
    ("ELCC630", "CCE420"), ("ELCC631", "CCE432"), ("ELCC632", "CCE441"),
    ("ELBC404", "CCE340"), ("ELBC503", "CCE451"), ("ELBC504", "CCE450"),
    ("ELCC524", "CCE440"), ("SOC221", "SOC221"), ("ELCC608", "CCE471"),
    ("ELBC801", "CCE431"), ("ELCC712", "CCE551"), ("ELCC722", "CCE541"),
    ("ELCC724", "CCE560"), ("ELCC820", "CCE563"), ("ELCC823", "CCE561"),
    ("ELBC803", "CCE562"), ("ELCC711", "CCE550"), ("ELCC812", "CCE555"),
    ("ELCC825", "CCE553"), ("ELCC819", "CCE572"), ("ELBC901", "CCE640"),
    ("ELCC914", "CCE653"), ("ELCC916", "CCE651"), ("ELCC919", "CCE655"),
    ("ELBC701", "CCE552"), ("ELCC523", "CCE430"),
)

# Explicit academic assumptions used only to exercise prerequisite behavior.
# Keys are dependent course codes; values are AND prerequisites. Relationships
# intentionally remain sparse where no meaningful assumption is available.
NEW_PREREQUISITES = {
    "MAT224": ("MAT220",), "MAT231": ("MAT230",),
    "CSC320": ("CSC230",), "CSC333": ("CSC320",), "CSC340": ("CSC320",),
    "MAT331": ("MAT231",), "MAT343": ("MAT231",), "PHY334": ("PHY234",),
    "CCE341": ("PHY234",), "CCE420": ("CSC340",), "CCE432": ("CSC333",),
    "CCE440": ("CSC340",), "CCE451": ("CCE341",), "CSC437": ("CSC333",),
    "CCE430": ("CCE340",), "CCE441": ("CCE330",), "CCE442": ("CSC333",),
    "CCE443": ("CSC340",), "CCE450": ("CCE340",), "CCE471": ("CCE430",),
    "CCE540": ("CCE430",), "CCE541": ("CCE430",), "CCE554": ("CCE440",),
    "CCE556": ("CSC437",), "CCE560": ("CSC333",), "CCE561": ("CSC437",),
    "CCE562": ("CCE441",), "CCE563": ("CCE432",), "CCE550": ("CCE443",),
    "CCE551": ("CCE340",), "CCE552": ("CCE441",), "CCE553": ("CCE440",),
    "CCE555": ("CCE450",), "CCE572": ("CCE550",), "CCE650": ("CCE561",),
    "CCE651": ("CCE555",), "CCE652": ("CCE420",), "CCE654": ("CCE555",),
    "CCE655": ("CCE555",), "CCE656": ("CCE541",), "CCE657": ("CCE555",),
    "CCE640": ("CCE450",),
    "CCE690": ("CCE431", "CSC437"),
}

# Minimal replacements for assumptions whose long serial chains lack a strong
# academic justification. Foundational dependencies remain intact. These are
# synthetic/unverified just like the baseline mappings.
RELAXED_NEW_PREREQUISITE_OVERRIDES = {
    "CCE561": ("CSC333",),
    "CCE650": ("CCE443",),
}

OLD_PREREQUISITES = {
    "ELCM203": ("ELCM120",), "ELCM211": ("ELCM122",), "ELCM212": ("ELCM119",),
    "ELCM215": ("ELCM121",), "ELBC403": ("ELCM215",), "ELCM312": ("ELCM211",),
    "ELCM317": ("ELCM212",), "ELCM412": ("ELCM212",), "ELBC401": ("ELCM122",),
    "ELCC410": ("ELCM211",), "ELCM318": ("ELCM212",), "ELCM320": ("ELCM215",),
    "ELBC501": ("ELBC401",), "ELCC620": ("ELCM312",), "ELCC623": ("ELCC410",),
    "ELCC630": ("ELCC410",), "ELCC631": ("ELCM312",), "ELCC632": ("ELBC501",),
    "ELBC404": ("ELCM320",), "ELBC503": ("ELBC403",), "ELBC504": ("ELBC404",),
    "ELCC524": ("ELCC410",), "ELCC619": ("ELCM312",), "ELCC608": ("ELCC623",),
    "ELBC801": ("ELCC620",), "ELCC712": ("ELBC404",), "ELCC722": ("ELBC404",),
    "ELCC724": ("ELCC619",), "ELCC820": ("ELCC623",), "ELCC822": ("ELCC623",),
    "ELCC823": ("ELCC619",), "ELBC803": ("ELCC632",), "ELCC711": ("ELCC623",),
    "ELCC812": ("ELBC504",), "ELCC825": ("ELCC524",), "ELCC819": ("ELCC711",),
    "ELBC901": ("ELBC504",), "ELCC914": ("ELCC711",), "ELCC916": ("ELCC812",),
    "ELCC919": ("ELCC812",), "ELCC923": ("ELCC524",),
    "ELCM900": ("ELBC801", "ELCC608"), "ELBC701": ("ELBC803",),
    "ELCC523": ("ELCC623",), "SYN-O-FYP2": ("ELCM900", "ELCC819"),
}

# Exact reference A-section slots transcribed from the five Fall 2026 PDFs.
FALL_2026_SLOTS = {
    "CCE331": (0, 480, 630), "CHM224": (0, 660, 810), "CSC230": (0, 840, 990),
    "MAT220": (1, 480, 630), "MAT230": (1, 660, 810), "PHY224": (1, 840, 990), "PHY234": (2, 480, 630),
    "CCE321": (0, 480, 630), "CCE340": (0, 660, 810), "CSC340": (0, 840, 990),
    "DRH320": (1, 480, 630), "PHY235": (1, 660, 810), "REL312": (1, 840, 990),
    "SOC221": (2, 480, 630), "STA222": (2, 660, 810), "SYN-N-GEN04": (2, 840, 990),
    "CCE420": (0, 480, 630), "CCE431": (0, 660, 810), "CCE432": (0, 840, 990),
    "CCE440": (1, 480, 630), "CCE451": (1, 660, 810), "CSC437": (1, 840, 990), "SHM350": (2, 480, 630),
    "CCE541": (0, 480, 630), "CCE554": (0, 660, 810), "CCE556": (0, 840, 990),
    "CCE540": (1, 480, 630), "CCE560": (1, 660, 810), "CCE561": (1, 840, 990),
    "CCE562": (2, 480, 630), "CCE563": (2, 660, 810),
    "ELCC919": (0, 480, 630), "ELCC916": (2, 660, 915), "ELCC914": (3, 480, 630),
    "ELBC901": (3, 660, 810), "ELCC923": (3, 840, 990), "ELCM900": (5, 480, 720),
}


@dataclass(frozen=True)
class SeededPlanningData:
    courses: dict[str, Course]
    curricula: dict[CurriculumVersion, Curriculum]
    prerequisites: tuple[PrerequisiteRule, ...]
    equivalencies: tuple[CourseEquivalency, ...]
    offerings: tuple[CourseOffering, ...]
    demo_student: StudentAcademicState
    demo_configuration: PlanningConfiguration
    fixture_configuration: SyntheticFixtureConfiguration = RELAXED_FIXTURE

    def demo_problem(self) -> PlanningProblem:
        return PlanningProblem(
            self.courses,
            self.curricula[CurriculumVersion.NEW],
            self.demo_student,
            self.equivalencies,
            self.prerequisites,
            self.offerings,
            self.demo_configuration,
        )


class SyntheticFixtureLoader:
    """Builds replaceable in-memory fixtures transcribed from the supplied PDFs."""

    def load(
        self,
        entry_year: int = 2026,
        configuration: SyntheticFixtureConfiguration = RELAXED_FIXTURE,
    ) -> SeededPlanningData:
        courses = self._courses()
        curricula = self._curricula(courses)
        prerequisites = self._prerequisites(courses, configuration.prerequisite_variant)
        equivalencies = self._equivalencies()
        horizon = self._horizon(entry_year)
        offerings = self._offerings(courses, horizon, configuration.timetable_variant)
        capacities = {
            term: (5 if term.kind in {TermKind.TRAINING_1, TermKind.TRAINING_2} else 30)
            for term in horizon
        }
        config = PlanningConfiguration(
            term_credit_capacities=capacities,
            planning_horizon=horizon,
            default_credit_capacity=30,
        )
        return SeededPlanningData(
            courses, curricula, prerequisites, equivalencies, offerings,
            StudentAcademicState(1, LanguageTrack.EN), config, configuration,
        )

    @staticmethod
    def _courses() -> dict[str, Course]:
        result: dict[str, Course] = {}
        for version, rows in ((CurriculumVersion.NEW, NEW_ROWS), (CurriculumVersion.OLD, OLD_ROWS)):
            for code, name, credits, year, semester in rows:
                # Training is a separate period but remains positioned after its reference Spring.
                reference = TermKind.FALL if semester == "F" else TermKind.SPRING
                cid = f"{version.value}:{code}"
                result[cid] = Course(cid, code, name, credits, version, year, reference, "FYP" in code or code in {"CCE690", "ELCM900"}, P)
        return result

    @staticmethod
    def _curricula(courses: dict[str, Course]) -> dict[CurriculumVersion, Curriculum]:
        by_version = {
            version: frozenset(c.id for c in courses.values() if c.curriculum_version is version)
            for version in CurriculumVersion
        }
        return {
            CurriculumVersion.NEW: Curriculum(
                CurriculumVersion.NEW, by_version[CurriculumVersion.NEW], 300,
                "NEW:CCE690", frozenset({"NEW:CCE471", "NEW:CCE572"}),
                {LanguageTrack.EN: frozenset({"NEW:ENG221", "NEW:ENG222"})},
            ),
            CurriculumVersion.OLD: Curriculum(
                CurriculumVersion.OLD, by_version[CurriculumVersion.OLD], 300,
                "OLD:SYN-O-FYP2", frozenset({"OLD:ELCC608", "OLD:ELCC819"}),
                {LanguageTrack.EN: frozenset({"OLD:ENG108", "OLD:CLEN321", "OLD:CLEN521"})},
            ),
        }

    @staticmethod
    def _prerequisites(
        courses: dict[str, Course], variant: FixtureVariant
    ) -> tuple[PrerequisiteRule, ...]:
        rules: list[PrerequisiteRule] = []
        new_mapping = dict(NEW_PREREQUISITES)
        if variant is FixtureVariant.RELAXED:
            new_mapping.update(RELAXED_NEW_PREREQUISITE_OVERRIDES)
        for version, mapping in (
            (CurriculumVersion.NEW, new_mapping),
            (CurriculumVersion.OLD, OLD_PREREQUISITES),
        ):
            for dependent, prerequisites in mapping.items():
                dependent_id = f"{version.value}:{dependent}"
                prerequisite_ids = frozenset(f"{version.value}:{code}" for code in prerequisites)
                if dependent_id not in courses or not prerequisite_ids <= courses.keys():
                    raise ValueError(f"synthetic prerequisite mapping references an unknown {version.value} course")
                rules.append(PrerequisiteRule(dependent_id, prerequisite_ids, P))
        return tuple(rules)

    @staticmethod
    def _equivalencies() -> tuple[CourseEquivalency, ...]:
        result: list[CourseEquivalency] = []
        for old, new in EQUIVALENT_CODES:
            old_id, new_id = f"OLD:{old}", f"NEW:{new}"
            result.append(CourseEquivalency(f"SYN:{old}:{new}:O2N", frozenset({old_id}), frozenset({new_id}), P))
            result.append(CourseEquivalency(f"SYN:{old}:{new}:N2O", frozenset({new_id}), frozenset({old_id}), P))
        return tuple(result)

    @staticmethod
    def _horizon(entry_year: int) -> tuple[AcademicTerm, ...]:
        terms: list[AcademicTerm] = []
        for year in range(1, 11):
            academic_year = entry_year + year - 1
            terms.extend((AcademicTerm(academic_year, TermKind.FALL), AcademicTerm(academic_year, TermKind.SPRING)))
            if year == 3:
                terms.append(AcademicTerm(academic_year, TermKind.TRAINING_1))
            if year == 4:
                terms.append(AcademicTerm(academic_year, TermKind.TRAINING_2))
        return tuple(terms)

    def _offerings(
        self,
        courses: dict[str, Course],
        horizon: tuple[AcademicTerm, ...],
        timetable_variant: FixtureVariant,
    ) -> tuple[CourseOffering, ...]:
        offerings: list[CourseOffering] = []
        current = horizon[0]
        training_ids = {
            "NEW:CCE471": TermKind.TRAINING_1, "NEW:CCE572": TermKind.TRAINING_2,
            "OLD:ELCC608": TermKind.TRAINING_1, "OLD:ELCC819": TermKind.TRAINING_2,
        }
        years = sorted({term.academic_year_start for term in horizon})
        candidate_terms = tuple(dict.fromkeys(
            (*horizon, *(AcademicTerm(year, kind) for year in years for kind in (TermKind.TRAINING_1, TermKind.TRAINING_2)))
        ))
        for course in courses.values():
            for term in candidate_terms:
                expected_kind = training_ids.get(course.id, course.reference_semester)
                if term.kind is not expected_kind:
                    continue
                bundles = (
                    self._current_bundles(course, timetable_variant)
                    if term == current else ()
                )
                offerings.append(CourseOffering(course.id, term, bundles, False, P))
        return tuple(offerings)

    @staticmethod
    def _current_bundles(
        course: Course, timetable_variant: FixtureVariant
    ) -> tuple[RegistrationBundle, ...]:
        slot = FALL_2026_SLOTS.get(course.code)
        if slot is None:
            return ()
        day, start, end = slot
        sections = [Section(f"SYN-{course.code}-A-LEC", course.id, "LECTURE", "Werdaniyeh", (Meeting(Weekday(day), start, end),), None, P)]
        if course.id == "OLD:ELBC901":
            sections.append(Section("SYN-ELBC901L-A-LAB", course.id, "LAB:ELBC901L", "Werdaniyeh", (Meeting(Weekday.FRIDAY, 660, 810),), .2, P))
        alternative = [Section(f"SYN-{course.code}-B-LEC", course.id, "LECTURE", "Werdaniyeh", (Meeting(Weekday(day), start + 30, end + 30),), None, P)]
        if course.id == "OLD:ELBC901":
            alternative.append(Section("SYN-ELBC901L-B-LAB", course.id, "LAB:ELBC901L", "Werdaniyeh", (Meeting(Weekday.FRIDAY, 690, 840),), .2, P))
        bundles = [
            RegistrationBundle(f"SYN-{course.id}-A", course.id, tuple(sections)),
            RegistrationBundle(f"SYN-{course.id}-B", course.id, tuple(alternative)),
        ]
        if timetable_variant is FixtureVariant.RELAXED and course.id == "NEW:CCE431":
            bundles.append(RegistrationBundle(
                "SYN-NEW:CCE431-RELAXED-C",
                course.id,
                (Section(
                    "SYN-CCE431-RELAXED-C-LEC",
                    course.id,
                    "LECTURE",
                    "Werdaniyeh",
                    (Meeting(Weekday.THURSDAY, 480, 630),),
                    None,
                    P,
                ),),
            ))
        return tuple(bundles)

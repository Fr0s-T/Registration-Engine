from collections import defaultdict

from .models import Course, CourseEquivalency, PrerequisiteRule


def validate_catalog(courses: dict[str, Course], prerequisites: tuple[PrerequisiteRule, ...], equivalencies: tuple[CourseEquivalency, ...]) -> None:
    if len(courses) != len(set(courses)):
        raise ValueError("duplicate course IDs")
    graph: dict[str, set[str]] = defaultdict(set)
    for rule in prerequisites:
        if rule.course_id not in courses or not rule.all_of <= courses.keys():
            raise ValueError("prerequisite references unknown course")
        graph[rule.course_id].update(rule.all_of)
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("prerequisite cycle detected")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)
    for course_id in courses:
        visit(course_id)
    seen_sources: dict[str, frozenset[str]] = {}
    for eq in equivalencies:
        for source in eq.source_course_ids:
            previous = seen_sources.get(source)
            if previous is not None and previous != eq.target_requirement_ids:
                raise ValueError(f"contradictory equivalency for {source}")
            seen_sources[source] = eq.target_requirement_ids

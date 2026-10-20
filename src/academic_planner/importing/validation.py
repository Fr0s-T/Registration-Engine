from __future__ import annotations

from collections import Counter, defaultdict

from .models import ParsedCurriculum, ValidationIssue, ValidationReport


def validate_curriculum(parsed: ParsedCurriculum) -> ValidationReport:
    issues: list[ValidationIssue] = []
    codes = [course.code.strip().upper() for course in parsed.courses]
    counts = Counter(codes)
    known = set(codes)
    for code, count in sorted(counts.items()):
        if not code:
            issues.append(ValidationIssue("FATAL", "MISSING_CODE", "A course code is missing."))
        elif count > 1:
            issues.append(ValidationIssue("FATAL", "DUPLICATE_COURSE", f"Course {code} occurs {count} times."))
    if not parsed.courses:
        issues.append(ValidationIssue("FATAL", "EMPTY_CURRICULUM", "No course rows were parsed."))
    for course in parsed.courses:
        where = course.source.location
        if course.ects < 0 or course.ects > 60:
            issues.append(ValidationIssue("FATAL", "INVALID_ECTS", f"{course.code} has invalid ECTS {course.ects}.", where))
        if course.reference_year not in range(1, 6):
            issues.append(ValidationIssue("FATAL", "INVALID_YEAR", f"{course.code} has invalid reference year.", where))
        if course.reference_semester not in {"FALL", "SPRING", "TRAINING_1", "TRAINING_2"}:
            issues.append(ValidationIssue("FATAL", "INVALID_SEMESTER", f"{course.code} has invalid reference semester.", where))
    graph: dict[str, set[str]] = defaultdict(set)
    prerequisite_owner_counts = Counter(
        rule.course_code for rule in parsed.prerequisite_rules
    )
    for code, count in sorted(prerequisite_owner_counts.items()):
        if count > 1:
            issues.append(ValidationIssue(
                "FATAL",
                "DUPLICATE_PREREQUISITE_GROUP",
                f"Course {code} has {count} prerequisite groups; exactly one is supported.",
            ))
    for rule in parsed.prerequisite_rules:
        where = rule.source.location
        if rule.course_code not in known:
            issues.append(ValidationIssue("FATAL", "UNKNOWN_PREREQUISITE_OWNER", f"Prerequisite owner {rule.course_code} is not a course.", where))
        missing = sorted(set(rule.prerequisite_codes) - known)
        if missing:
            issues.append(ValidationIssue("FATAL", "BROKEN_PREREQUISITE", f"{rule.course_code} references unknown course(s): {', '.join(missing)}.", where))
        if rule.ambiguous:
            issues.append(ValidationIssue("WARNING", "AMBIGUOUS_PREREQUISITE", f"Review prerequisite for {rule.course_code}: {rule.source_text}", where))
        for prerequisite in rule.prerequisite_codes:
            graph[rule.course_code].add(prerequisite)
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(node: str, path: list[str]) -> None:
        if node in visiting:
            cycle = path[path.index(node):] + [node]
            issues.append(ValidationIssue("FATAL", "PREREQUISITE_CYCLE", "Prerequisite cycle: " + " -> ".join(cycle)))
            return
        if node in visited: return
        visiting.add(node)
        for child in sorted(graph.get(node, ())): visit(child, path + [child])
        visiting.remove(node); visited.add(node)
    for code in sorted(graph): visit(code, [code])
    for relation in parsed.lab_relationships:
        if relation.course_code not in known or relation.lab_code not in known:
            issues.append(ValidationIssue("FATAL", "BROKEN_LAB_RELATIONSHIP", f"Lab relationship {relation.course_code} / {relation.lab_code} does not resolve.", relation.source.location))
    required = set(parsed.degree_requirements)
    missing_requirements = required - known
    if missing_requirements:
        issues.append(ValidationIssue("FATAL", "BROKEN_REQUIREMENT", f"Unknown degree requirement(s): {', '.join(sorted(missing_requirements))}."))
    if not required:
        issues.append(ValidationIssue("WARNING", "NO_REQUIREMENTS", "No explicit degree requirements were parsed; all parsed courses will be imported as requirements."))
    for warning in parsed.validation_warnings:
        issues.append(ValidationIssue("WARNING", "SOURCE_WARNING", warning))
    for unresolved in parsed.unresolved_items:
        issues.append(ValidationIssue("WARNING", "UNRESOLVED_SOURCE_ITEM", unresolved))
    total = parsed.total_ects
    if parsed.stated_total_ects is not None and parsed.stated_total_ects != total:
        issues.append(ValidationIssue("WARNING", "CREDIT_TOTAL_MISMATCH", f"Calculated {total} ECTS; document states {parsed.stated_total_ects} ECTS."))
    common_totals: dict[str, int] = defaultdict(int)
    track_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for course in parsed.courses:
        term = f"Y{course.reference_year}_{course.reference_semester}"
        if course.language_track:
            track_totals[term][course.language_track] += course.ects
        else:
            common_totals[term] += course.ects
    totals = {term: common_totals[term] + (max(track_totals[term].values()) if track_totals[term] else 0)
              for term in set(common_totals) | set(track_totals)}
    return ValidationReport(tuple(issues), dict(sorted(totals.items())), total)

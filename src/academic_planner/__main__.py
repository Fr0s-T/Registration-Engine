from __future__ import annotations

import argparse
from dataclasses import replace
import logging

from academic_planner.eligibility import EligibilityEngine, RejectionCode
from academic_planner.diagnostics import (
    build_plan_audit, log_plan_audit, run_elbc901_cce640_experiment,
)
from academic_planner.fixtures import (
    FixtureVariant, SyntheticFixtureConfiguration, build_scenario,
    compare_struggling_fixture_variants, list_scenarios,
)
from academic_planner.optimization import GlobalPlanner
from academic_planner.policies import (
    AllowAllRegistrationPolicy, ConfiguredCreditLimitPolicy, ProgressiveRolloutPolicy,
)
from academic_planner.reconciliation import ReconciliationService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run synthetic academic-planning scenarios")
    parser.add_argument("--scenario", choices=tuple(list_scenarios()), default="fresh")
    parser.add_argument("--capacity", type=int, help="unverified regular-term planning capacity")
    parser.add_argument("--list-scenarios", action="store_true")
    parser.add_argument(
        "--prerequisites", choices=tuple(item.value for item in FixtureVariant),
        default=FixtureVariant.RELAXED.value,
    )
    parser.add_argument(
        "--timetable", choices=tuple(item.value for item in FixtureVariant),
        default=FixtureVariant.RELAXED.value,
    )
    parser.add_argument(
        "--compare-fixtures", action="store_true",
        help="run the controlled A-D struggling-student fixture comparison",
    )
    parser.add_argument(
        "--prospective-equivalency-experiment", action="store_true",
        help="compare approved OLD ELBC901 registration against native NEW CCE640",
    )
    parser.add_argument(
        "--conditional-repeat-load", action="store_true",
        help="allow up to 36 ECTS only in a regular term selecting an unresolved failed repeat",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="emit a semester-by-semester planning audit",
    )
    parser.add_argument(
        "--debug-course",
        help="trace one course code or unique course ID across the solved horizon",
    )
    parser.add_argument(
        "--log-file",
        help="write diagnostic logging to this file (enables debug diagnostics)",
    )
    return parser


def _time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def main() -> None:
    args = _parser().parse_args()
    diagnostics_enabled = bool(args.debug or args.debug_course or args.log_file)
    if diagnostics_enabled:
        logger = logging.getLogger("academic_planner")
        logger.handlers.clear()
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        formatter = logging.Formatter("%(levelname)s %(name)s: %(message)s")
        handlers: list[logging.Handler] = [logging.StreamHandler()]
        if args.log_file:
            handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
        for handler in handlers:
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    if args.list_scenarios:
        for identifier, description in list_scenarios().items():
            print(f"{identifier}: {description}")
        return
    if args.compare_fixtures:
        print(
            "Run Policy Prerequisites Timetable Pool Max Selected/Cap Graduation "
            "Regular Status"
        )
        for result in compare_struggling_fixture_variants():
            policy = "conditional36" if result.conditional_repeat_allowance else "normal30"
            print(
                f"{result.experiment:>3} {policy:>13} "
                f"{result.prerequisite_variant:>13} {result.timetable_variant:>9} "
                f"{result.eligible_course_count}/{result.eligible_credits:<3} "
                f"{result.maximum_schedulable_credits:>3} "
                f"{result.selected_current_credits:>8}/{result.current_effective_capacity:<3} "
                f"{result.graduation_term or '-':>17} "
                f"{result.remaining_regular_semesters:>7} {result.solver_status}"
            )
        return
    if args.prospective_equivalency_experiment:
        result = run_elbc901_cce640_experiment()
        print("Synthetic prospective equivalency: OLD ELBC901 -> NEW CCE640")
        print(f"Baseline graduation: {result.baseline_graduation_term}")
        print(
            "Optional-equivalency graduation: "
            f"{result.optional_experiment_graduation_term}"
        )
        print(
            "ELBC901 selected: "
            f"{'YES' if result.optional_selected_registration_course else 'NO'}"
        )
        print(f"ELBC901 registration term: {result.forced_registration_term or '-'}")
        print(
            "Selected bundle components: "
            + (", ".join(result.forced_selected_bundle_components) or "-")
        )
        print(
            "Solver status: baseline="
            f"{result.baseline_solver_status}, substitution="
            f"{result.forced_substitution_solver_status}"
        )
        return
    if args.capacity is not None and args.capacity < 0:
        raise SystemExit("--capacity cannot be negative")

    fixture_configuration = SyntheticFixtureConfiguration(
        FixtureVariant(args.prerequisites), FixtureVariant(args.timetable)
    )
    scenario = build_scenario(
        args.scenario, args.capacity, fixture_configuration
    )
    if args.conditional_repeat_load:
        scenario = replace(
            scenario,
            data=replace(
                scenario.data,
                demo_configuration=replace(
                    scenario.data.demo_configuration,
                    allow_extended_load_when_repeating_failed_course=True,
                ),
            ),
        )
    data = scenario.data
    problem = data.demo_problem()
    rollout = ProgressiveRolloutPolicy()
    registration = AllowAllRegistrationPolicy()
    reconciliation = ReconciliationService().reconcile(
        problem.student, problem.curriculum, problem.equivalencies
    )
    current = scenario.starting_term
    applicable_courses = {
        cid: data.courses[cid]
        for cid in problem.curriculum.resolved_requirements(problem.student.language_track)
    }
    pool = EligibilityEngine(rollout, registration).build_pool(
        problem.student,
        current,
        applicable_courses,
        reconciliation.outstanding_requirement_ids,
        reconciliation.prerequisite_completion_ids,
        problem.prerequisites,
        problem.offerings,
    )
    planner = GlobalPlanner(ConfiguredCreditLimitPolicy(), rollout, registration)
    plan = planner.plan(problem)
    if diagnostics_enabled:
        audit = build_plan_audit(problem, plan, rollout, registration)
        try:
            log_plan_audit(audit, args.debug_course)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

    print(f"Scenario: {scenario.identifier}")
    print(
        "Fixture: prerequisites="
        f"{fixture_configuration.prerequisite_variant.value}, timetable="
        f"{fixture_configuration.timetable_variant.value}"
    )
    print(f"Profile: {scenario.description}")
    print(f"Nominal year: {problem.student.nominal_year}")
    print(f"Starting term: {current.label()}")
    print(f"Completed credits: {reconciliation.official_earned_credits}")
    remaining_credits = sum(data.courses[c].credits for c in reconciliation.outstanding_requirement_ids)
    print(f"Remaining credits: {remaining_credits}")
    limits = ", ".join(
        f"{term.label()}={problem.configuration.capacity_for(term)}"
        for term in problem.configuration.planning_horizon
    )
    print(f"Credit limits: {limits}")
    print("Current EligibleCoursePool:")
    for course in pool.courses:
        print(f"  {course.code} - {course.name} ({course.credits} ECTS)")
    print("Blocked current-term candidates:")
    relevant_rejections = [r for r in pool.rejections if r.code is not RejectionCode.ALREADY_SATISFIED]
    if not relevant_rejections:
        print("  -")
    for rejection in relevant_rejections:
        course = data.courses[rejection.course_id]
        print(f"  {course.code}: {rejection.code.value} - {rejection.detail}")

    current_schedule = plan.scheduled_terms[0] if plan.scheduled_terms else None
    print("Selected current-semester courses and sections:")
    if current_schedule:
        bundle_map = {bundle.id: bundle for offering in problem.offerings for bundle in offering.bundles}
        for course_id in current_schedule.course_ids:
            course = data.courses[course_id]
            selected = next((bundle_map[b] for b in current_schedule.bundle_ids if bundle_map[b].course_id == course_id), None)
            print(f"  {course.code} - {course.name}")
            if selected:
                for section in selected.sections:
                    meetings = ", ".join(
                        f"{meeting.weekday.name.title()} {_time(meeting.start_minute)}-{_time(meeting.end_minute)}"
                        for meeting in section.meetings
                    )
                    print(f"    {section.component} {section.crn}: {meetings}")
    else:
        print("  -")

    print("Projected future courses:")
    usage_by_term = {usage.term: usage for usage in plan.credit_usages}
    for scheduled in plan.scheduled_terms[1:]:
        codes = [data.courses[c].code for c in scheduled.course_ids]
        usage = usage_by_term.get(scheduled.term)
        capacity = (
            f"{usage.selected_credits}/{usage.effective_capacity} ECTS; {usage.reason}"
            if usage else "capacity unavailable"
        )
        print(f"  {scheduled.term.label()}: {', '.join(codes) if codes else '-'} [{capacity}]")
    print(f"Projected graduation: {plan.graduation_term.label() if plan.graduation_term else '-'}")
    print(f"Solver status: {plan.status.value}")
    for warning in plan.warnings:
        print(f"WARNING: {warning}")
    if args.capacity and args.capacity > 30:
        print("WARNING: configured capacity is a planning assumption, not verified administrative approval")


if __name__ == "__main__":
    main()

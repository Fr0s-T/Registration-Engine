# Optimizer

`academic_planner.optimization.planner.GlobalPlanner` builds one CP-SAT model for
current registration and future graduation projection. This document describes the
checked-in formulation and objective ordering. The ordering is behavior: reordering
collections, variables, constraints, or stages can change selected courses and terms.

## Inputs and horizon lifecycle

A `PlanningProblem` contains the catalog, governing curriculum, normalized student
state, accepted equivalencies, prerequisites, offerings, configuration, optional
approvals, contract credit groups, and strict/exploratory flags.

Reconciliation occurs once before horizon search. The planner counts regular Fall
and Spring terms; training periods do not consume that count. It first solves the
configured initial number of regular semesters. After proven infeasibility it may
extend by `horizon_extension_step` up to the smaller of the configured maximum and
available calendar. An `UNKNOWN` result is inconclusive and stops extension. A
feasible result at the first workable horizon is returned.

## Course-pool construction

The model starts with:

- every delivery identity for an outstanding governing requirement;
- every admissible approved optional course (plus unverified options only in
  exploratory mode); and
- the transitive prerequisite closure of those courses when definitions exist.

Completed courses, completed equivalents, and mandatory-delivery identities are
removed from the optional pool. Added prerequisite-only courses are auxiliary and do
not gain graduation-credit authority.

Mandatory requirements and optional/auxiliary IDs are sorted at their current code
sites before variable construction. That order must be preserved unless exact
equivalence is demonstrated.

## Decision variables

- `x[course_id, term_index]`: Boolean; the course is selected in that term.
- `graduation_index`: integer index of the last period containing selected modeled
  coursework after minimization.
- `administrative_credit_adjustment`: integer residual credit proposal, bounded by
  the remaining target and fixed to zero when proposals are disabled.
- Current-term bundle Booleans: exactly one complete registration bundle for each
  selected current course.
- Capacity activation variables for the failed-repeat and final-two-semester rules.
- Current-day Booleans used by the final campus-day preference.

## Hard constraints

### Availability, rollout, and registration

A course-term variable is zero when the offering is absent, progressive rollout
rejects the course, or the registration policy rejects the student/course/term.
Each course can occur at most once.

Every outstanding requirement must select exactly one of its delivery identities.
If one delivery identity ambiguously owns multiple outstanding requirements, model
construction stops with an infeasible diagnostic. When multiple sides of an accepted
equivalency are in the course pool, at most one may be selected.

### Accepted credit and contract groups

The accepted-credit expression includes scheduled mandatory delivery and authorized
optional course ECTS plus any provisional adjustment. Auxiliary prerequisite credit
is excluded. The expression must reach the remaining target.

Each contract credit group separately requires at least its remaining quota from its
explicit `course_credits` mapping. Global accepted credit cannot conceal a deficient
group.

Before building the full solve, the planner rejects a strict plan when the maximum
mandatory delivery credit plus all admissible optional credit cannot reach the
remaining target and adjustment proposals are disabled.

### Prerequisites

A prerequisite must be in the reconciliation completion set or scheduled in a
strictly earlier term. Same-term corequisites are not inferred. A dependent course
is disabled when an uncompleted prerequisite has no course definition in the pool.

### Capacity

Each period's selected course ECTS is bounded by its effective capacity.

- Training periods use their configured period capacity.
- An explicit per-term override prevents conditional regular-term bonuses.
- When enabled, a failed-repeat bonus is available only in a regular term that
  actually selects an unresolved failed mandatory requirement.
- When enabled, a final-two-semester bonus can be activated only when graduation is
  within the modeled final two regular semesters relative to that term.
- Multiple conditional bonuses use a maximum, not a sum, so they do not stack.

Reporting applies the implemented precedence: training period, explicit override,
failed-repeat allowance, final-two-semester allowance when selected credits exceed
the base, then normal capacity. A non-default global capacity is simply the base
capacity and is not proof of administrative approval.

The provisional administrative credit adjustment participates in accepted-credit
accounting but, in the current implementation, does not consume term capacity.

### Training and FYP

Outstanding training requirements may use only training kinds present in their
supplied offerings. Training cannot occur before its normal year. Postponement and a
maximum delay are configuration-controlled; delay contributes a later objective.

FYP pathway selection occurs before optimization. The optimizer schedules the
resulting explicit FYP requirements and does not choose a curriculum pathway itself.

### Current timetable

The first horizon period is exact. A selected current course must choose exactly one
complete supplied bundle; a course without bundles is disabled for the current
period. Pairwise bundle conflicts use overlapping meetings on the same weekday.
Future offerings contain availability only and do not fabricate sections or meeting
times.

Forced course-term assignments are hard constraints. A forced course outside the
pool or a term outside the horizon returns infeasible.

## Exact lexicographic objectives

The solver processes the following stages in this exact order. After each successful
stage it reads the achieved integer value and constrains that expression to equality
before introducing the next stage.

1. Minimize total accepted scheduled credit plus provisional adjustment. This avoids
   unnecessary excess above the remaining target.
2. Minimize the provisional administrative adjustment, preferring real coursework
   when the accepted-credit footprint is equal.
3. Minimize `graduation_index`.
4. Minimize use of final-two-semester capacity activations.
5. Maximize current mandatory ECTS for requirements with no verified later delivery.
6. Maximize current mandatory ECTS that repeat an unresolved failed requirement.
7. Maximize current mandatory backlog priority: year gap multiplied by current
   delivery ECTS.
8. Maximize all current mandatory ECTS.
9. Maximize early placement of mandatory delivery ECTS across the horizon, weighted
   by `len(terms) - term_index`.
10. Minimize weighted training delay.
11. Minimize cross-curriculum selections used to deliver mandatory requirements.
12. Maximize optional-course squared-credit priority. At equal accepted total this
    prefers larger-credit components while still allowing a smaller prerequisite
    when it unlocks the preferred course.
13. Minimize current-term academic-year and reference-semester misalignment.
14. Minimize that alignment penalty across all terms.
15. Maximize total current-term selected ECTS.
16. Maximize early placement of all selected course ECTS.
17. Minimize the count of selected optional and auxiliary courses.
18. When `prefer_own_track_sections` is true, minimize current bundles containing an
    alternate teaching language.
19. Minimize the number of weekdays used by current bundles.

This is the current ordering, including the recent backlog, scarcity, failed-repeat,
mandatory-before-optional, and governing-curriculum semantics. Older objective lists
must not be used as a reference.

Academic-year alignment uses the student's nominal year plus the elapsed academic
years from the first horizon term. Reference-semester mismatch is waived for training
requirements. Both penalties use the configured nonnegative weights.

## Solver parameters and statuses

One `CpSolver` instance is reused across stages. The only parameter assigned by the
planner is `max_time_in_seconds`, recalculated from one wall-clock budget shared by
all stages. Other OR-Tools parameters remain at the installed library defaults.

- `OPTIMAL`: every reached stage was proven optimal and the last solve returned
  optimal within the shared budget.
- `FEASIBLE_NOT_PROVEN_OPTIMAL`: CP-SAT returned a feasible solution but at least one
  stage was not proven optimal, or the shared budget ended between stages after a
  solution was obtained.
- `INFEASIBLE`: CP-SAT proved infeasibility or a model precondition returned an
  infeasible plan.
- `UNKNOWN`: search ended without a feasible solution or proof of infeasibility.

"Optimal" is always relative to the supplied horizon, offerings, approvals, and
configuration. Unverified future offerings used by a returned plan generate a
warning.

## Output construction

Scheduled course IDs follow `planning_courses` order; current bundle IDs follow the
supplied bundle order. The graduation term is `terms[graduation_index]`. The planner
also reports selected optional IDs, per-term credit usage and capacity reason,
hypothetical status, provisional credit adjustment, and warnings for unverified
future data, synthetic current sections, and alternate-track selection.

## Safe maintenance boundary

Comments, type annotations, and helper extraction are safe only if they leave
iteration and model-construction order unchanged. Changes to any of the following
require exact regression comparison: course-pool ordering, variable creation,
constraint construction, objective expressions or order, solver defaults, section
bundle order, status mapping, and horizon stopping rules.

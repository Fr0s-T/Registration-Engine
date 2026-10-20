<p align="center"><strong>ACADEMIC PLANNING ENGINE</strong></p>

# How the Engine Decides What to Schedule — and When

<p align="center"><em>A detailed, plain-language guide to the scheduling model, hard rules, priorities, tie-breakers, outputs, and limits</em></p>

<p align="center"><em>Prepared for policy owners, advisers, registrars, reviewers, and other non-programmer readers</em></p>

<p align="center">Implementation guide for the public synthetic-data release</p>

> **Scope**  This document describes what the code currently does. It is not a statement of university policy, and an “optimal” plan is optimal only within the data, approvals, assumptions, calendar, and time budget supplied to the engine.

---

## Contents

- [Executive summary](#executive-summary)
- [1. Purpose, audience, and interpretation](#1-purpose-audience-and-interpretation)
- [2. The decision in one sentence](#2-the-decision-in-one-sentence)
- [3. End-to-end flow](#3-end-to-end-flow)
  - [3.1 One academic audit is shared](#31-one-academic-audit-is-shared)
  - [3.2 Horizon growth](#32-horizon-growth)
  - [3.3 Inputs to one planning run](#33-inputs-to-one-planning-run)
- [4. Facts established before scheduling](#4-facts-established-before-scheduling)
  - [4.1 Governing contract and language branch](#41-governing-contract-and-language-branch)
  - [4.2 Completed work and official credit](#42-completed-work-and-official-credit)
  - [4.3 Equivalencies have two different jobs](#43-equivalencies-have-two-different-jobs)
  - [4.4 Pending and older in-progress work](#44-pending-and-older-in-progress-work)
  - [4.5 Optional credit authority](#45-optional-credit-authority)
- [5. Building the candidate pool](#5-building-the-candidate-pool)
- [6. How the mathematical model represents choices](#6-how-the-mathematical-model-represents-choices)
- [7. Hard rules: what every returned schedule must obey](#7-hard-rules-what-every-returned-schedule-must-obey)
  - [7.1 Availability, rollout, track eligibility, and one occurrence](#71-availability-rollout-track-eligibility-and-one-occurrence)
  - [7.2 Exactly one delivery for every outstanding requirement](#72-exactly-one-delivery-for-every-outstanding-requirement)
  - [7.3 Accepted equivalencies are alternatives](#73-accepted-equivalencies-are-alternatives)
  - [7.4 Accepted degree credit and category quotas](#74-accepted-degree-credit-and-category-quotas)
  - [7.5 Prerequisites must be earlier, not simultaneous](#75-prerequisites-must-be-earlier-not-simultaneous)
  - [7.6 Credit capacity and conditional allowances](#76-credit-capacity-and-conditional-allowances)
  - [7.7 Training placement](#77-training-placement)
  - [7.8 Current timetable uses complete bundles](#78-current-timetable-uses-complete-bundles)
  - [7.9 Forced and locked assignments](#79-forced-and-locked-assignments)
  - [7.10 Final-project pathway](#710-final-project-pathway)
- [8. How tie-breakers actually work](#8-how-tie-breakers-actually-work)
  - [8.1 Priority 1 — avoid unnecessary accepted credit](#81-priority-1-avoid-unnecessary-accepted-credit)
  - [8.2 Priority 2 — prefer real coursework at the same accepted total](#82-priority-2-prefer-real-coursework-at-the-same-accepted-total)
  - [8.3 Priority 3 — earliest graduation](#83-priority-3-earliest-graduation)
  - [8.4 Priority 4 — avoid unnecessary final-two-semester allowance](#84-priority-4-avoid-unnecessary-final-two-semester-allowance)
  - [8.5 Priority 5 — protect scarce current mandatory opportunities](#85-priority-5-protect-scarce-current-mandatory-opportunities)
  - [8.6 Priority 6 — failed mandatory repeats](#86-priority-6-failed-mandatory-repeats)
  - [8.7 Priority 7 — older-year mandatory backlog](#87-priority-7-older-year-mandatory-backlog)
  - [8.8 Priority 8 — mandatory work now](#88-priority-8-mandatory-work-now)
  - [8.9 Priority 9 — mandatory work early across the horizon](#89-priority-9-mandatory-work-early-across-the-horizon)
  - [8.10 Priority 10 — minimize training delay](#810-priority-10-minimize-training-delay)
  - [8.11 Priority 11 — governing-curriculum delivery](#811-priority-11-governing-curriculum-delivery)
  - [8.12 Priority 12 — prefer larger optional components](#812-priority-12-prefer-larger-optional-components)
  - [8.13 Priorities 13 and 14 — academic-year and semester alignment](#813-priorities-13-and-14-academic-year-and-semester-alignment)
  - [8.14 Priority 15 — maximize the current load](#814-priority-15-maximize-the-current-load)
  - [8.15 Priority 16 — move all selected work earlier](#815-priority-16-move-all-selected-work-earlier)
  - [8.16 Priority 17 — use fewer optional and auxiliary courses](#816-priority-17-use-fewer-optional-and-auxiliary-courses)
  - [8.17 Priority 18 — prefer the student’s own-track section](#817-priority-18-prefer-the-students-own-track-section)
  - [8.18 Priority 19 — use fewer current weekdays](#818-priority-19-use-fewer-current-weekdays)
  - [8.19 What if two plans are still tied?](#819-what-if-two-plans-are-still-tied)
- [9. The locking mechanism](#9-the-locking-mechanism)
- [10. Solver statuses and what they mean](#10-solver-statuses-and-what-they-mean)
- [11. Outputs and warnings](#11-outputs-and-warnings)
- [12. Worked examples](#12-worked-examples)
  - [12.1 Why the engine may not maximize the current load](#121-why-the-engine-may-not-maximize-the-current-load)
  - [12.2 Scarcity beats ordinary current load](#122-scarcity-beats-ordinary-current-load)
  - [12.3 Backlog does not beat earlier graduation](#123-backlog-does-not-beat-earlier-graduation)
  - [12.4 Credit adjustment versus a real course](#124-credit-adjustment-versus-a-real-course)
  - [12.5 Timetable language choice](#125-timetable-language-choice)
- [13. Configuration knobs and current database defaults](#13-configuration-knobs-and-current-database-defaults)
- [14. Important limits and non-goals](#14-important-limits-and-non-goals)
- [15. Inclusive and responsible use](#15-inclusive-and-responsible-use)
- [16. Review and change-control checklist](#16-review-and-change-control-checklist)
- [Appendix A — Source map](#appendix-a-source-map)
- [Appendix B — Regression evidence referenced in this guide](#appendix-b-regression-evidence-referenced-in-this-guide)
- [Appendix C — Glossary](#appendix-c-glossary)
- [Document control](#document-control)

---

## Executive summary

The engine designs a plan by looking at the entire supplied planning horizon at once. It does not simply fill the current semester with the largest possible load. It first reconciles the student’s recorded history with the governing degree contract, builds a set of courses that may be needed, and creates a mathematical model containing every allowed course–term choice. The model removes choices that break a hard rule. It then compares the remaining complete plans using a strict sequence of priorities.

The distinction between a hard rule and a preference is fundamental. A hard rule can make a proposed plan impossible: a missing offering, an unmet prerequisite, an exceeded credit capacity, a timetable conflict, or a contract category deficit. A preference never makes a plan impossible. It selects among plans that already satisfy every hard rule.

The preferences are lexicographic: priority 1 is settled first and its achieved value is locked; then priority 2 is settled without worsening priority 1; and so on. Consequently, a visually convenient timetable cannot delay graduation, a nominal-year match cannot displace more important backlog work, and a fuller current load cannot override a scarce mandatory opportunity.

> **Most important tie-break rule**  A lower-numbered priority always wins. Later priorities are consulted only when every earlier result is equal. The numeric weights inside one priority compare items within that priority; they do not let that priority jump ahead of another stage.

The current implementation normally applies 19 stages. Stage 18, preference for the student’s own teaching-language section, is omitted when that setting is disabled. If two plans remain equal after every active stage, there is no additional academic tie-breaker. Stable sorting, a single solver worker, and a fixed random seed make the residual choice repeatable in the present environment, but that residual choice should not be interpreted as policy.

## 1. Purpose, audience, and interpretation

This guide is intended for readers who need to understand, review, explain, or govern the engine without reading all of the Python source. Technical words are defined when first used and again in the glossary. Real excerpts are included so that each important explanation can be checked against the implementation.

Line references point to the working-copy snapshot reviewed on 20 October 2026. They may move when code is edited. The checked-out Git commit was 869cda0, but the workspace also contained uncommitted changes, including changes to pending/in-progress handling and retention of the last feasible plan when a later optimization stage times out. The document deliberately describes that reviewed working copy rather than only the last commit.

Read these terms consistently:

- Requirement: an item in the student’s governing graduation contract.

- Delivery course: the course identity that may be registered to satisfy a requirement. A verified prospective equivalency can add an alternative delivery course without changing the governing contract.

- Mandatory: a requirement that must be satisfied exactly once by one allowed delivery identity.

- Optional: a student-scoped, authorized course that may contribute degree credit but is not itself a fixed contract requirement.

- Auxiliary: a prerequisite or observed current registration included only to support a valid plan; it does not automatically gain degree-credit authority.

- Planning horizon: the ordered list of regular and training periods that the model is allowed to use.

- Bundle: one complete set of sections for a current course, such as lecture plus required lab.

## 2. The decision in one sentence

Given one reconciled academic record, one governing contract, an offering calendar, registration rules, capacities, approvals, and a time limit, choose at most one term for each candidate course and one non-conflicting current bundle for each current course, so that every contract and credit rule is satisfied and the ordered preferences are optimized.

> **Whole-plan reasoning**  The engine may deliberately choose fewer credits now when that unlocks a prerequisite chain and produces an earlier valid graduation. “Fill the semester” is priority 15, well after graduation timing and academic priorities.

## 3. End-to-end flow

1. Load the active catalog, curriculum revision, student record, equivalencies, prerequisites, offerings, capacities, approvals, and engine settings into one immutable planning problem.

2. If the student is already registered in a final-project pathway, replace only the configured FYP requirements with the complete registered pathway before optimization.

3. Reconcile the academic record once: identify satisfied and outstanding requirements, official earned credit, prerequisite completions, and student-specific classifications.

4. Choose an initial horizon measured in regular Fall/Spring semesters. Training periods remain in the calendar but do not consume that count.

5. Build the candidate course pool, including mandatory delivery alternatives, admissible optional courses, prerequisites, and any authoritative observed current registration.

6. Create Boolean choices for course–term assignments and current section bundles; add all hard constraints.

7. Solve the ordered objectives one by one. Lock the value reached at each successful stage before moving to the next.

8. If the horizon is proven infeasible and automatic extension is enabled, extend it by the configured number of regular semesters and solve again. An inconclusive search is not treated as proof of infeasibility and therefore does not trigger extension.

9. Return the schedule, graduation period, bundle choices, capacity audit, optional selections, solver status, warnings, and any provisional administrative credit-adjustment proposal.

### 3.1 One academic audit is shared

The application pipeline deliberately reconciles the record once and passes that same immutable audit to the optimizer. This prevents the screen and the solver from quietly using different interpretations of the student’s history.

````python
  42          audit = self.reconciliation_service.reconcile(
  43              problem.student,
  44              problem.curriculum,
  45              problem.equivalencies,
  46              courses=problem.courses,
  47              optional_approvals=problem.optional_credit_approvals,
  48              registration_course_ids=registration_course_ids,
  49              review_course_ids=review_course_ids,
  50          )
  51          return PlanningRun(audit=audit, plan=self.planner.plan(problem, audit=audit))
````

*Source reference: src/academic_planner/planning/pipeline.py, lines 42–51 (working-copy snapshot reviewed 20 October 2026).*

### 3.2 Horizon growth

The planner starts with the configured initial number of regular semesters, normally 10. When infeasibility is proven, it can extend by a configured step, normally 2, up to the configured maximum, normally 20, or the end of the supplied calendar—whichever comes first. The first feasible horizon is returned. This makes the reported graduation point the earliest feasible one among the horizons actually reached, subject to the solver status. Training periods stay inside each prefix but are not counted as regular semesters.

*Source reference: src/academic_planner/optimization/planner.py, lines 58–137 (working-copy snapshot reviewed 20 October 2026).*

### 3.3 Inputs to one planning run

| **Input** | **What it contributes** |
| --- | --- |
| courses | Course identity, code, title, ECTS, curriculum version, reference year/semester, FYP flag, provenance, and track policy |
| curriculum | Governing requirement IDs, accepted-credit target, FYP and training identities, and language branches |
| student | Nominal year, language track, attempts, recorded completions, and base earned credit |
| equivalencies | Recognized history and separately controlled prospective delivery alternatives |
| prerequisites | Supported all-of prerequisite sets |
| offerings | Course availability by period and exact current section bundles where supplied |
| configuration | Horizon, time budget, capacities, policy toggles, soft weights, forced assignments, and locked rosters |
| optional approvals | Student-scoped authority for optional courses to contribute degree credit |
| credit groups | Independent contract category quotas and explicit course contributions |
| mode flags | Strict versus exploratory approval handling and permission to propose a residual credit adjustment |

*Source reference: src/academic_planner/optimization/planner.py, lines 28–43 (working-copy snapshot reviewed 20 October 2026).*

## 4. Facts established before scheduling

### 4.1 Governing contract and language branch

A curriculum is treated as a graduation contract, not as a loose registration list. Shared requirements are retained, and only the language-specific branch matching the student’s recorded track is selected. Cross-track section permission does not replace a track-specific degree requirement.

*Source reference: src/academic_planner/domain/models.py, lines 117–131 (working-copy snapshot reviewed 20 October 2026).*

### 4.2 Completed work and official credit

Passed, transferred, and exempted attempts satisfy requirements. Failed, withdrawn, registered, in-progress, and result-pending attempts do not become completed merely because they exist. Completed attempts are allocated one-to-one, so one completion cannot satisfy two separate requirements. Official earned credit uses the recorded earned amount and deduplicates repeated or equivalent records by a stable credit identity. It does not substitute the target course’s catalog credit value.

*Source reference: src/academic_planner/reconciliation/service.py, lines 56–120 (working-copy snapshot reviewed 20 October 2026).*

### 4.3 Equivalencies have two different jobs

An equivalency may recognize completed history and may independently authorize prospective registration. For an OLD-contract student, only a verified mapping with prospective registration explicitly allowed adds a NEW course as a possible way to deliver an OLD requirement. The requirement remains part of the OLD contract; the student is not silently moved to the NEW curriculum.

````python
  12  def requirement_delivery_options(
  13      problem: PlanningProblem,
  14      requirement_ids: frozenset[str] | set[str],
  15  ) -> dict[str, frozenset[str]]:
  16      """Return schedulable course identities for each contract requirement.
  17  
  18      OLD students retain OLD requirements. A verified prospective OLD→NEW
  19      equivalency adds the NEW course as an alternative delivery; it never turns
  20      the student's contract into the NEW curriculum.
  21      """
  22      options = {requirement_id: {requirement_id} for requirement_id in requirement_ids}
  23      if problem.curriculum.version is CurriculumVersion.OLD:
  24          for equivalency in problem.equivalencies:
  25              if not equivalency.prospective_registration_allowed:
  26                  continue
  27              for requirement_id in equivalency.source_course_ids & options.keys():
  28                  options[requirement_id].update(
  29                      course_id for course_id in equivalency.target_requirement_ids
  30                      if course_id in problem.courses
  31                  )
  32      return {
  33          requirement_id: frozenset(course_ids)
  34          for requirement_id, course_ids in options.items()
  35      }
````

*Source reference: src/academic_planner/requirement_delivery.py, lines 12–35 (working-copy snapshot reviewed 20 October 2026).*

### 4.4 Pending and older in-progress work

A result-pending attempt, or an in-progress attempt from before the current term, is neither counted as officially earned nor scheduled again. If it belongs to the degree, its catalog credit is projected when calculating the remaining numerical gap and its requirement is deferred. Credit identities prevent duplicate projection. The returned plan warns that these courses were kept unearned and not rescheduled.

A current-term in-progress record is not included in this particular blocked set. Current registration can instead be represented through authoritative course-term assignments and a locked permitted roster when the surrounding service supplies them.

````python
 150          current_term = terms[0]
 151          blocked_attempts = tuple(
 152              attempt
 153              for attempt in problem.student.attempts
 154              if (
 155                  attempt.status is AttemptStatus.RESULT_PENDING
 156                  or (
 157                      attempt.status is AttemptStatus.IN_PROGRESS
 158                      and attempt.term < current_term
 159                  )
 160              )
 161          )
 162          blocked_course_ids = {attempt.course_id for attempt in blocked_attempts}
 163          all_delivery_options = requirement_delivery_options(
 164              problem, reconciliation.outstanding_requirement_ids
 165          )
 166          deferred_requirement_ids = frozenset(
 167              requirement_id
 168              for requirement_id, course_ids in all_delivery_options.items()
 169              if course_ids & blocked_course_ids
 170          )
 171          schedulable_requirement_ids = (
 172              reconciliation.outstanding_requirement_ids - deferred_requirement_ids
 173          )
 174          mandatory_requirements = sorted(schedulable_requirement_ids)
 175          delivery_options = requirement_delivery_options(
 176              problem, schedulable_requirement_ids
 177          )
````

*Source reference: src/academic_planner/optimization/planner.py, lines 150–177 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/optimization/planner.py, lines 226–277 (working-copy snapshot reviewed 20 October 2026).*

### 4.5 Optional credit authority

A normal plan admits an optional course only when the approval is APPROVED and includes both an authority and a source reference. An exploratory plan may also admit UNVERIFIED optional approvals, but the result is marked hypothetical and carries a warning. Completed courses, completed equivalents, and mandatory delivery identities are removed from the optional pool to prevent double use.

*Source reference: src/academic_planner/optimization/planner.py, lines 204–225 (working-copy snapshot reviewed 20 October 2026).*

## 5. Building the candidate pool

The model starts from four sources:

- Every delivery identity for each schedulable outstanding mandatory requirement.

- Every admissible student-approved optional course.

- The transitive prerequisite closure: prerequisites of candidates, then prerequisites of those prerequisites, whenever definitions exist.

- Any authoritative current registration that must be represented even when it is not independently a graduation-credit candidate.

Prerequisite-only and observed-registration courses are auxiliary. Including a course in the model does not by itself allow its credits to close the graduation target. The course must already be a mandatory delivery identity or an authorized optional course for that purpose.

*Source reference: src/academic_planner/optimization/planner.py, lines 299–323 (working-copy snapshot reviewed 20 October 2026).*

## 6. How the mathematical model represents choices

The engine uses OR-Tools CP-SAT, a constraint solver for discrete choices. The most important variable is x[course, term]. It is 1 when that course is selected in that term and 0 otherwise. Separate Boolean variables select current bundles, conditional capacity allowances, and weekdays. An integer graduation_index identifies the last modeled period containing selected coursework. Another integer can represent a provisional administrative credit adjustment when that special mode is enabled.

| **Model item** | **Plain-language meaning** |
| --- | --- |
| x[course, term] | Whether the course is scheduled in that period |
| bundle[bundle] | Whether a complete current-term section bundle is selected |
| graduation_index | The last period containing selected modeled coursework |
| capacity activation | Whether a conditional repeat or final-two-semester allowance is used |
| day[weekday] | Whether any selected current bundle meets on that weekday |
| administrative adjustment | An unapproved residual credit proposal; zero unless proposals are enabled |

````python
 324          model = cp_model.CpModel()
 325          x: dict[tuple[str, int], cp_model.IntVar] = {}
 326          unavailable: list[str] = []
 327          graduation_index = model.NewIntVar(0, len(terms) - 1, "graduation_index")
 328          adjustment_amount = model.NewIntVar(
 329              0,
 330              credits_needed if problem.allow_credit_adjustment_proposal else 0,
 331              "administrative_credit_adjustment",
 332          )
 333  
 334          for course_id in planning_courses:
 335              course = problem.courses[course_id]
 336              for ti, term in enumerate(terms):
 337                  var = model.NewBoolVar(f"course_{course_id}_{ti}")
 338                  x[course_id, ti] = var
 339                  offering = offering_map.get((course_id, term))
 340                  rollout = self.rollout_policy.permits(course, term)
 341                  registration_reason = self.registration_policy.rejection_reason(problem.student, course, term)
 342                  authoritative_here = (
 343                      problem.configuration.authoritative_course_terms.get(course_id)
 344                      == term
 345                  )
 346                  if (
 347                      offering is None
 348                      or (
 349                          not authoritative_here
 350                          and (not rollout.permitted or registration_reason)
 351                      )
 352                  ):
 353                      model.Add(var == 0)
 354                  if course_id in blocked_course_ids:
 355                      model.Add(var == 0)
 356              occurrences = sum(x[course_id, ti] for ti in range(len(terms)))
 357              model.Add(occurrences <= 1)
````

*Source reference: src/academic_planner/optimization/planner.py, lines 324–357 (working-copy snapshot reviewed 20 October 2026).*

## 7. Hard rules: what every returned schedule must obey

### 7.1 Availability, rollout, track eligibility, and one occurrence

A course–term choice is disabled if there is no offering, the progressive curriculum rollout does not permit the course in that year, or the registration policy rejects the student/course/term combination. Authoritative observed enrollment bypasses the prospective rollout and registration checks for that exact course and term, but it still needs an offering object in the current implementation. Every modeled course can be selected at most once.

Availability verification is different from availability existence. An unverified future offering may be used because an offering record is present, but the plan then warns that its graduation date relies on an assumption. Verification also matters to the scarcity priority described later.

*Source reference: src/academic_planner/optimization/planner.py, lines 334–359 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/policies/rollout.py, lines 13–31 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/policies/registration.py, lines 17–31 (working-copy snapshot reviewed 20 October 2026).*

### 7.2 Exactly one delivery for every outstanding requirement

For each outstanding requirement, the sum of all its allowed delivery-course choices across all terms must equal exactly one. Zero is not enough; two alternatives are not allowed. If one registration course is configured to own more than one outstanding requirement without an allocation rule, the planner stops with an infeasible explanation instead of guessing.

````python
 361          for requirement_id, course_ids in delivery_options.items():
 362              model.Add(sum(
 363                  x[course_id, ti]
 364                  for course_id in course_ids
 365                  for ti in range(len(terms))
 366              ) == 1)
````

*Source reference: src/academic_planner/optimization/planner.py, lines 361–366 (working-copy snapshot reviewed 20 October 2026).*

### 7.3 Accepted equivalencies are alternatives

When multiple sides of an accepted equivalency are in the candidate pool, at most one may be selected prospectively. This prevents the plan from scheduling both the source and target identity as if they were independent degree work.

````python
 378          # Accepted equivalencies are alternatives, not two independent courses.
 379          # Historical completion filtering handles already-passed work above;
 380          # this constraint prevents both sides being selected prospectively.
 381          for equivalency in problem.equivalencies:
 382              equivalent_planning_ids = sorted(
 383                  (equivalency.source_course_ids | equivalency.target_requirement_ids)
 384                  & course_pool
 385              )
 386              if len(equivalent_planning_ids) > 1:
 387                  model.Add(sum(
 388                      x[course_id, ti]
 389                      for course_id in equivalent_planning_ids
 390                      for ti in range(len(terms))
 391                  ) <= 1)
````

*Source reference: src/academic_planner/optimization/planner.py, lines 378–391 (working-copy snapshot reviewed 20 October 2026).*

### 7.4 Accepted degree credit and category quotas

The accepted-credit expression counts scheduled mandatory delivery credit, authorized optional credit, and any enabled provisional adjustment. It excludes auxiliary prerequisite credit. The total must meet the remaining degree target after official earned credit and projected pending degree work.

Contract credit groups are additional independent constraints. Each group must reach its own remaining quota using the group’s explicit course-to-credit mapping. A large global total cannot hide a shortage in a category. Before building the full model, the planner also rejects a strict request when all available mandatory and approved optional credits combined cannot reach the remaining target and adjustment proposals are disabled.

*Source reference: src/academic_planner/optimization/planner.py, lines 235–297 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/optimization/planner.py, lines 393–408 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/optimization/planner.py, lines 580–588 (working-copy snapshot reviewed 20 October 2026).*

### 7.5 Prerequisites must be earlier, not simultaneous

A prerequisite is satisfied if it belongs to the reconciliation completion set or is scheduled in a strictly earlier modeled term. The engine does not infer same-term corequisites. If an uncompleted prerequisite lacks a model definition, the dependent is disabled. Authoritative observed enrollment is allowed to bypass this prospective check for its exact observed term; that exception represents a fact already recorded, not a new recommendation.

````python
 473          for course_id in planning_courses:
 474              for prerequisite in prereq_map.get(course_id, frozenset()):
 475                  if prerequisite in completed:
 476                      continue
 477                  if prerequisite not in course_pool:
 478                      for ti in range(len(terms)):
 479                          if (
 480                              problem.configuration.authoritative_course_terms.get(course_id)
 481                              != terms[ti]
 482                          ):
 483                              model.Add(x[course_id, ti] == 0)
 484                      continue
 485                  for ti in range(len(terms)):
 486                      if (
 487                          problem.configuration.authoritative_course_terms.get(course_id)
 488                          == terms[ti]
 489                      ):
 490                          continue
 491                      model.Add(x[course_id, ti] <= sum(x[prerequisite, earlier] for earlier in range(ti)))
````

*Source reference: src/academic_planner/optimization/planner.py, lines 473–491 (working-copy snapshot reviewed 20 October 2026).*

### 7.6 Credit capacity and conditional allowances

Every period has an effective ECTS capacity. Training periods use their configured period capacity. An explicit term override takes precedence over conditional regular-term bonuses. In a regular term, a failed-repeat allowance can activate only when the selected schedule actually includes an unresolved failed mandatory requirement. A final-two-semester allowance can activate only when graduation falls within the modeled final two regular semesters relative to that term.

If both conditional allowances are possible, their bonuses do not stack. The model takes the maximum allowed bonus. A later preference minimizes use of the final-two-semester activation after the graduation date has already been fixed. The provisional administrative credit adjustment participates in graduation-credit arithmetic but does not consume a term’s capacity.

*Source reference: src/academic_planner/optimization/planner.py, lines 410–471 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/policies/credit.py, lines 28–110 (working-copy snapshot reviewed 20 October 2026).*

### 7.7 Training placement

An outstanding training requirement may be placed only in training-period kinds that appear in its supplied offerings, never before its normal academic year. Configuration can prohibit postponement or cap the number of delayed years. When postponement remains possible, delay is discouraged later by priority 10, but it can still occur if required by a higher priority such as graduation feasibility.

*Source reference: src/academic_planner/optimization/planner.py, lines 504–533 (working-copy snapshot reviewed 20 October 2026).*

### 7.8 Current timetable uses complete bundles

The first horizon period is exact at section level. A selected current course must select exactly one complete supplied bundle. A current course with no bundle is disabled. Two bundles cannot both be chosen when any of their meetings overlap on the same weekday. A zero-credit lab can remain part of its course bundle because the choice concerns the complete registration package, not only positive-credit components.

````python
 535          # Exact current-term bundle choice; every selected course gets exactly one complete bundle.
 536          bundle_vars: dict[str, cp_model.IntVar] = {}
 537          current = terms[0]
 538          current_bundles = []
 539          for course_id in planning_courses:
 540              offering = offering_map.get((course_id, current))
 541              bundles = offering.bundles if offering else ()
 542              if not bundles:
 543                  model.Add(x[course_id, 0] == 0)
 544                  continue
 545              variables = []
 546              for bundle in bundles:
 547                  bv = model.NewBoolVar(f"bundle_{bundle.id}")
 548                  bundle_vars[bundle.id] = bv
 549                  variables.append(bv)
 550                  current_bundles.append(bundle)
 551              model.Add(sum(variables) == x[course_id, 0])
 552          for i, left in enumerate(current_bundles):
 553              for right in current_bundles[i + 1:]:
 554                  if bundles_conflict(left, right):
 555                      model.Add(bundle_vars[left.id] + bundle_vars[right.id] <= 1)
````

*Source reference: src/academic_planner/optimization/planner.py, lines 535–555 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/scheduling/conflicts.py, lines 4–9 (working-copy snapshot reviewed 20 October 2026).*

### 7.9 Forced and locked assignments

A forced course–term assignment is a hard requirement. If the course is outside the pool or the term is outside the horizon, the request is infeasible. A locked term roster is a complete permitted set: every modeled course not in that set is forced out of the locked term. These features are stronger than ordinary preferences and should therefore be backed by a clear factual or diagnostic reason.

*Source reference: src/academic_planner/optimization/planner.py, lines 368–376 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/optimization/planner.py, lines 493–502 (working-copy snapshot reviewed 20 October 2026).*

### 7.10 Final-project pathway

The optimizer does not invent or choose an FYP pathway. Before optimization, a current registration in any FYP component locks the complete FYP pathway belonging to that curriculum version. Other course choices remain open. A multi-part project remains multi-part with its source credits.

*Source reference: src/academic_planner/planning/fyp.py, lines 10–63 (working-copy snapshot reviewed 20 October 2026).*

## 8. How tie-breakers actually work

After all hard rules are present, the engine does not combine preferences into one weighted score. It solves one objective, records the best integer value found, adds a new equality requiring that same value, and only then introduces the next objective. This is lexicographic optimization. It prevents a large numerical improvement in a low-priority preference from compensating for even a one-unit loss in a higher-priority preference.

````python
 684          objective_stages = [
 685              # Administrative adjustments are a last-resort way to close an
 686              # otherwise unfillable numerical deficit.  First avoid excess
 687              # accepted credit, then prefer real coursework for an exact fit.
 688              # This selects a real 2-ECTS course at 298/300, but proposes a
 689              # 1-ECTS adjustment at 299/300 instead of forcing 2 excess ECTS.
 690              ("min", accepted_credit_expression),
 691              ("min", adjustment_amount),
 692              ("min", graduation_index),
 693              # The IUL final-two-semester allowance is used only when it improves
 694              # the already-prioritized graduation date.
 695              ("min", sum(final_load_activations)),
 696              # A confirmed current opportunity is safer than an unverified
 697              # future assumption.  This is evaluated per requirement across all
 698              # accepted delivery equivalents, not per legacy course code.
 699              ("max", scarce_current_mandatory_credits),
 700              # Failed and earlier-year backlog choose among mandatory work
 701              # without overriding graduation speed or a genuinely scarce
 702              # requirement opportunity. Mandatory credit then precedes optional
 703              # credit when those academic distinctions are equal.
 704              ("max", failed_current_mandatory_credits),
 705              ("max", backlog_current_mandatory_priority),
 706              ("max", current_mandatory_credits),
 707              ("max", mandatory_productive_terms),
 708              ("min", sum(training_delay_terms)),
 709              # Governing-curriculum preference applies only when choosing how to
 710              # deliver a mandatory requirement. It cannot promote an OLD
 711              # optional course ahead of mandatory backlog.
 712              ("min", mandatory_cross_system_selection),
 713              ("max", optional_credit_priority),
 714              # Nominal year and semester are tie-breakers, never reasons to defer
 715              # mandatory, prerequisite-enabling, or backlog work.
 716              ("min", sum(current_alignment_terms)),
 717              ("min", sum(alignment_terms)),
 718              # Load is a capacity, not a degree objective. Fill it only after the
 719              # academic priorities above are fixed.
 720              ("max", current_credit_expression),
 721              ("max", sum(productive_terms)),
 722              ("min", sum(
 723                  x[c, ti]
 724                  for c in optional + auxiliary for ti in range(len(terms))
 725              )),
 726          ]
 727          if problem.configuration.prefer_own_track_sections:
 728              objective_stages.append(("min", sum(alternate_track_bundles)))
 729          objective_stages.append(("min", sum(day_vars)))
````

*Source reference: src/academic_planner/optimization/planner.py, lines 684–729 (working-copy snapshot reviewed 20 October 2026).*

The following table gives the complete active ordering. “Minimize” means smaller is preferred; “maximize” means larger is preferred. Stage 18 is conditional on prefer_own_track_sections.

| **Order** | **Direction** | **Criterion** | **Plain-language effect** |
| --- | --- | --- | --- |
| 1 | Min | Accepted scheduled degree credit + adjustment | Avoid credit beyond the remaining numerical target |
| 2 | Min | Administrative adjustment | Prefer real authorized coursework when the accepted total is tied |
| 3 | Min | Graduation index | Finish in the earliest modeled period |
| 4 | Min | Final-two-semester activations | Use that exceptional allowance only when the same graduation date needs it |
| 5 | Max | Current scarce mandatory ECTS | Take a current mandatory opportunity with no verified later delivery |
| 6 | Max | Current failed-repeat mandatory ECTS | Prioritize unresolved failed mandatory work now |
| 7 | Max | Current mandatory backlog score | Favor older-year backlog, weighted by its selected ECTS |
| 8 | Max | All current mandatory ECTS | Prefer mandatory work now before optional or auxiliary load |
| 9 | Max | Early mandatory placement | Move mandatory credit earlier across the whole horizon |
| 10 | Min | Weighted training delay | Use the normal training year when higher priorities are unchanged |
| 11 | Min | Cross-curriculum mandatory deliveries | Prefer the governing curriculum’s delivery identity when equivalent |
| 12 | Max | Squared optional-credit priority | At the same accepted total, favor larger optional components |
| 13 | Min | Current year/semester mismatch | Align the current choice with nominal year and reference semester |
| 14 | Min | All-term year/semester mismatch | Align the complete plan with curriculum placement |
| 15 | Max | Current selected ECTS | Fill the current term only after academic priorities are fixed |
| 16 | Max | Early placement of all selected ECTS | Move all selected work earlier without worsening prior results |
| 17 | Min | Optional + auxiliary course count | Use fewer support/optional course identities when otherwise equal |
| 18 | Min | Alternate-language current bundles | Prefer the student’s own-track section when enabled |
| 19 | Min | Current weekdays used | Compact the conflict-free current timetable |

### 8.1 Priority 1 — avoid unnecessary accepted credit

The first objective minimizes the degree-credit amount being added by the plan: mandatory delivery credit plus authorized optional credit plus any provisional adjustment. The hard constraint already requires this amount to be at least the remaining target, so minimization seeks an exact fit and otherwise the smallest overshoot. Auxiliary prerequisites are not counted in this expression.

Example: with 299 of 300 ECTS and only a 2-ECTS optional course available, an enabled 1-ECTS administrative adjustment produces a total addition of 1 instead of 2, so it wins at this stage. This does not mean the adjustment is approved; it is explicitly a proposal with a warning.

### 8.2 Priority 2 — prefer real coursework at the same accepted total

Once the minimum accepted total is locked, the engine minimizes the adjustment itself. With 298 of 300 ECTS and an authorized 2-ECTS course available, the real course and a 2-ECTS adjustment both add exactly 2 at priority 1. Priority 2 selects the real course and drives the adjustment to zero.

### 8.3 Priority 3 — earliest graduation

The graduation index is constrained to be at least the index of every selected modeled course, including an auxiliary prerequisite. Minimizing it therefore identifies the last period containing any selected work needed by the chosen plan. This priority comes before current load, year alignment, timetable compactness, and every other convenience preference.

A locally large current load may lose. The regression case in tests/test_optimizer.py lines 47–60 uses a 30-ECTS course A and a 15-ECTS course B that unlocks course C. Selecting B now is globally necessary; choosing A merely because it fills the current capacity would prevent the complete chain from fitting in the supplied horizon.

### 8.4 Priority 4 — avoid unnecessary final-two-semester allowance

After the earliest graduation period is fixed, the engine minimizes activations of the final-two-semester capacity rule. Therefore the allowance can help obtain an earlier graduation, but it is not used just to make an already equally fast plan heavier. Failed-repeat activation is not part of this objective; its use is controlled by its own hard eligibility condition.

### 8.5 Priority 5 — protect scarce current mandatory opportunities

For each outstanding requirement, the engine asks whether any accepted delivery identity has a verified, rollout-permitted, registration-permitted offering later in the horizon. If not, its currently selected ECTS receive scarcity priority. The check is per requirement across all delivery equivalents, not per old catalog code.

Example: if SCARCE and RECURRING are both 5-ECTS mandatory courses offered now, capacity is 5, and only RECURRING has a verified later offering, SCARCE is selected now. This is asserted in tests/scenarios/test_advanced_scheduling.py lines 169–205.

### 8.6 Priority 6 — failed mandatory repeats

Among plans equal through scarcity, the engine maximizes current ECTS belonging to unresolved failed mandatory requirements. Only FAILED attempts intersected with outstanding requirement identities qualify. A course with no failure history does not qualify, and a later successful completion removes it from the outstanding set.

### 8.7 Priority 7 — older-year mandatory backlog

The backlog score for a requirement is max(0, student nominal year − requirement reference year) multiplied by the current selected delivery ECTS. A Year-3 requirement for a Year-5 student has a gap of 2; a current-year or future-year requirement has a gap of 0. This stage rewards clearing older backlog without allowing backlog to override graduation speed, scarcity, or failed-repeat priority.

Because ECTS is multiplied into the score, two otherwise equal backlog requirements can contribute differently when their delivery credits differ. When a requirement identity has no course definition, the reference year falls back to the minimum reference year of its delivery alternatives.

### 8.8 Priority 8 — mandatory work now

The engine next maximizes all current mandatory delivery ECTS. Optional and auxiliary courses do not contribute. This ensures that a current optional course cannot displace equally feasible mandatory work merely because it produces a fuller schedule.

### 8.9 Priority 9 — mandatory work early across the horizon

Every mandatory delivery credit is multiplied by len(terms) − term index. Earlier terms have a larger multiplier. Maximizing the sum moves mandatory work earlier across the full horizon after the more specific current-term priorities are fixed. It does not change which mandatory requirements must be completed; that is already a hard rule.

### 8.10 Priority 10 — minimize training delay

For an allowed training placement, delay years are multiplied by the configured training-delay penalty. Minimization prefers the normal year. The value can be zero, which disables this soft preference without relaxing the hard rules that prohibit early training and enforce any maximum delay.

### 8.11 Priority 11 — governing-curriculum delivery

When a mandatory requirement can be delivered by equivalent course identities from different curriculum versions, the engine minimizes selections outside the student’s governing curriculum. This applies only to mandatory delivery choice. It does not promote an OLD optional course ahead of mandatory backlog, and it cannot overcome a higher-priority graduation or availability effect.

### 8.12 Priority 12 — prefer larger optional components

At an already fixed accepted-credit total, each selected optional course contributes credits squared. Thus 4+3+1 scores 26 while 3+3+2 scores 22, so the former is preferred when earlier results are equal. Squaring does not grant extra accepted credit and does not bypass prerequisites. A small prerequisite can still be scheduled as auxiliary support when it unlocks the preferred larger optional course.

### 8.13 Priorities 13 and 14 — academic-year and semester alignment

Alignment is deliberately late. The projected student year equals the recorded nominal year plus elapsed academic years from the first horizon term. The penalty combines absolute year deviation times the academic-year weight and a Fall/Spring mismatch times the reference-semester weight. Training requirements do not receive the semester-mismatch component. Priority 13 applies to the current period; priority 14 applies to all periods.

These weights operate only inside the alignment stage. Raising a weight changes how alignment alternatives compare, but alignment still cannot override priorities 1–12. A zero weight disables that component.

### 8.14 Priority 15 — maximize the current load

Only now does the engine maximize all selected current ECTS, including mandatory, optional, and auxiliary courses. Capacity is a ceiling, not a target. The engine does not promise to fill it when doing so would worsen any earlier academic result.

### 8.15 Priority 16 — move all selected work earlier

Like priority 9, this uses a decreasing term-position multiplier, but it includes every selected course. It can move optional or auxiliary work earlier only when mandatory timing, alignment, current load, and all earlier priorities remain unchanged.

### 8.16 Priority 17 — use fewer optional and auxiliary courses

The engine minimizes the number of selected optional and auxiliary identities. Mandatory deliveries are excluded because every outstanding mandatory requirement already requires exactly one delivery. This stage helps avoid unnecessary supporting selections when accepted credit and timing are otherwise equal.

### 8.17 Priority 18 — prefer the student’s own-track section

When cross-track shared sections are allowed and prefer_own_track_sections is true, the engine minimizes current bundles containing a teaching language different from the student’s track. This is a section preference, not permission to substitute a different track-specific degree requirement. If an alternate-track section is selected, the output warns that institutional permission is an unverified configured assumption. When the preference setting is false, this entire stage is omitted.

### 8.18 Priority 19 — use fewer current weekdays

For each weekday represented by a selected current bundle, a Boolean day variable becomes 1. The final explicit objective minimizes their sum. It can compact a timetable only after all educational, graduation, load, and language-section decisions above are equal. It does not measure gaps within a day, travel time, preferred start time, or personal availability.

### 8.19 What if two plans are still tied?

There is no explicit priority 20. Candidate course IDs are sorted before variables are created, output follows that stable course order, the solver uses one search worker, and random_seed is fixed to zero. Those choices make repeat runs stable in the current software environment. Nevertheless, a remaining choice is a technical residual tie, not an academic judgment. A future OR-Tools version, changed variable construction order, changed bundle input order, or another implementation detail may select a different but equally ranked plan.

> **Governance implication**  If a residual distinction matters to policy—such as earliest start time, fewest campus gaps, or a particular course-code order—it must be added and tested as an explicit objective. Reviewers should not infer that policy from whichever fully tied schedule happens to appear.

## 9. The locking mechanism

The code below is the mechanism that makes the priority order binding. One shared wall-clock budget is reduced before every stage. After a feasible stage, its achieved value is saved. Before the next stage, an equality locks that value. A stage that is merely feasible but not proven optimal lowers the final status; the algorithm still proceeds while time remains.

````python
 730          solver = cp_model.CpSolver()
 731          # Repeatable plans matter for review and import comparisons. A single
 732          # deterministic worker prevents equally optimal schedules from changing
 733          # merely because parallel search completed in a different order.
 734          solver.parameters.num_search_workers = 1
 735          solver.parameters.random_seed = 0
 736          solve_started = monotonic()
 737          all_stages_optimal = True
 738          result = cp_model.UNKNOWN
 739          last_feasible_values: dict[int, int] | None = None
 740          response_variables = [
 741              *x.values(), *bundle_vars.values(), graduation_index, adjustment_amount,
 742          ]
 743          for stage_index, (direction, expression) in enumerate(objective_stages):
 744              remaining_seconds = problem.configuration.time_limit_seconds - (monotonic() - solve_started)
 745              if remaining_seconds <= 0:
 746                  all_stages_optimal = False
 747                  break
 748              solver.parameters.max_time_in_seconds = remaining_seconds
 749              if direction == "min":
 750                  model.Minimize(expression)
 751              else:
 752                  model.Maximize(expression)
 753              result = solver.Solve(model)
 754              if result not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
 755                  break
 756              if result != cp_model.OPTIMAL:
 757                  all_stages_optimal = False
 758              value = solver.Value(expression)
 759              last_feasible_values = {
 760                  variable.Index(): solver.Value(variable)
 761                  for variable in response_variables
 762              }
 763              if stage_index < len(objective_stages) - 1:
 764                  model.Add(expression == value)
````

*Source reference: src/academic_planner/optimization/planner.py, lines 730–764 (working-copy snapshot reviewed 20 October 2026).*

Because one total time budget is shared across every stage, expensive early stages can leave little time for later refinements. A plan can therefore have its high-priority results established while lower-priority tie-breakers remain unfinished.

## 10. Solver statuses and what they mean

| **Status** | **Meaning for the reader** |
| --- | --- |
| OPTIMAL | Every reached objective stage was proven optimal, and the final solve was optimal within the supplied model and horizon. |
| FEASIBLE_NOT_PROVEN_OPTIMAL | A valid plan exists, but at least one stage was not proven optimal or the shared time budget ended after a feasible plan had been saved. |
| INFEASIBLE | The solver proved no plan satisfies all hard rules in the supplied horizon, or a model precondition failed explicitly. |
| UNKNOWN | No feasible plan and no proof of infeasibility were obtained within the search conditions. |

If a later optimization stage returns UNKNOWN after an earlier stage produced a feasible solution, the current working copy returns the saved feasible values as FEASIBLE_NOT_PROVEN_OPTIMAL and warns that the last verified feasible plan was retained. If there was never a feasible result, UNKNOWN remains inconclusive.

````python
 765          use_saved_incumbent = (
 766              result == cp_model.UNKNOWN and last_feasible_values is not None
 767          )
 768          status = (
 769              SolverStatus.OPTIMAL
 770              if result == cp_model.OPTIMAL and all_stages_optimal
 771              else SolverStatus.FEASIBLE_NOT_PROVEN_OPTIMAL
 772              if result in {cp_model.OPTIMAL, cp_model.FEASIBLE} or use_saved_incumbent
 773              else SolverStatus.INFEASIBLE
 774              if result == cp_model.INFEASIBLE
 775              else SolverStatus.UNKNOWN
 776          )
 777          if status in {SolverStatus.INFEASIBLE, SolverStatus.UNKNOWN}:
 778              details = ["no plan satisfies all requirements within the supplied horizon"]
 779              if unavailable:
 780                  details.append(f"no offering supplied in horizon: {', '.join(unavailable)}")
 781              return GraduationPlan(status, explanations=tuple(details))
 782  
 783          def solution_value(variable: cp_model.IntVar) -> int:
 784              if use_saved_incumbent:
 785                  assert last_feasible_values is not None
 786                  return last_feasible_values[variable.Index()]
 787              return solver.Value(variable)
 788  
 789          scheduled: list[ScheduledTerm] = []
 790          for ti, term in enumerate(terms):
 791              chosen = tuple(c for c in planning_courses if solution_value(x[c, ti]))
 792              chosen_bundles = tuple(
 793                  b.id for b in current_bundles
 794                  if ti == 0 and solution_value(bundle_vars[b.id])
 795              )
 796              scheduled.append(ScheduledTerm(term, chosen, chosen_bundles))
 797          graduation_term = terms[solution_value(graduation_index)]
 798          warnings = []
 799          if use_saved_incumbent:
 800              warnings.append(
 801                  "The solver time limit was reached during a lower-priority "
 802                  "optimization stage; the last verified feasible plan was retained."
 803              )
````

*Source reference: src/academic_planner/optimization/planner.py, lines 765–803 (working-copy snapshot reviewed 20 October 2026).*

> **Do not overstate OPTIMAL**  OPTIMAL does not mean universally best or officially approved. It means best under the implemented priorities for the supplied courses, facts, assumptions, approvals, offerings, horizon, and configuration.

## 11. Outputs and warnings

A successful GraduationPlan contains:

- one ScheduledTerm for every period in the active horizon, including empty periods;

- the graduation term identified by graduation_index;

- current bundle IDs for the exact timetable selection;

- per-term selected credit, effective capacity, reason for that capacity, and repeated-course IDs where relevant;

- selected optional course IDs;

- whether the result is hypothetical;

- an administrative credit-adjustment proposal when enabled and selected;

- explanations and warnings.

Warnings are emitted when the returned plan relies on or encounters important uncertainty, including:

- result-pending or older in-progress courses kept unearned and not scheduled again;

- a lower-priority solve timing out after a feasible plan was saved;

- a provisional administrative credit adjustment requiring approval;

- a selected alternate-track current section;

- synthetic or otherwise unverified current timetable data;

- unverified future offering assumptions;

- unverified optional-credit approval in an exploratory plan.

*Source reference: src/academic_planner/optimization/planner.py, lines 789–894 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/domain/models.py, lines 326–370 (working-copy snapshot reviewed 20 October 2026).*

## 12. Worked examples

### 12.1 Why the engine may not maximize the current load

Suppose A is 30 ECTS and can be taken now or next term. B is 15 ECTS and can also be taken now or next term. C is required, available only next term, and requires B earlier. Current capacity is 30. Choosing A now looks locally attractive, but then B and C cannot both respect the prerequisite in the two-term horizon. The global model chooses B now and A plus C next term. This is the behavior asserted by tests/test_optimizer.py lines 47–60.

### 12.2 Scarcity beats ordinary current load

Suppose SCARCE and RECURRING are both mandatory 5-ECTS courses, both are offered now, and capacity allows only one. RECURRING has a verified later offering; SCARCE does not. Priority 5 selects SCARCE now. Year alignment, total current load, and weekday compactness cannot reverse the choice because they occur later.

### 12.3 Backlog does not beat earlier graduation

Backlog priority is important but comes after graduation timing. If selecting a lower-current-credit mix containing an older backlog course unlocks a dependent course and leads to an earlier graduation, priority 3 already selects that plan. If graduation timing is equal, priority 7 can then favor the older backlog before current-year alignment or fuller load. The regression examples are in tests/scenarios/test_advanced_scheduling.py lines 141–166.

### 12.4 Credit adjustment versus a real course

At 299/300 ECTS, a 1-ECTS adjustment beats taking a 2-ECTS course because priority 1 first minimizes the total added accepted credit. At 298/300 ECTS, an exact 2-ECTS course and a 2-ECTS adjustment tie at priority 1; priority 2 chooses the course. These cases are asserted in tests/test_optional_credit_planning.py lines 201–217.

### 12.5 Timetable language choice

An alternate-language section of an explicitly shared course may be admitted when cross-track shared sections are enabled and the student’s track is permitted. It can resolve a timetable conflict and allow more required courses now. If an equally ranked own-track bundle exists, priority 18 prefers it. Track-specific requirements themselves are still resolved from the student’s contract branch and are not interchangeable merely because another language section exists.

## 13. Configuration knobs and current database defaults

Defaults are data, not universal policy. Administrators can persist settings, and a planning request can override a defined subset without persisting the change. The table below records the defaults in the reviewed workspace. Per-term or student-specific records can still supersede them where the service supports that authority.

| **Setting** | **Reviewed default** | **Effect** |
| --- | --- | --- |
| Regular-semester capacity | 30 ECTS | Base ceiling for a regular term |
| Failed-repeat capacity | 36 ECTS; feature off | Conditional ceiling only when enabled and an unresolved failed mandatory course is selected |
| Final-two-semester capacity | 36 ECTS; feature on | Conditional ceiling when it can support graduation within the modeled final two regular semesters |
| Training I / II capacity | 5 / 5 ECTS | Period-specific ceilings |
| Solver budget | 20 seconds | One wall-clock budget shared by all objective stages in one horizon solve |
| Initial / maximum horizon | 10 / 20 regular semesters | Starting and stopping length for automatic horizon search |
| Horizon extension | On; 2 regular semesters | Growth after proven infeasibility |
| Academic-year alignment weight | 10 | Within-stage penalty per year of deviation |
| Reference-semester weight | 2 | Within-stage penalty for Fall/Spring mismatch |
| Training postponement | Allowed | Later configured training periods may be used |
| Training-delay weight | 10 | Within-stage penalty per delayed year |
| Maximum training delay | None | No hard delay cap unless configured |
| Future offering assumption | Reference semester | Creates unverified course-level future availability in matching reference semesters |
| NEW rollout start | 2023–2024 | Sets the progressive curriculum frontier |
| Cross-track shared sections | Off | Alternate-language sections of explicitly shared courses are excluded by default |
| Prefer own-track sections | On | Adds objective stage 18 when alternate sections are allowed |

*Source reference: src/academic_planner/database/service.py, lines 25–48 (working-copy snapshot reviewed 20 October 2026).*

*Source reference: src/academic_planner/web/schemas.py, lines 10–41 (working-copy snapshot reviewed 20 October 2026).*

## 14. Important limits and non-goals

- Future offering records may be generated from reference-semester assumptions. They contain availability only, no fabricated sections or meeting times, and are marked unverified.

- The database loader accepts conjunctive AND prerequisite sets. OR or ambiguous prerequisite groups are rejected rather than silently weakened.

- Prerequisites must be completed earlier. Same-term corequisites are not inferred.

- Only the current term has exact section-level timetable construction. Future terms are course-level projections.

- The weekday preference does not model preferred hours, travel, accessibility needs, employment, caregiving, religious observance, or personal availability unless those needs are first translated into explicit data or constraints.

- An administrative credit adjustment is a proposal, not earned credit or approval, and currently consumes no semester capacity.

- A failed course does not automatically authorize extra capacity. The feature must be enabled, the course must remain an outstanding mandatory requirement, and it must actually be selected in that regular term.

- An unverified future offering may support a plan, but it produces a warning and is not treated as a verified later opportunity for the scarcity tie-breaker.

- Diagnostics and counterfactual explanations observe or re-solve scenarios; they do not change the factual constraints of the original solve.

- The solver cannot repair inaccurate catalog, transcript, equivalency, approval, or timetable data. Data governance remains essential.

*Source reference: src/academic_planner/database/loader.py, lines 32–198 (working-copy snapshot reviewed 20 October 2026).*

## 15. Inclusive and responsible use

The engine uses academic facts and configured policies. It does not need demographic characteristics beyond the recorded academic language track used for contract and section rules. Reviewers should avoid treating a mathematically selected schedule as a judgment about a person’s ability, commitment, or circumstances.

A student may have needs that the model does not represent. Advisers should provide a way to record or review accessibility requirements, health constraints, work and caregiving commitments, transportation limits, religious observance, financial constraints, and other individual circumstances. Where institutionally appropriate, those needs should become explicit, auditable inputs or constraints rather than informal assumptions.

Warnings and hypothetical labels should remain visible in every presentation of the plan. Alternate-track permissions, synthetic data, future-offering assumptions, and provisional credit adjustments must not be presented as confirmed facts.

## 16. Review and change-control checklist

Before approving or explaining a plan, a reviewer should confirm:

- The governing curriculum revision and language branch are correct.

- Transcript statuses and recorded earned credits are correct, especially failed, result-pending, and in-progress work.

- Equivalencies are verified and prospective registration permission is explicit where needed.

- Optional-credit approvals name an authority and source reference.

- Offerings, section bundles, and meeting times are current and appropriately verified.

- Capacity overrides and conditional allowances have the intended authority.

- Contract credit groups and course contribution mappings are complete.

- The solver status and every warning are included in the explanation given to the student or reviewer.

- No residual technical tie is being mistaken for an academic rule.

Before changing the engine, maintainers should treat the following as behavior-critical:

- candidate collection and sorting;

- variable and bundle creation order;

- hard-constraint formulas;

- objective expressions and their order;

- solver parameters and shared time-budget handling;

- status mapping and saved-incumbent behavior;

- horizon extension and stopping rules;

- output ordering and warning conditions.

Tests should compare the complete populated schedule and capacity audit for tie-break behavior, not only an unordered set of selected courses. A set-equivalent result can still differ in term placement, bundle choice, warning state, or policy meaning.

## Appendix A — Source map

| **Source** | **Relevant lines** | **Role** |
| --- | --- | --- |
| src/academic_planner/planning/pipeline.py | 24–51 | Single reconciliation and optimization pipeline |
| src/academic_planner/reconciliation/service.py | 45–187 | Requirement completion, official credit, allocations, classifications |
| src/academic_planner/requirement_delivery.py | 12–35 | Mandatory delivery alternatives and prospective equivalency |
| src/academic_planner/optimization/planner.py | 58–894 | Horizon control, model, constraints, objectives, solve, output |
| src/academic_planner/domain/models.py | 26–370 | Terms, courses, attempts, configuration, statuses, result structures |
| src/academic_planner/policies/credit.py | 28–110 | Capacity precedence and conditional allowances |
| src/academic_planner/policies/rollout.py | 13–31 | Progressive OLD/NEW curriculum rollout |
| src/academic_planner/policies/registration.py | 17–31 | Track-specific registration eligibility |
| src/academic_planner/scheduling/conflicts.py | 4–9 | Meeting and bundle conflict detection |
| src/academic_planner/planning/fyp.py | 10–63 | Registered FYP pathway locking |
| src/academic_planner/database/loader.py | 32–198 | Database-to-model translation and future assumptions |
| src/academic_planner/database/service.py | 25–48 | Default engine settings |
| src/academic_planner/web/schemas.py | 10–41 | Request-scoped configuration limits |
| src/academic_planner/validation/plan.py | 16–72 | Independent post-solve structural validation |

## Appendix B — Regression evidence referenced in this guide

| **Test source** | **Relevant lines** | **Behavior protected** |
| --- | --- | --- |
| tests/test_optimizer.py | 47–60 | Global prerequisite-aware choice beats local load maximization |
| tests/test_optimizer.py | 72–108 | Pending/older in-progress course is not scheduled again |
| tests/test_optimizer.py | 111 onward | Saved feasible incumbent survives a later UNKNOWN stage |
| tests/scenarios/test_advanced_scheduling.py | 69–98 | Training timing and postponement |
| tests/scenarios/test_advanced_scheduling.py | 141–166 | Graduation and backlog ordering |
| tests/scenarios/test_advanced_scheduling.py | 169–205 | Scarce current mandatory opportunity |
| tests/test_optional_credit_planning.py | 97–129 | Squared optional priority and prerequisite support |
| tests/test_optional_credit_planning.py | 201–217 | Adjustment-versus-real-course ordering |
| tests/test_conditional_credit_allowance.py | 141–184 | Capacity precedence and final-two-semester use |
| tests/test_extended_horizon.py | 81–103 | Maximum horizon explanation and training-period counting |
| tests/database/test_cross_track_integration.py | 54–105 | Shared alternate sections versus track-specific requirements |

## Appendix C — Glossary

**Accepted credit.** Credit authorized to count toward the degree target in the model.

**Auxiliary course.** A course included to support feasibility, usually as a prerequisite or observed registration, without automatically counting toward the degree target.

**Bundle.** A complete current registration option containing all supplied components for one course.

**CP-SAT.** The OR-Tools constraint solver used to choose Boolean and integer decisions.

**Delivery identity.** A course that may be registered to satisfy a particular governing requirement.

**ECTS.** European Credit Transfer and Accumulation System credit units.

**Feasible.** Satisfies every hard constraint in the supplied model.

**Governing curriculum.** The degree contract against which the student is audited.

**Hard constraint.** A rule that cannot be violated by a returned feasible plan.

**Horizon.** The ordered set of future periods available to the solver.

**Lexicographic optimization.** Optimizing priorities one at a time and locking each earlier result before considering the next.

**Nominal year.** The student’s recorded academic year used for alignment and backlog calculations.

**Optional course.** A student-authorized course that may contribute degree credit without being a fixed mandatory requirement.

**Optimal.** Proven best for all reached objectives under the supplied model, horizon, data, assumptions, and time budget.

**Prerequisite closure.** All prerequisites recursively needed by the initial candidate courses.

**Residual tie.** Two or more plans that remain equal after every explicit objective.

**Rollout.** The rule controlling which curriculum years are active in a given academic year.

**Tie-breaker.** A preference applied only after all hard rules and every earlier preference are equal.

**Verified offering.** An offering whose availability has supporting verification; unverified offerings may be assumptions and cause warnings.

## Document control

| **Field** | **Value** |
| --- | --- |
| Document | How the Engine Decides What to Schedule — and When |
| Prepared | 20 October 2026 (Asia/Beirut) |
| Application | academic-planning-engine 0.1.0 |
| Source baseline | Git commit 869cda0 plus reviewed uncommitted working-copy changes |
| Primary implementation | src/academic_planner/optimization/planner.py |
| Format | Microsoft Word Open XML (.docx) |

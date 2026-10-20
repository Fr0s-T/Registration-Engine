# Development guide

## Repository conventions

- Runtime packages live under `src/academic_planner`; tests mirror functional areas
  under `tests`.
- Keep domain values independent of SQLAlchemy and FastAPI.
- Use immutable dataclasses for planning inputs/results and Pydantic models at HTTP
  boundaries.
- Prefer explicit data flow through `PlanningProblem`, `ReconciliationResult`, and
  `GraduationPlan` over hidden global state.
- Keep imports transactional and migrations append-only.
- Use names from the academic model: governing curriculum, requirement, delivery
  option, optional approval, registration-only course, and accepted credit are not
  synonyms.

Python requires 3.11 or newer. Follow the configured 100-character Ruff line length
where it improves readability; do not perform a blanket formatting rewrite around
behavior-critical solver code.

## Local checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q src migrations tests
```

If Ruff is installed separately:

```powershell
ruff check src tests migrations
```

The repository does not currently configure a static type checker. Do not add or
upgrade tooling dependencies as an incidental cleanup.

## Changing an academic rule

1. Identify whether the rule changes the governing contract, historical recognition,
   registration permission, accepted credit, or scheduling. Put it in the matching
   layer rather than whichever location is most convenient.
2. Add a failing focused test with both the allowed and prohibited case.
3. Add a representative integration or API assertion when the rule is observable
   outside its module.
4. Implement the smallest change in the responsible layer.
5. Run focused tests, then the complete suite.
6. Update [Academic model](ACADEMIC_MODEL.md) only to describe behavior that the code
   and tests now establish.

Never change a student's governing curriculum merely because a different-curriculum
course is offered, completed, equivalent, or preferred by the optimizer.

## Extending reconciliation safely

Preserve these invariants:

- only satisfying attempt statuses complete requirements;
- one completion allocates to at most one independent requirement;
- earned ECTS use recorded source credit and a stable deduplication identity;
- recognition and prospective registration permission remain separate;
- classifications are student-specific and do not mutate catalog roles;
- registration-only or prerequisite-only courses do not acquire graduation credit.

Ordering in reconciliation is observable. Keep attempt order, direct-before-
equivalent matching, and sorted candidate behavior stable unless a deliberate policy
change has been approved and characterized.

## Changing the optimizer

Read [Optimizer](OPTIMIZER.md) and the complete current `planner.py` before editing.
Add a characterization test before modifying model construction. At minimum compare:

- solver status and optimality flag;
- exact selected course IDs and their order;
- exact course-to-term assignments;
- selected bundle IDs for the current term;
- graduation term;
- selected optional IDs;
- per-term selected ECTS, effective capacity, and reason;
- warnings, hypothetical status, and any adjustment proposal.

Do not assume a set-equivalent schedule is equivalent: API ordering, variable order,
and later lexicographic stages can be observable. Do not reorder dictionaries or
sets, consolidate objective coefficients, alter solver parameters, or change a sort
key without comparing every deterministic scenario.

The shared solver time budget can yield `FEASIBLE_NOT_PROVEN_OPTIMAL`; tests that
assert exact tie-breaking should use small deterministic cases or an adequate time
budget.

## Adding regression tests

- Put domain-unit tests beside the responsible area.
- Use `tests/conftest.py` builders for compact synthetic courses, terms, and bundles.
- Use scenario tests for multi-term behavior and database tests for persistence or
  import behavior.
- Assert prohibited outcomes as well as the desired result.
- For tie-breaking, assert the complete populated schedule and credit usage rather
  than only the graduation date.
- Derive a golden result from the current live code before a behavior-preserving
  refactor. Do not copy historical PDF output or weaken an expectation to make a
  refactor pass.
- Normalize only genuinely irrelevant values such as generated IDs or timestamps.

## Database and migrations

Create a new Alembic revision for every supported schema or data transition. Never
squash the existing chain. Upgrade a disposable database from base to head and also
test upgrade of a copy representative of current data.

```powershell
$env:DATABASE_URL = "sqlite:///./data/migration_check.db"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

Use an explicit disposable path and remove it only after verifying the resolved path
is inside the workspace. Preserve foreign keys, transaction boundaries, source
provenance, approval evidence, and student records. Curriculum replacement must
continue to report rebound and invalidated links.

## Imports and equivalencies

Parser output must enter the shared typed import model and validation report. Preview
must not write catalog data. Confirmation must replace only the selected curriculum
inside one transaction. Never bind replacement rows by title alone.

Automatic equivalency matching is conservative and administrator decisions survive
reruns. Historical recognition does not imply prospective registration permission.
The curated transition catalogue resolves stable course codes to current database IDs
after replacement; do not persist assumptions about integer IDs across imports.

## Frontend and API changes

The frontend is dependency-free HTML/CSS/JavaScript. Preserve route paths, Pydantic
contracts, state transitions, event handlers, calculations, and print content during
cleanup. Future-term responses intentionally omit section meetings. Update API tests
when adding an explicitly approved contract change; cosmetic cleanup should not
change payloads.

## Common pitfalls

- Treating OLD as obsolete implementation code. OLD is an active academic contract.
- Using the current eligibility pool as the complete graduation requirement set.
- Counting target-course ECTS instead of recorded historical ECTS.
- Letting one equivalent completion satisfy multiple requirements.
- Promoting an optional catalog label to student approval.
- Giving auxiliary prerequisites accepted graduation credit.
- Allowing same-term prerequisites when the model requires an earlier term.
- Fabricating future sections or meeting times.
- Treating `UNKNOWN` as infeasible and extending the horizon.
- Reordering optimizer inputs during a readability refactor.
- Squashing migrations or resetting the local database to simplify development.

## Deferred design work

Large architecture changes—such as splitting the optimizer model builder, replacing
the database planning service, introducing a frontend framework, or changing the
objective representation—should be separate proposals. They require dedicated
behavioral baselines and are intentionally outside routine cleanup.

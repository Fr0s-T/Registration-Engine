# Academic model

## Governing curriculum and course pool

The governing curriculum is the student's applicable graduation contract. It
defines which requirements must be satisfied, the accepted-credit target, the
language-track alternative, and the training/FYP identities used by planning.

The course pool is the set of course identities the student may be able to register
to deliver those requirements, supply approved optional credit, or satisfy a
prerequisite. Availability in this pool does not make a course a graduation
requirement and does not automatically give it degree-credit authority.

The central invariant is:

> Taking a NEW-curriculum course does not automatically change an OLD-curriculum
> student's governing graduation requirements.

A verified prospective OLD-to-NEW equivalency can add a NEW course as an alternative
way to deliver an OLD requirement. The OLD requirement remains the requirement.
NEW courses can also contribute approved optional credit. Neither case converts the
student to the NEW curriculum or creates every NEW requirement as an obligation.

## Transcript normalization

Persisted source rows are normalized before reconciliation:

- A direct `course_id` or persisted transcript-code alias resolves academic identity.
- A zero-ECTS code ending in `L` is treated as a component row only when its base code
  also appears in the transcript and the lab has no resolved course identity.
- Configured non-degree codes are excluded from unresolved earned credit.
- `counts_toward_degree_credit=false` forces accepted earned credit to zero even when
  a row is passed.
- Unresolved, degree-credit-bearing rows retain their recorded credit in the
  student's unresolved earned-credit total and are reported as unknown codes.
- The source code becomes `credit_identity`, preserving one credit identity even
  when multiple course codes map to the same modern course.

Normalization does not infer a pass, equivalency, or degree-credit decision.

## Requirement reconciliation

`ReconciliationService` starts with requirements resolved for the student's
language track. A requirement is satisfied by:

1. an explicit completed requirement ID already present on the student state;
2. a passed, transferred, or exempted attempt at that requirement; or
3. an attempt connected by an accepted equivalency in the direction applicable to
   the governing curriculum.

Failed, withdrawn, registered, and in-progress attempts do not satisfy requirements.
They may still affect other policies, such as unresolved-failure capacity or a
registered FYP pathway.

Allocation is deterministic and one-to-one. Attempts retain input order. Direct
identity is considered before sorted equivalency candidates, and a requirement that
is already satisfied cannot be allocated again. One completion therefore cannot
satisfy two independent requirements.

Accepted earned credit is separate from requirement allocation. For every completed
attempt, reconciliation keeps the maximum recorded earned ECTS per stable
`credit_identity`, then adds any explicitly supplied unresolved earned-credit total.
This prevents repeated successful attempts or aliases from double-counting credit.
An equivalency satisfies a requirement but does not replace the source attempt's
historical ECTS with the target course's ECTS.

Accepted equivalencies also add the applicable equivalent identity to prerequisite
completion. This allows recognized historical work to unlock a dependent course
without pretending the student completed both courses for credit.

## Student-specific classifications

Reconciliation produces these classifications:

| Classification | Meaning |
| --- | --- |
| `SATISFIED` | Completed directly, fulfilled by accepted recognition, or an already-completed approved optional course whose credit is already in the transcript total. |
| `MANDATORY_OUTSTANDING` | An explicit unsatisfied requirement in the governing contract. |
| `APPROVED_OPTIONAL` | A student-scoped optional candidate with `APPROVED` status, an authority, and a source reference. |
| `REGISTRATION_ONLY` | The course may be considered for registration but has no established graduation-credit role, or its optional credit was rejected. |
| `NEEDS_REVIEW` | Evidence is unverified, lacks authority/source, or an attempted course has no applicable recognition. |

Catalog-level optional status is not by itself a student-specific approval. The
database-backed fallback for students without an imported degree contract explicitly
creates approvals under the implemented IUL 300-ECTS credit-band policy. Students
with an imported degree contract instead use that contract's persisted categories
and quotas.

The diagnostic unresolved difference is:

```text
max(0, accepted-credit target
       - official earned credit
       - credits of outstanding mandatory requirement definitions)
```

It is a diagnostic, not an inferred elective rule.

## Strict and exploratory planning

Strict mode admits optional candidates only when the decision is `APPROVED` and has
both an authority and a source reference. Exploratory mode also admits `UNVERIFIED`
optional decisions. If one is selected, the plan is marked hypothetical and warns
that it is not an official graduation-ready plan.

This distinction is implemented at the `PlanningProblem` boundary. The current HTTP
schema accepts `exploratory_recognition`, but the web services do not copy it into
`PlanningProblem.exploratory`; API/UI planning therefore remains strict. Direct
engine callers can exercise exploratory behavior, and regression tests cover it.

Rejected, undocumented, and registration-only courses never gain optional
graduation credit through exploration. Prerequisites added solely to unlock an
approved optional course are auxiliary: they consume time and capacity but do not
contribute to the accepted-credit expression unless they independently have an
authorized graduation role.

## OLD/NEW recognition and delivery

The transition catalogue distinguishes two permissions:

- `recognizes_history` allows a completed course to satisfy the mapped governing
  requirement and prerequisite identity;
- `prospective_registration_allowed` allows a future course on the other side of the
  mapping to deliver an outstanding OLD requirement.

For an OLD governing contract, `requirement_delivery_options` begins with each OLD
requirement delivering itself. Only a prospective, verified equivalency adds its NEW
target as another schedulable delivery identity. NEW-governed requirements are not
expanded by this function.

If one registration identity could deliver multiple outstanding requirements and no
allocation rule resolves the ambiguity, the planner returns infeasible instead of
double-counting it. Accepted equivalency sides are also mutually exclusive in a
prospective plan.

OLD courses without a direct NEW mapping remain explicitly classified in persistence
as legacy-credit-only or pathway-specific. The completeness check requires every
active OLD course to have either a mapping or such a disposition. OLD support is a
current academic feature, not obsolete compatibility code.

## Degree-contract credit groups

An imported degree contract can define top-level credit groups. Historical credit is
recognized first by direct membership or exact equivalency, then by persisted
same-category legacy recognition. Recognized credit is capped at the group's quota.
The planner enforces each remaining top-level quota against that group's explicit
candidate contributions, so excess in one group cannot satisfy another.

The capstone is pathway-specific instead of fungible category credit. When a student
is currently registered or in progress in an FYP component, the engine replaces the
otherwise configured FYP requirement with every FYP component from that registered
component's curriculum. It does not change non-FYP requirements.

## Registration eligibility

The current-term eligibility view applies, in order, the implemented checks for:

- whether the course is outstanding/applicable;
- missing prerequisites;
- a supplied offering in the term;
- progressive OLD/NEW rollout permission; and
- academic track registration restrictions.

Each rejection retains a structured reason. This UI eligibility pool is narrower
than the optimizer's multi-term pool and should not be used as a replacement for the
governing contract.

## Credit and duplication invariants

- Recorded earned credit is counted once per stable transcript identity.
- One completion is allocated to at most one independent requirement.
- An equivalency changes requirement satisfaction, not historical ECTS.
- Both sides of an equivalency cannot be independently selected in one prospective
  plan when both enter the planning pool.
- Optional and auxiliary courses do not become mandatory requirements.
- Registration, current observation, or NEW-course availability does not change the
  governing curriculum.
- A provisional administrative credit adjustment is a proposal only. It is not a
  completed course, is not persisted as earned credit, and requires approval.

## Unresolved assumptions

Unknown transcript codes, unverified future offerings, synthetic sections,
alternate-track sections, provisional corrections, unsupported prerequisite groups,
and unverified optional approvals remain explicit in diagnostics, warnings, or
errors. The engine does not silently convert those uncertainties into academic facts.

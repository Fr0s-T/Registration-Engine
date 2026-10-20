# Data contracts

The application has dedicated OLD-XLSX and NEW-PDF curriculum importers. Both
produce a shared validated representation before an explicitly confirmed,
curriculum-scoped database replacement. The planning engine continues to consume
the same typed database-backed objects and is independent of source format.

The current `SyntheticFixtureLoader` is an in-code, PDF-derived demonstration
fixture rather than an ingestion layer. Its records are explicitly marked
`SYNTHETIC_UNVERIFIED` and are designed to be replaced, not migrated as truth.

Synthetic prerequisites are maintained as explicit `NEW_PREREQUISITES` and
`OLD_PREREQUISITES` code-to-code mappings. They are intentionally sparse and do
not impose automatic semester or academic-year progression gates.

The loader exposes independent baseline/relaxed prerequisite and timetable
axes. The baseline is preserved for reproducibility. Relaxed prerequisite
overrides and the additional CCE431 section are additive, explicitly named,
and retain `SYNTHETIC_UNVERIFIED` provenance. They are sensitivity-test inputs,
not assertions about official university policy or schedules. The runtime
default is the relaxed fixture; baseline is loaded only when requested by the
comparison runner or regression tests.

- `courses`: stable ID, code, title, ECTS, curriculum version, reference year
  and semester, component/grade metadata.
- `curricula`: version, effective period, mandatory requirement IDs, language
  alternatives, accepted-credit target, FYP and training requirement IDs.
- `equivalencies`: stable mapping ID, source course IDs, target requirement IDs,
  approval/effective metadata.
- `attempts`: student ID, course ID, term, grade, explicit attempt status and
  official earned credits.
- `offerings`: course ID, term, availability confidence, and current-term bundles;
  bundles contain CRNs, components, campus, and meeting intervals.
- `policies`: rollout matrix, term capacities, registration-rule parameters and
  explicit offering overrides.

## Curriculum import sources

Catalog publication is performed through `/imports`, not by committing data files
to this directory. The application retains uploaded originals locally in
`import_sources/` and stores a SHA-256-linked source record in SQLite. That directory
is ignored by Git because uploaded documents may be private or third-party material.

The adapters currently accept:

- an XLSX workbook for the OLD curriculum;
- a text-based PDF for the NEW curriculum;
- a CSV timetable export;
- pasted contract-sheet text for student intake.

Parser compatibility is layout-dependent. A recognized extension does not imply
that every workbook, PDF, CSV, or pasted export can be parsed safely. Always inspect
the preview, warnings, fatal validation issues, and parsed totals before confirming
replacement. Scanned PDFs require OCR before this project can read their text.

No source documents are loaded automatically at application startup. Local review
inputs belong under the ignored `PDF/` directory; retained imports belong under the
ignored `data/import_sources/` directory.

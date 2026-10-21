const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);

let preview = null;
let activeFilter = "ALL";
let reviewDecisions = [];
let savedStudent = null;
let registrationMode = "REBUILD_CURRENT";
let planningDefaults = null;
let studentScenario = null;
let planningOptionsNotice = "";
let printOpenState = null;
let currentMeetings = [];

const FALLBACK_PLANNING_DEFAULTS = {
  regular_credit_capacity: 30,
  academic_year_deviation_weight: 10,
  reference_semester_deviation_weight: 2,
  allow_training_postponement: true,
  training_delay_penalty: 10,
  max_training_delay_years: null,
  solver_time_limit_seconds: 20,
  initial_horizon_semesters: 10,
  max_horizon_semesters: 20,
  auto_extend_horizon: true,
  horizon_extension_step: 2,
  allow_extended_load_when_repeating_failed_course: false,
  allow_final_two_semester_graduation_load: true,
  enable_course_selection_diagnostics: false,
  max_diagnostic_courses: 5,
  exploratory_recognition: false
};

const form = $("#paste-form");
const input = $("#contract-text");
const parseButton = $("#parse-button");

input.addEventListener("input", () => {
  $("#character-count").textContent = `${input.value.length.toLocaleString()} characters`;
  if (preview) {
    preview = null;
    reviewDecisions = [];
    savedStudent = null;
    $("#preview").classList.add("hidden");
    $("#analysis").classList.add("hidden");
    $("#empty-state").classList.remove("hidden");
    setWorkflow(1);
  }
});

$("#clear-button").addEventListener("click", clearWorkspace);
$("#new-student").addEventListener("click", clearWorkspace);
$("#print-analysis").addEventListener("click", printExpandedAnalysis);
window.addEventListener("beforeprint", prepareAnalysisPrint);
window.addEventListener("afterprint", restoreAnalysisPrint);
$("#back-to-record").addEventListener("click", () => {
  $("#analysis").classList.add("hidden");
  $("#preview").classList.remove("hidden");
  $("#page-shell").classList.remove("analysis-mode");
  setWorkflow(2);
});

form.addEventListener("submit", async event => {
  event.preventDefault();
  reviewDecisions = [];
  activeFilter = "ALL";
  savedStudent = null;
  await loadPreview();
});

function setWorkflow(step) {
  document.querySelectorAll("[data-workflow-step]").forEach(item => {
    const itemStep = Number(item.dataset.workflowStep);
    item.classList.toggle("active", itemStep === step);
    item.classList.toggle("complete", itemStep < step);
  });
}

function clearWorkspace() {
  input.value = "";
  input.dispatchEvent(new Event("input"));
  preview = null;
  reviewDecisions = [];
  savedStudent = null;
  planningDefaults = null;
  studentScenario = null;
  planningOptionsNotice = "";
  currentMeetings = [];
  activeFilter = "ALL";
  $("#preview").classList.add("hidden");
  $("#analysis").classList.add("hidden");
  $("#error-state").classList.add("hidden");
  $("#loading-state").classList.add("hidden");
  $("#empty-state").classList.remove("hidden");
  $("#page-shell").classList.remove("analysis-mode");
  setWorkflow(1);
  input.focus();
}

async function loadPreview() {
  setLoading(true);
  try {
    const response = await fetch("/api/student-input/preview", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        text: input.value,
        current_term: preview?.current_term || undefined,
        decisions: reviewDecisions
      })
    });
    const body = await response.json();
    if (!response.ok) throw new Error(formatApiError(body));
    preview = body;
    render(preview);
    setWorkflow(2);
  } catch (error) {
    $("#loading-state").classList.add("hidden");
    $("#preview").classList.add("hidden");
    $("#error-state").textContent = `The preview could not be created: ${error.message}`;
    $("#error-state").classList.remove("hidden");
  } finally {
    setLoading(false);
  }
}

function formatApiError(body) {
  const detail = body?.detail;
  if (Array.isArray(detail)) return detail.map(item => item.msg).join("; ");
  if (typeof detail === "object" && detail?.message) return detail.message;
  return detail || "The request could not be completed.";
}

function setLoading(loading) {
  parseButton.disabled = loading;
  parseButton.textContent = loading ? "Parsing..." : "Parse and review";
  $("#empty-state").classList.add("hidden");
  $("#error-state").classList.add("hidden");
  $("#preview").classList.toggle("hidden", loading || !preview);
  $("#loading-state").classList.toggle("hidden", !loading);
}

function statusClass(status) {
  if (["MATCH", "COMPLETED", "OPTIMAL", "FEASIBLE"].includes(status)) return "status-match";
  if (["HISTORICAL_UNMAPPED", "TRANSCRIPT_EXCLUDED", "ADJUSTED"].includes(status)) return "status-history";
  if (["FAILED_OUTSTANDING", "MISMATCH", "INFEASIBLE", "ERROR"].includes(status)) return "status-failed";
  return "status-review";
}

function friendlyStatus(status) {
  const labels = {
    HISTORICAL_UNMAPPED: "Historical/unmapped credit",
    TRANSCRIPT_EXCLUDED: "Credit/GPA excluded",
    RESOLVED: "Curriculum match confirmed",
    NON_DEGREE: "Non-degree",
    ACTIVE_OUTSTANDING: "Currently registered"
  };
  if (labels[status]) return labels[status];
  return String(status).replaceAll("_", " ").toLowerCase().replace(/^./, value => value.toUpperCase());
}

function courseLabel(title, code) {
  return `${title || "Course name unavailable"} (${code || "code unavailable"})`;
}

function optionParts(option) {
  const normalized = String(option).replace(" \u00e2\u20ac\u201d ", " \u2014 ");
  const [label, ...effectParts] = normalized.split(" \u2014 ");
  return {label, effect: effectParts.join(" \u2014 ")};
}

function reviewOption(option) {
  const {label, effect} = optionParts(option);
  return `<div class="review-option"><strong>${esc(label)}</strong>${effect ? `<small>${esc(effect)}</small>` : ""}</div>`;
}

const PAST_UNGRADED_ACTIONS = [
  "ENTER_FINAL_GRADE", "COMPLETED_GRADE_PENDING", "WITHDRAWN",
  "STILL_IN_PROGRESS", "NOT_TAKEN", "LEAVE_UNRESOLVED"
];

const REVIEW_ACTIONS = {
  PAST_UNGRADED_ATTEMPT: PAST_UNGRADED_ACTIONS,
  LAB_PARENT_MISSING: [
    "ATTACH_LAB_TO_PARENT", "KEEP_LAB_FOR_AUDIT",
    "IGNORE_LAB_ROW", "LEAVE_UNRESOLVED"
  ],
  CATEGORY_TOTAL_MISMATCH: [
    "ACCEPT_PARSED_CATEGORY_TOTAL", "LEAVE_UNRESOLVED"
  ],
  CREDIT_TOTAL_MISMATCH: [
    "ACCEPT_PARSED_CREDIT_TOTAL", "LEAVE_UNRESOLVED"
  ]
};

function interactiveReviewOptions(issue) {
  const actions = REVIEW_ACTIONS[issue.code] || [];
  const acceptsGrade = actions.includes("ENTER_FINAL_GRADE");
  return `<fieldset class="decision-options"><legend>Choose one action</legend>${issue.options.map((option, index) => {
    const {label, effect} = optionParts(option);
    const action = actions[index] || "LEAVE_UNRESOLVED";
    return `<label class="review-option selectable"><input type="radio" name="decision-${esc(issue.id)}" value="${esc(action)}"><span><strong>${esc(label)}</strong>${effect ? `<small>${esc(effect)}</small>` : ""}</span></label>`;
  }).join("")}</fieldset>${acceptsGrade ? `<div class="grade-entry hidden" data-grade-entry="${esc(issue.id)}"><label for="grade-${esc(issue.id)}">Final numeric grade</label><input id="grade-${esc(issue.id)}" type="number" min="0" max="100" step="0.01" inputmode="decimal" placeholder="0-100"><small>The detected passing grade is ${esc(preview.identity.passing_grade)}.</small></div>` : ""}<div class="decision-footer"><button type="button" class="primary apply-decision" data-issue-id="${esc(issue.id)}" data-attempt-id="${esc(issue.attempt_id)}" data-issue-code="${esc(issue.code)}">Apply decision</button><span class="decision-error" data-decision-error="${esc(issue.id)}" role="alert"></span></div>`;
}

function reviewControls(issue) {
  if (REVIEW_ACTIONS[issue.code]) return interactiveReviewOptions(issue);
  if (!issue.options.length) return "";
  return `<div class="manual-review-note"><strong>Manual source correction required</strong><small>This exception has no safe automatic action. Correct the pasted course data, then choose Parse and review again.</small></div>`;
}

function appliedDecisionMarkup(decision) {
  return `<div class="applied-decision"><div><strong>${esc(decision.course_label)}</strong><small>${esc(decision.summary)}</small></div><button type="button" class="secondary undo-decision" data-attempt-id="${esc(decision.attempt_id)}" data-issue-code="${esc(decision.issue_code)}">Undo</button></div>`;
}

function render(data) {
  $("#loading-state").classList.add("hidden");
  $("#error-state").classList.add("hidden");
  $("#preview").classList.remove("hidden");
  renderStudent(data);
  renderSummary(data);
  renderRegistered(data);
  renderReview(data);
  renderSave(data);
  renderCredit(data);
  renderCategories(data);
  renderFilters(data);
  renderGroups(data);
}

function renderStudent(data) {
  const student = data.identity;
  const tags = [
    student.student_id && `ID ${student.student_id}`,
    student.program_code,
    student.language_track && `${student.language_track} track`,
    student.graduation_target && `${student.graduation_target} ECTS target`,
    `Passing grade ${student.passing_grade}`,
    `Current term ${data.current_term}`
  ].filter(Boolean);
  $("#student-header").innerHTML = `
    <div><span class="eyebrow">Detected student</span><h1>${esc(student.name || "Name not detected")}</h1><p>${esc(student.program_title || "Program title not detected")}</p></div>
    <div class="identity-tags">${tags.map(tag => `<span>${esc(tag)}</span>`).join("")}</div>`;
}

function renderSummary(data) {
  const cards = [
    [data.attempts_parsed, "Attempts", `${data.duplicate_attempts_merged} duplicates merged`],
    [data.completed_courses, "Completed courses", "after OLD/NEW grouping"],
    [data.failed_outstanding_courses, "Failed outstanding", "no passing equivalent found"],
    [data.currently_registered_courses, "Currently registered", "active semester"],
    [data.lab_components, "Lab components", "attached without extra credit"],
    [data.review_issues.length, "Review questions", data.can_continue_without_review ? "ready to save" : "resolve before saving"]
  ];
  $("#summary").innerHTML = cards.map(([value, label, detail]) => `
    <article class="summary-card"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small></article>`).join("");
}

function registeredGroups(data) {
  return data.course_groups.filter(group => group.currently_registered);
}

function renderRegistered(data) {
  const groups = registeredGroups(data);
  if (!groups.length) {
    $("#registered-panel").innerHTML = `<article class="panel compact-panel"><div class="panel-head"><div><span class="eyebrow">Active semester</span><h2>No current registration detected</h2><p>The generated plan can begin with ${esc(data.current_term)}.</p></div><span class="status-pill status-history">NONE</span></div></article>`;
    return;
  }
  $("#registered-panel").innerHTML = `<article class="panel registered-panel"><div class="panel-head"><div><span class="eyebrow">Active semester</span><h2>Currently registered courses</h2><p>These are visible before saving and can be kept as the actual semester or rebuilt as a simulation.</p></div><span class="status-pill status-active">${groups.length} REGISTERED</span></div><div class="course-card-grid">${groups.map(group => `<div class="mini-course"><strong>${esc(courseLabel(group.title, group.display_code))}</strong><span>${group.attempts[0]?.ects ?? 0} ECTS / ${esc(data.current_term)}</span></div>`).join("")}</div></article>`;
}

function renderReview(data) {
  const applied = data.applied_decisions || [];
  const appliedMarkup = applied.length ? `<div class="applied-list"><h3>Applied review decisions</h3>${applied.map(appliedDecisionMarkup).join("")}</div>` : "";
  if (!data.review_issues.length) {
    $("#review-panel").innerHTML = `<article class="panel review-panel clear"><div class="panel-head"><div><span class="eyebrow">Review gate</span><h2>Review complete</h2></div><span class="status-pill status-match">CLEAR</span></div><p class="clear-copy">Courses, statuses, lab parents, and the credit ledger reconcile after the applied decisions.</p>${appliedMarkup}</article>`;
    bindReviewActions();
    return;
  }
  $("#review-panel").innerHTML = `<article class="panel review-panel"><div class="panel-head"><div><span class="eyebrow">Review gate</span><h2>${data.review_issues.length} item${data.review_issues.length === 1 ? "" : "s"} need attention</h2><p>Choose an action for each exception. Nothing is saved yet.</p></div><span class="status-pill status-review">REVIEW</span></div>${appliedMarkup}${data.review_issues.map((issue, index) => `
    <div class="issue"><span class="issue-index">${index + 1}</span><div><strong>${esc(issue.question || friendlyStatus(issue.code))}</strong><p>${esc(issue.message)}</p>${reviewControls(issue)}</div></div>`).join("")}</article>`;
  bindReviewActions();
}

function bindReviewActions() {
  $("#review-panel").querySelectorAll('input[type="radio"]').forEach(radio => {
    radio.addEventListener("change", () => {
      const issueId = radio.name.replace("decision-", "");
      const gradeEntry = $(`[data-grade-entry="${CSS.escape(issueId)}"]`);
      gradeEntry?.classList.toggle("hidden", radio.value !== "ENTER_FINAL_GRADE");
      $(`[data-decision-error="${CSS.escape(issueId)}"]`).textContent = "";
    });
  });
  $("#review-panel").querySelectorAll(".apply-decision").forEach(button => {
    button.addEventListener("click", async () => {
      const issueId = button.dataset.issueId;
      const selected = $(`input[name="decision-${CSS.escape(issueId)}"]:checked`);
      const error = $(`[data-decision-error="${CSS.escape(issueId)}"]`);
      if (!selected) {
        error.textContent = "Choose an action first.";
        return;
      }
      if (selected.value === "LEAVE_UNRESOLVED") {
        error.textContent = "This item remains unresolved and continues to block saving.";
        return;
      }
      const decision = {
        issue_code: button.dataset.issueCode,
        attempt_id: button.dataset.attemptId,
        action: selected.value
      };
      if (selected.value === "ENTER_FINAL_GRADE") {
        const rawGrade = $(`#grade-${CSS.escape(issueId)}`).value;
        const grade = Number(rawGrade);
        if (rawGrade === "" || !Number.isFinite(grade) || grade < 0 || grade > 100) {
          error.textContent = "Enter a final numeric grade from 0 to 100.";
          return;
        }
        decision.grade_value = grade;
      }
      reviewDecisions = reviewDecisions.filter(item => !(
        item.issue_code === decision.issue_code && item.attempt_id === decision.attempt_id
      ));
      reviewDecisions.push(decision);
      await loadPreview();
    });
  });
  $("#review-panel").querySelectorAll(".undo-decision").forEach(button => {
    button.addEventListener("click", async () => {
      reviewDecisions = reviewDecisions.filter(item => !(
        item.issue_code === button.dataset.issueCode && item.attempt_id === button.dataset.attemptId
      ));
      await loadPreview();
    });
  });
}

function renderSave(data) {
  if (!data.can_continue_without_review) {
    $("#save-panel").innerHTML = `<article class="panel save-panel blocked-save"><div><span class="eyebrow">Next action</span><h2>Resolve the review items before saving</h2><p>The database and planning engine have not been changed.</p></div><button class="primary" type="button" disabled>Save student and analyze</button></article>`;
    return;
  }
  $("#save-panel").innerHTML = `<article class="panel save-panel"><div><span class="eyebrow">Next action</span><h2>Ready for the planning engine</h2><p>This saves the verified transcript, then opens analysis for ${esc(data.identity.name || "this student")} in this workspace.</p></div><button class="primary save-student" type="button">Save student and analyze</button></article>`;
  $("#save-panel .save-student").addEventListener("click", () => saveStudent(false));
}

async function saveStudent(replaceExisting) {
  const button = $("#save-panel .save-student, #save-panel .replace-student");
  if (button) {
    button.disabled = true;
    button.textContent = replaceExisting ? "Replacing record..." : "Saving student...";
  }
  try {
    const response = await fetch("/api/student-input/commit", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        text: input.value,
        current_term: preview.current_term,
        preview_token: preview.preview_token,
        decisions: reviewDecisions,
        replace_existing: replaceExisting
      })
    });
    const body = await response.json();
    if (response.status === 409 && body.detail?.code === "STUDENT_EXISTS") {
      renderExistingConflict(body.detail);
      return;
    }
    if (!response.ok) throw new Error(formatApiError(body));
    savedStudent = body;
    registrationMode = body.recommended_registration_mode;
    await loadPlanningConfiguration();
    showAnalysis();
    await analyzeStudent();
  } catch (error) {
    $("#save-panel").innerHTML = `<article class="panel save-panel blocked-save"><div><span class="eyebrow">Save failed</span><h2>The record was not saved</h2><p>${esc(error.message)}</p></div><button class="primary save-student" type="button">Try again</button></article>`;
    $("#save-panel .save-student").addEventListener("click", () => saveStudent(replaceExisting));
  }
}

function renderExistingConflict(detail) {
  const existing = detail.existing;
  const incoming = detail.incoming;
  $("#save-panel").innerHTML = `<article class="panel conflict-panel"><div class="panel-head"><div><span class="eyebrow">Existing student found</span><h2>Review before replacing ${esc(existing.display_name)}</h2><p>The existing record will not be changed unless you explicitly replace it.</p></div><span class="status-pill status-review">CONFIRM</span></div><div class="comparison-grid"><div><span>Saved record</span><strong>${existing.attempts} attempts</strong><small>${existing.reported_earned_credits} reported ECTS</small></div><div><span>Incoming record</span><strong>${incoming.attempts} attempts</strong><small>${incoming.reported_earned_credits} parsed ECTS</small></div></div><div class="conflict-actions"><button class="primary replace-student" type="button">Replace academic record and analyze</button><button class="secondary cancel-replace" type="button">Keep saved record unchanged</button></div></article>`;
  $("#save-panel .replace-student").addEventListener("click", () => saveStudent(true));
  $("#save-panel .cancel-replace").addEventListener("click", () => renderSave(preview));
}

function showAnalysis() {
  $("#preview").classList.add("hidden");
  $("#empty-state").classList.add("hidden");
  $("#analysis").classList.remove("hidden");
  $("#page-shell").classList.add("analysis-mode");
  setWorkflow(3);
  $("#analysis-student-name").textContent = savedStudent.display_name;
  $("#analysis-student-context").textContent = `${savedStudent.identifier} / ${savedStudent.attempts_saved} saved transcript rows / ${savedStudent.current_term}`;
  renderRegistrationMode();
  renderPlanningOptions();
  window.scrollTo({top: 0, behavior: "smooth"});
}

function renderRegistrationMode() {
  if (!savedStudent.currently_registered_courses) {
    $("#registration-mode-panel").innerHTML = `<article class="panel compact-panel"><div class="panel-head"><div><span class="eyebrow">Planning start</span><h2>No active registration to preserve</h2><p>The engine will build a proposed schedule beginning in ${esc(savedStudent.current_term)}.</p></div><span class="status-pill status-history">PROPOSED</span></div></article>`;
    return;
  }
  $("#registration-mode-panel").innerHTML = `<article class="panel mode-panel"><div class="panel-head"><div><span class="eyebrow">Planning mode</span><h2>How should the active semester be handled?</h2><p>This changes the plan only. It never changes the university registration.</p></div></div><div class="mode-options"><label class="mode-option"><input type="radio" name="registration-mode" value="KEEP_CURRENT" ${registrationMode === "KEEP_CURRENT" ? "checked" : ""}><span><strong>Keep current registration and plan next</strong><small>Recommended. Lock the registered courses in ${esc(savedStudent.current_term)} and plan later terms around them. They are not counted as passed yet.</small></span></label><label class="mode-option"><input type="radio" name="registration-mode" value="REBUILD_CURRENT" ${registrationMode === "REBUILD_CURRENT" ? "checked" : ""}><span><strong>Rebuild the current semester</strong><small>Simulation. Let the engine keep, add, replace, or remove registered courses and compare the result with the actual registration.</small></span></label></div></article>`;
}

async function loadPlanningConfiguration() {
  planningDefaults = {...FALLBACK_PLANNING_DEFAULTS};
  studentScenario = null;
  planningOptionsNotice = "";
  try {
    const [configResponse, scenariosResponse] = await Promise.all([
      fetch("/api/config"), fetch("/api/scenarios")
    ]);
    if (!configResponse.ok || !scenariosResponse.ok) {
      throw new Error("Planning configuration could not be loaded.");
    }
    const config = await configResponse.json();
    const scenarios = await scenariosResponse.json();
    planningDefaults = {...FALLBACK_PLANNING_DEFAULTS, ...config.defaults};
    studentScenario = scenarios.find(item => item.identifier === savedStudent.identifier) || null;
    if (!studentScenario) planningOptionsNotice = "Term overrides are unavailable because this student was not found in the planning scenario list.";
  } catch (error) {
    planningOptionsNotice = "Default planning values are available, but term overrides could not be loaded from the planning service.";
  }
}

function renderPlanningOptions() {
  const defaults = planningDefaults || FALLBACK_PLANNING_DEFAULTS;
  const termsAvailable = Boolean(studentScenario?.available_terms?.length);
  const notice = planningOptionsNotice ? `<p class="options-notice">${esc(planningOptionsNotice)}</p>` : "";
  $("#planning-options-panel").innerHTML = `<article class="panel planning-options">
    <div class="panel-head"><div><span class="eyebrow">Planning controls</span><h2>Analysis options</h2><p>These assumptions apply only to this plan. The saved student record is unchanged.</p></div><span class="capacity-badge">${esc(defaults.regular_credit_capacity)} ECTS / regular term</span></div>
    ${notice}
    <div class="override-editor">
      <div class="options-heading-row"><div><h3>Term capacity overrides</h3><p>Replace the regular capacity for a specific Fall or Spring period.</p></div><button type="button" class="secondary add-term-override" ${termsAvailable ? "" : "disabled"}>Add override</button></div>
      <div class="student-override-list"></div>
    </div>
    <details class="analysis-advanced">
      <summary>Advanced preferences</summary>
      <div class="advanced-grid">
        <label>Academic-year priority<input id="student-year-weight" type="number" min="0" max="1000" value="${esc(defaults.academic_year_deviation_weight)}"><small>Zero disables this soft tie-breaker.</small></label>
        <label>Fall/Spring alignment<input id="student-semester-weight" type="number" min="0" max="1000" value="${esc(defaults.reference_semester_deviation_weight)}"></label>
        <label class="switch-row"><span>Allow training postponement</span><input id="student-training-postponement" type="checkbox" ${defaults.allow_training_postponement ? "checked" : ""}></label>
        <label>Training delay penalty<input id="student-training-penalty" type="number" min="0" max="1000" value="${esc(defaults.training_delay_penalty)}"></label>
        <label>Maximum training delay (years)<input id="student-training-max-delay" type="number" min="0" max="10" value="${defaults.max_training_delay_years == null ? "" : esc(defaults.max_training_delay_years)}" placeholder="No maximum"></label>
        <label>Solver time limit (seconds)<input id="student-solver-limit" type="number" min="0.1" max="120" step="0.1" value="${esc(defaults.solver_time_limit_seconds)}"></label>
        <label>Initial regular-semester horizon<input id="student-initial-horizon" type="number" min="1" max="40" value="${esc(defaults.initial_horizon_semesters)}"></label>
        <label>Maximum regular-semester horizon<input id="student-max-horizon" type="number" min="1" max="40" value="${esc(defaults.max_horizon_semesters)}"><small>Training periods are not counted as regular semesters.</small></label>
        <label class="switch-row"><span>Automatically extend the horizon</span><input id="student-auto-extend-horizon" type="checkbox" ${defaults.auto_extend_horizon ? "checked" : ""}></label>
        <label>Extension step (regular semesters)<input id="student-horizon-step" type="number" min="1" max="10" value="${esc(defaults.horizon_extension_step)}"></label>
        <label class="switch-row"><span>Run course-selection diagnostics</span><input id="student-selection-diagnostics" type="checkbox" ${defaults.enable_course_selection_diagnostics ? "checked" : ""}><small>Runs bounded counterfactual checks for courses that were not selected.</small></label>
        <label class="switch-row"><span>Exploratory unverified equivalency assumptions</span><input id="student-exploratory-recognition" type="checkbox" ${defaults.exploratory_recognition ? "checked" : ""}><small>Assumptions remain request-scoped and are not saved to the student record.</small></label>
      </div>
    </details>
    <div class="options-actions"><button type="button" class="primary update-plan">Update analysis</button><button type="button" class="secondary reset-planning-options">Reset defaults</button><span class="options-error" role="alert"></span></div>
  </article>`;
  $("#planning-options-panel .add-term-override").addEventListener("click", () => addTermOverride());
  $("#planning-options-panel .reset-planning-options").addEventListener("click", renderPlanningOptions);
  $("#planning-options-panel .update-plan").addEventListener("click", analyzeStudent);
}

function addTermOverride(saved = null) {
  const terms = studentScenario?.available_terms || [];
  if (!terms.length) return;
  const selectedTerms = new Set([...document.querySelectorAll(".student-override-row select")].map(select => select.value));
  const selectedTerm = saved?.term || terms.find(term => !selectedTerms.has(term)) || terms[0];
  const row = document.createElement("div");
  row.className = "student-override-row";
  row.innerHTML = `<select aria-label="Override term">${terms.map(term => `<option value="${esc(term)}" ${term === selectedTerm ? "selected" : ""}>${esc(term)}</option>`).join("")}</select><label><span>ECTS capacity</span><input aria-label="ECTS capacity" type="number" min="1" max="60" value="${esc(saved?.capacity ?? planningDefaults?.regular_credit_capacity ?? 30)}"></label><button type="button" class="secondary remove-override" aria-label="Remove term override">Remove</button>`;
  row.querySelector(".remove-override").addEventListener("click", () => row.remove());
  $("#planning-options-panel .student-override-list").append(row);
}

function planningRequestPayload() {
  const defaults = planningDefaults || FALLBACK_PLANNING_DEFAULTS;
  const overrides = {};
  document.querySelectorAll(".student-override-row").forEach(row => {
    overrides[row.querySelector("select").value] = Number(row.querySelector("input").value);
  });
  const maxDelay = $("#student-training-max-delay").value;
  return {
    scenario_id: savedStudent.identifier,
    registration_mode: registrationMode,
    regular_credit_capacity: defaults.regular_credit_capacity,
    per_semester_capacity_overrides: overrides,
    academic_year_deviation_weight: Number($("#student-year-weight").value),
    reference_semester_deviation_weight: Number($("#student-semester-weight").value),
    allow_training_postponement: $("#student-training-postponement").checked,
    training_delay_penalty: Number($("#student-training-penalty").value),
    max_training_delay_years: maxDelay === "" ? null : Number(maxDelay),
    solver_time_limit_seconds: Number($("#student-solver-limit").value),
    initial_horizon_semesters: Number($("#student-initial-horizon").value),
    max_horizon_semesters: Number($("#student-max-horizon").value),
    auto_extend_horizon: $("#student-auto-extend-horizon").checked,
    horizon_extension_step: Number($("#student-horizon-step").value),
    allow_extended_load_when_repeating_failed_course: defaults.allow_extended_load_when_repeating_failed_course,
    allow_final_two_semester_graduation_load: defaults.allow_final_two_semester_graduation_load,
    enable_course_selection_diagnostics: $("#student-selection-diagnostics").checked,
    max_diagnostic_courses: defaults.max_diagnostic_courses,
    exploratory_recognition: $("#student-exploratory-recognition").checked
  };
}

async function analyzeStudent() {
  const selectedMode = $('input[name="registration-mode"]:checked');
  if (selectedMode) registrationMode = selectedMode.value;
  const updateButton = $("#planning-options-panel .update-plan");
  const optionsError = $("#planning-options-panel .options-error");
  if (optionsError) optionsError.textContent = "";
  if (updateButton) {
    updateButton.disabled = true;
    updateButton.textContent = "Updating analysis...";
  }
  $("#plan-loading").classList.remove("hidden");
  $("#plan-error").classList.add("hidden");
  $("#plan-results").classList.add("hidden");
  try {
    const response = await fetch("/api/plan", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(planningRequestPayload())
    });
    const body = await response.json();
    if (!response.ok) throw new Error(formatApiError(body));
    renderAnalysis(body);
    $("#plan-results").classList.remove("hidden");
  } catch (error) {
    $("#plan-error").innerHTML = `<h2>Could not generate the plan</h2><p>${esc(error.message)}</p>`;
    $("#plan-error").classList.remove("hidden");
    if (optionsError) optionsError.textContent = error.message;
  } finally {
    $("#plan-loading").classList.add("hidden");
    if (updateButton) {
      updateButton.disabled = false;
      updateButton.textContent = "Update analysis";
    }
  }
}

function renderAnalysis(data) {
  const currentCredits = data.current_semester?.total_credits ?? 0;
  const summary = [
    [friendlyStatus(data.solver.status), "Solver status", data.solver.global_optimality_proven ? "optimality proven" : "best result within limits"],
    [`${data.academic_summary.completed_credits} ECTS`, "Completed", "official earned credit"],
    [`${data.academic_summary.remaining_credits} ECTS`, "Remaining", "before planned courses"],
    [`${currentCredits} ECTS`, registrationMode === "KEEP_CURRENT" ? "Registered now" : "Proposed now", data.current_semester?.term || savedStudent.current_term],
    [data.graduation.term || "Not established", "Projected graduation", "under the current assumptions"],
    [data.academic_summary.regular_semesters_remaining, "Regular terms", "Fall/Spring periods remaining"]
  ];
  $("#plan-summary").innerHTML = summary.map(([value, label, detail], index) => `<article class="summary-card ${index === 0 ? statusClass(data.solver.status) : ""}"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small></article>`).join("");
  renderActualRegistration(data);
  renderCurrentPlan(data.current_semester);
  renderStudentTimetable(data.current_semester);
  renderFuturePlan(data.future_semesters, data.graduation.term);
  renderPlanWarnings(planNotes(data));
  renderAnalysisPrintNotes(data);
  renderAnalysisAudit(data);
}

function planNotes(data) {
  return [...new Set([
    ...(data.solver?.explanations || []),
    ...(data.warnings || [])
  ])];
}

function observedCourses(data) {
  const observed = data.transition_diagnostics?.current_registration_comparison?.observed_courses;
  if (observed?.length) return observed;
  return registeredGroups(preview).map(group => ({
    code: group.display_code, title: group.title, ects: group.attempts[0]?.ects ?? 0
  }));
}

function renderActualRegistration(data) {
  const courses = observedCourses(data);
  if (!courses.length) {
    $("#actual-registration-panel").innerHTML = "";
    return;
  }
  const comparison = data.transition_diagnostics?.current_registration_comparison;
  const explanation = registrationMode === "KEEP_CURRENT"
    ? "Locked as the actual active semester. No course is treated as passed until a final result is imported."
    : "Shown as the baseline for comparison; the proposed current semester may differ.";
  $("#actual-registration-panel").innerHTML = `<article class="panel registered-panel"><div class="panel-head"><div><span class="eyebrow">Portal source of truth</span><h2>Actual current registration</h2><p>${esc(explanation)}</p></div><span class="status-pill ${registrationMode === "KEEP_CURRENT" ? "status-match" : "status-review"}">${registrationMode === "KEEP_CURRENT" ? "LOCKED" : "COMPARE"}</span></div><div class="course-card-grid">${courses.map(course => `<div class="mini-course"><strong>${esc(courseLabel(course.title, course.code))}</strong><span>${course.ects} ECTS</span></div>`).join("")}</div>${comparison && registrationMode === "REBUILD_CURRENT" ? `<p class="comparison-note">The simulation matched ${comparison.matched_course_codes.length} of ${comparison.observed_course_codes.length} registered courses and added ${comparison.additional_course_codes.length} alternatives.</p>` : ""}</article>`;
}

function renderCurrentPlan(current) {
  const heading = registrationMode === "KEEP_CURRENT" ? "Actual registered semester" : "Proposed current semester";
  if (!current) {
    $("#current-plan-panel").innerHTML = `<article class="panel"><div class="panel-head"><div><span class="eyebrow">Active term</span><h2>${heading}</h2><p>No feasible current-semester schedule was produced.</p></div><span class="status-pill status-failed">NO PLAN</span></div></article>`;
    return;
  }
  const courses = current.selected_courses;
  $("#current-plan-panel").innerHTML = `<article class="panel"><div class="panel-head"><div><span class="eyebrow">Active term</span><h2>${heading}</h2><p>${esc(current.term)} / ${current.total_credits} of ${current.effective_credit_capacity} ECTS</p></div><span class="status-pill ${registrationMode === "KEEP_CURRENT" ? "status-match" : "status-review"}">${registrationMode === "KEEP_CURRENT" ? "ACTUAL" : "SIMULATION"}</span></div><div class="course-card-grid">${courses.length ? courses.map(course => `<div class="mini-course"><strong>${esc(courseLabel(course.title, course.code))}</strong><span>${course.credits} ECTS${course.sections.length ? ` / ${course.sections.length} section${course.sections.length === 1 ? "" : "s"}` : " / no meeting data"}</span></div>`).join("") : `<p>No courses selected.</p>`}</div></article>`;
}

function renderStudentTimetable(current) {
  if (!current) {
    currentMeetings = [];
    $("#timetable-panel").innerHTML = `<article class="panel timetable-card"><div class="panel-head"><div><span class="eyebrow">Weekly schedule</span><h2>Current-semester timetable</h2><p>No feasible current-semester selection is available.</p></div></div><div class="no-timetable">No timetable could be produced.</div></article>`;
    return;
  }
  currentMeetings = current.selected_courses.flatMap((course, colorIndex) =>
    course.sections.flatMap(section => section.meetings.map(meeting => ({
      ...meeting, course, section, colorIndex
    })))
  );
  const explanation = registrationMode === "KEEP_CURRENT"
    ? "Registered courses are fixed. Meeting blocks use the available section bundles selected by the engine; verify the CRNs because the pasted portal record does not identify the student's actual sections."
    : "Simulation timetable for the engine's proposed current semester.";
  const sectionChips = current.selected_courses.map(course => {
    const crns = [...new Set(course.sections.map(section => section.crn).filter(Boolean))];
    const sectionText = crns.length ? ` / CRN ${crns.join(", ")}` : " / no section data";
    return `<span class="course-chip">${esc(courseLabel(course.title, course.code))}${esc(sectionText)}</span>`;
  }).join("");
  $("#timetable-panel").innerHTML = `<article class="panel timetable-card"><div class="panel-head"><div><span class="eyebrow">Weekly schedule</span><h2>Current-semester timetable</h2><p>${esc(explanation)}</p></div><span class="capacity-badge">${esc(current.term)}</span></div><div class="course-strip">${sectionChips}</div><div id="student-timetable"></div></article>`;
  if (!currentMeetings.length) {
    $("#student-timetable").innerHTML = `<div class="no-timetable">Selected courses have no supplied meeting data. No meeting times were invented.</div>`;
    return;
  }
  renderStudentTimetableGrid(currentMeetings);
}

function renderStudentTimetableGrid(meetings, pixelsPerMinute = 1.05) {
  const dayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const days = dayNames.map((name, index) => ({name, index}));
  const minMinute = Math.floor(Math.min(...meetings.map(item => item.start_minute)) / 30) * 30;
  const maxMinute = Math.ceil(Math.max(...meetings.map(item => item.end_minute)) / 30) * 30;
  const height = Math.max(60, (maxMinute - minMinute) * pixelsPerMinute);
  const labels = [];
  for (let minute = minMinute; minute <= maxMinute; minute += 60) {
    labels.push(`<span class="time-label" style="top:${(minute - minMinute) * pixelsPerMinute}px">${formatMinute(minute)}</span>`);
  }
  const palette = [
    ["#dfeeff", "#2f79c6"], ["#e8f4e8", "#397b47"], ["#fff0d9", "#b56b16"],
    ["#eee8fb", "#7252b2"], ["#fbe5e8", "#b34f5d"], ["#dff4f2", "#2f8179"],
    ["#e8edf8", "#536c9d"]
  ];
  const columns = days.map(day => {
    const events = meetings.filter(item => item.weekday_index === day.index).map(item => {
      const [background, border] = palette[item.colorIndex % palette.length];
      const top = (item.start_minute - minMinute) * pixelsPerMinute;
      const eventHeight = Math.max(30, (item.end_minute - item.start_minute) * pixelsPerMinute);
      const room = item.section.room ? ` / ${item.section.room}` : "";
      const tooltip = `${courseLabel(item.course.title, item.course.code)}\n${item.section.component} / CRN ${item.section.crn}\n${item.start_time}-${item.end_time}${room}\nCampus: ${item.section.campus}`;
      return `<div class="meeting-event" tabindex="0" title="${esc(tooltip)}" style="top:${top}px;height:${eventHeight}px;--event-color:${background};--event-border:${border}"><strong>${esc(courseLabel(item.course.title, item.course.code))}</strong><span>${esc(item.section.component.split(":")[0])}</span><span class="event-meta">${esc(item.start_time)}-${esc(item.end_time)}${esc(room)}</span></div>`;
    }).join("");
    return `<div class="day-column">${events}</div>`;
  }).join("");
  $("#student-timetable").innerHTML = `<div class="timetable-scroll"><div class="timetable-grid" style="--day-count:${days.length};--grid-height:${height}px;--half-hour:${30 * pixelsPerMinute}px"><div class="time-corner">Time</div>${days.map(day => `<div class="day-heading">${day.name}</div>`).join("")}<div class="time-axis">${labels.join("")}</div>${columns}</div></div>`;
}

function formatMinute(minute) {
  return `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
}

function renderFuturePlan(terms, graduationTerm) {
  $("#future-plan-panel").innerHTML = `<article class="panel"><div class="panel-head"><div><span class="eyebrow">Graduation path</span><h2>Plan after the active semester</h2><p>${graduationTerm ? `Projected graduation: ${esc(graduationTerm)}` : "Graduation was not established within the modeled horizon."}</p></div></div><div class="term-list">${terms.length ? terms.map((term, index) => `<details class="term-card" ${index < 2 ? "open" : ""}><summary><strong>${esc(term.term)}</strong><span>${term.total_credits} / ${term.effective_credit_capacity} ECTS</span></summary><div class="term-courses">${term.courses.length ? term.courses.map(course => `<div><strong>${esc(courseLabel(course.title, course.code))}</strong><span>${course.credits} ECTS</span></div>`).join("") : `<p>No courses selected in this period.</p>`}</div></details>`).join("") : `<p>No future periods were produced.</p>`}</div></article>`;
}

function renderPlanWarnings(warnings) {
  $("#plan-warnings").innerHTML = warnings.length ? `<article class="panel warning-list"><div class="panel-head"><div><span class="eyebrow">Planning notes</span><h2>What to verify</h2></div></div>${warnings.map(warning => `<p>${esc(warning)}</p>`).join("")}</article>` : "";
}

function renderAnalysisPrintNotes(data) {
  const notes = [];
  if (registrationMode === "KEEP_CURRENT" && savedStudent.currently_registered_courses) {
    notes.push("Current registered courses are locked, but section and CRN assignments must be verified because they are not present in the pasted portal record.");
  }
  notes.push(...planNotes(data));
  $("#analysis-print-notes").innerHTML = notes.length
    ? `<strong>Planning notes</strong><ul>${notes.map(note => `<li>${esc(note)}</li>`).join("")}</ul>`
    : "";
}

function renderAnalysisAudit(data) {
  const groups = [
    ["Satisfied requirements", data.satisfied_requirements || []],
    ["Mandatory outstanding", data.mandatory_outstanding || []],
    ["Approved optional candidates", data.approved_optional_candidates || []],
    ["Courses needing review", data.courses_needing_review || []]
  ];
  const classification = groups.map(([label, courses]) => `<details class="audit-group"><summary>${esc(label)} <span>${courses.length}</span></summary>${courses.length ? courses.map(course => `<div class="audit-course">${esc(courseLabel(course.title, course.code))} / ${course.credits} ECTS</div>`).join("") : `<p>None</p>`}</details>`).join("");
  const eligible = (data.eligible_pool || []).map(course => `<div class="audit-course">${esc(courseLabel(course.title, course.code))} / ${course.credits} ECTS</div>`).join("");
  const blocked = (data.blocked_courses || []).map(course => `<div class="audit-course">${esc(courseLabel(course.title, course.code))}: ${esc(course.reason)}</div>`).join("");
  $("#analysis-audit").innerHTML = `<div class="audit-columns"><div><h3>Requirement classification</h3>${classification}</div><div><details class="audit-group"><summary>Eligible active-term pool <span>${data.eligible_pool.length}</span></summary>${eligible || "<p>None</p>"}</details><details class="audit-group"><summary>Blocked courses <span>${data.blocked_courses.length}</span></summary>${blocked || "<p>None</p>"}</details></div></div>`;
}

function printExpandedAnalysis() {
  prepareAnalysisPrint();
  window.print();
}

function prepareAnalysisPrint() {
  if (printOpenState) return;
  const details = [...document.querySelectorAll("#future-plan-panel details.term-card")];
  printOpenState = details.map(item => ({item, open: item.open}));
  details.forEach(item => { item.open = true; });
  if (currentMeetings.length) renderStudentTimetableGrid(currentMeetings, 0.5);
}

function restoreAnalysisPrint() {
  if (!printOpenState) return;
  printOpenState.forEach(({item, open}) => { item.open = open; });
  printOpenState = null;
  if (currentMeetings.length) renderStudentTimetableGrid(currentMeetings);
}

function renderCredit(data) {
  const credit = data.credit_check;
  const difference = credit.difference == null ? "-" : (credit.difference === 0 ? "0" : `${credit.difference > 0 ? "+" : ""}${credit.difference}`);
  $("#credit-panel").innerHTML = `<article class="panel"><div class="panel-head"><div><span class="eyebrow">Credit ledger</span><h2>Earned-credit reconciliation</h2></div><span class="status-pill ${statusClass(credit.status)}">${esc(credit.status)}</span></div><div class="credit-equation"><div class="credit-value"><span>Parsed unique degree credit</span><strong>${credit.parsed_degree_earned_ects}</strong></div><span class="operator">vs</span><div class="credit-value"><span>Portal reported total</span><strong>${credit.reported_earned_ects ?? "-"}</strong></div><span class="operator">=</span><div class="credit-value"><span>Difference</span><strong>${esc(difference)}</strong></div></div><p class="credit-explanation">${esc(credit.explanation)}</p></article>`;
}

function renderCategories(data) {
  $("#category-panel").innerHTML = `<article class="panel"><div class="panel-head"><div><span class="eyebrow">Source checks</span><h2>Portal category subtotals</h2><p>These checks validate parsing; the categories are not added together as independent degree requirements.</p></div></div><div class="table-wrap"><table><thead><tr><th>Category</th><th>Required</th><th>Portal earned</th><th>Parsed</th><th>Check</th></tr></thead><tbody>${data.categories.map(category => `<tr><td>${esc(category.label)}</td><td>${category.required_ects ?? "-"}</td><td>${category.reported_earned_ects ?? "-"}</td><td>${category.parsed_earned_ects ?? "-"}</td><td><span class="status-pill ${statusClass(category.validation_status)}">${esc(category.validation_status)}</span></td></tr>`).join("")}</tbody></table></div></article>`;
}

function renderFilters(data) {
  const counts = {
    ALL: data.course_groups.length,
    NEEDS_REVIEW: data.course_groups.filter(group => group.effective_status === "NEEDS_REVIEW" || group.mapping_status === "NEEDS_REVIEW").length,
    FAILED_OUTSTANDING: data.course_groups.filter(group => group.effective_status === "FAILED_OUTSTANDING").length,
    CURRENTLY_REGISTERED: registeredGroups(data).length,
    COMPLETED: data.course_groups.filter(group => group.effective_status === "COMPLETED").length,
    HISTORICAL_UNMAPPED: data.course_groups.filter(group => group.mapping_status === "HISTORICAL_UNMAPPED").length
  };
  const labels = {ALL: "All", NEEDS_REVIEW: "Needs review", FAILED_OUTSTANDING: "Failed", CURRENTLY_REGISTERED: "Currently registered", COMPLETED: "Completed", HISTORICAL_UNMAPPED: "Historical credit"};
  $("#filters").innerHTML = Object.entries(counts).map(([key, count]) => `<button type="button" class="filter-button ${activeFilter === key ? "active" : ""}" data-filter="${key}">${labels[key]} ${count}</button>`).join("");
  $("#filters").querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    renderFilters(data);
    renderGroups(data);
  }));
}

function renderGroups(data) {
  const groups = data.course_groups.filter(group => (
    activeFilter === "ALL"
    || (activeFilter === "CURRENTLY_REGISTERED" && group.currently_registered)
    || group.effective_status === activeFilter
    || group.mapping_status === activeFilter
  ));
  $("#course-groups").innerHTML = groups.length ? groups.map(group => {
    const open = ["NEEDS_REVIEW", "FAILED_OUTSTANDING"].includes(group.effective_status) || group.mapping_status === "NEEDS_REVIEW" ? "open" : "";
    const sourceLabels = [...new Set(group.attempts.map(attempt => courseLabel(attempt.source_title, attempt.source_code)))];
    const mappingBadge = group.mapping_status === "RESOLVED" ? "" : `<span class="status-pill ${statusClass(group.mapping_status)}">${esc(friendlyStatus(group.mapping_status))}</span>`;
    return `<details class="course-group" ${open}><summary><div class="course-title"><span class="course-name">${esc(courseLabel(group.title, group.display_code))}${sourceLabels.length ? `<small class="source-codes">Transcript source${sourceLabels.length === 1 ? "" : "s"}: ${esc(sourceLabels.join(" / "))}</small>` : ""}</span></div><span class="status-stack"><span class="status-pill ${statusClass(group.effective_status)}">${esc(friendlyStatus(group.effective_status))}</span>${mappingBadge}</span></summary><div class="group-body">${group.attempts.map(attempt => attemptRow(attempt)).join("")}${group.components.map(component => `<div class="component"><strong>${esc(courseLabel(component.source_title, component.source_code))}</strong> / ${esc(component.term)} / 0 ECTS lab component of ${esc(courseLabel(group.title, component.parent_code))}${component.parent_attempt_id ? "" : " / parent needs review"}</div>`).join("")}</div></details>`;
  }).join("") : `<div class="empty-groups">No course groups match this filter.</div>`;
}

function attemptRow(attempt) {
  const grade = attempt.grade_token === "-" ? "No grade" : `${attempt.grade_token}${attempt.grade_value == null ? "" : ` / ${attempt.grade_value}`}`;
  const selectedMatch = attempt.catalog_matches.find(match => match.selected);
  const mapping = selectedMatch
    ? `${attempt.selected_curriculum_version} / ${courseLabel(selectedMatch.title, selectedMatch.code)}`
    : friendlyStatus(attempt.match_status);
  return `<div class="attempt"><div class="attempt-code">${esc(courseLabel(attempt.source_title, attempt.source_code))}<small>${attempt.ects} ECTS</small></div><div>${esc(attempt.term)}<small>${esc(grade)}</small></div><div><span class="status-pill ${statusClass(attempt.status)}">${esc(friendlyStatus(attempt.status))}</span><small>${esc(mapping)}${attempt.duplicate_occurrences > 1 ? ` / ${attempt.duplicate_occurrences} identical rows merged` : ""}</small></div><div>${attempt.note ? `<span class="note">${esc(attempt.note)}</span>` : `<small>${attempt.counts_toward_degree_credit ? "Counts toward degree credit when completed" : "Excluded from degree credit"}${attempt.counts_toward_gpa ? "" : " / excluded from GPA"}</small>`}</div></div>`;
}

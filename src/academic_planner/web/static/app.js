const state = {
  scenarios: [], defaults: null, result: null,
  currentMeetings: [], printOpenState: null,
  sort: { key: "reference_year", asc: true }
};
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

document.addEventListener("DOMContentLoaded", initialize);

async function initialize() {
  bindEvents();
  try {
    const [scenariosResponse, configResponse] = await Promise.all([fetch("/api/scenarios"), fetch("/api/config")]);
    if (!scenariosResponse.ok || !configResponse.ok) throw new Error("The planning service is unavailable.");
    state.scenarios = await scenariosResponse.json();
    state.defaults = (await configResponse.json()).defaults;
    populateScenarios();
    updateScenarioProfile();
  } catch (error) {
    showError(error.message);
  }
}

function bindEvents() {
  $("#planner-form").addEventListener("submit", submitPlan);
  $("#scenario").addEventListener("change", () => { updateScenarioProfile(); clearOverrides(); });
  $("#add-override").addEventListener("click", addOverride);
  $("#reset-button").addEventListener("click", resetDefaults);
  $("#print-button").addEventListener("click", printExpandedPlan);
  window.addEventListener("beforeprint", preparePrintLayout);
  window.addEventListener("afterprint", restorePrintLayout);
  $("#eligible-table thead").addEventListener("click", event => {
    const button = event.target.closest("button[data-sort]");
    if (!button || !state.result) return;
    const key = button.dataset.sort;
    state.sort.asc = state.sort.key === key ? !state.sort.asc : true;
    state.sort.key = key;
    renderEligible(state.result);
  });
}

function populateScenarios() {
  $("#scenario").innerHTML = state.scenarios.map(item => {
    const label = labelScenario(item.identifier);
    return `<option value="${escapeHtml(item.identifier)}">${escapeHtml(label === item.identifier ? item.description : label)}</option>`;
  }).join("");
}

function labelScenario(id) {
  return ({fresh:"Fresh first-year student", "struggling-third":"Struggling third-year student", "regular-fourth":"Regular fourth-year student", "failed-fourth":"Fourth-year student with failed course"})[id] || id;
}

function selectedScenario() { return state.scenarios.find(item => item.identifier === $("#scenario").value); }

function updateScenarioProfile() {
  const scenario = selectedScenario();
  if (!scenario) return;
  $("#scenario-description").textContent = scenario.description;
  const facts = scenario.fixture_prerequisites==='DATABASE' ? [
    scenario.student_type, `${scenario.curriculum_version} target`, scenario.language_track,
    `${scenario.completed_credits} ECTS completed`, scenario.starting_term,
    'SQLite curriculum and active timetable'
  ] : [
    `Year ${scenario.nominal_year}`, `${scenario.curriculum_version} curriculum`, scenario.language_track,
    `${scenario.completed_credits} ECTS completed`, scenario.starting_term,
    `${scenario.fixture_prerequisites}/${scenario.fixture_timetable} synthetic fixture`
  ];
  $("#profile-facts").innerHTML = facts.map(value => `<span>${escapeHtml(value)}</span>`).join("");
}

function addOverride(saved = null) {
  const scenario = selectedScenario();
  if (!scenario) return;
  const row = document.createElement("div");
  row.className = "override-row";
  row.innerHTML = `<select aria-label="Override term">${scenario.available_terms.map(term => `<option ${saved?.term === term ? "selected" : ""}>${escapeHtml(term)}</option>`).join("")}</select><input aria-label="ECTS capacity" type="number" min="1" max="60" value="${escapeHtml(saved?.capacity || 30)}"><button type="button" class="remove-override" aria-label="Remove override">×</button>`;
  row.querySelector(".remove-override").addEventListener("click", () => row.remove());
  $("#override-list").append(row);
}

function clearOverrides() { $("#override-list").replaceChildren(); }

function requestPayload() {
  const overrides = {};
  document.querySelectorAll(".override-row").forEach(row => {
    overrides[row.querySelector("select").value] = Number(row.querySelector("input").value);
  });
  const maxDelay = $("#training-max-delay").value;
  return {
    scenario_id: $("#scenario").value,
    regular_credit_capacity: state.defaults?.regular_credit_capacity ?? 30,
    per_semester_capacity_overrides: overrides,
    academic_year_deviation_weight: Number($("#year-weight").value),
    reference_semester_deviation_weight: Number($("#semester-weight").value),
    allow_training_postponement: $("#training-postponement").checked,
    training_delay_penalty: Number($("#training-penalty").value),
    max_training_delay_years: maxDelay === "" ? null : Number(maxDelay),
    solver_time_limit_seconds: Number($("#solver-limit").value),
    initial_horizon_semesters: Number($("#initial-horizon").value),
    max_horizon_semesters: Number($("#max-horizon").value),
    auto_extend_horizon: $("#auto-extend-horizon").checked,
    horizon_extension_step: Number($("#horizon-step").value),
    enable_course_selection_diagnostics: $("#selection-diagnostics").checked,
    max_diagnostic_courses: 5
    ,exploratory_recognition: $("#exploratory-recognition").checked
  };
}

async function submitPlan(event) {
  event.preventDefault();
  const button = $("#generate-button");
  button.disabled = true;
  button.textContent = "Generating plan…";
  showOnly("loading-state");
  try {
    const response = await fetch("/api/plan", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(requestPayload()) });
    const body = await response.json();
    if (!response.ok) throw new Error(formatApiError(body));
    state.result = body;
    renderResults(body);
    showOnly("results");
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Generate Academic Plan";
  }
}

function formatApiError(body) {
  if (Array.isArray(body.detail)) return body.detail.map(item => `${item.loc.at(-1)}: ${item.msg}`).join("; ");
  return body.detail || "The planner could not process this configuration.";
}

function showOnly(id) {
  ["empty-state", "loading-state", "error-state", "results"].forEach(item => $("#" + item).classList.toggle("hidden", item !== id));
}

function showError(message) { $("#error-message").textContent = message; showOnly("error-state"); }

function renderResults(data) {
  const resultLabel = labelScenario(data.scenario.identifier);
  $("#result-scenario").textContent = resultLabel === data.scenario.identifier
    ? data.scenario.description
    : resultLabel;
  $("#result-context").textContent = `${data.scenario.starting_term} · Year ${data.student.nominal_year} · ${data.student.language_track} track`;
  const statusClass = `status-${data.solver.status.toLowerCase().split("_")[0]}`;
  const currentCredits = data.current_semester?.total_credits ?? 0;
  const currentCap = data.current_semester?.effective_credit_capacity ?? data.configuration.regular_credit_capacity;
  const cards = [
    ["Solver status", data.solver.status.replaceAll("_", " "), statusClass],
    ["Completed", `${data.academic_summary.completed_credits} ECTS`, ""],
    ["Remaining", `${data.academic_summary.remaining_credits} ECTS`, ""],
    ["Current selection", `${currentCredits} / ${currentCap} ECTS`, ""],
    ["Graduation", data.graduation.term || "Not established", ""],
    ["Planned regular terms remaining", data.academic_summary.regular_semesters_remaining, "Fall/Spring terms, not the student's current semester number"],
    ["Training periods", data.academic_summary.training_periods_remaining, ""],
    ["Optimality proven", data.solver.global_optimality_proven ? "Yes" : "No", ""]
  ];
  $("#summary-cards").innerHTML = cards.map(([label, value, cls]) => `<article class="summary-card ${cls}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
  const credit = data.graduation_credit_breakdown || {};
  const acceptedPlan = Object.keys(credit).length
    ? `Accepted-credit plan: ${credit.accepted_completed_ects} completed + ${credit.mandatory_outstanding_ects} mandatory + ${credit.approved_optional_ects_selected} optional${credit.proposed_credit_adjustment_ects ? ` + ${credit.proposed_credit_adjustment_ects} proposed adjustment` : ""} = ${data.academic_summary.accepted_credit_target} ECTS.`
    : null;
  const printNotes = [acceptedPlan, ...(data.warnings || [])].filter(Boolean);
  $("#print-notes").innerHTML = printNotes.length
    ? `<strong>Planning notes</strong><ul>${printNotes.map(note => `<li>${escapeHtml(note)}</li>`).join("")}</ul>`
    : "";
  const transition=data.transition_diagnostics;
  let transitionRows="";
  if (transition) {
    const comparison=transition.current_registration_comparison;
    const categoryAudit=transition.contract_credit_category_audit;
    const degreeContract=transition.degree_contract_audit;
    const coverage=transition.transition_catalogue_coverage;
    const coverageLine=coverage ? `<br>Catalogue coverage: ${coverage.direct_historical_equivalencies} direct mappings + ${coverage.legacy_credit_only} legacy-credit-only + ${coverage.pathway_specific} pathway-specific = ${coverage.active_old_courses} OLD courses · uncovered: ${coverage.uncovered_old_courses}` : "";
    transitionRows += `<div class="warning-item"><strong>Transition reconciliation</strong><br>Reported: ${transition.source_reported_earned_credits} ECTS · recomputed completed: ${transition.recomputed_completed_source_credits} ECTS<br>Recognition mode: ${escapeHtml(transition.recognition_mode)} · recognized OLD→NEW mappings: ${transition.recognized_old_to_new_mappings}${coverageLine}<br>Unknown codes: ${escapeHtml((transition.unknown_transcript_codes||[]).join(', ')||'none')}</div>`;
    if (comparison?.observed_course_codes?.length) {
      const coursePercent=Math.round(100*comparison.course_match_rate);
      const ectsPercent=Math.round(100*comparison.ects_match_rate);
      const courseNames = items => items?.map(item => `${item.title} (${item.code})`).join(', ') || 'none';
      transitionRows += `<div class="warning-item"><strong>Current registration comparison (evaluation only)</strong><br>Matched ${comparison.matched_course_codes.length}/${comparison.observed_course_codes.length} courses (${coursePercent}%) and ${comparison.matched_ects}/${comparison.observed_ects} ECTS (${ectsPercent}%). The observed IN_PROGRESS load did not influence the optimizer.<br>Missed: ${escapeHtml(courseNames(comparison.missed_courses))} · Added by engine: ${escapeHtml(courseNames(comparison.additional_courses))}</div>`;
    }
    if (degreeContract?.groups?.length) {
      const roots=degreeContract.groups.filter(group => group.solver_enforced);
      const rows=roots.map(group => `${group.title}: ${group.recognized_ects}/${group.required_ects} ECTS recognized`).join(' Â· ');
      transitionRows += `<div class="warning-item"><strong>Official degree contract (solver enforced)</strong><br>${escapeHtml(rows)}<br>${escapeHtml(degreeContract.enforcement_model)}</div>`;
    }
    if (categoryAudit?.categories?.length) {
      const rows=categoryAudit.categories.map(item => `${item.label}: ${item.source_reported_earned_ects}/${item.required_ects} ECTS`).join(' · ');
      transitionRows += `<div class="warning-item"><strong>Contract credit-category audit</strong><br>${escapeHtml(rows)}<br>Audit only: the source category requirements total ${categoryAudit.required_ects_total} ECTS against a ${categoryAudit.graduation_ects_target}-ECTS degree target; ${categoryAudit.required_total_above_graduation_target} ECTS of overlap/allocation rules still require verification.</div>`;
    }
  }
  $("#warnings-section").innerHTML = transitionRows+data.warnings.map(text => `<div class="warning-item">${escapeHtml(text)}</div>`).join("");
  renderRequirementClassifications(data);
  renderEligible(data);
  renderBlocked(data.blocked_courses);
  renderCurrent(data.current_semester);
  renderFuture(data.future_semesters, data.graduation.term);
  renderValidation(data);
}

function renderRequirementClassifications(data) {
  const groups = [
    ["Mandatory outstanding", data.mandatory_outstanding || []],
    ["Satisfied", data.satisfied_requirements || []],
    ["Approved optional", data.approved_optional_candidates || []],
    ["Registration only", data.registration_only_courses || []],
    ["Needs academic review", data.courses_needing_review || []]
  ];
  $("#requirement-classifications").innerHTML = groups.map(([label, courses]) => {
    const rows = courses.length ? courses.map(course => {
      const selected = course.selected_for_graduation ? " · selected" : "";
      const approval = course.approval_status ? ` · ${course.approval_status}` : "";
      return `<div class="future-course"><strong>${escapeHtml(course.code)}</strong> · ${escapeHtml(course.title)} <span>(${course.credits} ECTS${escapeHtml(approval + selected)})</span><small class="diagnostic-facts">${escapeHtml(course.explanation)}${course.credit_category ? ` · ${escapeHtml(course.credit_category)}` : ""}</small></div>`;
    }).join("") : `<div class="future-course">None</div>`;
    return `<details class="future-term" ${label === "Mandatory outstanding" ? "open" : ""}><summary><strong>${escapeHtml(label)}</strong><span>${courses.length}</span></summary><div class="future-courses">${rows}</div></details>`;
  }).join("");
}

function renderEligible(data) {
  const diagnostics = Object.fromEntries((data.course_selection_diagnostics || []).map(item => [item.course_id, item]));
  const items = [...data.eligible_pool].sort((a, b) => {
    const av = a[state.sort.key], bv = b[state.sort.key];
    const comparison = typeof av === "number" ? av - bv : String(av).localeCompare(String(bv));
    return state.sort.asc ? comparison : -comparison;
  });
  $("#pool-summary").textContent = `${items.length} candidates · ${data.eligible_pool_total_credits} available ECTS · credit limits are applied later`;
  $("#eligible-table tbody").innerHTML = items.length ? items.map(course => {
    const diagnostic = diagnostics[course.id];
    const facts = [];
    if (diagnostic?.conflicts_with_selected_course_codes?.length) facts.push(`Overlaps selected bundles: ${diagnostic.conflicts_with_selected_course_codes.join(", ")}`);
    if (diagnostic?.would_exceed_current_cap_if_added_without_changes) facts.push("Would exceed the cap if added without changing the schedule");
    return `<tr><td>${escapeHtml(course.code)}</td><td>${escapeHtml(course.title)}</td><td>${course.credits}</td><td>Year ${course.reference_year}</td><td>${escapeHtml(course.curriculum_version)}</td><td><span class="diagnostic-status">${escapeHtml((diagnostic?.status || "UNKNOWN_NOT_DIAGNOSED").replaceAll("_", " "))}</span>${facts.length ? `<small class="diagnostic-facts">${escapeHtml(facts.join(" · "))}</small>` : ""}</td></tr>`;
  }).join("") : `<tr><td colspan="6">No eligible current-term courses.</td></tr>`;
}

function renderBlocked(items) {
  $("#blocked-count").textContent = items.length;
  $("#blocked-list").innerHTML = items.map(item => {
    const missing = item.missing_prerequisites.length ? ` Missing: ${item.missing_prerequisites.join(", ")}.` : "";
    return `<article class="blocked-item"><strong>${escapeHtml(item.code)}</strong><span class="reason-tag">${escapeHtml(item.reason_code.replaceAll("_", " "))}</span><p>${escapeHtml(item.reason)}${escapeHtml(missing)}</p></article>`;
  }).join("");
}

function renderCurrent(current) {
  if (!current) {
    state.currentMeetings = [];
    $("#current-term-label").textContent = "No feasible current-semester selection.";
    $("#current-credit-pill").textContent = "0 ECTS";
    $("#selected-course-strip").replaceChildren();
    $("#timetable").innerHTML = `<div class="no-timetable">No current-semester timetable is available.</div>`;
    return;
  }
  $("#current-term-label").textContent = current.term;
  $("#current-credit-pill").textContent = `${current.total_credits} / ${current.effective_credit_capacity} ECTS`;
  $("#current-term-label").textContent = `${current.term} · ${capacityReason(current)}`;
  $("#selected-course-strip").innerHTML = current.selected_courses.map(course => `<span class="course-chip">${escapeHtml(course.title)} (${escapeHtml(course.code)}) · ${course.credits} ECTS</span>`).join("");
  const meetings = current.selected_courses.flatMap((course, index) => course.sections.flatMap(section => section.meetings.map(meeting => ({...meeting, course, section, colorIndex:index}))));
  state.currentMeetings = meetings;
  if (!meetings.length) {
    $("#timetable").innerHTML = `<div class="no-timetable">Selected courses have no supplied meeting data. No times were invented.</div>`;
    return;
  }
  renderTimetable(meetings);
}

function renderTimetable(meetings, pixelsPerMinute = 1.05) {
  const dayNames = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const presentDays = dayNames.map((name, index) => ({name,index}));
  const minMinute = Math.floor(Math.min(...meetings.map(item => item.start_minute)) / 30) * 30;
  const maxMinute = Math.ceil(Math.max(...meetings.map(item => item.end_minute)) / 30) * 30;
  const height = (maxMinute - minMinute) * pixelsPerMinute;
  const labels = [];
  for (let minute = minMinute; minute <= maxMinute; minute += 60) labels.push(`<span class="time-label" style="top:${(minute-minMinute)*pixelsPerMinute}px">${formatMinute(minute)}</span>`);
  const palette = [["#dfeeff","#2f79c6"],["#e8f4e8","#397b47"],["#fff0d9","#b56b16"],["#eee8fb","#7252b2"],["#fbe5e8","#b34f5d"],["#dff4f2","#2f8179"],["#e8edf8","#536c9d"]];
  const columns = presentDays.map(day => {
    const events = meetings.filter(item => item.weekday_index === day.index).map(item => {
      const [background,border] = palette[item.colorIndex % palette.length];
      const top = (item.start_minute - minMinute) * pixelsPerMinute;
      const eventHeight = Math.max(28, (item.end_minute - item.start_minute) * pixelsPerMinute);
      const title = `${item.course.code} — ${item.course.title}\n${item.section.component} · ${item.section.crn}\n${item.start_time}–${item.end_time}\nCampus: ${item.section.campus}\nSynthetic/unverified timetable`;
      return `<div class="meeting-event" tabindex="0" title="${escapeHtml(title)}" style="top:${top}px;height:${eventHeight}px;--event-color:${background};--event-border:${border}"><strong>${escapeHtml(item.course.code)}</strong><span>${escapeHtml(item.section.component.split(":")[0])}</span><span class="event-meta">${item.start_time}–${item.end_time}</span></div>`;
    }).join("");
    return `<div class="day-column">${events}</div>`;
  }).join("");
  $("#timetable").innerHTML = `<div class="timetable-scroll"><div class="timetable-grid" style="--day-count:${presentDays.length};--grid-height:${height}px;--half-hour:${30*pixelsPerMinute}px"><div class="time-corner">Time</div>${presentDays.map(day => `<div class="day-heading">${day.name}</div>`).join("")}<div class="time-axis">${labels.join("")}</div>${columns}</div></div>`;
}

function formatMinute(minute) { return `${String(Math.floor(minute / 60)).padStart(2,"0")}:${String(minute % 60).padStart(2,"0")}`; }

function renderFuture(semesters, graduation) {
  $("#graduation-label").textContent = graduation ? `Projected graduation: ${graduation}` : "Graduation was not established within the horizon.";
  $("#future-plan").innerHTML = semesters.length ? semesters.map((term, index) => {
    const training = term.period_type.startsWith("TRAINING");
    const courseList = term.courses.length ? term.courses.map(course => `<div class="future-course"><strong>${escapeHtml(course.code)}</strong> · ${escapeHtml(course.title)} <span>(${course.credits} ECTS)</span></div>`).join("") : `<div class="future-course">No courses selected in this period.</div>`;
    return `<details class="future-term ${training ? "training" : ""}" ${index < 2 ? "open" : ""}><summary><strong>${escapeHtml(term.term)}</strong><span>${escapeHtml(capacityReason(term))}</span><span>${term.total_credits} / ${term.effective_credit_capacity} ECTS</span></summary><div class="future-courses">${courseList}</div></details>`;
  }).join("") : `<div class="no-timetable">No projected future periods are available.</div>`;
}

function capacityReason(term) {
  const repeat = term.repeated_course_codes?.length ? `: repeating ${term.repeated_course_codes.join(", ")}` : "";
  const labels = {
    FAILED_COURSE_REPEAT_ALLOWANCE: "Extended failed-repeat allowance",
    FINAL_TWO_SEMESTER_GRADUATION_ALLOWANCE: "Final-two-semester graduation allowance",
    EXPLICIT_TERM_OVERRIDE: "Explicit term override",
    MANUAL_REGULAR_CAPACITY: "Manual regular capacity",
    TRAINING_PERIOD_CAP: "Training-period capacity",
    NORMAL_REGULAR_CAPACITY: "Normal credit allowance: no failed repeat selected",
    CONFIGURED_CAPACITY: "Configured capacity"
  };
  return `${labels[term.credit_capacity_reason] || term.credit_capacity_reason}${repeat}`;
}

function renderValidation(data) {
  const earlier = data.graduation.earlier_deadline_tested;
  const credit = data.graduation_credit_breakdown || {};
  const lines = [
    `Accepted-credit target: ${data.academic_summary.accepted_credit_target} ECTS`,
    Object.keys(credit).length ? `Credit breakdown: completed ${credit.accepted_completed_ects} + mandatory ${credit.mandatory_outstanding_ects} + selected optional ${credit.approved_optional_ects_selected}${credit.proposed_credit_adjustment_ects ? ` + proposed administrative adjustment ${credit.proposed_credit_adjustment_ects}` : ""}; unresolved ${credit.remaining_unresolved_ects}; excess ${credit.excess_accepted_ects} ECTS${credit.hypothetical ? " (hypothetical)" : ""}.` : null,
    credit.credit_adjustment_requires_approval ? `Administrative approval required for the proposed ${credit.proposed_credit_adjustment_ects}-ECTS adjustment in ${credit.proposed_credit_adjustment_term}.` : null,
    `Satisfied / outstanding requirements: ${data.academic_summary.satisfied_requirements} / ${data.academic_summary.outstanding_requirements}`,
    data.graduation.earliest_feasible_under_model ? "Earliest feasible graduation was proven within the modeled horizon." : "Earliest graduation was not proven.",
    earlier ? `${earlier} was ruled out by the optimal graduation objective under the same model.` : "No earlier modeled period applies."
  ];
  $("#graduation-validation").innerHTML = lines.filter(Boolean).map(line => `<p>${escapeHtml(line)}</p>`).join("");
}

function printExpandedPlan() {
  preparePrintLayout();
  window.print();
}

function preparePrintLayout() {
  if (state.printOpenState) return;
  const terms = [...document.querySelectorAll("#future-plan details.future-term")];
  state.printOpenState = terms.map(term => ({ term, open: term.open }));
  terms.forEach(term => { term.open = true; });
  if (state.currentMeetings.length) renderTimetable(state.currentMeetings, 0.78);
}

function restorePrintLayout() {
  if (!state.printOpenState) return;
  state.printOpenState.forEach(({term, open}) => { term.open = open; });
  state.printOpenState = null;
  if (state.currentMeetings.length) renderTimetable(state.currentMeetings);
}

function resetDefaults() {
  $("#scenario").value = "fresh";
  $("#year-weight").value = state.defaults?.academic_year_deviation_weight ?? 10;
  $("#semester-weight").value = state.defaults?.reference_semester_deviation_weight ?? 2;
  $("#training-postponement").checked = true;
  $("#training-penalty").value = state.defaults?.training_delay_penalty ?? 10;
  $("#training-max-delay").value = "";
  $("#solver-limit").value = state.defaults?.solver_time_limit_seconds ?? 20;
  $("#initial-horizon").value = state.defaults?.initial_horizon_semesters ?? 10;
  $("#max-horizon").value = state.defaults?.max_horizon_semesters ?? 20;
  $("#auto-extend-horizon").checked = state.defaults?.auto_extend_horizon ?? true;
  $("#horizon-step").value = state.defaults?.horizon_extension_step ?? 2;
  $("#selection-diagnostics").checked = false;
  $("#exploratory-recognition").checked = false;
  clearOverrides();
  updateScenarioProfile();
}

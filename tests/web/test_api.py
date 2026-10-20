from fastapi.testclient import TestClient

from academic_planner.web.app import app


client = TestClient(app)


def test_dashboard_and_scenario_listing():
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "Academic Planning Engine" in dashboard.text
    assert "Scenario Lab" in dashboard.text
    assert client.get("/scenario-lab").status_code == 200
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    scenarios = response.json()
    assert {
        "fresh", "struggling-third", "regular-fourth", "failed-fourth",
    } == {item["identifier"] for item in scenarios}
    assert all(item["available_terms"] for item in scenarios)


def test_print_view_keeps_only_the_compact_plan_sections():
    dashboard = client.get("/").text
    styles = client.get("/static/styles.css").text
    script = client.get("/static/app.js").text

    assert 'id="eligible-pool-section"' in dashboard
    assert 'id="future-plan-section"' in dashboard
    assert 'id="print-notes"' in dashboard
    assert (
        "#requirement-classification-section,\n"
        "  #eligible-pool-section, .validation-card { display: none !important; }"
    ) in styles
    assert "#future-plan-section { break-before: page" in styles
    assert "@page { size: landscape; margin: 9mm; }" in styles
    assert 'querySelectorAll("#future-plan details.future-term")' in script
    assert "renderTimetable(state.currentMeetings, 0.78)" in script


def test_configuration_describes_only_supported_controls():
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["defaults"]["regular_credit_capacity"] == 30
    assert body["options"]["regular_credit_capacity"]["suggested_values"] == [30, 36]
    assert "allow_training_postponement" in body["options"]
    assert "academic_year_deviation_weight" in body["options"]
    assert "allow_extended_load_when_repeating_failed_course" in body["options"]
    assert "enable_elbc901_cce640_experiment" not in body["options"]
    assert body["defaults"]["initial_horizon_semesters"] == 10
    assert body["defaults"]["max_horizon_semesters"] == 20


def test_valid_request_runs_optimizer_and_serializes_plan():
    response = client.post("/api/plan", json={"scenario_id": "fresh"})
    assert response.status_code == 200
    body = response.json()
    assert body["solver"]["status"] == "OPTIMAL"
    assert body["academic_summary"]["remaining_credits"] == 300
    assert body["current_semester"]["selected_courses"]
    assert body["graduation"]["term"] == "2030-2031 SPRING"
    assert body["warnings"]
    assert any("synthetic" in warning.lower() for warning in body["warnings"])


def test_invalid_scenario_and_credit_limit_are_rejected():
    unknown = client.post("/api/plan", json={"scenario_id": "does-not-exist"})
    assert unknown.status_code == 404
    invalid_credit = client.post(
        "/api/plan", json={"scenario_id": "fresh", "regular_credit_capacity": -1}
    )
    assert invalid_credit.status_code == 422


def test_unknown_term_override_is_rejected_cleanly():
    response = client.post("/api/plan", json={
        "scenario_id": "fresh",
        "per_semester_capacity_overrides": {"2099-2100 FALL": 30},
    })
    assert response.status_code == 422
    assert "unknown planning term" in response.json()["detail"]


def test_future_semesters_never_contain_meeting_data():
    response = client.post("/api/plan", json={"scenario_id": "regular-fourth"})
    assert response.status_code == 200
    for semester in response.json()["future_semesters"]:
        assert "meetings" not in semester
        assert all("sections" not in course for course in semester["courses"])


def test_struggling_third_year_poc_has_no_empty_regular_gap():
    response = client.post("/api/plan", json={"scenario_id": "struggling-third"})
    assert response.status_code == 200
    body = response.json()
    assert body["solver"]["status"] == "OPTIMAL"
    assert body["academic_summary"]["completed_credits"] == 113
    assert body["academic_summary"]["remaining_credits"] == 187
    assert body["scenario"]["fixture_prerequisites"] == "relaxed"
    assert body["scenario"]["fixture_timetable"] == "relaxed"
    assert body["current_semester"]["total_credits"] == 20
    regular_future = [
        term for term in body["future_semesters"]
        if term["period_type"] in {"FALL", "SPRING"}
    ]
    assert regular_future
    assert all(term["courses"] for term in regular_future)
    spring_terms = [term for term in regular_future if term["period_type"] == "SPRING"]
    assert len(spring_terms[-1]["courses"]) == 2
    assert {course["code"] for course in spring_terms[-1]["courses"]} == {"CCE640", "CCE690"}
    assert body["graduation"]["earlier_deadline_tested"] == "2028-2029 SPRING"
    assert body["graduation"]["earlier_deadline_proven_infeasible"] is True


def test_default_relaxed_fixture_selects_cce431_without_a_conflict_claim():
    response = client.post("/api/plan", json={
        "scenario_id": "struggling-third",
        "enable_course_selection_diagnostics": True,
        "max_diagnostic_courses": 5,
    })
    assert response.status_code == 200
    body = response.json()
    cce431 = next(
        item for item in body["course_selection_diagnostics"]
        if item["course_code"] == "CCE431"
    )
    assert cce431["status"] == "SELECTED"
    assert cce431["counterfactual_graduation_term"] == "2029-2030 FALL"
    assert cce431["conflicts_with_selected_course_codes"] == []
    assert "due to" not in cce431["detail"].lower()


def test_failed_repeat_toggle_changes_only_the_repeat_semester_effective_cap():
    off = client.post("/api/plan", json={"scenario_id": "failed-fourth"}).json()
    on = client.post("/api/plan", json={
        "scenario_id": "failed-fourth",
        "allow_extended_load_when_repeating_failed_course": True,
    }).json()
    off_repeat = next(
        term for term in off["future_semesters"]
        if any(course["code"] == "CCE443" for course in term["courses"])
    )
    on_repeat = next(
        term for term in on["future_semesters"]
        if any(course["code"] == "CCE443" for course in term["courses"])
    )
    assert off_repeat["effective_credit_capacity"] == 30
    assert on_repeat["effective_credit_capacity"] == 36
    assert on_repeat["credit_capacity_reason"] == "FAILED_COURSE_REPEAT_ALLOWANCE"
    assert on_repeat["repeated_course_codes"] == ["CCE443"]
    assert off["graduation"]["term"] == on["graduation"]["term"]


def test_infeasible_solve_returns_structured_response():
    scenario = client.get("/api/scenarios").json()[0]
    overrides = {term: 1 for term in scenario["available_terms"]}
    response = client.post("/api/plan", json={
        "scenario_id": "fresh",
        "regular_credit_capacity": 1,
        "per_semester_capacity_overrides": overrides,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["solver"]["status"] == "INFEASIBLE"
    assert body["solver"]["is_success"] is False
    assert body["current_semester"] is None
    assert body["solver"]["explanations"]


def test_seeded_timetable_is_synthetic_and_contains_registration_bundles():
    response = client.get("/api/admin/timetable")
    assert response.status_code == 200
    offerings = response.json()["offerings"]
    assert offerings
    assert all(item["provenance"] == "SYNTHETIC_TEST_FIXTURE" for item in offerings)
    assert all(item["verification_status"] == "UNVERIFIED" for item in offerings)
    assert any(len(item["sections"]) > 1 for item in offerings)


def test_persistent_student_administration_is_not_exposed():
    assert client.get("/api/admin/students").status_code == 404

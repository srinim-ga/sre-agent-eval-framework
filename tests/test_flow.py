from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_list_incidents():
    res = client.get("/api/incidents")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 3
    assert data[0]["incident"]["incident_id"] == "ICM-501230"


def test_incident_detail():
    res = client.get("/api/incidents/ICM-501230")
    assert res.status_code == 200
    data = res.json()
    assert data["incident"]["incident_id"] == "ICM-501230"
    assert data["response_plan"]["plan_id"] == "OOM_RESTART_PLAYBOOK"
    assert len(data["trace"]["execution_steps"]) == 4


def test_hil1_approval_and_evaluation():
    # Submit HIL 1 Approve
    res = client.post(
        "/api/incidents/ICM-501230/hil1",
        json={"decision": "Approve", "reason": "Execution plan verified against playbook."}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "Mitigated"
    assert data["evaluation"]["q1"]["score"] == 1.0
    assert data["evaluation"]["q2"]["score"] == 1.0


def test_hil2_efficiency_feedback():
    res = client.post(
        "/api/incidents/ICM-501230/hil2",
        json={"rating": 5, "notes": "Execution was flawless and direct.", "tags": ["Optimal"]}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "Feedback logged"
    assert data["hil2_feedback"]["efficiency_rating"] == 5


def test_hil1_denial_and_safety_alert():
    # Submit HIL 1 Deny for destructive plan
    res = client.post(
        "/api/incidents/ICM-501232/hil1",
        json={"decision": "Deny", "reason": "Destructive cluster reboot forbidden in canary rollback."}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "Cancelled"
    assert data["evaluation"]["q1"]["score"] == 0.0
    assert len(data["evaluation"]["q1"]["unauthorized_actions"]) > 0


def test_maturity_and_mode_flip():
    res = client.get("/api/maturity")
    assert res.status_code == 200
    assessments = res.json()
    assert len(assessments) == 3

    # Flip mode for OOM_RESTART_PLAYBOOK
    flip_res = client.post("/api/playbooks/OOM_RESTART_PLAYBOOK/flip-mode")
    assert flip_res.status_code == 200
    assert flip_res.json()["new_mode"] == "Autonomous"


def test_ui_serves_html():
    res = client.get("/")
    assert res.status_code == 200
    assert "Azure SRE Agent" in res.text
    assert "HIL Action 1" in res.text

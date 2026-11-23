import os
import json
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.models import (
    Incident,
    ResponsePlan,
    AgentTrace,
    HIL1Decision,
    HIL1DecisionType,
    HIL2Feedback,
    EvaluationResult,
    Q1AdherenceResult,
    Q2EfficiencyResult,
    MaturityAssessment,
)
from core.evaluators.q1_adherence import PlanAdherenceEvaluator
from core.evaluators.q2_efficiency import EfficiencyEvaluator
from core.maturity import MaturityEngine

app = FastAPI(title="Azure SRE Agent - Evaluation & HITL Framework")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# In-Memory State for Prototype
incidents_db: Dict[str, Dict[str, Any]] = {}
plans_db: Dict[str, Dict[str, Any]] = {}
traces_db: Dict[str, Dict[str, Any]] = {}
evaluations_db: Dict[str, EvaluationResult] = {}
playbook_modes: Dict[str, str] = {}  # playbook_id -> "Review" | "Autonomous"

q1_evaluator = PlanAdherenceEvaluator()
q2_evaluator = EfficiencyEvaluator()
maturity_engine = MaturityEngine(min_runs=2)


def load_initial_data():
    global incidents_db, plans_db, traces_db, playbook_modes
    with open(os.path.join(DATA_DIR, "incidents.json")) as f:
        incidents_db = {i["incident_id"]: i for i in json.load(f)}

    with open(os.path.join(DATA_DIR, "response_plans.json")) as f:
        plans_db = {p["plan_id"]: p for p in json.load(f)}

    with open(os.path.join(DATA_DIR, "traces.json")) as f:
        traces_db = {t["incident_id"]: t for t in json.load(f)}

    for p_id in plans_db:
        playbook_modes[p_id] = "Review"


load_initial_data()


@app.get("/api/incidents")
def list_incidents():
    result = []
    for inc_id, inc in incidents_db.items():
        trace = traces_db.get(inc_id)
        plan_id = trace.get("plan_id") if trace else None
        eval_res = evaluations_db.get(inc_id)
        result.append({
            "incident": inc,
            "plan_id": plan_id,
            "plan_name": plans_db.get(plan_id, {}).get("name") if plan_id else None,
            "has_evaluated": eval_res is not None,
            "q1_score": eval_res.q1.score if eval_res else None,
            "q2_score": eval_res.q2.score if eval_res else None,
            "status": inc.get("status", "Active"),
        })
    return result


@app.get("/api/incidents/{incident_id}")
def get_incident_detail(incident_id: str):
    inc = incidents_db.get(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    trace = traces_db.get(incident_id)
    plan_id = trace.get("plan_id") if trace else None
    plan = plans_db.get(plan_id) if plan_id else None
    eval_res = evaluations_db.get(incident_id)

    return {
        "incident": inc,
        "response_plan": plan,
        "trace": trace,
        "evaluation": eval_res.model_dump() if eval_res else None,
        "current_playbook_mode": playbook_modes.get(plan_id, "Review"),
    }


@app.post("/api/incidents/{incident_id}/hil1")
def submit_hil1_decision(
    incident_id: str,
    decision_payload: Dict[str, Any] = Body(...),
):
    """
    HIL Action 1: SRE approves or denies the agent's drafted execution plan.
    """
    inc = incidents_db.get(incident_id)
    trace = traces_db.get(incident_id)
    if not inc or not trace:
        raise HTTPException(status_code=404, detail="Incident or trace not found")

    decision_str = decision_payload.get("decision", "Approve")
    reason = decision_payload.get("reason", "")
    reviewer = decision_payload.get("reviewer", "sre-oncall@microsoft.com")

    hil1_decision = HIL1Decision(
        incident_id=incident_id,
        decision=HIL1DecisionType.APPROVE if decision_str == "Approve" else HIL1DecisionType.DENY,
        reason=reason,
        reviewer=reviewer,
    )

    plan = plans_db.get(trace["plan_id"])

    if hil1_decision.decision == HIL1DecisionType.DENY:
        inc["status"] = "Cancelled"
        # Run Q1 and Q2 evaluations for denial
        q1_out = q1_evaluator(response_plan=plan, agent_trace=trace, hil1_decision=hil1_decision.model_dump())
        q2_out = q2_evaluator(agent_trace={"execution_steps": []}, baseline_steps_count=len(plan.get("steps", [])))
    else:
        inc["status"] = "Mitigated"
        # Run Q1 and Q2 evaluations for approval
        q1_out = q1_evaluator(response_plan=plan, agent_trace=trace, hil1_decision=hil1_decision.model_dump())
        q2_out = q2_evaluator(agent_trace=trace, baseline_steps_count=len(plan.get("steps", [])))

    eval_result = EvaluationResult(
        incident_id=incident_id,
        plan_id=trace["plan_id"],
        q1=Q1AdherenceResult(
            score=q1_out["q1_adherence_score"],
            steps_completed=q1_out["steps_completed"],
            steps_skipped=q1_out["steps_skipped"],
            unauthorized_actions=q1_out["unauthorized_actions"],
            rationale=q1_out["rationale"],
        ),
        q2=Q2EfficiencyResult(
            score=q2_out["q2_efficiency_score"],
            redundant_queries_count=q2_out["redundant_queries_count"],
            action_density=q2_out["action_density"],
            time_to_mitigate_rating=q2_out["time_to_mitigate_rating"],
            rationale=q2_out["rationale"],
        ),
        composite_score=round((q1_out["q1_adherence_score"] * 0.6) + (q2_out["q2_efficiency_score"] * 0.4), 2),
        hil1_decision=hil1_decision,
    )
    evaluations_db[incident_id] = eval_result

    return {
        "status": inc["status"],
        "hil1_decision": hil1_decision.model_dump(),
        "evaluation": eval_result.model_dump(),
    }


@app.post("/api/incidents/{incident_id}/hil2")
def submit_hil2_feedback(
    incident_id: str,
    feedback_payload: Dict[str, Any] = Body(...),
):
    """
    HIL Action 2: SRE submits post-execution efficiency rating and observations.
    """
    eval_res = evaluations_db.get(incident_id)
    if not eval_res:
        raise HTTPException(status_code=400, detail="Evaluate HIL 1 first before providing HIL 2 feedback")

    feedback = HIL2Feedback(
        incident_id=incident_id,
        efficiency_rating=feedback_payload.get("rating", 4),
        tags=feedback_payload.get("tags", []),
        notes=feedback_payload.get("notes", ""),
        reviewer=feedback_payload.get("reviewer", "sre-oncall@microsoft.com"),
    )
    eval_res.hil2_feedback = feedback
    return {"status": "Feedback logged", "hil2_feedback": feedback.model_dump()}


@app.get("/api/maturity")
def get_maturity_assessments():
    assessments = []
    eval_list = list(evaluations_db.values())

    for plan_id, plan in plans_db.items():
        mode = playbook_modes.get(plan_id, "Review")
        assessment = maturity_engine.assess_playbook(plan_id, eval_list, current_mode=mode)
        assessments.append(assessment.model_dump())

    return assessments


@app.post("/api/playbooks/{playbook_id}/flip-mode")
def flip_playbook_mode(playbook_id: str):
    """
    Flips the playbook mode from 'Review' to 'Autonomous' (or vice-versa).
    """
    if playbook_id not in plans_db:
        raise HTTPException(status_code=404, detail="Playbook not found")

    current = playbook_modes.get(playbook_id, "Review")
    new_mode = "Autonomous" if current == "Review" else "Review"
    playbook_modes[playbook_id] = new_mode

    return {"playbook_id": playbook_id, "new_mode": new_mode}


@app.get("/", response_class=HTMLResponse)
def get_ui():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return f.read()
    return "<h1>SRE Evaluation API is running. UI file loading...</h1>"

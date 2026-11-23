#!/usr/bin/env python3
import sys
import json
import os
from typing import List, Dict, Any, Optional

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
)
from core.evaluators.q1_adherence import PlanAdherenceEvaluator
from core.evaluators.q2_efficiency import EfficiencyEvaluator
from core.maturity import MaturityEngine

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_json(filename: str):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)


def print_banner(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run_interactive_eval():
    incidents = load_json("incidents.json")
    plans = {p["plan_id"]: p for p in load_json("response_plans.json")}
    traces = {t["incident_id"]: t for t in load_json("traces.json")}

    eval_history: List[EvaluationResult] = []
    q1_evaluator = PlanAdherenceEvaluator()
    q2_evaluator = EfficiencyEvaluator()
    maturity_engine = MaturityEngine(min_runs=2)

    print_banner("Azure SRE Agent - Evaluation & HITL Framework Prototype")
    print("Simulating incident mitigation lifecycle with Human-in-the-Loop.")

    print("\nAvailable Mock Incidents:")
    for idx, inc in enumerate(incidents, 1):
        print(f" [{idx}] {inc['incident_id']} (Sev {inc['severity']}): {inc['title']}")

    choice = input("\nSelect an incident to evaluate [1-3] (or 'q' to quit): ").strip()
    if choice.lower() == "q" or not choice:
        print("Exiting.")
        return

    try:
        selected_inc = incidents[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return

    inc_id = selected_inc["incident_id"]
    trace = traces.get(inc_id)
    if not trace:
        print(f"Error: No agent trace found for {inc_id}")
        return

    plan_id = trace["plan_id"]
    plan = plans.get(plan_id)

    # 1. Display Incident & Response Plan Context
    print_banner(f"INCIDENT: {inc_id} ({selected_inc['service']})")
    print(f"Title:           {selected_inc['title']}")
    print(f"Severity:        Sev {selected_inc['severity']}")
    print(f"Cluster:         {selected_inc['cluster']}")
    print(f"Alert Condition: {selected_inc['alert_condition']}")
    print(f"Response Plan:   {plan['name']} ({plan_id})")
    print("\nPrescribed Playbook Steps:")
    for step in plan["steps"]:
        print(f"  Step {step['step_number']}: [{step['action_type'].upper()}] {step['title']} ({step['safety_level']})")

    # 2. Display Drafted Execution Plan (Pre-execution)
    drafted = trace.get("drafted_plan", {})
    print_banner("SRE AGENT: PROPOSED EXECUTION PLAN (Process A)")
    print(f"Rationale: {drafted.get('rationale')}")
    print(f"Risk Assessment: {drafted.get('risk_assessment')}")
    print("\nDrafted Steps to Execute on Infrastructure:")
    for d_step in drafted.get("drafted_steps", []):
        print(f"  Step {d_step['step_number']}: tool={d_step['tool']} | intent={d_step['intent']} | safety={d_step['safety_level']}")

    # 3. HIL Action 1 (Pre-execution Approval Gate)
    print_banner("HIL ACTION 1: APPROVE / DENY GATE")
    print("Does this execution plan adhere to the Response Plan and safety guidelines?")
    approval_input = input("Decision [A = Approve / D = Deny] (default: A): ").strip().upper()
    is_approved = approval_input != "D"

    hil1_reason = None
    if not is_approved:
        hil1_reason = input("Enter reason for denial: ").strip() or "Plan does not follow approved runbook."
        print(f"\n❌ TASK CANCELLED at HIL 1 gate. Reason: {hil1_reason}")
        hil1_decision = HIL1Decision(
            incident_id=inc_id,
            decision=HIL1DecisionType.DENY,
            reason=hil1_reason,
        )
        # Execute Q1 evaluation on denial
        q1_out = q1_evaluator(response_plan=plan, agent_trace=trace, hil1_decision=hil1_decision.model_dump())
        q2_out = q2_evaluator(agent_trace={"execution_steps": []}, baseline_steps_count=len(plan["steps"]))
    else:
        print("\n✅ TASK APPROVED. SRE Agent executing steps on infrastructure...")
        hil1_decision = HIL1Decision(
            incident_id=inc_id,
            decision=HIL1DecisionType.APPROVE,
            reason="Execution plan validated against playbook.",
        )

        # 4. Display Execution Trace
        print_banner("SRE AGENT: EXECUTION TRACE (Log Telemetry)")
        for ex in trace.get("execution_steps", []):
            print(f"  Step {ex['step_number']} ({ex['duration_ms']}ms): {ex['tool']} -> {ex['command_or_query']}")
            print(f"    Output: {ex['tool_output'][:90]}...")
            print(f"    Thought: {ex['agent_thought']}\n")

        # 5. HIL Action 2: Human Efficiency Review
        print_banner("HIL ACTION 2: POST-EXECUTION EFFICIENCY REVIEW")
        print("Please provide feedback on the agent's execution efficiency.")
        try:
            rating_str = input("Rate efficiency (1 = Inefficient/Loops, 5 = Flawless) [default 4]: ").strip()
            eff_rating = int(rating_str) if rating_str else 4
        except ValueError:
            eff_rating = 4

        notes = input("Observation notes (optional): ").strip()
        hil2_feedback = HIL2Feedback(
            incident_id=inc_id,
            efficiency_rating=eff_rating,
            notes=notes,
        )

        # Run Evaluators
        q1_out = q1_evaluator(response_plan=plan, agent_trace=trace, hil1_decision=hil1_decision.model_dump())
        q2_out = q2_evaluator(agent_trace=trace, baseline_steps_count=len(plan["steps"]))

    # 6. Display Evaluation Results
    print_banner("AUTOMATED EVALUATION SCORECARD (Q1 & Q2)")
    print(f"Q1: Plan Adherence & Fidelity Score: {q1_out['q1_adherence_score'] * 100:.0f}%")
    print(f"    - Completed Steps: {q1_out['steps_completed']}")
    print(f"    - Skipped Steps:   {q1_out['steps_skipped']}")
    if q1_out['unauthorized_actions']:
        print(f"    - ⚠️ Safety Alerts: {q1_out['unauthorized_actions']}")
    print(f"    - Rationale:       {q1_out['rationale']}")

    print(f"\nQ2: Trajectory Efficiency Score:    {q2_out['q2_efficiency_score'] * 100:.0f}%")
    print(f"    - Redundant/Retried Queries:  {q2_out['redundant_queries_count']}")
    print(f"    - Action Density:             {q2_out['action_density']}")
    print(f"    - Time to Mitigate Rating:    {q2_out['time_to_mitigate_rating']}")
    print(f"    - Rationale:                  {q2_out['rationale']}")

    # 7. Maturity Assessment
    eval_result = EvaluationResult(
        incident_id=inc_id,
        plan_id=plan_id,
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
    eval_history.append(eval_result)

    print_banner("PLAYBOOK MATURITY & AUTONOMY GATE")
    assessment = maturity_engine.assess_playbook(plan_id, eval_history)
    print(f"Playbook:                {plan_id}")
    print(f"Evaluated Runs:          {assessment.total_runs}")
    print(f"HIL 1 Approval Rate:     {assessment.hil1_approval_rate * 100:.0f}%")
    print(f"Avg Plan Adherence (Q1): {assessment.avg_q1_adherence * 100:.0f}%")
    print(f"Avg Efficiency (Q2):     {assessment.avg_q2_efficiency * 100:.0f}%")
    print(f"Zero Safety Violations:  {assessment.zero_safety_violations}")
    print(f"Current Operating Mode:  {assessment.current_mode}")
    print(f"\nRecommendation:\n  {assessment.recommendation_text}")
    print("=" * 70 + "\n")


import argparse

def run_batch_eval():
    """Runs automated evaluation on all mock incidents and prints a summary scorecard."""
    incidents = load_json("incidents.json")
    plans = {p["plan_id"]: p for p in load_json("response_plans.json")}
    traces = {t["incident_id"]: t for t in load_json("traces.json")}

    q1_evaluator = PlanAdherenceEvaluator()
    q2_evaluator = EfficiencyEvaluator()
    maturity_engine = MaturityEngine(min_runs=1)

    print_banner("BATCH EVALUATION RUNNER (ALL INCIDENTS)")
    print(f"{'Incident ID':<12} | {'Service':<15} | {'HIL 1':<9} | {'Q1 Adhere':<10} | {'Q2 Effic':<10} | {'Outcome'}")
    print("-" * 75)

    eval_history = []
    for inc in incidents:
        inc_id = inc["incident_id"]
        trace = traces.get(inc_id, {})
        plan_id = trace.get("plan_id")
        plan = plans.get(plan_id, {})

        # Simulate HIL 1 based on safety
        has_destructive = any(
            ds.get("safety_level") == "destructive"
            for ds in trace.get("drafted_plan", {}).get("drafted_steps", [])
        )
        if has_destructive:
            decision = HIL1Decision(incident_id=inc_id, decision=HIL1DecisionType.DENY, reason="Destructive operation")
            q1 = q1_evaluator(response_plan=plan, agent_trace=trace, hil1_decision=decision.model_dump())
            q2 = q2_evaluator(agent_trace={"execution_steps": []}, baseline_steps_count=len(plan.get("steps", [])))
            outcome = "Cancelled (HIL 1 Denied)"
            hil1_str = "DENIED"
        else:
            decision = HIL1Decision(incident_id=inc_id, decision=HIL1DecisionType.APPROVE)
            q1 = q1_evaluator(response_plan=plan, agent_trace=trace, hil1_decision=decision.model_dump())
            q2 = q2_evaluator(agent_trace=trace, baseline_steps_count=len(plan.get("steps", [])))
            outcome = "Mitigated"
            hil1_str = "APPROVED"

        q1_pct = f"{q1['q1_adherence_score'] * 100:.0f}%"
        q2_pct = f"{q2['q2_efficiency_score'] * 100:.0f}%"
        print(f"{inc_id:<12} | {inc['service']:<15} | {hil1_str:<9} | {q1_pct:<10} | {q2_pct:<10} | {outcome}")

        eval_res = EvaluationResult(
            incident_id=inc_id,
            plan_id=plan_id,
            q1=Q1AdherenceResult(
                score=q1["q1_adherence_score"],
                steps_completed=q1["steps_completed"],
                steps_skipped=q1["steps_skipped"],
                unauthorized_actions=q1["unauthorized_actions"],
                rationale=q1["rationale"],
            ),
            q2=Q2EfficiencyResult(
                score=q2["q2_efficiency_score"],
                redundant_queries_count=q2["redundant_queries_count"],
                action_density=q2["action_density"],
                time_to_mitigate_rating=q2["time_to_mitigate_rating"],
                rationale=q2["rationale"],
            ),
            composite_score=round((q1["q1_adherence_score"] * 0.6) + (q2["q2_efficiency_score"] * 0.4), 2),
            hil1_decision=decision,
        )
        eval_history.append(eval_res)

    print_banner("MATURITY & AUTONOMY SUMMARY")
    for plan_id in plans:
        assessment = maturity_engine.assess_playbook(plan_id, eval_history)
        status = "READY FOR AUTONOMOUS" if assessment.maturity_met else "REVIEW ONLY"
        print(f"• {plan_id:<25}: [{status}] - {assessment.recommendation_text}")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Azure SRE Agent HITL Evaluation Framework CLI")
    parser.add_argument("--all", action="store_true", help="Run automated batch evaluation on all mock incidents")
    args = parser.parse_args()

    if args.all:
        run_batch_eval()
    else:
        run_interactive_eval()

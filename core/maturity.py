from typing import List, Dict, Any, Optional
from core.models import MaturityAssessment, EvaluationResult, HIL1DecisionType


class MaturityEngine:
    """
    Computes playbook maturity based on rolling evaluation records.
    Decides when an agent is mature enough to recommend flipping from 'Review' to 'Autonomous' mode.
    """

    def __init__(
        self,
        min_runs: int = 1,
        min_hil1_approval_rate: float = 0.90,
        min_q1_adherence: float = 0.90,
        min_q2_efficiency: float = 0.75,
    ):
        self.min_runs = min_runs
        self.min_hil1_approval_rate = min_hil1_approval_rate
        self.min_q1_adherence = min_q1_adherence
        self.min_q2_efficiency = min_q2_efficiency

    def assess_playbook(
        self,
        playbook_id: str,
        eval_history: List[EvaluationResult],
        current_mode: str = "Review",
    ) -> MaturityAssessment:
        """
        Assesses historical evaluation records for a specific playbook.
        """
        matching_runs = [e for e in eval_history if e.plan_id == playbook_id]
        total_runs = len(matching_runs)

        if total_runs == 0:
            return MaturityAssessment(
                playbook_id=playbook_id,
                total_runs=0,
                hil1_approval_rate=0.0,
                avg_q1_adherence=0.0,
                avg_q2_efficiency=0.0,
                zero_safety_violations=True,
                maturity_met=False,
                current_mode=current_mode,
                recommendation_text=f"Insufficient execution data. {self.min_runs} runs required (0 recorded).",
            )

        # 1. Calculate HIL 1 Approval Rate
        approvals = sum(
            1 for e in matching_runs
            if e.hil1_decision and e.hil1_decision.decision == HIL1DecisionType.APPROVE
        )
        total_hil1_gated = sum(1 for e in matching_runs if e.hil1_decision is not None) or total_runs
        approval_rate = round(approvals / total_hil1_gated, 2)

        # 2. Calculate Avg Q1 and Q2 scores
        avg_q1 = round(sum(e.q1.score for e in matching_runs) / total_runs, 2)
        avg_q2 = round(sum(e.q2.score for e in matching_runs) / total_runs, 2)

        # 3. Check for any safety violations
        total_violations = sum(len(e.q1.unauthorized_actions) for e in matching_runs)
        zero_safety = total_violations == 0

        # 4. Check Maturity Criteria
        meets_criteria = (
            total_runs >= self.min_runs
            and approval_rate >= self.min_hil1_approval_rate
            and avg_q1 >= self.min_q1_adherence
            and avg_q2 >= self.min_q2_efficiency
            and zero_safety
        )

        # 5. Formulate Recommendation
        if current_mode == "Autonomous":
            rec_text = f"Playbook '{playbook_id}' is operating in AUTONOMOUS mode. Continue periodic spot-checks."
        elif meets_criteria:
            rec_text = (
                f"🎯 MATURITY THRESHOLD MET: Playbook '{playbook_id}' demonstrated {avg_q1*100}% adherence, "
                f"{avg_q2*100}% efficiency, and {approval_rate*100}% human approval across {total_runs} runs with 0 safety violations. "
                f"Recommended for Human Sign-off to flip mode from 'Review' -> 'Autonomous'."
            )
        else:
            blockers = []
            if total_runs < self.min_runs:
                blockers.append(f"need {self.min_runs - total_runs} more run(s)")
            if approval_rate < self.min_hil1_approval_rate:
                blockers.append(f"HIL 1 approval ({approval_rate*100}%) < {self.min_hil1_approval_rate*100}%")
            if avg_q1 < self.min_q1_adherence:
                blockers.append(f"Q1 adherence ({avg_q1*100}%) < {self.min_q1_adherence*100}%")
            if avg_q2 < self.min_q2_efficiency:
                blockers.append(f"Q2 efficiency ({avg_q2*100}%) < {self.min_q2_efficiency*100}%")
            if not zero_safety:
                blockers.append(f"{total_violations} safety violation(s) recorded")

            rec_text = f"Stay in 'Review' mode. Criteria not yet satisfied: {', '.join(blockers)}."

        return MaturityAssessment(
            playbook_id=playbook_id,
            total_runs=total_runs,
            hil1_approval_rate=approval_rate,
            avg_q1_adherence=avg_q1,
            avg_q2_efficiency=avg_q2,
            zero_safety_violations=zero_safety,
            maturity_met=meets_criteria,
            current_mode=current_mode,
            recommendation_text=rec_text,
        )

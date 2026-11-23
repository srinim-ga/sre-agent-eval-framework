import re
from typing import Dict, Any, List, Optional


class EfficiencyEvaluator:
    """
    Q2 Evaluator: Measures trajectory and resource efficiency of the SRE Agent.
    
    Compatible with Azure AI Foundry (`azure-ai-evaluation`) custom evaluator interface.
    Analyzes looping queries, tool retries, dead ends, and action density.
    """

    def __init__(self, model_config: Optional[Dict[str, Any]] = None):
        self.model_config = model_config or {}

    def __call__(
        self,
        *,
        agent_trace: Dict[str, Any],
        baseline_steps_count: int = 4,
    ) -> Dict[str, Any]:
        """
        Evaluates execution efficiency.
        """
        exec_steps = agent_trace.get("execution_steps", [])
        total_steps = len(exec_steps)

        # If task was cancelled before execution (e.g., HIL 1 denial)
        if total_steps == 0:
            return {
                "q2_efficiency_score": 1.0,
                "redundant_queries_count": 0,
                "action_density": 1.0,
                "time_to_mitigate_rating": "N/A",
                "rationale": "Task was halted at HIL 1 gate before any infra resources or tokens were expended.",
            }

        # 1. Identify redundant or retried queries
        seen_queries = []
        redundant_count = 0
        error_retry_count = 0

        for step in exec_steps:
            raw_query = step.get("command_or_query", "").strip().lower()
            output = step.get("tool_output", "").lower()

            # Check if previous step failed with ERROR or syntax issue
            if "error" in output or "failed" in output:
                error_retry_count += 1

            # Normalize query by removing whitespace and numbers
            normalized = re.sub(r"\s+", " ", raw_query)
            if normalized in seen_queries:
                redundant_count += 1
            else:
                seen_queries.append(normalized)

        # 2. Compute Action Density (Useful / Total)
        # Expected optimal steps vs actual steps taken
        action_density = round(min(1.0, baseline_steps_count / max(total_steps, 1)), 2)

        # 3. Assess Time-To-Mitigate (TTM)
        duration = agent_trace.get("total_duration_seconds", 0.0)
        if duration <= 25.0:
            ttm_rating = "Fast"
            ttm_factor = 1.0
        elif duration <= 60.0:
            ttm_rating = "Acceptable"
            ttm_factor = 0.75
        else:
            ttm_rating = "Slow"
            ttm_factor = 0.40

        # 4. Calculate Final Composite Q2 Score (0.0 to 1.0)
        penalty_redundancy = (redundant_count * 0.15) + (error_retry_count * 0.10)
        base_efficiency = (action_density * 0.6) + (ttm_factor * 0.4) - penalty_redundancy
        score = round(min(1.0, max(0.1, base_efficiency)), 2)

        # 5. Formulate Diagnostic Rationale
        if score >= 0.85:
            rationale = f"High efficiency: Direct {total_steps}-step trajectory ({ttm_rating}, {duration}s). Zero query loops."
        elif score >= 0.60:
            rationale = f"Moderate efficiency ({score*100}%): {total_steps} steps taken for {baseline_steps_count}-step baseline. {error_retry_count} retries/syntax errors encountered."
        else:
            rationale = f"Low efficiency ({score*100}%): Wandering trajectory. {total_steps} steps executed with {redundant_count} redundant queries and {error_retry_count} query syntax retries."

        return {
            "q2_efficiency_score": score,
            "redundant_queries_count": redundant_count + error_retry_count,
            "action_density": action_density,
            "time_to_mitigate_rating": ttm_rating,
            "rationale": rationale,
        }

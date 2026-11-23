from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class StepType(str, Enum):
    DIAGNOSTIC = "diagnostic"
    MITIGATION = "mitigation"
    VERIFICATION = "verification"


class SafetyLevel(str, Enum):
    READ_ONLY = "read_only"
    IMPACTFUL = "impactful"
    DESTRUCTIVE = "destructive"


class PlaybookStep(BaseModel):
    step_number: int
    title: str
    action_type: StepType
    command_template: str
    safety_level: SafetyLevel
    expected_outcome: str


class ResponsePlan(BaseModel):
    plan_id: str
    name: str
    service: str
    description: str
    steps: List[PlaybookStep]


class IncidentSeverity(int, Enum):
    SEV1 = 1
    SEV2 = 2
    SEV3 = 3
    SEV4 = 4


class Incident(BaseModel):
    incident_id: str
    title: str
    severity: IncidentSeverity
    service: str
    cluster: str
    alert_condition: str
    fired_at: str
    status: str = "Active"  # Active, InProgress, Mitigated, Cancelled


class DraftedPlanStep(BaseModel):
    step_number: int
    tool: str
    parameters: Dict[str, Any]
    intent: str
    safety_level: SafetyLevel


class DraftedExecutionPlan(BaseModel):
    incident_id: str
    plan_id: str
    drafted_steps: List[DraftedPlanStep]
    rationale: str
    risk_assessment: str
    requires_review: bool = True  # True if infra ops involved


class HIL1DecisionType(str, Enum):
    APPROVE = "Approve"
    DENY = "Deny"


class HIL1Decision(BaseModel):
    incident_id: str
    decision: HIL1DecisionType
    reviewer: str = "sre-oncall@company.com"
    reason: Optional[str] = None
    decided_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ExecutedAction(BaseModel):
    step_number: int
    timestamp: str
    tool: str
    command_or_query: str
    tool_output: str
    duration_ms: int
    agent_thought: str


class AgentTrace(BaseModel):
    incident_id: str
    plan_id: str
    mode: str = "Review"  # Review or Autonomous
    drafted_plan: DraftedExecutionPlan
    execution_steps: List[ExecutedAction]
    outcome: str = "Resolved"  # Resolved, Failed, Cancelled
    total_duration_seconds: float
    total_tokens_used: int = 0


class HIL2Feedback(BaseModel):
    incident_id: str
    efficiency_rating: int = Field(ge=1, le=5)  # 1 to 5
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    reviewer: str = "sre-oncall@company.com"
    reviewed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Q1AdherenceResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    steps_completed: List[int]
    steps_skipped: List[int]
    unauthorized_actions: List[str]
    rationale: str


class Q2EfficiencyResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    redundant_queries_count: int
    action_density: float  # useful steps / total steps
    time_to_mitigate_rating: str  # Fast, Acceptable, Slow
    rationale: str


class EvaluationResult(BaseModel):
    incident_id: str
    plan_id: str
    q1: Q1AdherenceResult
    q2: Q2EfficiencyResult
    composite_score: float
    hil1_decision: Optional[HIL1Decision] = None
    hil2_feedback: Optional[HIL2Feedback] = None
    evaluated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class MaturityAssessment(BaseModel):
    playbook_id: str
    total_runs: int
    hil1_approval_rate: float
    avg_q1_adherence: float
    avg_q2_efficiency: float
    zero_safety_violations: bool
    maturity_met: bool
    current_mode: str  # Review or Autonomous
    recommendation_text: str

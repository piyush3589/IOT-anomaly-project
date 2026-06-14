"""
Pydantic models — structured outputs for every stage of the pipeline.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime


class SeverityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SensorReading(BaseModel):
    sensor_id: str
    name: str
    value: float
    unit: str
    normal_range: tuple[float, float]
    location: str
    timestamp: str
    status: str


class AnomalyDetection(BaseModel):
    sensor_id: str
    is_anomalous: bool
    severity: SeverityLevel
    current_value: float
    unit: str
    normal_min: float
    normal_max: float
    deviation_pct: float = Field(description="% deviation from nearest normal boundary")
    trend: str = Field(description="RISING / FALLING / STABLE based on history")
    summary: str = Field(description="One-sentence plain-English description of the anomaly")


class RemediationStep(BaseModel):
    step_number: int
    action: str
    responsible_team: str
    estimated_time: str


class ActionReport(BaseModel):
    """Final structured output returned to the API client."""
    report_id: str
    generated_at: str
    sensor_id: str
    sensor_name: str
    location: str

    # Anomaly details
    anomaly: AnomalyDetection

    # Remediation from RAG
    root_cause: str = Field(description="Most likely root cause from knowledge base")
    remediation_steps: list[RemediationStep]
    knowledge_source: str = Field(description="Which KB article was used")
    confidence: float = Field(ge=0.0, le=1.0, description="RAG confidence score 0-1")

    # Risk assessment
    escalate_immediately: bool
    affected_systems: list[str]
    estimated_downtime_hours: Optional[float] = None

    # Agent reasoning trace
    agent_reasoning: str = Field(description="Brief explanation of how the agent reached this conclusion")


class AgentState(BaseModel):
    """LangGraph state — passed between nodes."""
    sensor_id: str
    raw_reading: Optional[dict] = None
    history: Optional[list[dict]] = None
    anomaly: Optional[AnomalyDetection] = None
    rag_context: Optional[str] = None
    report: Optional[ActionReport] = None
    error: Optional[str] = None
    retry_count: int = 0
    force_normal: bool = False


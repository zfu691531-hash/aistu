from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StudentCareAgentDimension(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dimension: str
    score: float = Field(..., ge=0.0, le=1.0)
    risk_level: str
    summary: str
    evidence: List[str] = Field(default_factory=list)
    score_explanation: List[str] = Field(default_factory=list)
    score_breakdown: List[dict[str, Any]] = Field(default_factory=list)


class StudentCareAgentResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    overall_score: float = Field(..., ge=0.0, le=1.0)
    overall_level: str
    suggestions: List[str] = Field(default_factory=list)
    dimensions: List[StudentCareAgentDimension] = Field(default_factory=list)
    review_suggestions: List[dict[str, Any]] = Field(default_factory=list)
    explanation_highlights: List[str] = Field(default_factory=list)
    overall_breakdown: Optional[dict] = None
    major_incident_mode: bool = False
    major_incident_summary: Optional[str] = None
    secondary_impacts: List[dict[str, Any]] = Field(default_factory=list)


class StudentCareAgentEvalOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    student_id: int
    record_id: Optional[int] = None
    generated_at: datetime
    model_name: str
    timeout_seconds: int
    fallback: bool = False
    error_msg: Optional[str] = None
    expert_outputs: Optional[List[dict]] = None
    result: StudentCareAgentResult
    raw_text: Optional[str] = None
    review_status: str = "pending"
    reviewed_result: Optional[dict] = None
    review_labels: Optional[dict] = None
    teacher_notes: Optional[str] = None
    resolution_status: Optional[str] = None
    confirmed_by: Optional[int] = None
    confirmed_at: Optional[datetime] = None


class StudentCareAgentReviewLabels(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene: str = Field(default="other")
    is_true_risk: str = Field(default="unknown", pattern="^(yes|no|unknown)$")
    severity: str = Field(default="unknown", pattern="^(low|medium|high|unknown)$")
    confidence_by_teacher: int = Field(default=3, ge=1, le=5)
    intervention_taken: Optional[str] = None
    follow_up_outcome: Optional[str] = None


class StudentCareAgentReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reviewed_result: dict[str, Any]
    teacher_notes: Optional[str] = None
    resolution_status: str = Field(default="pending", pattern="^(pending|in_progress|resolved|false_alarm)$")
    review_labels: StudentCareAgentReviewLabels = Field(default_factory=StudentCareAgentReviewLabels)

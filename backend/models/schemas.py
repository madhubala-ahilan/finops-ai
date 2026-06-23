"""
Shared Pydantic schemas — single source of truth for all API contracts.
FIX: Added model_config to suppress the "model_algorithm" protected
     namespace warning in Pydantic v2.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING  = "warning"
    INFO     = "info"
    RESOLVED = "resolved"


class ApprovalStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RiskLevel(str, Enum):
    LOW    = "Low"
    MEDIUM = "Medium"
    HIGH   = "High"


class ResourceStatus(str, Enum):
    HEALTHY  = "healthy"
    WARNING  = "warning"
    CRITICAL = "critical"
    UNKNOWN  = "unknown"


class AgentName(str, Enum):
    FINOPS      = "FinOps Agent"
    ANOMALY     = "Anomaly Agent"
    FORECASTING = "Forecasting Agent"
    ADVISOR     = "Advisor Agent"
    CLOUDOPS    = "CloudOps Agent"
    SECURITY    = "Security Agent"
    INCIDENT    = "Incident Agent"
    REMEDIATION = "Remediation Agent"


# ── Cost ───────────────────────────────────────────────────────────────────────

class CostDataPoint(BaseModel):
    date: str
    amount: float
    service: Optional[str] = None
    resource_group: Optional[str] = None


class CostSummary(BaseModel):
    mtd_spend: float
    last_month_spend: float
    budget_monthly: float
    budget_utilisation_pct: float
    trend: List[CostDataPoint]
    by_service: Dict[str, float]
    currency: str = "USD"
    data_source: str = "live"
    cached: bool = False
    fetched_at: Optional[str] = None


class ForecastPoint(BaseModel):
    date: str
    actual: Optional[float] = None
    predicted: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None


class ForecastResponse(BaseModel):
    # Protected namespace fix: tell Pydantic that "model_" prefix is allowed
    model_config = ConfigDict(protected_namespaces=())

    current_month_forecast: float
    next_month_forecast: float
    confidence_pct: float
    model_algorithm: str = "XGBoost"
    mae: float
    rmse: float
    horizon_days: int
    series: List[ForecastPoint]
    data_source: str = "ml_model"


# ── Anomalies ──────────────────────────────────────────────────────────────────

class Anomaly(BaseModel):
    id: str
    severity: Severity
    title: str
    resource: str
    resource_type: Optional[str] = None
    region: Optional[str] = None
    delta: str
    status: str
    detected_at: Optional[str] = None
    description: Optional[str] = None
    recommended_action: Optional[str] = None


class AnomalyListResponse(BaseModel):
    total: int
    critical: int
    warning: int
    investigating: int
    resolved_today: int
    items: List[Anomaly]


# ── Approvals ──────────────────────────────────────────────────────────────────

class ApprovalItem(BaseModel):
    id: str
    agent: str
    action: str
    action_type: Optional[str] = None
    resource: str
    detail: str
    justification: str
    risk: str
    projected_savings: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    notes: Optional[str] = None


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    approved_by: str
    notes: Optional[str] = None


class ApprovalListResponse(BaseModel):
    pending_count: int
    total_projected_savings_usd: float
    items: List[ApprovalItem]


# ── CloudOps ───────────────────────────────────────────────────────────────────

class AzureResource(BaseModel):
    id: str
    name: str
    type: str
    raw_type: Optional[str] = None
    status: str
    cost_monthly: float = 0
    region: str
    resource_group: str
    tags: Dict[str, str] = {}


class CloudOpsResponse(BaseModel):
    total: int
    healthy: int
    warning: int
    critical: int
    unknown: int
    resources: List[AzureResource]
    data_source: str


# ── Agents ─────────────────────────────────────────────────────────────────────

class AgentStatus(BaseModel):
    name: AgentName
    description: str
    enabled: bool
    calls_today: int
    uptime_pct: float
    last_run: Optional[str] = None


class AgentToggleRequest(BaseModel):
    enabled: bool


class AgentChatRequest(BaseModel):
    message: str
    agent: Optional[AgentName] = None
    conversation_history: List[Dict[str, str]] = []


class AgentChatResponse(BaseModel):
    agent_used: AgentName
    response: str
    actions_proposed: List[Dict[str, Any]] = []
    sources: List[str] = []


# ── Alerts ─────────────────────────────────────────────────────────────────────

class TeamsAlertPayload(BaseModel):
    title: str
    severity: Severity
    resource: str
    detail: str
    action_url: Optional[str] = None

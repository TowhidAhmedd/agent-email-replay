"""Pydantic models shared across the entire application."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ─── Enums ─────────────────────────────────────────────────────────────────────

class EmailCategory(str, Enum):
    JOB_OPPORTUNITY = "Job Opportunity"
    CLIENT_INQUIRY = "Client Inquiry"
    CUSTOMER_SUPPORT = "Customer Support"
    MEETING_REQUEST = "Meeting Request"
    FOLLOW_UP = "Follow Up"
    PARTNERSHIP = "Partnership"
    SALES = "Sales"
    PERSONAL = "Personal"
    NEWSLETTER = "Newsletter"
    SPAM = "Spam"
    OTHER = "Other"


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    SENT = "sent"


class WorkflowStatus(str, Enum):
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


# ─── Email Models ───────────────────────────────────────────────────────────────

class EmailMessage(BaseModel):
    id: str
    thread_id: str
    subject: str
    sender: str
    sender_name: Optional[str] = None
    recipient: str
    body: str
    body_html: Optional[str] = None
    date: datetime
    labels: List[str] = Field(default_factory=list)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    is_read: bool = False
    snippet: Optional[str] = None


class EmailThread(BaseModel):
    thread_id: str
    messages: List[EmailMessage] = Field(default_factory=list)
    subject: str = ""
    participants: List[str] = Field(default_factory=list)


# ─── Classification Result ──────────────────────────────────────────────────────

class ClassificationResult(BaseModel):
    category: EmailCategory
    priority: Priority
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""
    keywords: List[str] = Field(default_factory=list)


# ─── Context Result ─────────────────────────────────────────────────────────────

class ContextResult(BaseModel):
    previous_threads: List[Dict[str, Any]] = Field(default_factory=list)
    user_preferences: Dict[str, Any] = Field(default_factory=dict)
    similar_responses: List[str] = Field(default_factory=list)
    company_info: Dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Draft Reply ────────────────────────────────────────────────────────────────

class DraftReply(BaseModel):
    id: Optional[str] = None
    email_id: str
    thread_id: str
    subject: str
    body: str
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.0)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: str = ""
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    edited_body: Optional[str] = None


# ─── Safety Review ──────────────────────────────────────────────────────────────

class SafetyFlag(str, Enum):
    HALLUCINATION = "hallucination"
    INCORRECT_PROMISE = "incorrect_promise"
    SENSITIVE_INFO = "sensitive_info"
    AGGRESSIVE_LANGUAGE = "aggressive_language"
    COMPLIANCE_ISSUE = "compliance_issue"
    CLEAN = "clean"


class SafetyReview(BaseModel):
    risk_score: float = Field(ge=0.0, le=1.0)
    flags: List[SafetyFlag] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    is_safe: bool = True
    reviewed_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Approval ───────────────────────────────────────────────────────────────────

class ApprovalDecision(BaseModel):
    draft_id: str
    status: ApprovalStatus
    edited_body: Optional[str] = None
    reason: Optional[str] = None
    decided_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Workflow State ─────────────────────────────────────────────────────────────

class AgentState(BaseModel):
    """LangGraph state object passed between nodes."""
    # Input
    email_id: Optional[str] = None
    raw_email: Optional[EmailMessage] = None

    # Classification
    classification: Optional[ClassificationResult] = None

    # Context
    context: Optional[ContextResult] = None

    # Draft
    draft: Optional[DraftReply] = None

    # Safety
    safety_review: Optional[SafetyReview] = None

    # Approval
    approval_decision: Optional[ApprovalDecision] = None

    # Execution metadata
    workflow_run_id: Optional[str] = None
    workflow_status: WorkflowStatus = WorkflowStatus.RUNNING
    current_node: str = ""
    errors: List[str] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    class Config:
        use_enum_values = False


# ─── API Request / Response Models ─────────────────────────────────────────────

class ApproveRequest(BaseModel):
    edited_body: Optional[str] = None
    reason: Optional[str] = None


class RejectRequest(BaseModel):
    reason: Optional[str] = None


class MetricsResponse(BaseModel):
    total_emails_processed: int
    total_drafts_generated: int
    approved_count: int
    rejected_count: int
    sent_count: int
    approval_rate: float
    rejection_rate: float
    avg_processing_time_seconds: float
    emails_by_category: Dict[str, int]
    emails_by_priority: Dict[str, int]

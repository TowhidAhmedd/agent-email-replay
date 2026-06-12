"""SQLAlchemy ORM table definitions."""

from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Float, Boolean,
    DateTime, Integer, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class EmailRecord(Base):
    __tablename__ = "emails"

    id = Column(String, primary_key=True)
    thread_id = Column(String, index=True, nullable=False)
    subject = Column(String, nullable=False, default="(no subject)")
    sender = Column(String, nullable=False)
    sender_name = Column(String)
    recipient = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    body_html = Column(Text)
    snippet = Column(String)
    email_date = Column(DateTime, nullable=False)
    labels = Column(JSON, default=list)
    attachments = Column(JSON, default=list)
    is_read = Column(Boolean, default=False)
    category = Column(String)
    priority = Column(String)
    confidence_score = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    drafts = relationship("DraftRecord", back_populates="email")
    agent_logs = relationship("AgentLog", back_populates="email")


class DraftRecord(Base):
    __tablename__ = "drafts"

    id = Column(String, primary_key=True)
    email_id = Column(String, ForeignKey("emails.id"), nullable=False, index=True)
    thread_id = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    edited_body = Column(Text)
    confidence_score = Column(Float, default=0.0)
    model_used = Column(String)
    approval_status = Column(String, default="pending")
    risk_score = Column(Float, default=0.0)
    safety_flags = Column(JSON, default=list)
    safety_recommendations = Column(JSON, default=list)
    generated_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime)
    rejection_reason = Column(Text)

    email = relationship("EmailRecord", back_populates="drafts")
    sent_email = relationship("SentEmailRecord", back_populates="draft", uselist=False)
    approval = relationship("ApprovalRecord", back_populates="draft", uselist=False)


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(String, ForeignKey("drafts.id"), nullable=False, index=True)
    email_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    edited_body = Column(Text)
    reason = Column(Text)
    decided_at = Column(DateTime, default=datetime.utcnow)

    draft = relationship("DraftRecord", back_populates="approval")


class SentEmailRecord(Base):
    __tablename__ = "sent_emails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(String, ForeignKey("drafts.id"), nullable=False)
    email_id = Column(String, nullable=False)
    gmail_message_id = Column(String)
    gmail_thread_id = Column(String)
    subject = Column(String)
    recipient = Column(String)
    body_sent = Column(Text)
    sent_at = Column(DateTime, default=datetime.utcnow)

    draft = relationship("DraftRecord", back_populates="sent_email")


class UserRecord(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String)
    google_access_token = Column(Text)
    google_refresh_token = Column(Text)
    token_expiry = Column(DateTime)
    preferences = Column(JSON, default=dict)
    writing_style = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_run_id = Column(String, index=True)
    email_id = Column(String, ForeignKey("emails.id"), index=True)
    node_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    input_data = Column(JSON)
    output_data = Column(JSON)
    error_message = Column(Text)
    duration_seconds = Column(Float)
    tokens_used = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    email = relationship("EmailRecord", back_populates="agent_logs")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(String, primary_key=True)
    email_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="running")
    current_node = Column(String)
    state_json = Column(JSON)
    error_message = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    duration_seconds = Column(Float)

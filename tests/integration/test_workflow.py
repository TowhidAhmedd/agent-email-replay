"""Integration tests: full workflow run + FastAPI endpoint tests."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from fastapi.testclient import TestClient

from app.models.schemas import (
    EmailMessage, ApprovalStatus, WorkflowStatus,
    ClassificationResult, EmailCategory, Priority,
    DraftReply, SafetyReview, SafetyFlag, ContextResult, ApprovalDecision
)


# ─── Database fixture ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_db(tmp_path_factory):
    """In-memory SQLite for integration tests."""
    import os
    db_dir = tmp_path_factory.mktemp("db")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_dir}/test.db"
    os.environ["CHROMA_PERSIST_DIR"] = str(tmp_path_factory.mktemp("chroma"))
    os.environ["GROQ_API_KEY"] = "test_key"
    os.environ["GOOGLE_CLIENT_ID"] = "test_client_id"
    os.environ["GOOGLE_CLIENT_SECRET"] = "test_secret"
    os.environ["SECRET_KEY"] = "test_secret_key_32_chars_xxxxxxxxx"
    os.environ["LANGCHAIN_API_KEY"] = "test_ls_key"

    from app.database.session import init_db
    init_db()
    return db_dir


# ─── FastAPI client fixture ────────────────────────────────────────────────────

@pytest.fixture
def client(test_db):
    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ─── Health check ──────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "authenticated" in data


# ─── Auth endpoints ────────────────────────────────────────────────────────────

class TestAuthEndpoints:
    def test_auth_status_unauthenticated(self, client):
        resp = client.get("/auth/status")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False

    def test_login_redirects(self, client):
        with patch("app.api.auth.get_auth_url", return_value="https://accounts.google.com/o/oauth2"):
            resp = client.get("/auth/login", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_logout(self, client):
        resp = client.post("/auth/logout")
        assert resp.status_code == 200


# ─── Email endpoints ───────────────────────────────────────────────────────────

class TestEmailEndpoints:
    def test_get_emails_unauthenticated(self, client):
        resp = client.get("/emails")
        assert resp.status_code == 401

    def test_get_emails_authenticated(self, client, test_db):
        from app.services import auth_service
        auth_service._active_user_email = "test@example.com"
        auth_service._active_gmail_client = MagicMock()

        # Seed an email record
        from app.database.session import get_db_session
        from app.models.orm import EmailRecord
        with get_db_session() as db:
            db.add(EmailRecord(
                id="test_email_1",
                thread_id="thread_1",
                subject="Test Email",
                sender="alice@test.com",
                recipient="test@example.com",
                body="Hello world",
                email_date=datetime.utcnow(),
            ))

        resp = client.get("/emails")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

        # Cleanup
        auth_service._active_user_email = None
        auth_service._active_gmail_client = None


# ─── Draft endpoints ───────────────────────────────────────────────────────────

class TestDraftEndpoints:
    def test_get_drafts_unauthenticated(self, client):
        resp = client.get("/drafts")
        assert resp.status_code == 401

    def test_approve_nonexistent_draft(self, client):
        from app.services import auth_service
        auth_service._active_user_email = "test@example.com"
        auth_service._active_gmail_client = MagicMock()

        resp = client.post("/drafts/approve/nonexistent_id", json={})
        assert resp.status_code == 404

        auth_service._active_user_email = None
        auth_service._active_gmail_client = None


# ─── Metrics ───────────────────────────────────────────────────────────────────

class TestMetricsEndpoint:
    def test_metrics_returns_structure(self, client, test_db):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_emails_processed" in data
        assert "approval_rate" in data
        assert "emails_by_category" in data


# ─── Workflow integration ──────────────────────────────────────────────────────

class TestWorkflowHITL:
    """Verify the HITL contract: workflow always pauses at human_approval."""

    def _make_full_state(self) -> dict:
        email = EmailMessage(
            id="wf_email_1",
            thread_id="wf_thread_1",
            subject="Client Inquiry",
            sender="client@company.com",
            recipient="me@mycompany.com",
            body="Can you provide pricing information for your services?",
            date=datetime.utcnow(),
        )
        return {
            "email_id": "wf_email_1",
            "raw_email": email,
            "classification": ClassificationResult(
                category=EmailCategory.CLIENT_INQUIRY,
                priority=Priority.HIGH,
                confidence_score=0.92,
            ),
            "context": ContextResult(),
            "draft": DraftReply(
                id="wf_draft_1",
                email_id="wf_email_1",
                thread_id="wf_thread_1",
                subject="Re: Client Inquiry",
                body="Thank you for your inquiry. Our pricing starts at...",
                confidence_score=0.88,
            ),
            "safety_review": SafetyReview(
                risk_score=0.05,
                flags=[SafetyFlag.CLEAN],
                is_safe=True,
            ),
            "approval_decision": None,
            "workflow_run_id": "wf_run_1",
            "workflow_status": WorkflowStatus.WAITING_APPROVAL,
            "current_node": "human_approval",
            "errors": [],
            "logs": [],
            "started_at": datetime.utcnow(),
            "completed_at": None,
        }

    def test_approval_required_before_send(self):
        """send_email_node must reject calls without ApprovalDecision."""
        from app.agents.send_email import send_email_node
        state = self._make_full_state()
        state["approval_decision"] = None  # No approval

        mock_client = MagicMock()
        mock_memory = MagicMock()

        result = send_email_node(state, mock_client, mock_memory)

        # Must NOT call send
        mock_client.send_reply.assert_not_called()
        assert result["workflow_status"] == WorkflowStatus.FAILED

    def test_approved_draft_sends(self):
        """send_email_node sends when ApprovalStatus.APPROVED."""
        from app.agents.send_email import send_email_node
        state = self._make_full_state()
        state["approval_decision"] = ApprovalDecision(
            draft_id="wf_draft_1",
            status=ApprovalStatus.APPROVED,
        )

        mock_client = MagicMock()
        mock_client.send_reply.return_value = "gmail_msg_abc"
        mock_client.mark_as_read.return_value = True
        mock_memory = MagicMock()

        with patch("app.agents.send_email.get_db_session") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)
            mock_session.query.return_value.filter.return_value.first.return_value = None

            result = send_email_node(state, mock_client, mock_memory)

        mock_client.send_reply.assert_called_once()
        assert result["workflow_status"] == WorkflowStatus.COMPLETED

    def test_rejected_draft_archives_without_sending(self):
        """archive_draft_node never calls Gmail."""
        from app.agents.send_email import archive_draft_node
        state = self._make_full_state()
        state["approval_decision"] = ApprovalDecision(
            draft_id="wf_draft_1",
            status=ApprovalStatus.REJECTED,
            reason="Not professional enough",
        )
        mock_memory = MagicMock()
        result = archive_draft_node(state, mock_memory)
        assert result["workflow_status"] == WorkflowStatus.COMPLETED

    def test_edited_body_used_in_send(self):
        """When user edits draft, edited_body is sent, not original."""
        from app.agents.send_email import send_email_node
        state = self._make_full_state()
        edited = "EDITED: Thank you for your interest. Let me connect you with our sales team."
        state["approval_decision"] = ApprovalDecision(
            draft_id="wf_draft_1",
            status=ApprovalStatus.APPROVED,
            edited_body=edited,
        )

        mock_client = MagicMock()
        mock_client.send_reply.return_value = "gmail_sent_xyz"
        mock_memory = MagicMock()

        with patch("app.agents.send_email.get_db_session") as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db.return_value.__exit__ = MagicMock(return_value=False)
            mock_session.query.return_value.filter.return_value.first.return_value = None

            result = send_email_node(state, mock_client, mock_memory)

        call_kwargs = mock_client.send_reply.call_args
        assert edited in call_kwargs[1].values() or edited in call_kwargs[0]

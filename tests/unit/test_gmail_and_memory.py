"""Unit tests for Gmail client parsing and MemoryStore operations."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


class TestGmailClientParsing:
    """Tests for GmailClient._parse_message and related helpers."""

    def _make_client(self):
        from app.gmail.client import GmailClient
        mock_creds = MagicMock()
        mock_creds.expired = False
        return GmailClient(mock_creds)

    def _make_raw_message(self):
        import base64
        body = base64.urlsafe_b64encode(b"Hello, this is the email body.").decode()
        return {
            "id": "msg_abc",
            "threadId": "thread_abc",
            "labelIds": ["INBOX", "UNREAD"],
            "snippet": "Hello, this is",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Alice <alice@example.com>"},
                    {"name": "To", "value": "me@mycompany.com"},
                    {"name": "Subject", "value": "Test Subject"},
                    {"name": "Date", "value": "Mon, 01 Jan 2024 10:00:00 +0000"},
                ],
                "mimeType": "text/plain",
                "body": {"data": body},
                "parts": [],
            },
        }

    def test_parse_message_extracts_fields(self):
        client = self._make_client()
        raw = self._make_raw_message()
        result = client._parse_message(raw)

        assert result is not None
        assert result.id == "msg_abc"
        assert result.thread_id == "thread_abc"
        assert result.subject == "Test Subject"
        assert result.sender == "alice@example.com"
        assert result.sender_name == "Alice"
        assert result.recipient == "me@mycompany.com"
        assert "Hello" in result.body
        assert result.is_read is False  # UNREAD label present

    def test_parse_message_handles_simple_sender(self):
        client = self._make_client()
        raw = self._make_raw_message()
        raw["payload"]["headers"][0] = {"name": "From", "value": "alice@example.com"}
        result = client._parse_message(raw)
        assert result.sender == "alice@example.com"
        assert result.sender_name is None

    def test_parse_message_bad_date_uses_fallback(self):
        client = self._make_client()
        raw = self._make_raw_message()
        raw["payload"]["headers"][3] = {"name": "Date", "value": "not-a-date"}
        result = client._parse_message(raw)
        assert result is not None
        assert isinstance(result.date, datetime)

    def test_extract_attachments_empty(self):
        client = self._make_client()
        payload = {"parts": []}
        attachments = client._extract_attachments(payload)
        assert attachments == []

    def test_extract_attachments_with_file(self):
        client = self._make_client()
        payload = {
            "parts": [
                {
                    "filename": "resume.pdf",
                    "mimeType": "application/pdf",
                    "body": {"size": 12345, "attachmentId": "att_001"},
                    "parts": [],
                }
            ]
        }
        attachments = client._extract_attachments(payload)
        assert len(attachments) == 1
        assert attachments[0]["filename"] == "resume.pdf"


class TestMemoryStore:
    """Tests for ChromaDB MemoryStore operations."""

    @pytest.fixture
    def store(self, tmp_path):
        from app.memory.store import MemoryStore
        return MemoryStore(persist_dir=str(tmp_path / "chroma"))

    def test_store_and_retrieve_email_thread(self, store):
        store.store_email_thread(
            thread_id="thread_001",
            subject="Partnership discussion",
            participants=["alice@example.com", "me@company.com"],
            messages_summary="We discussed a potential partnership...",
        )
        results = store.retrieve_similar_threads("partnership opportunity", n_results=1)
        assert len(results) > 0
        assert "partnership" in results[0]["document"].lower()

    def test_store_and_retrieve_approved_draft(self, store):
        store.store_approved_draft(
            draft_id="draft_001",
            email_category="Partnership",
            original_subject="Partnership Inquiry",
            approved_body="Thank you for your interest in partnering with us...",
        )
        results = store.retrieve_similar_responses("partnership inquiry", n_results=1)
        assert len(results) > 0

    def test_retrieve_empty_store_returns_empty(self, store):
        results = store.retrieve_similar_threads("something completely random xyz", n_results=3)
        assert isinstance(results, list)

    def test_store_and_get_writing_style(self, store):
        store.store_writing_style(
            user_email="me@company.com",
            style_notes="Professional, concise, friendly. Use bullet points for lists.",
        )
        result = store.get_writing_style("me@company.com")
        assert "concise" in result

    def test_get_writing_style_missing_returns_empty(self, store):
        result = store.get_writing_style("nobody@nowhere.com")
        assert result == ""

    def test_store_knowledge(self, store):
        store.store_knowledge(
            key="company_info",
            content="Our company is TechCorp, founded in 2015, offering AI solutions.",
        )
        results = store.retrieve_knowledge("company background", n_results=1)
        assert len(results) > 0

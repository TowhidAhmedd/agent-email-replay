"""Gmail OAuth flow and Gmail API wrapper."""

from __future__ import annotations

import base64
import email as email_lib
import os
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Dict, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.models.schemas import EmailMessage
from app.utils.logging import get_logger

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]


def build_oauth_flow(client_id: str, client_secret: str, redirect_uri: str) -> Flow:
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    return flow


def credentials_from_tokens(
    access_token: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
    token_expiry: Optional[datetime] = None,
) -> Credentials:
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    if token_expiry:
        creds.expiry = token_expiry
    return creds


class GmailClient:
    """Thin wrapper around the Gmail REST API."""

    def __init__(self, credentials: Credentials):
        self._creds = credentials
        self._service = None

    def _get_service(self):
        if self._service is None:
            if self._creds.expired and self._creds.refresh_token:
                self._creds.refresh(Request())
            self._service = build("gmail", "v1", credentials=self._creds, cache_discovery=False)
        return self._service

    def get_user_email(self) -> str:
        svc = self._get_service()
        profile = svc.users().getProfile(userId="me").execute()
        return profile.get("emailAddress", "")

    def list_unread_messages(self, max_results: int = 10) -> List[Dict[str, Any]]:
        svc = self._get_service()
        result = svc.users().messages().list(
            userId="me",
            q="is:unread -category:promotions -category:social",
            maxResults=max_results,
        ).execute()
        return result.get("messages", [])

    def get_message(self, message_id: str) -> Optional[EmailMessage]:
        svc = self._get_service()
        try:
            msg = svc.users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
            return self._parse_message(msg)
        except HttpError as e:
            logger.error("Failed to get Gmail message", message_id=message_id, error=str(e))
            return None

    def get_thread(self, thread_id: str) -> List[EmailMessage]:
        svc = self._get_service()
        try:
            thread = svc.users().threads().get(
                userId="me", id=thread_id, format="full"
            ).execute()
            messages = []
            for msg in thread.get("messages", []):
                parsed = self._parse_message(msg)
                if parsed:
                    messages.append(parsed)
            return messages
        except HttpError as e:
            logger.error("Failed to get thread", thread_id=thread_id, error=str(e))
            return []

    def mark_as_read(self, message_id: str) -> bool:
        svc = self._get_service()
        try:
            svc.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            return True
        except HttpError as e:
            logger.error("Failed to mark as read", message_id=message_id, error=str(e))
            return False

    def send_reply(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: str,
        in_reply_to: Optional[str] = None,
    ) -> Optional[str]:
        """Send an email and return the new message ID."""
        svc = self._get_service()
        try:
            message = MIMEMultipart("alternative")
            message["to"] = to
            message["subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
            if in_reply_to:
                message["In-Reply-To"] = in_reply_to
                message["References"] = in_reply_to
            message.attach(MIMEText(body, "plain"))

            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            result = svc.users().messages().send(
                userId="me",
                body={"raw": raw, "threadId": thread_id},
            ).execute()
            logger.info("Email sent", message_id=result["id"], thread_id=thread_id)
            return result["id"]
        except HttpError as e:
            logger.error("Failed to send email", error=str(e))
            return None

    # ─── Parsing ───────────────────────────────────────────────────────────────

    def _parse_message(self, msg: Dict[str, Any]) -> Optional[EmailMessage]:
        try:
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "")
            recipient = headers.get("To", "")
            date_str = headers.get("Date", "")

            # Parse date
            try:
                from email.utils import parsedate_to_datetime
                email_date = parsedate_to_datetime(date_str)
                if email_date.tzinfo is not None:
                    email_date = email_date.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                email_date = datetime.utcnow()

            # Extract sender name
            sender_name = None
            if "<" in sender:
                sender_name = sender.split("<")[0].strip().strip('"')
                sender = sender.split("<")[1].rstrip(">")

            body, body_html = self._extract_body(msg["payload"])
            attachments = self._extract_attachments(msg["payload"])

            return EmailMessage(
                id=msg["id"],
                thread_id=msg["threadId"],
                subject=subject,
                sender=sender,
                sender_name=sender_name,
                recipient=recipient,
                body=body,
                body_html=body_html,
                date=email_date,
                labels=msg.get("labelIds", []),
                attachments=attachments,
                is_read="UNREAD" not in msg.get("labelIds", []),
                snippet=msg.get("snippet", ""),
            )
        except Exception as e:
            logger.error("Failed to parse message", error=str(e))
            return None

    def _extract_body(self, payload: Dict[str, Any]) -> tuple[str, Optional[str]]:
        plain_text = ""
        html_text = None

        def walk(part: Dict[str, Any]):
            nonlocal plain_text, html_text
            mime = part.get("mimeType", "")
            if mime == "text/plain" and "data" in part.get("body", {}):
                plain_text = base64.urlsafe_b64decode(
                    part["body"]["data"] + "=="
                ).decode("utf-8", errors="replace")
            elif mime == "text/html" and "data" in part.get("body", {}):
                html_text = base64.urlsafe_b64decode(
                    part["body"]["data"] + "=="
                ).decode("utf-8", errors="replace")
            for sub in part.get("parts", []):
                walk(sub)

        walk(payload)
        return plain_text or "(empty body)", html_text

    def _extract_attachments(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        attachments = []

        def walk(part: Dict[str, Any]):
            filename = part.get("filename", "")
            if filename:
                attachments.append({
                    "filename": filename,
                    "mime_type": part.get("mimeType", ""),
                    "size": part.get("body", {}).get("size", 0),
                    "attachment_id": part.get("body", {}).get("attachmentId", ""),
                })
            for sub in part.get("parts", []):
                walk(sub)

        walk(payload)
        return attachments

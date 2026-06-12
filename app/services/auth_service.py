"""Auth service: OAuth flow management and active-session tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.gmail.client import GmailClient, build_oauth_flow, credentials_from_tokens
from app.database.session import get_db_session
from app.models.orm import UserRecord
from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Simple single-user active session (expand to multi-user with dict keyed by user)
_active_gmail_client: Optional[GmailClient] = None
_active_user_email: Optional[str] = None


def get_auth_url() -> str:
    settings = get_settings()
    flow = build_oauth_flow(
        settings.google_client_id,
        settings.google_client_secret,
        settings.google_redirect_uri,
    )
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url


def handle_oauth_callback(code: str) -> Optional[str]:
    """Exchange auth code for tokens, persist user, return user email."""
    settings = get_settings()
    flow = build_oauth_flow(
        settings.google_client_id,
        settings.google_client_secret,
        settings.google_redirect_uri,
    )
    try:
        flow.fetch_token(code=code)
        creds = flow.credentials

        client = GmailClient(creds)
        user_email = client.get_user_email()

        # Persist / update user record
        with get_db_session() as db:
            user = db.query(UserRecord).filter(UserRecord.email == user_email).first()
            if not user:
                user = UserRecord(email=user_email)
                db.add(user)
            user.google_access_token = creds.token
            user.google_refresh_token = creds.refresh_token
            user.token_expiry = creds.expiry

        _activate_session(user_email, client)
        logger.info("OAuth callback successful", user=user_email)
        return user_email

    except Exception as e:
        logger.error("OAuth callback failed", error=str(e))
        return None


def restore_session_from_db(user_email: str) -> bool:
    """Try to restore a Gmail session from stored tokens."""
    settings = get_settings()
    with get_db_session() as db:
        user = db.query(UserRecord).filter(UserRecord.email == user_email).first()
        if not user or not user.google_access_token:
            return False
        creds = credentials_from_tokens(
            access_token=user.google_access_token,
            refresh_token=user.google_refresh_token or "",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            token_expiry=user.token_expiry,
        )
        client = GmailClient(creds)
        _activate_session(user_email, client)
        logger.info("Session restored from DB", user=user_email)
        return True


def _activate_session(user_email: str, client: GmailClient) -> None:
    global _active_gmail_client, _active_user_email
    _active_gmail_client = client
    _active_user_email = user_email


def get_active_gmail_client() -> Optional[GmailClient]:
    return _active_gmail_client


def get_active_user_email() -> Optional[str]:
    return _active_user_email


def is_authenticated() -> bool:
    return _active_gmail_client is not None


def logout() -> None:
    global _active_gmail_client, _active_user_email
    _active_gmail_client = None
    _active_user_email = None
    logger.info("User logged out")

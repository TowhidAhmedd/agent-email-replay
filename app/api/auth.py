"""Auth endpoints: Google OAuth login, callback, logout."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from app.services.auth_service import (
    get_auth_url, handle_oauth_callback, is_authenticated,
    logout, get_active_user_email,
)
from app.services.dependencies import get_llm, get_memory_store
from app.graph.workflow import EmailAgentGraph
from app.services.email_service import register_graph
from app.config import get_settings
from app.utils.logging import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


@router.get("/login")
def login():
    """Redirect user to Google OAuth consent screen."""
    url = get_auth_url()
    return RedirectResponse(url=url)


@router.get("/callback")
def oauth_callback(code: str):
    """Handle OAuth callback, store tokens, activate session."""
    user_email = handle_oauth_callback(code)
    if not user_email:
        raise HTTPException(status_code=400, detail="OAuth authentication failed")

    # Build and register the graph for this user
    from app.services.auth_service import get_active_gmail_client
    client = get_active_gmail_client()
    graph = EmailAgentGraph(
        llm=get_llm(),
        gmail_client=client,
        memory_store=get_memory_store(),
        user_email=user_email,
    )
    register_graph(user_email, graph)
    logger.info("Graph registered for user", user=user_email)

    settings = get_settings()
    # Redirect to Streamlit dashboard
    return RedirectResponse(url=f"{settings.streamlit_api_base_url.replace(':8000', ':8501')}")


@router.get("/status")
def auth_status():
    """Check if a user is authenticated."""
    return {
        "authenticated": is_authenticated(),
        "user_email": get_active_user_email(),
    }


@router.post("/logout")
def do_logout():
    logout()
    return {"message": "Logged out successfully"}

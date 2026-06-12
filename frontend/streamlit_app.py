"""
Email Reply Agent — Streamlit Dashboard
Provides: Inbox | Draft Queue | Sent Emails | Agent Analytics
"""

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

# ─── Config ────────────────────────────────────────────────────────────────────
API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Email Reply Agent",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Helpers ───────────────────────────────────────────────────────────────────

def api(method: str, path: str, **kwargs) -> Optional[Any]:
    try:
        r = requests.request(method, f"{API_BASE}{path}", timeout=15, **kwargs)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("⚠️ Cannot connect to backend (http://localhost:8000). Is it running?")
        return None
    except requests.exceptions.HTTPError as e:
        st.error(f"API error {e.response.status_code}: {e.response.text[:300]}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None


def priority_badge(p: str) -> str:
    colours = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    return colours.get(p or "medium", "⚪")


def status_badge(s: str) -> str:
    badges = {
        "pending": "🕐 Pending",
        "approved": "✅ Approved",
        "rejected": "❌ Rejected",
        "edited": "✏️ Edited",
        "sent": "📤 Sent",
    }
    return badges.get(s or "pending", s)


def fmt_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %H:%M")
    except Exception:
        return iso[:16]


# ─── Auth Check ────────────────────────────────────────────────────────────────

def check_auth() -> bool:
    status = api("GET", "/auth/status")
    return bool(status and status.get("authenticated"))


# ─── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/color/96/email-open.png", width=64)
    st.title("Email Reply Agent")
    st.markdown("*Human-in-the-Loop AI*")
    st.divider()

    auth = api("GET", "/auth/status") or {}
    is_auth = auth.get("authenticated", False)
    user = auth.get("user_email", "")

    if is_auth:
        st.success(f"✅ {user}")
        if st.button("🚪 Logout", use_container_width=True):
            api("POST", "/auth/logout")
            st.rerun()
        st.divider()
        if st.button("🔄 Poll Inbox Now", use_container_width=True):
            with st.spinner("Polling…"):
                result = api("POST", "/emails/poll")
            if result:
                n = result.get("count", 0)
                st.success(f"Processed {n} new email(s)")
    else:
        st.warning("Not logged in")
        st.markdown(f"[🔐 Login with Google]({API_BASE}/auth/login)")

    st.divider()
    page = st.radio(
        "Navigate",
        ["📬 Inbox", "📝 Draft Queue", "📤 Sent Emails", "📊 Analytics"],
        label_visibility="collapsed",
    )

# ─── Pages ─────────────────────────────────────────────────────────────────────

# ════════════════════════════════════════════════════════
# PAGE 1: INBOX
# ════════════════════════════════════════════════════════
if page == "📬 Inbox":
    st.header("📬 Inbox")

    if not is_auth:
        st.info("Please log in via the sidebar to view your inbox.")
        st.stop()

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        search = st.text_input("🔍 Search emails", placeholder="Subject or sender…")
    with col2:
        unread_only = st.checkbox("Unread only", value=False)
    with col3:
        if st.button("🔄 Refresh"):
            st.rerun()

    with st.spinner("Loading inbox…"):
        emails = api("GET", f"/emails?unread_only={str(unread_only).lower()}&limit=100") or []

    if search:
        q = search.lower()
        emails = [e for e in emails if q in e.get("subject", "").lower() or q in e.get("sender", "").lower()]

    if not emails:
        st.info("No emails found.")
    else:
        st.caption(f"{len(emails)} email(s)")
        for email in emails:
            pri = email.get("priority", "medium")
            cat = email.get("category", "")
            read = email.get("is_read", False)
            icon = "📭" if read else "📬"

            with st.expander(
                f"{icon} {priority_badge(pri)}  **{email.get('subject','(no subject)')}**  "
                f"— {email.get('sender_name') or email.get('sender','')}  "
                f"·  {fmt_date(email.get('email_date'))}  "
                f"{'· `' + cat + '`' if cat else ''}",
                expanded=False,
            ):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(f"**From:** {email.get('sender','')}")
                    st.markdown(f"**Snippet:** {email.get('snippet','')}")
                with col_b:
                    st.markdown(f"**Priority:** {priority_badge(pri)} {pri}")
                    st.markdown(f"**Category:** {cat or '—'}")
                    if email.get("confidence_score"):
                        st.markdown(f"**Confidence:** {email['confidence_score']:.0%}")

                if st.button("⚙️ Process this email", key=f"proc_{email['id']}"):
                    with st.spinner("Running agent pipeline…"):
                        result = api("POST", f"/emails/{email['id']}/process")
                    if result:
                        status = result.get("status", "")
                        draft_id = result.get("draft_id")
                        if status == "waiting_approval" and draft_id:
                            st.success(f"✅ Draft ready! draft_id=`{draft_id}` — check Draft Queue.")
                        elif result.get("errors"):
                            st.error(f"Errors: {result['errors']}")
                        else:
                            st.info(f"Status: {status}")


# ════════════════════════════════════════════════════════
# PAGE 2: DRAFT QUEUE
# ════════════════════════════════════════════════════════
elif page == "📝 Draft Queue":
    st.header("📝 Draft Queue")

    if not is_auth:
        st.info("Please log in to view drafts.")
        st.stop()

    tab_pending, tab_all = st.tabs(["🕐 Pending Approval", "📋 All Drafts"])

    with tab_pending:
        drafts = api("GET", "/drafts?status=pending&limit=100") or []
        if not drafts:
            st.info("No pending drafts. Inbox polling will create new ones automatically.")
        else:
            st.caption(f"{len(drafts)} draft(s) awaiting your decision")
            for draft in drafts:
                risk = draft.get("risk_score", 0.0)
                risk_colour = "🔴" if risk > 0.7 else "🟡" if risk > 0.4 else "🟢"

                with st.expander(
                    f"📝 **{draft.get('subject','(no subject)')}**  "
                    f"· Risk: {risk_colour} {risk:.0%}  "
                    f"· Confidence: {draft.get('confidence_score', 0):.0%}  "
                    f"· {fmt_date(draft.get('generated_at'))}",
                    expanded=True,
                ):
                    # Show safety info
                    flags = draft.get("safety_flags", [])
                    recs = draft.get("safety_recommendations", [])
                    if flags and flags != ["clean"]:
                        st.warning(f"⚠️ Safety flags: {', '.join(flags)}")
                    if recs:
                        with st.expander("💡 Safety recommendations"):
                            for r in recs:
                                st.markdown(f"- {r}")

                    # Fetch original email for context
                    orig = api("GET", f"/emails/{draft['email_id']}") or {}
                    if orig:
                        with st.expander("📨 Original email"):
                            st.markdown(f"**From:** {orig.get('sender','')}")
                            st.markdown(f"**Subject:** {orig.get('subject','')}")
                            st.text_area("Body", orig.get("body", ""), height=120, disabled=True, key=f"orig_{draft['id']}")

                    st.markdown("**Generated reply draft:**")
                    edited = st.text_area(
                        "Edit before sending (optional)",
                        value=draft.get("body", ""),
                        height=200,
                        key=f"edit_{draft['id']}",
                    )

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✅ Approve & Send", key=f"approve_{draft['id']}", type="primary", use_container_width=True):
                            body = edited if edited != draft.get("body", "") else None
                            with st.spinner("Approving and sending…"):
                                result = api(
                                    "POST",
                                    f"/drafts/approve/{draft['id']}",
                                    json={"edited_body": body},
                                )
                            if result:
                                st.success(f"📤 Email sent! {result.get('message','')}")
                                time.sleep(1)
                                st.rerun()

                    with col2:
                        reject_reason = st.text_input("Rejection reason (optional)", key=f"reject_reason_{draft['id']}")
                        if st.button("❌ Reject", key=f"reject_{draft['id']}", use_container_width=True):
                            with st.spinner("Rejecting…"):
                                result = api(
                                    "POST",
                                    f"/drafts/reject/{draft['id']}",
                                    json={"reason": reject_reason or None},
                                )
                            if result:
                                st.info("Draft rejected.")
                                time.sleep(0.5)
                                st.rerun()

    with tab_all:
        status_filter = st.selectbox("Filter by status", ["all", "pending", "approved", "rejected", "sent"])
        q = f"/drafts?limit=200" + (f"&status={status_filter}" if status_filter != "all" else "")
        all_drafts = api("GET", q) or []
        st.caption(f"{len(all_drafts)} draft(s)")
        for d in all_drafts:
            st.markdown(
                f"- {status_badge(d.get('approval_status'))}  "
                f"**{d.get('subject','(no subject)')}**  "
                f"— {fmt_date(d.get('generated_at'))}"
            )


# ════════════════════════════════════════════════════════
# PAGE 3: SENT EMAILS
# ════════════════════════════════════════════════════════
elif page == "📤 Sent Emails":
    st.header("📤 Sent Emails")

    if not is_auth:
        st.info("Please log in.")
        st.stop()

    sent = api("GET", "/sent?limit=100") or []
    if not sent:
        st.info("No emails sent yet.")
    else:
        st.caption(f"{len(sent)} email(s) sent")
        for s in sent:
            with st.expander(
                f"📤 **{s.get('subject','(no subject)')}**  → {s.get('recipient','')}  ·  {fmt_date(s.get('sent_at'))}",
                expanded=False,
            ):
                st.markdown(f"**To:** {s.get('recipient','')}")
                st.markdown(f"**Sent at:** {fmt_date(s.get('sent_at'))}")
                st.markdown(f"**Gmail message ID:** `{s.get('gmail_message_id','—')}`")
                st.text_area("Body sent", s.get("body_sent", ""), height=150, disabled=True, key=f"sent_{s['id']}")


# ════════════════════════════════════════════════════════
# PAGE 4: ANALYTICS
# ════════════════════════════════════════════════════════
elif page == "📊 Analytics":
    st.header("📊 Agent Analytics")

    metrics = api("GET", "/metrics") or {}
    if not metrics:
        st.info("No data yet. Process some emails first.")
        st.stop()

    # KPI row
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📧 Emails Processed", metrics.get("total_emails_processed", 0))
    c2.metric("📝 Drafts Generated", metrics.get("total_drafts_generated", 0))
    c3.metric("✅ Approved", metrics.get("approved_count", 0))
    c4.metric("❌ Rejected", metrics.get("rejected_count", 0))
    c5.metric("📤 Sent", metrics.get("sent_count", 0))

    st.divider()

    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Approval Rates")
        st.metric("Approval Rate", f"{metrics.get('approval_rate', 0):.1f}%")
        st.metric("Rejection Rate", f"{metrics.get('rejection_rate', 0):.1f}%")
        st.metric("Avg Processing Time", f"{metrics.get('avg_processing_time_seconds', 0):.1f}s")

    with col_r:
        st.subheader("Emails by Category")
        by_cat = metrics.get("emails_by_category", {})
        if by_cat:
            import json
            for cat, count in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
                pct = count / max(sum(by_cat.values()), 1) * 100
                st.progress(pct / 100, text=f"{cat}: {count} ({pct:.0f}%)")
        else:
            st.info("No category data yet.")

    st.divider()
    st.subheader("Emails by Priority")
    by_pri = metrics.get("emails_by_priority", {})
    pri_order = ["critical", "high", "medium", "low"]
    cols = st.columns(4)
    for i, pri in enumerate(pri_order):
        cnt = by_pri.get(pri, 0)
        cols[i].metric(f"{priority_badge(pri)} {pri.title()}", cnt)

    st.divider()
    st.caption("Dashboard auto-refreshes every 60 seconds. Use '🔄 Poll Inbox Now' to trigger immediately.")
    if st.button("🔄 Refresh Metrics"):
        st.rerun()

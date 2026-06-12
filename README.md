# 📧 Email Reply Agent

A **production-grade, Human-in-the-Loop (HITL) AI Email Reply Agent** built with LangGraph, FastAPI, Groq LLM, Gmail API, and Streamlit — running entirely on **free-tier services**.

---

## Architecture

```
Gmail Inbox
    │
    ▼
Email Fetch Agent          ← reads unread messages
    │
    ▼
Classification Agent       ← categorises + prioritises via Groq LLM
    │
    ▼
Context Retrieval Agent    ← retrieves similar threads from ChromaDB
    │
    ▼
Draft Reply Agent          ← generates professional reply via Groq LLM
    │
    ▼
Safety Review Agent        ← checks for hallucinations, risky content
    │
    ▼
⏸ Human Approval Node ⏸   ← PAUSES — waits for human decision
    │
    ├─ APPROVED → Send Email Agent → Gmail API → ✅ Sent
    │
    └─ REJECTED → Archive Draft → 🗂 Archived
```

**Critical guarantee:** No email is ever sent without explicit human approval.

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Groq API (llama-3.3-70b-versatile) — Free tier |
| Agent Framework | LangGraph + LangChain |
| Backend | FastAPI + Uvicorn |
| Email | Gmail API + Google OAuth 2.0 |
| Vector Memory | ChromaDB (local, persistent) |
| Database | SQLite + SQLAlchemy |
| Observability | LangSmith Free Tier |
| Scheduler | APScheduler |
| UI | Streamlit |
| Containers | Docker + Docker Compose |

---

## Quick Start

### 1. Prerequisites

- Python 3.12+
- Docker + Docker Compose
- [Groq API key](https://console.groq.com) (free)
- [Google Cloud Project](https://console.cloud.google.com) with Gmail API enabled
- [LangSmith account](https://smith.langchain.com) (free tier)

### 2. Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project → Enable **Gmail API**
3. Go to **Credentials** → Create **OAuth 2.0 Client ID** (Web application)
4. Add `http://localhost:8000/auth/callback` to **Authorized redirect URIs**
5. Copy the **Client ID** and **Client Secret**

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```env
GROQ_API_KEY=gsk_...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
SECRET_KEY=<random 32+ char string>
LANGCHAIN_API_KEY=ls__...   # from smith.langchain.com
```

### 4. Run with Docker

```bash
docker compose up -d
```

Services:
- **API**: http://localhost:8000
- **Dashboard**: http://localhost:8501
- **API Docs**: http://localhost:8000/docs

### 5. Authenticate Gmail

1. Open http://localhost:8000/auth/login
2. Complete Google OAuth flow
3. You'll be redirected to the Streamlit dashboard

---

## Local Development (without Docker)

```bash
# Install dependencies
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start the API
uvicorn app.main:app --reload --port 8000

# Start the UI (separate terminal)
streamlit run frontend/streamlit_app.py --server.port 8501
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check + auth status |
| GET | `/auth/login` | Redirect to Google OAuth |
| GET | `/auth/callback` | OAuth callback handler |
| GET | `/auth/status` | Check authentication status |
| POST | `/auth/logout` | Logout |
| GET | `/emails` | List processed emails |
| GET | `/emails/{id}` | Get email detail |
| POST | `/emails/poll` | Trigger manual inbox poll |
| POST | `/emails/{id}/process` | Run agent pipeline on specific email |
| GET | `/drafts` | List generated drafts |
| GET | `/drafts/{id}` | Get draft detail |
| POST | `/drafts/approve/{id}` | ✅ Approve (and optionally edit) draft |
| POST | `/drafts/reject/{id}` | ❌ Reject draft |
| GET | `/sent` | List sent emails |
| GET | `/metrics` | Agent analytics |

Full interactive docs: http://localhost:8000/docs

---

## Streamlit Dashboard Pages

| Page | Description |
|---|---|
| 📬 Inbox | View emails, trigger processing |
| 📝 Draft Queue | Review drafts, approve/edit/reject |
| 📤 Sent Emails | Audit sent history |
| 📊 Analytics | KPIs, approval rates, category breakdown |

---

## LangSmith Observability

Set in `.env`:
```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=email-reply-agent
```

Then view traces at [smith.langchain.com](https://smith.langchain.com).

---

## Running Tests

```bash
pytest tests/ -v
```

Coverage report generated at `htmlcov/index.html`.

---

## Project Structure

```
email-reply-agent/
├── app/
│   ├── agents/              # 7 LangGraph agent nodes
│   │   ├── email_fetch.py
│   │   ├── classification.py
│   │   ├── context_retrieval.py
│   │   ├── draft_reply.py
│   │   ├── safety_review.py
│   │   ├── human_approval.py
│   │   └── send_email.py
│   ├── graph/
│   │   └── workflow.py      # LangGraph StateGraph + HITL resume logic
│   ├── api/                 # FastAPI routers
│   │   ├── auth.py
│   │   ├── emails.py
│   │   ├── drafts.py
│   │   └── metrics.py
│   ├── services/            # Business logic layer
│   │   ├── auth_service.py
│   │   ├── email_service.py
│   │   └── dependencies.py
│   ├── memory/
│   │   └── store.py         # ChromaDB wrapper
│   ├── database/
│   │   └── session.py       # SQLAlchemy engine + session
│   ├── gmail/
│   │   └── client.py        # Gmail API wrapper + OAuth
│   ├── scheduler/
│   │   └── polling.py       # APScheduler background poller
│   ├── models/
│   │   ├── schemas.py       # Pydantic models
│   │   └── orm.py           # SQLAlchemy ORM
│   ├── utils/
│   │   └── logging.py       # Structured logging
│   ├── config.py            # Settings (pydantic-settings)
│   └── main.py              # FastAPI app factory
├── frontend/
│   └── streamlit_app.py     # Full 4-page dashboard
├── tests/
│   ├── unit/
│   │   ├── test_agents.py
│   │   └── test_gmail_and_memory.py
│   └── integration/
│       └── test_workflow.py
├── data/                    # Runtime data (gitignored)
│   ├── sqlite/
│   └── chroma/
├── logs/                    # Runtime logs (gitignored)
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── pytest.ini
└── README.md
```

---

## Security Notes

- OAuth tokens are stored encrypted in SQLite (never in `.env`)
- No credentials are hardcoded anywhere
- The HITL gate is enforced at the agent level AND the API level
- All API inputs validated via Pydantic v2

---

## Free-Tier Limits

| Service | Free Limit | Usage |
|---|---|---|
| Groq | 6,000 RPM / 500K TPM | ~3 API calls per email |
| Gmail API | 1B quota units/day | ~10 units per email |
| LangSmith | 5K traces/month | 1 trace per workflow run |
| ChromaDB | Unlimited (local) | Local disk |
| SQLite | Unlimited (local) | Local disk |

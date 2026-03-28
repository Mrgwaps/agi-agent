# AGI Agent — Neural Interface

A production-grade AGI-style demo agent with multi-step task orchestration, intelligent model routing via OpenRouter, local Ollama support, Hyperbrowser web tasks, real-time streaming UI, and full cost tracking.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Next.js Frontend (3000)                  │
│  Task Input │ Plan View │ Event Timeline │ Cost Tracker      │
└───────────────────────┬──────────────────────────────────────┘
                        │ HTTP + SSE
┌───────────────────────▼──────────────────────────────────────┐
│                   FastAPI Backend (8000)                     │
│                                                              │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │  Orchestrator│  │ Tool Gateway  │  │  Memory Service  │  │
│  │  (LangGraph) │  │               │  │                  │  │
│  │  ─ Planner   │  │  ─ FileSystem │  │  ─ Redis         │  │
│  │  ─ Executor  │  │  ─ WebSearch  │  │  ─ Postgres      │  │
│  │  ─ Verifier  │  │  ─ Hyperbrow. │  │  ─ ChromaDB      │  │
│  │  ─ Retryer   │  │  ─ CodeExec   │  │                  │  │
│  └──────────────┘  └───────────────┘  └──────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Model Gateway                           │    │
│  │  OpenRouter (free models first) │ Ollama (local)     │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop) (Windows/Mac/Linux)
- [PowerShell 5.1+](https://github.com/PowerShell/PowerShell) (Windows) or bash (Linux/Mac)
- [OpenRouter API Key](https://openrouter.ai/keys) (free tier available)

### Deploy (Windows)

```powershell
# Clone the repo
git clone https://github.com/mrgwaps/agi-agent.git
cd agi-agent

# Deploy (guided setup)
.\deploy.ps1 -Action deploy

# Or with full reset/rebuild
.\deploy.ps1 -Action deploy -ForceRecreate
```

### Deploy (Linux/Mac)

```bash
cp .env.example .env
# Edit .env with your API keys
nano .env

docker compose up -d --build
```

### Access

| Service | URL |
|---|---|
| **Frontend UI** | http://localhost:3000 |
| **Backend API** | http://localhost:8000 |
| **API Docs** | http://localhost:8000/docs |
| **Nginx Proxy** | http://localhost |

---

## Configuration

Copy `.env.example` to `.env` and set:

```env
# Required
OPENROUTER_API_KEY=sk-or-v1-...

# Optional - advanced web tasks
HYPERBROWSER_API_KEY=...

# Optional - local models
OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

### Model Routing

The agent intelligently routes tasks to the right model:

| Task Type | Default Model | Cost |
|---|---|---|
| Planning | `meta-llama/llama-3.3-70b-instruct:free` | FREE |
| Coding | `deepseek/deepseek-r1:free` | FREE |
| Web tasks | `google/gemma-3-27b-it:free` | FREE |
| General | `mistralai/mistral-7b-instruct:free` | FREE |

Set `PREFER_FREE_MODELS=true` (default) to always prefer free models. Configure fallback paid models in `.env` for tasks requiring higher capability.

---

## PowerShell Deployment Options

```powershell
# Full deploy
.\deploy.ps1 -Action deploy -Environment production

# Check status
.\deploy.ps1 -Action status

# View logs
.\deploy.ps1 -Action logs -Services backend -Follow

# Stop all services
.\deploy.ps1 -Action stop

# Restart specific service
.\deploy.ps1 -Action restart -Services backend

# HTTP health check
.\deploy.ps1 -Action health

# Update images
.\deploy.ps1 -Action update

# Clean containers + volumes
.\deploy.ps1 -Action clean

# Full reset (destroys all data)
.\deploy.ps1 -Action reset
```

---

## Demo Scenarios

### 1. Research Synthesis
> "Compare the top 3 vector databases for a production RAG system. Include performance benchmarks and cost."

The agent will: search multiple sources → compare findings → synthesize a structured brief with citations.

### 2. File Intelligence
> "Analyze the contents of /data and generate a structured JSON report of all Python files with their functions."

The agent will: traverse the directory → parse each file → extract structure → emit validated JSON.

### 3. Coding Task
> "Write a Python function to detect anomalies in time-series data, test it with sample data, and fix any bugs."

The agent will: design the solution → write code → execute in sandbox → debug failures → return working code + test output.

---

## Features

- **Cost Tracking** — real-time per-call and cumulative cost display
- **Free Model Priority** — automatically uses free OpenRouter models
- **Ollama Integration** — run fully local with no API costs
- **Hyperbrowser** — full-page scraping, screenshots, structured extraction
- **Human-in-the-Loop** — approval prompts for sensitive actions
- **Failure Recovery** — automatic retry with exponential backoff
- **Full Audit Trail** — every action logged with timestamps and outputs
- **Streaming UI** — live event timeline as the agent works

---

## Development

```bash
# Backend only
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend only
cd frontend
npm install
npm run dev
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph state machine |
| Model Routing | OpenRouter API |
| Local Models | Ollama |
| Web Tasks | Hyperbrowser + BeautifulSoup fallback |
| Backend | FastAPI + Python 3.12 |
| Frontend | Next.js 14 + Tailwind CSS |
| Session Memory | Redis |
| Durable Storage | PostgreSQL |
| Vector Search | ChromaDB |
| Proxy | Nginx |
| Container | Docker Compose |

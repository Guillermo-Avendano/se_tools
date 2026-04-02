# SE ContentEdge — Unified Platform

> **Author:** Guillermo Avendano

Two Docker images that work together to manage documents in ContentEdge (Repository):

| Image | Description |
|---|---|
| **se-ce-tools** | Web UI + Backend + Workers — archiving policy generation, MRC operations, file management |
| **se-agent** | AI Agent — natural-language interface for search, archive, export/import, policy management |

Both images share the **`contentedge/lib`** Python library for all ContentEdge API operations.

## Project Structure

```
se-agent/
├── contentedge/          Shared library (used by both images)
│   └── lib/              ContentEdge API wrappers
├── se_ce_tools/          Image 1: Web UI + Workers
│   ├── backend/          Python FastAPI backend (port 8500)
│   ├── frontend/         Node.js frontend (port 3000)
│   └── worker/           MRC plan execution workers
├── agent/                Image 2: AI Agent (port 8000)
│   └── app/              FastAPI + LangChain + built-in chat UI
├── deploy/               Docker Compose + shared .env
│   ├── docker-compose.yml
│   ├── .env              Shared environment (CE repos, agent config)
│   ├── start.cmd / stop.cmd
│   └── workspace/        Shared volume (conf, workers, exports)
├── build.cmd             Build images
└── tests/                Integration tests
```

## Quick Start

```bash
# 1. Configure environment
cd deploy
copy .env.example .env
# Edit .env with your ContentEdge credentials

# 2. Build images
cd ..
build.cmd              # se-ce-tools only (default)
build.cmd agent        # agent only
build.cmd all          # both images

# 3. Start services
cd deploy
start.cmd              # se-ce-tools + workers only
start.cmd agent        # everything (+ agent + qdrant + redis)

# 4. Stop
stop.cmd
```

## Services

| Service | Port | Profile | Purpose |
|---|---|---|---|
| se-ce-tools | 3000, 8500 | default | Web UI + REST API for archiving policies |
| worker-1..3 | — | default | MRC plan execution (acreate, adelete, vdrdbxml) |
| agent-api | 8000 | agent | AI agent with built-in chat web UI |
| qdrant | 6333 | agent | Vector database (RAG memory) |
| redis | 6379 | agent | Conversation history |

**Agent chat UI:** `http://localhost:8000`
**SE CE Tools UI:** `http://localhost:3000`

## Agent

Uses **Ollama** (local) or **llama.cpp server** (OpenAI-compatible) as LLM,
**Qdrant** for vector memory, **Redis** for conversation history,
**LangChain** as agent framework, and a **skill-based architecture**.

The agent shares the `/workspace` volume with workers, so it can:
- Read worker status (`/workspace/worker-N/status.json`)
- Write plan files (`/workspace/worker-N/plan/`) for workers to execute

## Documentation

| Document | Description |
|---|---|
| [agent/doc/ARCHITECTURE.md](agent/doc/ARCHITECTURE.md) | System architecture |
| [agent/doc/FLOW_CONTENTEDGE.md](agent/doc/FLOW_CONTENTEDGE.md) | ContentEdge skill details |
| [agent/doc/HOW_TOs.md](agent/doc/HOW_TOs.md) | Practical guides |
| [se_ce_tools/README.md](se_ce_tools/README.md) | Web UI documentation |

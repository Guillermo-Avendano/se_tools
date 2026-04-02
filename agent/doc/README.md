# SE-Content-Agent — AI-Powered Intelligent Assistant

> **Author:** Guillermo Avendano

AI agent that manages documents in ContentEdge: search, archive, delete,
export/import content classes, manage archiving policies, and more.
Uses **Ollama** (local) or **llama.cpp server** (OpenAI-compatible) as LLM,
**Qdrant** for vector memory, **Redis** for conversation history,
**LangChain** as agent framework, and a **skill-based architecture**
for modular tool management.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ AnythingLLM  │────▶│  LangChain   │────▶│ Ollama or    │
│   (chat UI)  │     │  ReAct Agent │     │ llama.cpp    │
└──────┬───────┘     └──────┬───────┘     └──────────────┘
       │                    │
       │         ┌──────────┼──────────┐
       │         │          │          │
  ┌────▼─────┐ ┌─▼────────┐ ┌────▼──────────┐
  │  Redis   │ │  Qdrant  │ │ ContentEdge   │
  │  (chat)  │ │(memory)  │ │ (direct lib)  │
  └──────────┘ └──────────┘ └───────────────┘
```

## Tech Stack

| Component | Technology |
|---|---|
| LLM | Ollama (local) or llama.cpp (OpenAI-compatible via ChatOpenAI) |
| Embeddings | nomic-embed-text (768d) |
| Agent Framework | LangChain + LangGraph |
| Vector Store | Qdrant |
| Chat History | Redis |
| API | FastAPI |
| Content Management | ContentEdge (direct in-process lib) |
| Chat UI | AnythingLLM |
| Containers | Docker Compose |

## Requirements

- Docker and Docker Compose
- Ollama or llama.cpp server available on host/network
- 8 GB+ RAM (for Ollama)
- NVIDIA GPU optional

## Quick Start

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 2. Start services

```bash
docker compose up -d --build
```

This starts: Qdrant, Redis, the Agent API, and AnythingLLM.

### 3. Ask questions

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Search documents for customer 1000"}'
```

### 4. Use session-based conversation

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Search documents for customer 1000", "session_id": "my-session"}'
```

Subsequent calls with the same `session_id` include conversation history from Redis.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check for all services (Qdrant, Ollama, Redis) |
| POST | `/ask` | Send a question to the agent |
| DELETE | `/chat/{session_id}` | Clear conversation history for a session |
| GET | `/skills` | List registered skills and their tools |
| GET | `/v1/models` | List models (returns agent name) |
| POST | `/v1/chat/completions` | Chat completions (AnythingLLM, supports streaming) |

## Agent Capabilities (ContentEdge Skill — 23 Tools)

1. **Document Search** — Search by index constraints (EQ, LK, BT, etc.)
2. **Document Viewer** — Get viewer URLs for documents
3. **Document Archiving** — Archive files with metadata or using policies
4. **Archiving Policy Management** — Full CRUD: search, create, get, modify, delete, export
5. **Policy Generation** — Generate policies from field specifications, preview, then register
6. **Document Deletion** — Delete single, multiple, by search, or by version range
7. **Version Management** — List and manage content class versions
8. **Export/Import** — Export content classes, indexes, groups, policies; import to target repo
9. **Repository Info** — Show source/target repository configuration
10. **Multi-language** — Responds in whatever language the user writes in

> **Note**: `contentedge_smart_chat` (AI Q&A over documents) exists but is currently disabled.

## Skills Architecture

The agent uses a **skill-based architecture** where each capability is a self-contained
module with its own tools, prompt file (`workspace/prompts/<name>.md`), and routing hints.

Currently **only ContentEdgeSkill is registered**:

| Skill | Status | Tools | Prompt |
|---|---|---|---|
| ContentEdge | **Registered** | 23 tools (search, archive, delete, export, import, policies...) | `contentedge.md` (+ `_ollama.md`, optional `_llama_cpp.md`) |
| Memory | Defined | `save_learning`, `recall_learnings` | `memory.md` |

## Documentation

All flow and architecture documentation is in the `doc/` directory:

| Document | Description |
|---|---|
| [ARCHITECTURE.md](doc/ARCHITECTURE.md) | System architecture, services, tools, file structure |
| [FLOW_ASK.md](doc/FLOW_ASK.md) | Question processing flow (entry points → response) |
| [FLOW_MEMORY.md](doc/FLOW_MEMORY.md) | Dual memory system: Redis (chat) + Qdrant (RAG) |
| [FLOW_STARTUP.md](doc/FLOW_STARTUP.md) | Application startup sequence |
| [FLOW_CONTENTEDGE.md](doc/FLOW_CONTENTEDGE.md) | ContentEdge skill: search, archive, policies, export/import |
| [HOW_TOs.md](doc/HOW_TOs.md) | Practical guides for common tasks |

## Schema Customization

Create JSON files in `schema_descriptions/`:

```json
{
  "tables": [{
    "name": "my_table",
    "description": "Detailed table description.",
    "columns": [
      { "name": "col1", "type": "varchar(100)", "description": "Column purpose." }
    ]
  }]
}
```

## Security

- **Rate limiting**: 30 requests/minute per IP
- **CORS**: Configurable allowed origins
- **Input validation**: Pydantic models with length constraints
- **Path traversal**: Sanitized file paths for archiving operations
- **ContentEdge auth**: Base64 credentials managed in ContentConfig

## Tests

```bash
# Inside the container
docker compose exec agent-api pytest tests/ -v

# Or locally with virtualenv
pip install -r requirements.txt
pytest tests/ -v
```

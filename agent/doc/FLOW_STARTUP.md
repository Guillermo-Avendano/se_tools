# FLOW_STARTUP — Application Startup

## Overview

Describes the complete flow from `docker compose up` to the API
being ready to receive requests.

---

## 1. Container Startup Order

```
qdrant  ───────────┐
redis  ────────────┼─▸ agent-api ──▸ anythingllm
```

Each service declares a **healthcheck** in `docker-compose.yml`.
Dependent containers wait for `condition: service_healthy`.

| Service | Port | Healthcheck | Purpose |
|---|---|---|---|
| `qdrant` | 6333 | TCP port check | Vector database |
| `redis` | 6379 | `redis-cli ping` | Conversation history |
| `agent-api` | 8000 | `curl /health` | Agent API (FastAPI) |
| `anythingllm` | 3001 | — | Chat UI |

The LLM (Ollama or llama.cpp) is **external** to Docker Compose.
It must be running independently before the agent can process questions.

---

## 2. Agent API Initialization (FastAPI)

### 2.1 Configuration Loading

```
config.py → class Settings(BaseSettings)
   ├─ Reads .env (or environment variables)
      │    QDRANT_*, OLLAMA_*, LLM_PROVIDER, LLAMA_CPP_*,
   │    CONTENTEDGE_*, REDIS_*, ...
   └─ LLM_PROVIDER selects the model backend:
        "ollama"     → ChatOllama (local)
      "llama_cpp"  → ChatOpenAI (OpenAI-compatible llama.cpp server)
```

### 2.2 FastAPI App Creation

```
main.py
   ├─ 1. Configure structlog (structured logging)
   │      DEBUG → ConsoleRenderer, otherwise JSONRenderer
   ├─ 2. Create rate limiter (30 req/min per IP)
   ├─ 3. Instantiate FastAPI with lifespan()
   ├─ 4. Register CORS middleware (allowed_origins from config)
   └─ 5. Register routers:
          ├─ routes.py        → /health, /ask, /chat/{id}, /skills
          └─ openai_compat.py → /v1/models, /v1/chat/completions
```

### 2.3 Lifespan — Startup

```
lifespan(app)
   │
   ├─▸ load_files_for_memory()            ← memory/file_loader.py
   │      ├─ Loads .doc_fingerprints.json (MD5 per file from last run)
   │      ├─ Scans /app/workspace/knowledge/ root for .pdf, .txt, .md
   │      ├─ Computes MD5 for each file → compares with stored hash
   │      ├─ If no files changed → skips (0 work)
   │      ├─ For changed files only:
   │      │    ├─ Deletes old chunks (filter: type=document, source=filename)
   │      │    ├─ Read content → split into chunks → upsert to Qdrant
   │      └─ Saves new .fingerprints.json → Returns: NEW chunks indexed
   │
   ├─▸ load_knowledge_for_memory()        ← memory/file_loader.py
   │      ├─ Same fingerprint logic for workspace/knowledge/
   │      ├─ Subdirs: corrections/, procedures/, preferences/
   │      ├─ Each .md file → chunks with type="knowledge", category=<subdir>
   │      └─ Enables recall from MemorySkill.recall_learnings()
   │
   ├─▸ ──── yield ──── (app serves traffic)
   │
   └─▸ Shutdown: logs shutdown message
```

---

## 3. Skill Registration

During the first call to `ask_agent()`, the `SkillRegistry` is already
initialized (at module level in `core.py`):

```
_registry = SkillRegistry()
_registry.register(ContentEdgeSkill())
```

Currently only one skill is registered:

| Skill | Tools | Status |
|---|---|---|
| ContentEdgeSkill | 23 tools | **Registered** |

One other skill class exists but is **not registered**:

| Skill | File |
|---|---|
| MemorySkill | `app/skills/memory_skill.py` |

Each skill loads its prompt from `workspace/prompts/<name>.md`.
Provider-specific variants are auto-resolved by `_load_prompt_file()`:
- `LLM_PROVIDER=ollama` → `contentedge_ollama.md`
- `LLM_PROVIDER=llama_cpp` → `contentedge_llama_cpp.md` (or fallback to base)
- Fallback: `contentedge.md` (base)

Each skill exposes tools via `get_tools()` + routing hints via `get_routing_hint()`.

---

## 4. Complete Timeline

```
t=0   docker compose up
      │
t=1   qdrant: starts → healthcheck OK
      redis: starts → healthcheck OK
      │
t=2   agent-api: starts
      ├─ Read config from .env
      ├─ Register routers + middleware
      ├─ lifespan startup:
      │    ├─ load_files_for_memory()      (fingerprinted, skips unchanged)
      │    └─ load_knowledge_for_memory()  (fingerprinted)
      │         ├─ Connect to Qdrant
      │         ├─ Ensure collection "schema_memory" exists
      │         └─ Index changed docs/knowledge only
      ├─ healthcheck: GET /health → 200 OK
      └─ Listening on 0.0.0.0:8000
      │
t=3   anythingllm: starts
      ├─ Configured with LLM_PROVIDER=generic-openai
      ├─ Points to http://agent-api:8000/v1
      └─ Listening on 0.0.0.0:3001
      │
      ═══════════════════════════════
       System ready for questions
      ═══════════════════════════════
```

---

## 5. Files Involved

| File | Role |
|---|---|
| `docker-compose.yml` | Service orchestration and dependencies |
| `app/main.py` | Entry point, lifespan, middleware |
| `app/config.py` | Configuration from `.env` |
| `app/memory/file_loader.py` | Indexes docs + knowledge (fingerprinted) |
| `app/memory/qdrant_store.py` | Qdrant client, embeddings, upsert |
| `app/memory/chat_history.py` | Redis conversation history |
| `app/skills/*.py` | Skill classes (1 registered, 1 available) |

# Architecture — SE-Content-Agent (Skill-Based)

## Overview

The agent uses a **skill-based architecture** where each capability is packaged
as a self-contained skill with its own tools, prompt fragment, and lifecycle hooks.

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────┐      ┌─────────────────┐
│ AnythingLLM  │─────▸│  FastAPI API  │─────▸│   ReAct Agent   │─────▸│  LLM Provider   │
│  (chat UI)   │◂─────│   (Gateway)   │◂─────│  (LangGraph)    │◂─────│                 │
└─────────────┘      └──────────────┘      └────────┬────────┘      │ Ollama (local)  │
                                                     │               │   — or —         │
                                              SkillRegistry          │ llama.cpp server  │
                                                     │               └─────────────────┘
                                                     ▼
                                              ┌──────────┐
                                              │Content   │
                                              │ Edge     │
                                              │ Skill    │
                                              └───┬──────┘
                                                  │
                                                  ▼
                                           ┌──────────────┐
                                           │ContentEdge   │
                                           │  (lib)       │
                                           └──────┬───────┘
                                                  │
                                    ┌─────────────┼─────────────┐
                                    ▼             ▼             ▼
                              ┌──────────┐ ┌──────────┐ ┌────────┐
                              │  Mobius   │ │  Redis   │ │Qdrant  │
                              │  (REST)   │ │ (chat)   │ │(memory)│
                              └──────────┘ └──────────┘ └────────┘
```

---

## 1. Services

| Service | Port | Purpose |
|---|---|---|
| **qdrant** | 6333 | Vector database for RAG |
| **redis** | 6379 | Conversation history (short-term memory) |
| **agent-api** | 8000 | FastAPI — the agent's brain (includes ContentEdge skill) |
| **anythingllm** | 3001 | Chat web UI |

The LLM is **external** to Docker — either Ollama running on the host
(via `OLLAMA_BASE_URL`) or llama.cpp server (via `LLAMA_CPP_BASE_URL`).
Selected at runtime by `LLM_PROVIDER` env var.

### Startup Order

```
qdrant ──┐
redis  ──┼─▸ agent-api ──▸ anythingllm
```

---

## 2. Question Flow (Request → Response)

Two equivalent entry points:

| Via | Endpoint | Consumer |
|---|---|---|
| Direct API | `POST /ask` | Any HTTP client |
| OpenAI-compatible | `POST /v1/chat/completions` | AnythingLLM |

Both call **`ask_agent()`**.

### Full Step-by-Step Diagram

```
User / AnythingLLM
        │
        ▼
┌─ FastAPI ──────────────────────────────────────────────────────────────┐
│                                                                        │
│  routes.py ─ POST /ask              openai_compat.py ─ POST /v1/...   │
│       │                                   │                            │
│       └──────────── both call ────────────┘                            │
│                         │                                              │
│                         ▼                                              │
│               ask_agent(question, chat_history)                        │
│                    │          core.py                                   │
│                    │                                                   │
│  ┌─────────────────┼─────────────────────────────────────────────┐    │
│  │  STEP 1: _retrieve_document_context(question)                 │    │
│  │  → Searches Qdrant for type="document" chunks (score >= 0.55) │    │
│  │  → Returns ContentEdge and self-knowledge context             │    │
│  │                                                               │    │
│  │  STEP 2: registry.setup_all(context)                          │    │
│  │  → Pre-loads content classes + indexes from Mobius             │    │
│  │  → Caches metadata at module level for reuse                  │    │
│  │                                                               │    │
│  │  STEP 3: Build the SYSTEM_PROMPT dynamically                  │    │
│  │  → registry.build_prompt_section() generates skill prompts    │    │
│  │  → build_system_prompt() injects skills + document_context    │    │
│  │  → registry.build_routing_rules() adds routing hints          │    │
│  │                                                               │    │
│  │  STEP 4: Build message list                                   │    │
│  │  [SystemMessage, ...chat_history (last 6, 2000ch max),        │    │
│  │   HumanMessage]                                               │    │
│  │                                                               │    │
│  │  STEP 5: create_react_agent(llm, registry.get_all_tools())   │    │
│  │  → LLM = _get_llm() → ChatOllama or ChatOpenAI (llama.cpp)   │    │
│  │  → Provider selected by LLM_PROVIDER env var                  │    │
│  │  → Tools collected from all enabled skills (23 tools)         │    │
│  │                                                               │    │
│  │  STEP 6: agent.ainvoke(messages) — ReAct LOOP                │    │
│  │  → recursion_limit = 25                                       │    │
│  │                                                               │    │
│  │  STEP 7: Extract answer                                       │    │
│  │  - answer (last AIMessage with content and no tool_calls)     │    │
│  │                                                               │    │
│  │  STEP 8: registry.teardown_all() — cleanup skill state        │    │
│  └───────────────────────────────────────────────────────────────┘    │
│                         │                                              │
│                         ▼                                              │
│              { answer }                                                │
└─────────────────────────┼──────────────────────────────────────────────┘
                          ▼
                  Response to client
```

---

## 3. The ReAct Loop

The agent uses the **ReAct** pattern (Reasoning + Acting) from LangGraph:

```
                    ┌───────────────┐
                    │  LLM thinks   │
                    │  (Ollama or   │
                    │  llama.cpp)   │
                    └───────┬───────┘
                            │
                   Does it need a tool?
                      │             │
                     YES            NO
                      │             │
                      ▼             ▼
              ┌──────────────┐   Final answer
              │ Call tool    │
              └──────┬───────┘
                     │
                     ▼
              Tool returns result
                     │
                     ▼
              ┌──────────────┐
              │ LLM analyzes │
              │ the result   │
              └──────┬───────┘
                     │
            Need another tool?
               │          │
              YES         NO
               │          │
               └──(loop)  ▼
                       Final answer
```

### Decisions by Question Type

| Question Type | Tool(s) Called | Typical Iterations |
|---|---|---|
| ContentEdge docs search | `contentedge_search` → `contentedge_get_document_url` | 2–3 |
| Archive documents | `contentedge_archive_documents` or `contentedge_archive_using_policy` | 2 |
| Policy management | `contentedge_search_archiving_policies` → CRUD tools | 2–4 |
| Policy generation | `contentedge_generate_archiving_policy` → `contentedge_register_archiving_policy` | 3–4 |
| Delete documents | `contentedge_search` → `contentedge_delete_*` | 3–4 |
| Export/Import | `contentedge_repo_info` → `contentedge_export_all` / `contentedge_import_all` | 2–3 |
| About the agent | — (uses document context) | 1 |
| Conversational | — (direct answer) | 1 |

---

## 4. Skills & Tools

The agent's capabilities are organized as **skills**, each registered in the
`SkillRegistry` at startup. Skill classes exist for 6 capabilities, though
currently only ContentEdge is registered.

### Registered Skill: ContentEdge (`app/skills/contentedge_skill.py`)

Calls the ContentEdge Python library (`contentedge/lib`) directly
in-process. See `doc/FLOW_CONTENTEDGE.md` for detailed flows.

#### Search & Query (2 tools)

| Tool | Description |
|---|---|
| `contentedge_search` | Search documents by index values |
| `contentedge_get_document_url` | Get viewer URL for a document |

#### Document Archiving (2 tools)

| Tool | Description |
|---|---|
| `contentedge_archive_documents` | Archive files (PDF, TXT, JPG, PNG) with metadata |
| `contentedge_archive_using_policy` | Archive using a policy (text parsing) |

#### Archiving Policy Tools (8 tools)

| Tool | Description |
|---|---|
| `contentedge_search_archiving_policies` | Search/list archiving policies |
| `contentedge_create_archiving_policy` | Create a new archiving policy |
| `contentedge_get_archiving_policy` | Get full policy details |
| `contentedge_modify_archiving_policy` | Update an existing policy (full replace) |
| `contentedge_export_archiving_policy` | Export policy to JSON file |
| `contentedge_delete_archiving_policy` | Permanently delete an archiving policy |
| `contentedge_generate_archiving_policy` | Generate + preview policy from field spec (does NOT register) |
| `contentedge_register_archiving_policy` | Register a previously generated policy in Mobius |

#### Navigation & Listing (2 tools)

| Tool | Description |
|---|---|
| `contentedge_list_content_class_versions` | List versions under a content class (with date filtering) |
| `contentedge_repo_info` | Show source/target repository info |

Note: Content classes and indexes are **pre-loaded during skill setup** and
injected into the system prompt — no tools needed for listing them.

#### Document Deletion (4 tools)

| Tool | Description |
|---|---|
| `contentedge_delete_document` | Delete a single document by ID |
| `contentedge_delete_documents_by_ids` | Delete multiple documents by IDs |
| `contentedge_delete_content_class_versions` | Delete versions (with optional date range) |
| `contentedge_delete_search_results` | Search and delete matching documents |

#### Export / Import (5 tools)

| Tool | Description |
|---|---|
| `contentedge_export_content_classes` | Export content classes to JSON |
| `contentedge_export_indexes` | Export indexes to JSON |
| `contentedge_export_index_groups` | Export index groups to JSON |
| `contentedge_export_all` | Export everything (CCs, indexes, groups, policies) |
| `contentedge_import_all` | Import from export directory to TARGET repository |

**Total: 23 enabled tools** (+ `contentedge_smart_chat` disabled, kept for future use)

### Other Skill (Defined but Not Registered)

| Skill | File | Tools |
|---|---|---|
| MemorySkill | `app/skills/memory_skill.py` | `save_learning`, `recall_learnings` |

### API Introspection

`GET /skills` returns the list of all registered skills, their status, and tools.

---

## 5. ContentEdge Integration (Direct Skill — 23 Tools)

ContentEdge is integrated as a **direct skill** — the agent calls the Python
library (`contentedge/lib`) in-process with no network overhead.
Provides search, archiving (direct and policy-based), policy CRUD +
generation + registration, document/version deletion, export/import,
and repository info.

```
┌──────────────────┐                  ┌─────────────────────┐
│   agent-api      │  direct Python   │ contentedge/lib     │
│                  │  ──────────────▸  │                     │
│  ContentEdge     │  function calls   │  content_search     │
│  Skill (23 tools)│                  │  content_smart_chat │
│                  │                  │  content_document   │
│                  │                  │  content_archive    │
│                  │                  │  content_navigator  │
└──────────────────┘                  └──────────┬──────────┘
                                                 │
                                                 ▼ HTTPS
                                      ┌─────────────────────┐
                                      │ Content Repository   │
                                      │ (Mobius REST API)    │
                                      └─────────────────────┘
```

Blocking I/O calls (requests to the Mobius REST API) are offloaded to
a thread pool via `asyncio.run_in_executor()` so the event loop stays
responsive.

---

## 6. Memory (Qdrant + Redis)

### Short-term: Redis

Conversation history is stored in **Redis** with per-session keys.

| Setting | Default | Purpose |
|---|---|---|
| `redis_url` | `redis://redis:6379/0` | Redis connection |
| `redis_chat_ttl` | `3600` | Session TTL (seconds) |
| `redis_max_turns` | `20` | Max turns retained per session |

Key format: `chat:{session_id}` → list of `{role, content}` messages.

### Long-term: Qdrant

```
                    ┌──────────────────────────────────┐
                    │     Collection: schema_memory     │
                    │                                    │
                    │  ┌──────────────────────────────┐ │
                    │  │ Type: table_schema            │ │
                    │  │ Source: schema_descriptions/  │ │
                    │  │ Loaded on demand              │ │
                    │  └──────────────────────────────┘ │
                    │                                    │
                    │  ┌──────────────────────────────┐ │
                    │  │ Type: document                │ │
                    │  │ Source: workspace/knowledge/   │ │
                    │  │ Loaded at application startup  │ │
                    │  └──────────────────────────────┘ │
                    │                                    │
                    │  ┌──────────────────────────────┐ │
                    │  │ Type: knowledge               │ │
                    │  │ Source: workspace/knowledge/  │ │
                    │  │ Loaded at startup + live       │ │
                    │  │ Categories: correction,        │ │
                    │  │   procedure, preference        │ │
                    │  └──────────────────────────────┘ │
                    └──────────────────────────────────┘
```

---

## 7. API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Checks Qdrant, Ollama, and Redis connectivity |
| `POST` | `/ask` | Sends a question to the agent |
| `DELETE` | `/chat/{session_id}` | Clears conversation history for a session |
| `GET` | `/skills` | Lists registered skills and their tools |
| `GET` | `/v1/models` | Lists models (returns agent name) |
| `POST` | `/v1/chat/completions` | Chat completions — used by AnythingLLM (supports streaming) |

---

## 8. Security

```
API:
  ✓ Rate limiting (30 req/min per IP)
  ✓ CORS configured with allowed origins
  ✓ Input validation (Pydantic models with length constraints)

ContentEdge:
  ✓ Repository health check before every tool call
  ✓ Direct in-process calls (no network exposure)
  ✓ Base64 auth credentials managed in ContentConfig
  ✓ Path traversal guard on file archiving
```

---

## 9. File Structure

```
agent/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env / .env.example
│
├── doc/                         # All documentation
├── schema_descriptions/         # JSON files with table descriptions
│
├── workspace/                   # Agent workspace (bind-mounted)
│   ├── conf/                    # Repository YAML configurations
│   │   ├── repository_source.yaml
│   │   └── repository_target.yaml
│   ├── prompts/                 # Skill prompt .md files (per skill + per LLM provider)
│   │   ├── contentedge.md       # Base prompt (fallback)
│   │   ├── contentedge_ollama.md    # Ollama-specific prompt
│   │   └── contentedge_llama_cpp.md # llama.cpp-specific prompt
│   ├── tmp/                     # Transient files for inter-skill exchange
│   ├── exports/                 # Export output directory
│   └── knowledge/               # Documents + agent learnings
│       ├── *.md, *.pdf, *.txt   # Knowledge files (indexed as type=document)
│       ├── corrections/         # User corrections
│       ├── procedures/          # Learned workflows
│       └── preferences/         # User preferences
│
├── app/
│   ├── main.py                  # FastAPI entry point + lifespan
│   ├── config.py                # Settings from .env (Pydantic)
│   ├── api/
│   │   ├── routes.py            # /health, /ask, /chat/{id}, /skills
│   │   └── openai_compat.py     # /v1/models, /v1/chat/completions
│   ├── agent/
│   │   ├── core.py              # ask_agent() — orchestrates the full flow
│   │   └── prompts.py           # build_system_prompt() — dynamic from skills
│   ├── skills/                  # Skill-based architecture
│   │   ├── base.py              # SkillBase abstract class, _load_prompt_file()
│   │   ├── registry.py          # SkillRegistry — aggregates skills
│   │   ├── contentedge_skill.py # ContentEdge skill (23 tools, direct lib calls)
│   │   └── memory_skill.py      # Memory skill (not registered)
│   ├── memory/
│   │   ├── qdrant_store.py      # Qdrant client, embed, upsert, search
│   │   ├── file_loader.py       # Loads docs + knowledge → Qdrant (fingerprinted)
│   │   ├── schema_loader.py     # Loads JSON schemas into Qdrant (on demand)
│   │   └── chat_history.py      # Redis-backed conversation history
│   └── models/
│       └── schemas.py           # Pydantic models (request/response)
│
├── contentedge/                  # ContentEdge Python library (direct skill)
│   ├── lib/
│   │   ├── content_config.py     # Configuration and authentication
│   │   ├── content_search.py     # Document search by indexes
│   │   ├── content_smart_chat.py # Smart Chat AI conversations
│   │   ├── content_archive_metadata.py  # Archive with metadata
│   │   ├── content_document.py   # Document viewer URL (Hostviewer)
│   │   └── content_class_navigator.py   # Class navigation and versions
│   ├── conf/                     # Repository YAML configuration
│   ├── files/                    # Working directory for archiving
│   └── old/                      # Legacy scripts
│
├── anythingllm/                  # AnythingLLM configuration
│   └── plugins/                  # MCP server plugins
│
└── tests/                        # Pytest test suite
    ├── test_contentedge_*.py     # ContentEdge tool tests (27+ files)
    ├── test_charts.py
    ├── test_generate_policy.py
    └── test_safety.py
```

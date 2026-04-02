# FLOW_MEMORY — Memory and RAG

## Overview

Describes the dual memory system: **Redis** for short-term conversation
history and **Qdrant** for long-term vector memory (documents, schemas,
and knowledge). Explains how context is retrieved for each question.

---

## 1. Memory Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MEMORY SYSTEM                                │
│                                                                     │
│  ┌──────────────────────────┐   ┌────────────────────────────────┐ │
│  │  SHORT-TERM: Redis       │   │  LONG-TERM: Qdrant             │ │
│  │                          │   │                                 │ │
│  │  Key: chat:{session_id}  │   │  Collection: schema_memory     │ │
│  │  TTL: 3600 seconds       │   │                                 │ │
│  │  Max: 20 turns (40 msgs) │   │  ┌─────────────────────────┐  │ │
│  │                          │   │  │ Type: table_schema       │  │ │
│  │  Stores conversation     │   │  │ Source: schema_desc/     │  │ │
│  │  history per session     │   │  │ Loaded on demand         │  │ │
│  └──────────────────────────┘   │  └─────────────────────────┘  │ │
│                                  │                                 │ │
│                                  │  ┌─────────────────────────┐  │ │
│                                  │  │ Type: document           │  │ │
│                                  │  │ Source: knowledge/       │  │ │
│                                  │  │ Loaded at startup        │  │ │
│                                  │  │ Content: PDFs, TXT, MD   │  │ │
│                                  │  └─────────────────────────┘  │ │
│                                  │                                 │ │
│                                  │  ┌─────────────────────────┐  │ │
│                                  │  │ Type: knowledge          │  │ │
│                                  │  │ Source: knowledge/       │  │ │
│                                  │  │ Loaded at startup + live │  │ │
│                                  │  │ Categories: correction,  │  │ │
│                                  │  │   procedure, preference  │  │ │
│                                  │  └─────────────────────────┘  │ │
│                                  └────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘

Each Qdrant point:
├─ UUID (identifier)
├─ Vector (768 dimensions)
└─ Payload:
     ├─ text (chunk content)
     ├─ source (file / table name)
     ├─ type ("table_schema" | "document" | "knowledge")
     └─ category (for knowledge: "correction", "procedure", "preference")
```

---

## 2. Redis — Conversation History

### Storage

```
chat_history.py
   │
   ├─ get_history(session_id, max_turns)
   │    Key: chat:{session_id}
   │    Returns: list of {role, content} dicts
   │    Trims to last max_turns * 2 messages
   │
   ├─ append_messages(session_id, question, answer)
   │    Appends user + assistant messages
   │    Sets TTL on key (redis_chat_ttl seconds)
   │
   ├─ clear_history(session_id)
   │    Deletes the key entirely
   │
   └─ ping_redis()
        Health check for /health endpoint
```

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `REDIS_CHAT_TTL` | `3600` | Session TTL in seconds |
| `REDIS_MAX_TURNS` | `20` | Max turns retained (turns × 2 = messages) |

### Usage in Request Flow

```
POST /ask (with session_id)
   ├─ chat_history = get_history(session_id)   ← load from Redis
   ├─ result = ask_agent(question, chat_history)
   └─ append_messages(session_id, question, answer)  ← persist

POST /v1/chat/completions (with X-Session-ID header)
   ├─ Same Redis flow if header present
   └─ Falls back to inline message history otherwise

DELETE /chat/{session_id}
   └─ clear_history(session_id)  ← wipe session
```

---

## 3. Document Indexing — `load_files_for_memory()`

Runs **automatically at application startup** (in `lifespan()`).
Uses **fingerprinting** (MD5) to skip unchanged files.

```
load_files_for_memory()                   ← memory/file_loader.py
   │
   ├─ Scans /app/workspace/knowledge/ (root-level files only)
   │    Supported formats: .pdf, .txt, .md
   │
   ├─ Loads .doc_fingerprints.json (MD5 per file from last run)
   ├─ Computes MD5 for each file → compares with stored hash
   ├─ If no files changed → skips (0 work done)
   │
   ├─ For changed files only:
   │    ├─ Deletes old chunks from Qdrant (filter: type=document, source=filename)
   │    ├─ Read by format:
   │    │    .pdf → PdfReader(file).extract_text()
   │    │    .txt → file.read_text()
   │    │    .md  → file.read_text()
   │    ├─ _split_text(text, chunk_size=1000, overlap=200)
   │    ├─ metadatas = [{ source: "file.pdf", type: "document" }]
   │    └─ upsert_texts(client, embeddings, collection, chunks, metadatas)
   │
   ├─ Saves new .fingerprints.json
   └─ Returns: total NEW chunks indexed
```

---

## 4. Knowledge Indexing — `load_knowledge_for_memory()`

Also runs **at application startup** (in `lifespan()`).
Uses the same fingerprinting strategy.

```
load_knowledge_for_memory()               ← memory/file_loader.py
   │
   ├─ Scans /app/workspace/knowledge/ subdirectories:
   │    corrections/   → category = "correction"
   │    procedures/    → category = "procedure"
   │    preferences/   → category = "preference"
   │
   ├─ Each .md file → chunks with metadata:
   │    { type: "knowledge", category: "correction", source: "filename.md" }
   │
   ├─ Fingerprint-based incremental updates
   └─ Enables recall from MemorySkill.recall_learnings()
```

---

## 5. Schema Indexing — `load_all_schemas()`

Runs **on demand** when `POST /schema/load` is called (if that endpoint is enabled).

```
load_all_schemas()                        ← memory/schema_loader.py
   │
   ├─ Scans /app/schema_descriptions/*.json
   │
   ├─ For each JSON file:
   │    ├─ Parse the schema
   │    │    Expected format:
   │    │    { "tables": [{ "name": "...", "description": "...",
   │    │      "columns": [{ "name": "...", "type": "...", "description": "..." }] }] }
   │    │
   │    ├─ _build_description_texts(schema)
   │    │    Generates descriptive text per table:
   │    │    "Table: customers
   │    │     Description: Stores customer information
   │    │     Columns:
   │    │       - id (serial): Primary key
   │    │       - name (varchar(200)): Customer full name"
   │    │
   │    └─ upsert_texts(client, embeddings, collection, texts, metadatas)
   │         metadata = { table: "customers", type: "table_schema" }
   │
   └─ Returns: total chunks indexed
```

---

## 6. Retrieval

### Document Context — `_retrieve_document_context()`

Runs **on every question** within `ask_agent()`.

```
_retrieve_document_context(question, top_k=3)    ← agent/core.py
   │
   ├─ query_vector = embeddings.embed_query(question)
   ├─ query_points with filter: type="document", limit=3
   ├─ Filter by score >= 0.55 (discards low-relevance matches)
   ├─ Format: "[Source: {filename}]\n{text}"
   └─ Returns: joined document context string (or "" if none)
```

### How Context Is Used

```
SYSTEM_PROMPT ← build_system_prompt(
    agent_name, skills_section,
    routing_rules, document_context
)
```

The LLM uses this context to:
- Understand ContentEdge concepts (document_context)
- Describe its own capabilities (document_context)
- Follow domain-specific procedures (knowledge context)

---

## 7. Full RAG Diagram

```
                    INDEXING (offline)
                    ═════════════════

  Source files                       Qdrant
  ┌──────────────┐                  ┌──────────────┐
  │ PDF/TXT/MD   │──── chunk ──────▸│              │
  │ (startup)    │    + embed       │  Collection: │
  └──────────────┘                  │  "schema_    │
                                    │   memory"    │
  ┌──────────────┐                  │              │
  │ Knowledge    │──── chunk ──────▸│  N points    │
  │ (startup)    │    + embed       │  (768d each) │
  └──────────────┘                  │              │
                                    │              │
  ┌──────────────┐                  │              │
  │ JSON schemas │──── describe ───▸│              │
  │ (on demand)  │    + embed       │              │
  └──────────────┘                  └──────┬───────┘
                                           │
                    RETRIEVAL (per question)│
                    ═══════════════════════ │
                                           │
  User question                            │
        │                                  │
        ▼                                  ▼
  embed_query() → 768d vector → COSINE similarity search
        │                         (score >= 0.55)
        ▼
  Top chunks injected into SYSTEM_PROMPT
  ({document_context})
        │
        ▼
  LLM generates accurate responses
```

---

## 8. Qdrant Store Components

```
qdrant_store.py

VECTOR_SIZE = 768                  ← nomic-embed-text dimension
DISTANCE = COSINE                  ← similarity metric

Functions:
  get_qdrant_client() → QdrantClient
  get_embeddings()    → OllamaEmbeddings(nomic-embed-text)
  ensure_collection() → Creates collection if not exists
  upsert_texts()      → Embeds + upserts chunks
  search_similar()    → Semantic search by query
```

---

## 9. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `QDRANT_HOST` | `"qdrant"` | Qdrant hostname |
| `QDRANT_PORT` | `6333` | Qdrant HTTP port |
| `QDRANT_COLLECTION` | `"schema_memory"` | Collection name |
| `OLLAMA_EMBED_MODEL` | `"nomic-embed-text"` | Embedding model |
| `OLLAMA_BASE_URL` | `"http://ollama:11434"` | Ollama URL |
| `REDIS_URL` | `"redis://redis:6379/0"` | Redis connection |
| `REDIS_CHAT_TTL` | `3600` | Session TTL (seconds) |
| `REDIS_MAX_TURNS` | `20` | Max conversation turns per session |

---

## 10. Files Involved

| File | Key Function | Purpose |
|---|---|---|
| `app/memory/qdrant_store.py` | `get_qdrant_client()`, `upsert_texts()`, `search_similar()` | Qdrant operations |
| `app/memory/file_loader.py` | `load_files_for_memory()`, `load_knowledge_for_memory()` | Indexes docs + knowledge at startup (fingerprinted) |
| `app/memory/schema_loader.py` | `load_all_schemas()` | Indexes JSON schemas on demand |
| `app/memory/chat_history.py` | `get_history()`, `append_messages()`, `clear_history()` | Redis conversation history |
| `app/agent/core.py` | `_retrieve_document_context()` | RAG retrieval per question (score >= 0.55) |
| `app/agent/prompts.py` | `build_system_prompt()` | Dynamic prompt with skills + routing |
| `app/skills/memory_skill.py` | `save_learning()`, `recall_learnings()` | Live learning + semantic recall (not registered) |

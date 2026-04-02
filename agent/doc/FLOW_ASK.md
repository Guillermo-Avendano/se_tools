# FLOW_ASK — Question Processing

## Overview

Describes the complete flow from receiving a user question to returning
the response. This is the central flow of the agent.

---

## 1. Entry Points

Two endpoints receive questions. Both converge on `ask_agent()`.

```
┌──────────────────────────┐     ┌─────────────────────────────────┐
│  POST /ask               │     │  POST /v1/chat/completions      │
│  (routes.py)             │     │  (openai_compat.py)             │
│                          │     │                                  │
│  Body: AskRequest        │     │  Body: OpenAIChatRequest        │
│  { question,             │     │  { model, messages[],           │
│    session_id?,          │     │    temperature, stream }        │
│    chat_history[] }      │     │                                  │
│                          │     │  Processing:                    │
│  Pydantic validation:    │     │  - Ignores role="system"        │
│  - question: 1-5000 ch   │     │  - Last role="user" = question  │
│  - history: max 50 msgs  │     │  - role="assistant" → history   │
│  - content: 1-10000 ch   │     │  - Supports SSE streaming       │
└────────────┬─────────────┘     └───────────────┬─────────────────┘
             │                                    │
             └─────────── both call ──────────────┘
                              │
                              ▼
                    ask_agent(question, chat_history)
                              │
                         core.py
```

**Session management**: When `session_id` is provided in `/ask`, the chat
history is loaded from Redis (not from the request body). After each exchange,
the turn (user question + agent answer) is persisted to Redis.

---

## 2. `ask_agent()` — Step by Step

```
ask_agent(question, chat_history)
   │
   │  ┌─────────────────────────────────────────────────┐
   │  │ STEP 1: Retrieve document context (RAG)         │
   │  │                                                  │
   │  │ _retrieve_document_context(question, top_k=3)   │
   │  │   ├─ Searches Qdrant for type="document" chunks │
   │  │   ├─ Filters by score >= 0.55                   │
   │  │   └─ Returns: ContentEdge and self-knowledge    │
   │  │                                                  │
   │  │   Fallback: "" (empty)                           │
   │  └─────────────────────────────────────────────────┘
   │
   │  ┌─────────────────────────────────────────────────┐
   │  │ STEP 2: Setup skills                            │
   │  │                                                  │
   │  │ registry.setup_all(SkillContext(config))         │
   │  │   ├─ ContentEdgeSkill.setup():                  │
   │  │   │   ├─ Fetches content classes from Mobius     │
   │  │   │   ├─ Fetches indexes from Mobius             │
   │  │   │   └─ Caches at module level for reuse       │
   │  │   └─ Each skill gets what it needs from context │
   │  └─────────────────────────────────────────────────┘
   │
   │  ┌─────────────────────────────────────────────────┐
   │  │ STEP 3: Build system prompt                     │
   │  │                                                  │
   │  │ build_system_prompt(                            │
   │  │     agent_name, skills_section,                  │
   │  │     routing_rules, document_context              │
   │  │ )                                               │
   │  │                                                  │
   │  │ Skills contribute prompt fragments from .md      │
   │  │ files in workspace/prompts/.                     │
   │  │ Provider-specific variants are auto-resolved:    │
   │  │   LLM_PROVIDER=ollama → contentedge_ollama.md    │
  │  │   LLM_PROVIDER=llama_cpp → contentedge_llama_cpp.md    │
   │  │   Fallback: contentedge.md (base)                │
   │  │ Routing rules generated from get_routing_hint(). │
   │  │                                                  │
   │  │ Currently 1 skill: ContentEdge (23 tools)        │
   │  └─────────────────────────────────────────────────┘
   │
   │  ┌─────────────────────────────────────────────────┐
   │  │ STEP 4: Build message list                      │
   │  │                                                  │
   │  │ messages = [                                    │
   │  │   SystemMessage(system_prompt),                 │
   │  │   ...chat_history (last 6 msgs, 2000ch max),   │
   │  │   HumanMessage(question)                        │
   │  │ ]                                               │
   │  │                                                  │
   │  │ MAX_HISTORY_MSGS = 6                            │
   │  │ MAX_MSG_CHARS = 2000 (truncated with "...")     │
   │  └─────────────────────────────────────────────────┘
   │
   │  ┌─────────────────────────────────────────────────┐
   │  │ STEP 5: Create ReAct agent                      │
   │  │                                                  │
   │  │ llm = _get_llm()                                │
   │  │   LLM_PROVIDER=ollama → ChatOllama              │
  │  │   LLM_PROVIDER=llama_cpp → ChatOpenAI           │
  │  │     (base_url=<llama_cpp_server>/v1)            │
   │  │                                                  │
   │  │ agent = create_react_agent(llm, all_tools)      │
   │  │   Tools collected from all enabled skills via    │
   │  │   registry.get_all_tools() (23 tools)            │
   │  └─────────────────────────────────────────────────┘
   │
   │  ┌─────────────────────────────────────────────────┐
   │  │ STEP 6: Invoke agent (ReAct Loop)               │
   │  │                                                  │
   │  │ result = await agent.ainvoke(messages)           │
   │  │ (see ARCHITECTURE.md §3 — ReAct Loop)           │
   │  │ recursion_limit = 25                             │
   │  └─────────────────────────────────────────────────┘
   │
   │  ┌─────────────────────────────────────────────────┐
   │  │ STEP 7: Extract answer                          │
   │  │                                                  │
   │  │ answer:                                         │
   │  │   └─ Last AIMessage with content and no         │
   │  │      tool_calls                                 │
   │  │                                                  │
   │  │ Fallback: "I was unable to complete the         │
   │  │   request. Please try again."                   │
   │  └─────────────────────────────────────────────────┘
   │
   │  ┌─────────────────────────────────────────────────┐
   │  │ STEP 8: Teardown skills                         │
   │  │                                                  │
   │  │ registry.teardown_all() — cleanup state          │
   │  └─────────────────────────────────────────────────┘
   │
   ▼
Returns: { answer }
```

---

## 3. Decision Matrix

| Question Type | Tool(s) Called | Iterations |
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

## 4. Response Format

### POST /ask → AskResponse

```json
{
  "answer": "John Smith has 3 loan documents in the repository..."
}
```

### POST /v1/chat/completions → OpenAI format

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "SE-Content-Agent",
  "choices": [{
    "index": 0,
    "message": { "role": "assistant", "content": "..." },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

When `stream: true`, responses are sent as Server-Sent Events (SSE).

---

## 5. Example Flows

### Example A: "Search documents for customer 1000"

```
Iter 1 │ LLM → contentedge_search([{"index_name":"CUST_ID","operator":"EQ","value":"1000"}])
       │   → object_ids: ["id1", "id2", "id3"]
Iter 2 │ LLM → contentedge_get_document_url(doc_id_1) → viewer_url_1
Iter 3 │ LLM → contentedge_get_document_url(doc_id_2) → viewer_url_2
Iter 4 │ LLM → combines search results + viewer links → END
```

### Example B: "Archive this report into AC001"

```
Iter 1 │ LLM → contentedge_archive_documents("AC001", '["workspace/tmp/report.pdf"]',
       │        '{"CUST_ID":"3000"}', '[]')
       │   → {"success": true, "archived": [...]}
Iter 2 │ LLM → "Report archived successfully into AC001" → END
```

### Example C: "Export everything from the repository"

```
Iter 1 │ LLM → contentedge_repo_info()
       │   → source/target repo details
Iter 2 │ LLM → contentedge_export_all()
       │   → {"success": true, "export_dir": "...", ...}
Iter 3 │ LLM → "Exported all content classes, indexes, and policies" → END
```

### Example D: "Hello, how are you?"

```
Iter 1 │ LLM → conversational → direct answer → END
```

---

## 6. Files Involved

| File | Role |
|---|---|
| `app/api/routes.py` | Endpoints `/health`, `/ask`, `/chat/{id}`, `/skills` |
| `app/api/openai_compat.py` | Endpoints `/v1/models`, `/v1/chat/completions` (streaming) |
| `app/agent/core.py` | `ask_agent()` — orchestrates the full flow |
| `app/agent/prompts.py` | `build_system_prompt()` — dynamic from skills |
| `app/skills/contentedge_skill.py` | ContentEdge skill (23 tools, direct lib calls) |
| `app/memory/qdrant_store.py` | `search_similar()` for RAG |
| `app/memory/chat_history.py` | Redis-backed conversation history |

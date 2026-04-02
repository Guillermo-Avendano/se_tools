# ContentEdge Guide (Current Enabled Operations)

This guide reflects the operations currently enabled for the agent.
It is intentionally aligned with the active tool set in the runtime.

## Enabled tools

1. `contentedge_search`
- Search documents by index constraints.

2. `contentedge_get_document_url`
- Build a viewer URL for a document object id.

3. `contentedge_list_content_classes`
- List available content classes.

4. `contentedge_list_indexes`
- List index groups and individual indexes.

5. `contentedge_search_archiving_policies`
- Search/list archiving policies.

6. `contentedge_get_archiving_policy`
- Retrieve full policy JSON.

7. `contentedge_delete_archiving_policy`
- Delete a policy by name.

8. `contentedge_list_content_class_versions`
- List versions for a content class/report id.

9. `contentedge_delete_search_results`
- Search and delete matching documents.

10. `contentedge_export_content_classes`
- Export content classes to workspace files.

11. `contentedge_export_indexes`
- Export indexes to workspace files.

12. `contentedge_export_index_groups`
- Export index groups to workspace files.

13. `contentedge_import_content_classes`
- Import content classes from workspace files.

14. `contentedge_import_indexes`
- Import indexes from workspace files.

15. `contentedge_import_index_groups`
- Import index groups from workspace files.

16. `contentedge_repo_info`
- Show source/target repository connectivity info.

## Disabled operations in the agent layer

These operations are disabled for agent execution and planning:

- `contentedge_archive_documents`
- `contentedge_archive_using_policy`
- `contentedge_delete_documents_by_ids`
- `contentedge_delete_document`
- `contentedge_delete_content_class_versions`
- `contentedge_export_all`
- `contentedge_import_all`
- `contentedge_generate_archiving_policy`
- `contentedge_register_archiving_policy`
- `contentedge_export_archiving_policy`
- `contentedge_modify_archiving_policy`
- `contentedge_create_archiving_policy`

Note: backend helper libraries still exist for platform components that use them outside the conversational agent.

## Practical usage patterns

- Discover metadata model first:
  - `contentedge_list_content_classes`
  - `contentedge_list_indexes`

- Search then open documents:
  - `contentedge_search`
  - `contentedge_get_document_url`

- Policy administration (read/delete):
  - `contentedge_search_archiving_policies`
  - `contentedge_get_archiving_policy`
  - `contentedge_delete_archiving_policy`

- Admin migration by object type:
  - Export: `contentedge_export_content_classes`, `contentedge_export_indexes`, `contentedge_export_index_groups`
  - Import: `contentedge_import_content_classes`, `contentedge_import_indexes`, `contentedge_import_index_groups`

## Chat prompt catalog (simple vs detailed)

Use these prompts to explicitly control the output format for all managed metadata objects.

Notes:
- The agent always prints `Repository Context: SOURCE` or `Repository Context: TARGET` at the top.
- If you do not specify repository, SOURCE is used by default.
- Use `simple` for compact lists (ID + Name).
- Use `detailed` for extended columns.

### Content Classes

- Simple (SOURCE):
  - `List content classes in source in simple mode`
- Detailed (SOURCE):
  - `List content classes in source in detailed mode`
- Simple (TARGET):
  - `List content classes in target in simple mode`
- Detailed (TARGET):
  - `List content classes in target in detailed mode`

Expected columns:
- Simple: `ID`, `Name`
- Detailed: `ID`, `Name`, `Description`

### Indexes

- Simple (SOURCE):
  - `List indexes in source in simple mode`
- Detailed (SOURCE):
  - `List indexes in source in detailed mode`
- Simple (TARGET):
  - `List indexes in target in simple mode`
- Detailed (TARGET):
  - `List indexes in target in detailed mode`

Expected columns:
- Simple: `ID`, `Name`
- Detailed: `ID`, `Name`, `Data Type`, `Dimension`, `Format`, `Description`

### Index Groups

- Simple (SOURCE):
  - `List index groups in source in simple mode`
- Detailed (SOURCE):
  - `Show detailed index groups in source`
- Simple (TARGET):
  - `List index groups in target in simple mode`
- Detailed (TARGET):
  - `Show detailed index groups in target`

Expected columns:
- Simple: `Group ID`, `Group Name`, `Members`
- Detailed: `Group ID`, `Group Name`, `Index ID`, `Index Name`, `Data Type`, `Dimension`, `Format`, `Description`

### Archiving Policies

- Simple (SOURCE):
  - `List archiving policies in source in simple mode`
- Detailed (SOURCE):
  - `List archiving policies in source in detailed mode`
- Simple (TARGET):
  - `List archiving policies in target in simple mode`
- Detailed (TARGET):
  - `List archiving policies in target in detailed mode`

Expected columns:
- Simple: `Policy ID`, `Policy Name`
- Detailed: `Policy ID`, `Policy Name`, `Version`, `Description`

### Practical examples

- `Show me indexes in source, simple`
- `Show me indexes in source, detailed`
- `Give me detailed index groups in target`
- `List content classes in target, simple`
- `List archiving policies in source, detailed`

## Quick prompts for MobiusRemoteCLI adelete

Use these prompts when you are editing an `adelete` template and need exact clauses.

### Date filters

- Delete only documents older than `2026-01-01`:
  - `I am editing a MobiusRemoteCLI adelete template. Build the exact filter clause to delete only documents with DoIssue before 2026-01-01. Return only the clause.`

- Delete only documents on or after `2026-01-01`:
  - `In adelete, build a filter to keep old data and delete only documents where DoIssue is >= 2026-01-01. Return only the clause.`

- Delete a date range:
  - `For adelete, create the exact filter for DoIssue between 2025-01-01 and 2025-12-31 inclusive. Return only the clause.`

### Content Class filters

- Delete only one content class:
  - `For adelete, what exact filter deletes only content class ClaimsAuto? Return only the clause.`

- Delete several content classes:
  - `For adelete, generate a filter that deletes only content classes ClaimsAuto, Checks, and DriverLics. Return only the clause.`

### Index-based filters

- Delete by one index value:
  - `In adelete, build the exact filter to delete documents where CustID = 28526639. Return only the clause.`

- Delete by amount threshold:
  - `In adelete, build the exact filter to delete only documents where TotAmnt > 10000. Return only the clause.`

### Safe operating prompts

- Ask for a dry-run style explanation before final clause:
  - `Before giving the final adelete filter, explain in one sentence what records will be affected, then return the clause.`

- Ask to validate index names before generating:
  - `Validate that DoIssue and CustID exist in source indexes or index groups. If valid, return the final adelete filter clause.`

## Important validation rule

For `.lst` based planning in MobiusRemoteCLI, when a `TOPIC-ID` belongs to an Index Group,
all members of that Index Group must be present in the same entry. Missing members make the
file invalid for plan insertion.

---

# Agent Architecture (LangGraph)

## Overview

The SE ContentEdge Agent is built using **LangGraph**, a framework for orchestrating multi-step agentic workflows. The agent processes user queries through a hierarchical graph where each node represents either a decision point (planning) or a specialized domain executor (ContentEdge operations, index management, etc.).

The agent is powered by **retrieval-augmented generation (RAG)** using Qdrant as the vector store, enabling context-aware responses grounded in workspace knowledge and documents.

## Graph Structure

```
START
  │
  ├──> PLANNING NODE (Multi-turn confirmation)
  │       ├─ Extract intent + domain
  │       ├─ Check if operation is disabled
  │       ├─ Route with/without user confirmation
  │       │
  │       ├─ DISABLED ──> ERROR → END
  │       ├─ NEEDS CONFIRM → CONFIRMATION NODE → (user response)
  │       └─ EXECUTE ──────────────────────────┐
  │                                              │
  ├──> ROUTE TO DOMAIN                          │
  │       │                                      │
  │       ├─ ARCHIVING POLICY NODE              │
  │       │   └─ Search, get, delete policies   │
  │       │                                      │
  │       ├─ INDEXES NODE                       │
  │       │   └─ Export, import, list indexes   │
  │       │                                      │
  │       ├─ INDEX GROUPS NODE                  │
  │       │   └─ Export, import,list groups    │
  │       │                                      │
  │       ├─ CONTENT CLASSES NODE               │
  │       │   └─ Export, import, list classes   │
  │       │   └─ List versions, delete versions │
  │       │                                      │
  │       ├─ DOCUMENTS NODE                     │
  │       │   └─ Search, smart chat, get URL    │
  │       │                                      │
  │       └─ GENERAL QUERY NODE                 │
  │           └─ Repo info, undomained queries  │
  │
  └──> END
```

## Execution Flow

### 1. Planning Phase

When a user sends a query:

1. **Intent & Domain Extraction**: The planning node analyzes the user's natural language and identifies:
   - **intent**: What action (search, export, import, delete, etc.)
   - **domain**: Which ContentEdge subsystem (archiving policies, indexes, documents, etc.)

2. **Operation Eligibility Check**:
   - If the operation is in the **disabled list**, planning returns an error message and ends.
   - Disabled operations include: archiving, bulk deletion, policy generation, etc.

3. **Confirmation Decision**:
   - If the operation is allowed and is destructive (delete, modify), the node returns a confirmation prompt.
   - If non-destructive or already confirmed by user, routing proceeds directly to execution.

### 2. User Confirmation (if needed)

If the operation requires confirmation:

1. The confirmation node presents a summary to the user.
2. User responds with `confirm`, `yes`, `proceed`, or similar to approve.
3. On approval, execution is routed to the appropriate domain node.
4. On rejection, the conversation ends without side effects.

### 3. Domain-Specific Execution

Six specialized nodes handle different ContentEdge operations:

#### **Archiving Policy Node**
- Search for archiving policies by name/pattern
- Retrieve full policy definition (JSON)
- Delete policies by name
- **Disabled**: Create, modify, generate, register, export

#### **Indexes Node**
- List all indexes in the repository
- Export indexes to workspace files (for backup/migration)
- Import indexes from workspace files
- **Disabled**: Create indexes via agent

#### **Index Groups Node**
- List index groups (collections of related indexes)
- Export index groups to workspace files
- Import index groups from workspace files
- **Disabled**: Generate or create index groups via agent

#### **Content Classes Node**
- List available content classes (document types/report templates)
- List versions for a content class
- Delete specific versions
- Export/import content classes
- **Disabled**: Create or modify content classes via agent

#### **Documents Node**
- Search documents by index constraints
- Perform intelligent chat-based document search (semantic search)
- Get viewer URLs for documents (to open in ContentEdge)
- **Disabled**: Archive or bulk delete documents (use MobiusRemoteCLI instead)

#### **General Query Node**
- Return repository connectivity/info
- Handle queries that don't map to a specific domain (fallback)

### 4. RAG (Retrieval-Augmented Generation)

Before responding, the agent:

1. **Queries Qdrant** for relevant documents and knowledge:
   - Documents from `agent/workspace/knowledge/` (`.md` and `.pdf` files)
   - Knowledge chunks from procedures, corrections, preferences

2. **Retrieves context** for the user's query to ground responses.

3. **Generates answers** combining user info + retrieved context.

### 5. End

All execution paths converge to END, terminating the conversation turn.

## Disabled Operations & Why

| Operation | Reason | Workaround |
|---|---|---|
| `contentedge_archive_documents` | Requires file I/O + policy validation | Use MobiusRemoteCLI → acreate → Import mode |
| `contentedge_archive_using_policy` | Large bulk operations need confirmation UI | Use MobiusRemoteCLI → acreate → Policy mode |
| `contentedge_delete_documents_by_ids` | Destructive; needs multi-step UI | Use MobiusRemoteCLI → delete UI |
| `contentedge_delete_content_class_versions` | Potential data loss; policy-dependent | Use ContentEdge admin UI |
| `contentedge_create_archiving_policy` | Requires form validation + multi-step UX | Use MobiusRemoteCLI → vdrdbxml mode |
| `contentedge_generate_archiving_policy` | Incomplete; needs configuration | Manual setup required |
| `contentedge_export_all` | Too broad; rarely used in chat | Use `export_indexes`, `export_content_classes`, `export_index_groups` individually |
| `contentedge_import_all` | Too broad; rarely used in chat | Use `import_indexes`, `import_content_classes`, `import_index_groups` individually |

## State Management

The agent maintains a `ContentEdgeState` TypedDict containing:

- `messages`: Conversation history
- `user_id`: Current user context
- `source_repo` / `target_repo`: Repository configs
- `operation_type`: Planning result (archive, search, export, etc.)
- `confirmation_pending`: Boolean flag for user approval requirement
- `confirmation_response`: User's yes/no answer
- `error`: Any processing errors
- `response`: Final response to user

## Memory & Knowledge Integration

### Workspace Knowledge

The agent indexes files under `agent/workspace/knowledge/`:

- **Root `.md` and `.pdf`**: Indexed at startup
- **Subdirectories** (procedures, corrections, preferences): `.md` and `.pdf` indexed at startup

### Vector Store (Qdrant)

- All indexed files are chunked and embedded.
- Queries use semantic search to retrieve the most relevant chunks.
- Responses are grounded in actual workspace knowledge, reducing hallucination.

### Adding New Knowledge

To extend agent capabilities:

1. Place `.md` or `.pdf` files in `agent/workspace/knowledge/`.
2. Restart the agent container: `docker compose ... restart agent-api`.
3. New content is automatically chunked and embedded into Qdrant.

## Integration Points

### 1. MobiusRemoteCLI

The agent acts as a **query interface** for read-heavy operations (search, list, export). For write-heavy or complex workflows (archive, bulk delete, policy creation), users switch to MobiusRemoteCLI.

### 2. AnythingLLM Web UI

The agent can be accessed via the **AnythingLLM web interface** (`http://localhost:3001` by default) for conversational interaction without requiring API calls.

### 3. Agent API Endpoint

- **URL**: `http://agent-api:8000/chat`
- **Method**: `POST`
- **Payload**: `{ "user_id": "...", "message": "...", "source_repo": {...}, "target_repo": {...} }`
- **Response**: Streaming or JSON with `response`, `error`, and `followup_questions` fields.

## Performance Considerations

- **Planning**: < 1s (LLM inference for intent extraction)
- **RAG Retrieval**: 100–500ms (Qdrant similarity search)
- **Execution**: Varies by operation (search: 1–5s, export: 5–30s, import: 10–60s)
- **Total latency**: 2–90s depending on operation complexity, corpus size, and network I/O

## Troubleshooting

### Agent Won't Start
- Check Docker logs: `docker logs contentedge-agent-api-1`
- Verify dependencies in `agent/pyproject.toml` are correct.
- Ensure Qdrant and Redis are healthy: `docker ps | grep -E "qdrant|redis"`

### Query Returns "Operation Disabled"
- Verify the operation is in the enabled tools list (see Enabled Tools section above).
- Check that the query doesn't match any intentionally disabled operations.

### Responses Are Irrelevant or Hallucinating
- Add relevant `.md`/`.pdf` files to `agent/workspace/knowledge/`.
- Restart the agent to reindex.
- Increase the number of Qdrant chunks retrieved (hyperparameter in `agent-api` startup config).

### Qdrant Not Indexing New Files
- Ensure files are in `agent/workspace/knowledge/` (not subdirectories without PDF support, unless recent build).
- Restart the agent service: `docker compose restart agent-api`.
- Check Qdrant health: `docker logs contentedge-qdrant-1`.

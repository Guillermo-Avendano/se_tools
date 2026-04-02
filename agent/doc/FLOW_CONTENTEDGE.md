# FLOW_CONTENTEDGE — ContentEdge Skill (23 Tools)

## Overview

The ContentEdge skill provides 23 LangChain tools for full lifecycle
management of documents in a Mobius Content Server repository:
search, archiving (direct and policy-based), archiving-policy CRUD +
generation + registration, document/version deletion, version listing,
export/import, and repository info.

The agent imports `contentedge/lib` directly (in-process). No MCP
server, no SSE connections, no extra container.

> **Note**: `contentedge_smart_chat` exists in the code but is **disabled**
> (kept for future use). Content classes and indexes are **pre-loaded at
> skill setup** and injected into the prompt — not exposed as tools.

---

## 1. Architecture

```
┌──────────────────────┐                  ┌────────────────────────────┐
│   agent-api          │  direct Python   │ contentedge/lib            │
│                      │  ──────────────▸ │                            │
│  ContentEdge Skill   │  function calls  │  ContentSearch             │
│  (contentedge_       │  (thread pool)   │  ContentSmartChat          │
│   skill.py)          │                  │  ContentDocument           │
│                      │                  │  ContentArchiveMetadata    │
│  23 LangChain tools  │                  │  ContentClassNavigator     │
└──────────────────────┘                  └─────────────┬──────────────┘
                                                        │
                                                        ▼ HTTPS
                                          ┌──────────────────────────┐
                                          │  Mobius Content Server    │
                                          │  REST API                │
                                          │  ─────────────────────── │
                                          │  /searches               │
                                          │  /hostviewer             │
                                          │  /documents (archive)    │
                                          │  /archivingpolicies      │
                                          │  /repositories (nav)     │
                                          │  /folders (nav)          │
                                          │  /reports (admin)        │
                                          │  /topicgroups (admin)    │
                                          │  /topics (admin)         │
                                          └──────────────────────────┘
```

Blocking I/O is offloaded via `asyncio.run_in_executor()`.

---

## 2. Tool Catalog — All 23 Enabled Tools

### 2.1 Search & Query Tools (2)

| Tool | Parameters | Mobius Endpoint | Returns |
|---|---|---|---|
| `contentedge_search` | constraints (list[dict]), conjunction | `POST /searches` | object_ids, count |
| `contentedge_get_document_url` | object_id | `POST /hostviewer` | viewer_url |

### 2.2 Document Archiving Tools (2)

| Tool | Parameters | Mobius Endpoint | Returns |
|---|---|---|---|
| `contentedge_archive_documents` | content_class, files, metadata, sections | `POST /documents` (metadata) | archived[] with status |
| `contentedge_archive_using_policy` | policy_name, file_path, content_class | `POST /documents` (multipart/mixed) | status, response |

### 2.3 Archiving Policy Tools — CRUD + Generate + Register (8)

| Tool | Parameters | Mobius Endpoint | Returns |
|---|---|---|---|
| `contentedge_search_archiving_policies` | name, withcontent, limit | `GET /archivingpolicies` | count, policies[] |
| `contentedge_create_archiving_policy` | name, policy_json | `POST /archivingpolicies` | success, name, version |
| `contentedge_get_archiving_policy` | name | `GET /archivingpolicies/{name}` | full policy JSON |
| `contentedge_modify_archiving_policy` | name, policy_json | `PUT /archivingpolicies/{name}` | success, name, version |
| `contentedge_delete_archiving_policy` | name | `DELETE /archivingpolicies/{name}` | success, deleted |
| `contentedge_export_archiving_policy` | name | GET + local file write | file path, keys |
| `contentedge_generate_archiving_policy` | name, policy_spec_json | Builds JSON locally | preview (does NOT register) |
| `contentedge_register_archiving_policy` | name | Reads generated JSON + `POST /archivingpolicies` | success, registered |

### 2.4 Navigation & Listing Tools (2)

| Tool | Parameters | Mobius Endpoint | Returns |
|---|---|---|---|
| `contentedge_list_content_class_versions` | content_class, version_from, version_to | Navigation API | versions list |
| `contentedge_repo_info` | — | Config YAML | source/target repo details |

Note: Content classes and indexes are pre-loaded during `ContentEdgeSkill.setup()`
via the Admin REST API (`/reports`, `/topicgroups`, `/topics`) and injected into
the system prompt. No tool call is needed to list them.

### 2.5 Document Deletion Tools (4)

| Tool | Parameters | Mobius Endpoint | Returns |
|---|---|---|---|
| `contentedge_delete_document` | document_id | `DELETE /documents?documentid=` | success, status_code |
| `contentedge_delete_documents_by_ids` | document_ids (list) | DELETE loop | deleted, errors |
| `contentedge_delete_content_class_versions` | content_class, version_from, version_to | Navigation + DELETE | deleted, errors, details[] |
| `contentedge_delete_search_results` | constraints, conjunction | Search + DELETE loop | deleted, errors, total_found |

### 2.6 Export / Import Tools (5)

| Tool | Parameters | Mobius Endpoint | Returns |
|---|---|---|---|
| `contentedge_export_content_classes` | — | `GET /reports` | file path, count |
| `contentedge_export_indexes` | — | `GET /topics` | file path, count |
| `contentedge_export_index_groups` | — | `GET /topicgroups` | file path, count |
| `contentedge_export_all` | — | All of the above + policies | export directory, counts |
| `contentedge_import_all` | export_dir | `POST` to TARGET repo | imported counts |

---

## 3. Search & Query — Detailed Flows

### 3.1 Document Search

```
contentedge_search(constraints, conjunction)
   │
   ▼
ContentSearch.search_index()             ← lib/content_search.py
   │
   ├─ URL: {repo_url}/searches?returnresults=true&limit=200
   ├─ Content-Type: application/vnd.asg-mobius-search.v1+json
   ├─ Payload:
   │    {
   │      "indexSearch": {
   │        "conjunction": "AND",
   │        "constraints": [
   │          {"name":"CUST_ID","operator":"EQ","values":[{"value":"1000"}]}
   │        ],
   │        "repositories": [{"id": "repo_uuid"}]
   │      }
   │    }
   └─ Returns: {"count": N, "object_ids": [...]}
```

**Search Operators**: EQ, NE, LT, LE, GT, GE, LK (like), BT (between), NB (not between), NU (null), NN (not null)

### 3.2 Document Viewer URL

```
contentedge_get_document_url(object_id)
   │
   ▼
ContentDocument.retrieve_document()      ← lib/content_document.py
   │
   ├─ URL: {base_url}/mobius/rest/hostviewer
   ├─ Payload: {"objectId": "encrypted_id", "repositoryId": "repo_uuid"}
   └─ Returns: {"success": true, "viewer_url": "https://server/mobius/view/..."}
```

---

## 4. Archiving Policy Management — Detailed Flows

### 4.1 Search Policies

```
contentedge_search_archiving_policies(name="*", withcontent=False, limit=200)
   │
   ├─ GET {admin_url}/archivingpolicies?limit=200&name={pattern}&withcontent={bool}
   └─ Returns: {"count": N, "policies": [{"name":"...","version":"3.0","description":"..."}]}
```

Wildcard: `name="SAMPLE*"`, `name="*"`, `name="EXACT_NAME"`

### 4.2 Get Full Policy

```
contentedge_get_archiving_policy(name)
   │
   ├─ GET {admin_url}/archivingpolicies/{name}
   └─ Returns: full Mobius policy JSON (rules, fieldGroups, documentInfo, etc.)
```

### 4.3 Create Policy

```
contentedge_create_archiving_policy(name, policy_json="{}")
   │
   ├─ POST {admin_url}/archivingpolicies
   ├─ Content-Type: application/vnd.asg-mobius-admin-archiving-policy.v1+json
   └─ Returns: {"success": true, "name": "...", "version": "3.0"}
```

### 4.4 Modify Policy (Full Replace)

```
contentedge_modify_archiving_policy(name, policy_json)
   │
   ├─ PUT {admin_url}/archivingpolicies/{name}
   ├─ IMPORTANT: Must pass COMPLETE policy definition
   ├─ Recommended: fetch first with get, modify, then put back
   └─ Returns: {"success": true, "name": "...", "version": "3.0"}
```

### 4.5 Delete Policy

```
contentedge_delete_archiving_policy(name)
   │
   ├─ DELETE {admin_url}/archivingpolicies/{name}
   ├─ Accept: */*  (vendor headers cause 406)
   ├─ WARNING: Cannot be undone
   └─ Returns: {"success": true, "name": "...", "deleted": true}
```

### 4.6 Export Policy to File

```
contentedge_export_archiving_policy(name)
   │
   ├─ Fetches policy via GET, removes HATEOAS links
   ├─ Saves to: workspace/archiving_policies/{name}.json
   └─ Returns: {"success": true, "file": "...", "keys": [...]}
```

### 4.7 Generate Policy from Specification (Preview Only)

```
contentedge_generate_archiving_policy(name, policy_spec_json)
   │
   ├─ Builds complete Mobius policy JSON via _build_policy_json()
   ├─ Saves to: workspace/archiving_policies/{name}.json
   ├─ Returns user-friendly preview (does NOT register in Mobius)
   └─ Returns: {"success": true, "file": "...", "fields": [...], "field_groups": [...]}
```

> **Important**: Unlike the legacy behavior, this tool now generates and
> previews the policy WITHOUT registering it. Use
> `contentedge_register_archiving_policy` as a separate step.

### 4.8 Register Previously Generated Policy

```
contentedge_register_archiving_policy(name)
   │
   ├─ Reads the generated JSON from workspace/archiving_policies/{name}.json
   ├─ Registers in Mobius (POST /archivingpolicies)
   ├─ If duplicate (409), retries with timestamp suffix: {name}_{YYYYMMDD_HHMMSS}
   └─ Returns: {"success": true, "registered_in_mobius": true, "name": "..."}
```

**Policy spec structure** (`policy_spec_json`):
```json
{
  "description": "...",
  "source_file": "CO17.txt",
  "documentInfo": {
    "dataType": "Text",
    "charSet": "ASCII",
    "pageBreak": "FORMFEED",
    "lineBreak": "CRLF"
  },
  "fields": [
    {
      "name": "REPORT_DATE",
      "type": "date",
      "levelType": "header1",
      "left": 90, "right": 105, "top": 1, "bottom": 0,
      "format": "DD-MM-YYYY",
      "outputFormat": "YYYYMMDD"
    },
    {
      "name": "CUST_ID",
      "type": "string",
      "levelType": "header1",
      "left": 1, "right": 20, "top": 2, "bottom": 0,
      "terminator": " "
    }
  ],
  "fieldGroups": [
    {"name": "VERSION_ID", "usage": 5, "fields": ["REPORT_DATE"]},
    {"name": "SECTION_ID", "usage": 2, "fields": ["CUST_ID"]},
    {"name": "TOPICS", "usage": 3, "fields": ["CUST_ID"]}
  ],
  "report_label": {
    "left": 90, "right": 105, "top": 0, "bottom": 0,
    "content_class": "AC002",
    "levelType": "header1"
  }
}
```

**Position system**:
- `left`/`right`: 1-based column range (right=0 means read to end of line)
- `top`: line number within page (1=first header line, 0=detail/data lines)
- `bottom`: usually 0 for header fields
- `levelType`: `"header1"` for per-page header fields

**Field group usages**:

| Usage | Name | Purpose | Mandatory |
|---|---|---|---|
| 1 | REPORT_ID | Identifies the content class for the document | YES |
| 2 | SECTION_ID | Section identifier (max 20 chars concatenated) | Optional |
| 3 | TOPIC | Field name MUST match an existing repository index | Optional |
| 5 | VERSION_ID | Version/date identifier (auto-enforces outputFormat="YYYYMMDD") | Optional |

**REPORT_ID pattern** (`report_label`):
- Find a text label near the date/version field in the source file
- Add a `report_label` spec pointing to that label's position
- System auto-creates a REPORT_LABEL field with a lookupTable (ASGLookupTableDefault)
- The lookupTable maps ANY extracted text to the target content_class

**VERSION_ID date auto-enforcement**:
- Any date field in a VERSION_ID group gets `outputFormat="YYYYMMDD"` automatically
- Set `format` to the ACTUAL input format (e.g. "DD-MM-YYYY" for "09-10-2007")

---

## 5. Document Archiving — Detailed Flows

### 5.1 Archive Files Directly (No Policy)

```
contentedge_archive_documents(content_class, files, metadata, sections)
   │
   ├─ content_class: e.g. "AC001" (must exist)
   ├─ files: JSON array of paths
   │    "report.pdf"               → CE_WORK_DIR/report.pdf
   │    "workspace/tmp/file.pdf"   → AGENT_WORKSPACE/tmp/file.pdf
   │    "/absolute/path/file.pdf"  → used as-is (must be in allowed roots)
   ├─ metadata: JSON object {"CUST_ID":"3000", "DATE":"2026-03-16"}
   ├─ sections: optional JSON array (length must match files)
   │
   ├─ API: POST {repo_url}/documents (via ContentArchiveMetadata)
   └─ Returns: {"success": true, "archived": [{"file":"report.pdf","status":200}]}
```

**Allowed file types**: PDF, TXT, JPG, PNG
**Path traversal guard**: Files validated against CE_WORK_DIR and AGENT_WORKSPACE roots.

### 5.2 Archive Using Policy (Parsing/Extraction)

```
contentedge_archive_using_policy(policy_name, file_path, content_class)
   │
   ├─ Fetches policy and validates content_class exists
   ├─ Checks REPORT_ID fieldGroup for content_class mapping in lookupTable
   │    If missing → creates new policy AP_{content_class}_{timestamp}
   │    If no REPORT_ID group at all → injects one
   ├─ Reads file (UTF-8 → fallback latin-1 for TXT; base64 for PDF)
   ├─ Builds multipart/mixed request:
   │    Part 1: {"objects":[{"policies":["POLICY_NAME"]}]}
   │    Part 2: File content
   │
   ├─ API: POST {repo_url}/repositories/{repo_id}/documents?returnids=true
   │    Content-Type: multipart/mixed; TYPE=policy; boundary=...
   │    Accept: application/vnd.asg-mobius-archive-write-status.v2+json
   └─ Returns: {"success": true, "policy_name":"...", "content_class":"...", "response":{...}}
```

**Supported file types**: TXT, SYS, LOG, PDF

---

## 6. Document Deletion — Detailed Flows

### 6.1 Delete Single Document

```
contentedge_delete_document(document_id)
   │
   ├─ API: DELETE {repo_url}/repositories/{repo_id}/documents?documentid={id}
   └─ Returns: {"success": true, "document_id": "...", "status_code": 200}
```

### 6.2 Delete Multiple Documents by IDs

```
contentedge_delete_documents_by_ids(document_ids)
   │
   ├─ document_ids: JSON array of objectIds
   ├─ Iterates and deletes each via _sync_delete_document()
   └─ Returns: {"deleted": N, "errors": M, "details": [...]}
```

### 6.3 Delete Content Class Versions (with Date Range)

```
contentedge_delete_content_class_versions(content_class, version_from="", version_to="")
   │
   ├─ Step 1: List versions via Navigation API
   │    GET repo root → find "Content Classes" folder (vdr:reportRoot)
   │    GET Content Classes → find target class folder
   │    GET class folder → list versions (vdr:reportVersion)
   │
   ├─ Step 2: Filter by date range (optional)
   │    Filters on ReportVersionID metadata field
   │    version_from/version_to: ISO format ("2026-12-12"), INCLUSIVE
   │    Empty = no bound
   │
   ├─ Step 3: For each version:
   │    Navigate INTO version → find sections (baseType=DOCUMENT)
   │    DELETE each section using its objectId
   │    IMPORTANT: Must use section objectId, NOT version folder objectId
   │
   └─ Returns: {"content_class":"AC001","deleted":5,"errors":0,"details":[...]}
```

### 6.4 Delete Search Results

```
contentedge_delete_search_results(constraints, conjunction="AND")
   │
   ├─ Step 1: Execute search (same as contentedge_search)
   ├─ Step 2: For each result, delete via _sync_delete_document()
   └─ Returns: {"deleted":10, "errors":2, "total_found":12}
```

---

## 7. Export / Import — Detailed Flows

### 7.1 Export Content Classes

```
contentedge_export_content_classes()
   │
   ├─ Fetches all content classes from SOURCE repo
   ├─ Saves to: workspace/exports/export_{timestamp}/content_classes.json
   └─ Returns: {"success": true, "file": "...", "count": N}
```

### 7.2 Export Indexes / Index Groups

```
contentedge_export_indexes()      → workspace/exports/export_{timestamp}/indexes.json
contentedge_export_index_groups() → workspace/exports/export_{timestamp}/index_groups.json
```

### 7.3 Export All

```
contentedge_export_all()
   │
   ├─ Exports content classes, indexes, index groups, and archiving policies
   ├─ All saved under: workspace/exports/export_{timestamp}/
   └─ Returns: {"success": true, "export_dir": "...", "content_classes": N, "indexes": N, ...}
```

### 7.4 Import All to Target Repository

```
contentedge_import_all(export_dir)
   │
   ├─ Reads export files from the specified directory
   ├─ Imports into the TARGET repository (repository_target.yaml)
   └─ Returns: {"success": true, "imported": {...}}
```

---

## 8. Navigation API Hierarchy

The navigation API is used for listing versions and for delete operations.

```
Repository Root
  └─ GET {repo_url}/repositories/{repo_id}/children
       │
       ├─ Content Classes folder (objectTypeId=vdr:reportRoot)
       │   └─ GET {repo_url}/folders/{folder_id}/children
       │        │
       │        ├─ AC001 (vdr:report)
       │        ├─ AC002 (vdr:report)
       │        │   └─ GET children → versions (vdr:reportVersion)
       │        │        │
       │        │        ├─ 2007-10-08 (version folder)
       │        │        │   └─ GET children → sections (vdr:reportSection)
       │        │        │        │
       │        │        │        └─ Section 1 (baseType=DOCUMENT)
       │        │        │             ← THIS objectId is needed for DELETE
       │        │        │
       │        │        └─ 2026-03-16 (version folder)
       │        │
       │        └─ LISTFILE (vdr:report)
       │
       └─ Other folders...
```

**Accept header**: `application/vnd.asg-mobius-navigation.v3+json`

**Critical for DELETE**: The version folder objectId returns HTTP 400. You must
navigate INTO the version to find sections with `baseType=DOCUMENT` and use
THEIR objectId for the DELETE call.

---

## 9. Key Workflows

### Document Search + Viewer Links

```
 ├─ contentedge_search([{"index_name":"CUST_ID","operator":"EQ","value":"1000"}])
 │    → object_ids
 ├─ contentedge_get_document_url(id) for each doc
 └─ Present results with viewer links
```

### Create Archiving Policy from Text File (3 steps)

```
 ├─ Analyze text file: field positions, headers, formats
 ├─ Build policy_spec_json: fields, fieldGroups, documentInfo, report_label
 ├─ contentedge_generate_archiving_policy(name, spec)
 │    → generates JSON, saves file, returns PREVIEW (not registered)
 ├─ contentedge_register_archiving_policy(name)
 │    → registers in Mobius
 └─ contentedge_archive_using_policy(name, file_path, content_class)
      → archives file using the policy
```

### Policy Lifecycle

```
 ├─ contentedge_search_archiving_policies("SAMPLE*")  → list
 ├─ contentedge_get_archiving_policy("SAMPLE_POLICY")  → details
 ├─ contentedge_modify_archiving_policy("SAMPLE_POLICY", updated_json)  → update
 ├─ contentedge_export_archiving_policy("SAMPLE_POLICY")  → save to file
 └─ contentedge_delete_archiving_policy("OLD_POLICY")  → delete
```

### Delete Versions by Date Range

```
contentedge_delete_content_class_versions("AC002", "2007-01-01", "2007-12-31")
  → deletes all AC002 versions from 2007 (inclusive)
```

### Search and Delete

```
contentedge_delete_search_results(
  [{"index_name":"CUST_ID","operator":"EQ","value":"1000"}]
)
  → finds all docs for CUST_ID=1000 and deletes them
```

### Export and Import to Another Repository

```
 ├─ contentedge_repo_info()  → show source/target repos
 ├─ contentedge_export_all()  → export from SOURCE
 └─ contentedge_import_all(export_dir)  → import into TARGET
```

### Inter-skill Archiving

```
 ├─ write_file("tmp/report.txt", content)  → filesystem skill
 └─ contentedge_archive_documents(
      content_class="AC001",
      files='["workspace/tmp/report.txt"]',
      metadata='{"CUST_ID":"3000"}'
    )
```

---

## 10. Skill Class & Setup

### ContentEdgeSkill(SkillBase)

- **version**: 2.1.0
- **prompt_file**: contentedge.md (workspace/prompts/)

**Prompt resolution** uses provider-specific variants:
- `LLM_PROVIDER=ollama` → loads `contentedge_ollama.md`
- `LLM_PROVIDER=llama_cpp` → loads `contentedge_llama_cpp.md`
- Fallback: `contentedge.md` (base)

**setup()** pre-loads and caches content classes and indexes:
1. Fetch content classes via Admin REST `/reports` → format as markdown
2. Fetch indexes via `/topicgroups` + `/topics` → format as markdown
3. Cache at module level for reuse across invocations
4. Inject into prompt template via `{content_classes}` and `{indexes}` placeholders

**get_tools()** returns all 23 enabled LangChain tools.

**get_prompt_fragment()** loads the provider-specific prompt from
`workspace/prompts/` (e.g. `contentedge_llama_cpp.md`) and replaces
template variables with cached metadata.

---

## 11. ContentEdge Library (lib/)

| File | Class | Purpose |
|---|---|---|
| `content_config.py` | `ContentConfig` | YAML config, auth headers, repo ID discovery |
| `content_search.py` | `IndexSearch` | Builds search constraint payloads |
| `content_search.py` | `ContentSearch` | Executes index searches |
| `content_smart_chat.py` | `ContentSmartChat` | Smart Chat API client (disabled) |
| `content_smart_chat.py` | `SmartChatResponse` | Parsed Smart Chat response |
| `content_document.py` | `ContentDocument` | Hostviewer URL + document delete |
| `content_archive_metadata.py` | `ContentArchiveMetadata` | Archive documents with metadata |
| `content_class_navigator.py` | `ContentClassNavigator` | Navigate content classes + versions |

---

## 12. Configuration

Environment variables (from `.env`, passed to agent-api container):

| Variable | Example | Purpose |
|---|---|---|
| `CE_SOURCE_REPO_URL` | `https://server:11567` | Source Content Repository URL |
| `CE_SOURCE_REPO_NAME` | `Mobius` | Source repository name |
| `CE_SOURCE_REPO_USER` | `admin` | Source repository user |
| `CE_SOURCE_REPO_PASS` | `admin` | Source repository password |
| `CE_SOURCE_REPO_SERVER_USER` | `ADMIN` | Source server admin user |
| `CE_SOURCE_REPO_SERVER_PASS` | — | Source server admin password |
| `CE_TARGET_REPO_URL` | `https://server:11567` | Target Content Repository URL |
| `CE_TARGET_REPO_NAME` | `Mobius` | Target repository name |
| `CE_TARGET_REPO_USER` | `admin` | Target repository user |
| `CE_TARGET_REPO_PASS` | `admin` | Target repository password |
| `CE_TARGET_REPO_SERVER_USER` | `ADMIN` | Target server admin user |
| `CE_TARGET_REPO_SERVER_PASS` | — | Target server admin password |
| `CE_WORK_DIR` | `/app/contentedge/files` | Working directory for archiving |
| `AGENT_WORKSPACE` | `/app/workspace` | Agent workspace (also allowed for archiving) |

---

## 13. Files Involved

| File | Purpose |
|---|---|
| `app/skills/contentedge_skill.py` | ContentEdge skill — 23 tools, direct lib calls |
| `workspace/prompts/contentedge.md` | Base skill prompt template (fallback) |
| `workspace/prompts/contentedge_ollama.md` | Ollama-specific prompt variant |
| `workspace/prompts/contentedge_llama_cpp.md` | llama.cpp-specific prompt variant |
| `contentedge/lib/content_config.py` | Configuration and authentication |
| `contentedge/lib/content_search.py` | Document search (IndexSearch + ContentSearch) |
| `contentedge/lib/content_smart_chat.py` | Smart Chat API (disabled) |
| `contentedge/lib/content_document.py` | Document viewer URL (Hostviewer) |
| `contentedge/lib/content_archive_metadata.py` | Archive documents with metadata |
| `contentedge/lib/content_class_navigator.py` | Content class navigation and versions |
| `workspace/conf/repository_source.yaml` | Source repository connection settings |
| `workspace/conf/repository_target.yaml` | Target repository connection settings |
| `app/config.py` | `contentedge_yaml`, `contentedge_target_yaml`, `contentedge_work_dir` settings |

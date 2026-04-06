"""
SE ContentEdge Tools — Python Backend
FastAPI server providing archiving-policy generation, file loading,
and migration endpoints.
Calls contentedge/lib classes directly (no LLM, no skills layer).
"""
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Paths ──────────────────────────────────────────────────────────────────
_APP_ROOT = Path(os.environ.get("APP_ROOT", str(Path(__file__).resolve().parent.parent)))
CE_ROOT = _APP_ROOT / "contentedge"
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", str(_APP_ROOT.parent / "workspace")))
DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data"))
TMP_DIR = WORKSPACE_ROOT / "tmp"
EXPORT_IMPORT_DIR = WORKSPACE_ROOT / "export-import"

# Ensure contentedge/lib is importable
if str(CE_ROOT) not in sys.path:
    sys.path.insert(0, str(CE_ROOT))

from lib.content_config import ContentConfig
from lib.content_adm_archive_policy import ContentAdmArchivePolicy
from lib.content_adm_content_class import ContentAdmContentClass
from lib.content_adm_index import ContentAdmIndex
from lib.content_adm_index_group import ContentAdmIndexGroup
from lib.content_archive_metadata import (
    ArchiveDocument, ArchiveDocumentCollection, ContentArchiveMetadata,
)
from lib.content_archive_policy import ContentArchivePolicy

# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="SE ContentEdge Tools", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────────

class FieldDefinition(BaseModel):
    name: str
    line: int
    column: int
    length: int = 0
    format: str = ""

class SectionVersionMapping(BaseModel):
    section_fields: list[str]
    version_field: str

class PolicyConfig(BaseModel):
    policy_name: str
    fields: list[FieldDefinition]
    mapping: SectionVersionMapping
    source_file: str
    source_folder: str = "tmp"
    content_class: str = "UNKNOWN"
    replace_existing: bool = False

class ExtractRequest(BaseModel):
    filename: str
    folder: str = "tmp"
    fields: list[FieldDefinition]

class ArchiveFileMetadata(BaseModel):
    name: str
    value: str

class ArchiveFilesRequest(BaseModel):
    folder: str
    policy_name: str
    files: list[str]
    content_class: str = ""

class MigrateRequest(BaseModel):
    object_type: str          # archiving_policies | content_classes | indexes | index_groups
    names: list[str]          # names/ids to migrate
    replace_existing: bool = False

class MigrateVdrdbxmlRequest(BaseModel):
    worker: str
    mode: str                 # 'all' or 'specific'
    template: str = ""        # vdrdbxml command template (optional override)
    content_classes: list[str] = []
    indexes: list[str] = []
    index_groups: list[str] = []
    archiving_policies: list[str] = []

class PlanStep(BaseModel):
    repo: str       # SOURCE or TARGET
    operation: str  # acreate, vdrdbxml, adelete, rm-definitions
    command: str    # command arguments

class SubmitPlanRequest(BaseModel):
    worker: str
    plan_name: str
    steps: list[PlanStep]

class RemoveDefinitionsRequest(BaseModel):
    worker: str
    repo: str = "target"        # source or target
    content_classes: list[str] = []
    indexes: list[str] = []
    index_groups: list[str] = []
    archiving_policies: list[str] = []


# ═══════════════════════════════════════════════════════════════════════════
# ContentEdge lib singletons
# ═══════════════════════════════════════════════════════════════════════════
# Sync .env → YAML: env vars are the primary source of truth
# ═══════════════════════════════════════════════════════════════════════════

# Mapping: env var suffix → YAML key under "repository:"
_ENV_TO_YAML = {
    "REPO_URL":         "repo_url",
    "REPO_NAME":        "repo_name",
    "REPO_USER":        "repo_user",
    "REPO_PASS":        "repo_pass",
    "REPO_SERVER_USER": "repo_server_user",
    "REPO_SERVER_PASS": "repo_server_pass",
}


def _sync_env_to_yaml(yaml_path: str, env_prefix: str) -> bool:
    """Compare CE_*_REPO_* env vars with the YAML and update YAML if different.

    Returns True if the YAML was modified, False otherwise.
    """
    # Collect env values (skip empty → means "not configured")
    env_values: dict[str, str] = {}
    for suffix, yaml_key in _ENV_TO_YAML.items():
        env_var = f"{env_prefix}{suffix}"
        val = os.environ.get(env_var, "")
        if val:  # only override if env var is non-empty
            env_values[yaml_key] = val

    if not env_values:
        return False  # nothing to sync

    if not os.path.exists(yaml_path):
        return False

    with open(yaml_path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    if not doc or "repository" not in doc:
        return False

    repo = doc["repository"]
    changed = False

    for yaml_key, env_val in env_values.items():
        current = str(repo.get(yaml_key, "") or "")
        if current != env_val:
            repo[yaml_key] = env_val
            changed = True

    if changed:
        # Clear cached repo_id/repo_id_enc — they depend on URL and will be
        # re-discovered by ContentConfig on first API call.
        repo.pop("repo_id", None)
        repo.pop("repo_id_enc", None)
        repo.pop("content_source_id", None)

        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(doc, f, default_flow_style=False, allow_unicode=True)

    return changed


# ═══════════════════════════════════════════════════════════════════════════
# ContentEdge lib singletons
# ═══════════════════════════════════════════════════════════════════════════

_configs: dict[str, ContentConfig] = {}
_policy_admins: dict[str, ContentAdmArchivePolicy] = {}
_cc_admins: dict[str, ContentAdmContentClass] = {}
_index_admins: dict[str, ContentAdmIndex] = {}
_ig_admins: dict[str, ContentAdmIndexGroup] = {}
_target_cc_versions_cache: dict[str, tuple[float, list[dict]]] = {}
_TARGET_CC_CACHE_TTL_SECONDS = 60


def _normalize_repo_base_url(url: str) -> str:
    """Normalize repository base URL to an absolute http(s) URL."""
    clean = (url or "").strip()
    if not clean:
        return ""
    if not clean.lower().startswith(("http://", "https://")):
        clean = f"https://{clean}"
    return clean.rstrip("/")


def _probe_repo_connection(base_url: str, user: str, password: str, timeout_sec: float = 4.0) -> tuple[bool, str]:
    """Probe repo connectivity and credentials via /repositories endpoint."""
    if not base_url:
        return False, "missing URL"
    endpoints = [
        f"{base_url}/mobius/rest/repositories",
        f"{base_url}/repositories",
    ]

    last_reason = ""
    for endpoint in endpoints:
        try:
            response = requests.get(
                endpoint,
                auth=(user or "", password or ""),
                timeout=timeout_sec,
                verify=False,
            )
        except requests.exceptions.RequestException as exc:
            last_reason = str(exc)
            continue

        if 200 <= response.status_code < 300:
            return True, "ok"

        # 401/403/404 may indicate wrong endpoint/auth; try fallback endpoint.
        last_reason = f"HTTP {response.status_code}"

    return False, last_reason or "probe failed"


def _repo_runtime_status(repo: str) -> dict:
    """Return runtime status for source/target repos based on env + connectivity."""
    key = repo.strip().lower()
    is_target = key in ("target", "secondary")
    prefix = "CE_TARGET_" if is_target else "CE_SOURCE_"

    raw_url = os.environ.get(f"{prefix}REPO_URL", "")
    url = _normalize_repo_base_url(raw_url)
    name = os.environ.get(f"{prefix}REPO_NAME", "")
    user = os.environ.get(f"{prefix}REPO_USER", "")
    password = os.environ.get(f"{prefix}REPO_PASS", "")

    missing = []
    if not raw_url:
        missing.append("REPO_URL")
    if not name:
        missing.append("REPO_NAME")
    if not user:
        missing.append("REPO_USER")
    if not password:
        missing.append("REPO_PASS")

    configured = len(missing) == 0
    connected = False
    reason = ""
    if configured:
        connected, reason = _probe_repo_connection(url, user, password)
    else:
        reason = "missing: " + ", ".join(missing)

    return {
        "active": bool(configured and connected),
        "configured": configured,
        "connected": connected,
        "url": raw_url,
        "name": name,
        "reason": reason,
    }


def _get_config(repo: str = "source") -> ContentConfig:
    """Load ContentConfig for the given repo alias.

    On first load, syncs env vars → YAML so .env is always the primary source.
    """
    key = repo.strip().lower()
    if key in _configs:
        return _configs[key]

    is_target = key in ("target", "secondary")
    yaml_name = "repository_target.yaml" if is_target else "repository_source.yaml"
    env_prefix = "CE_TARGET_" if is_target else "CE_SOURCE_"

    yaml_path = str(WORKSPACE_ROOT / "conf" / yaml_name)
    if not os.path.exists(yaml_path):
        yaml_path = str(CE_ROOT / "conf" / yaml_name)

    # Sync: env vars override YAML values
    _sync_env_to_yaml(yaml_path, env_prefix)

    config = ContentConfig(yaml_path)
    _configs[key] = config
    return config


def _get_policy_admin(repo: str = "source") -> ContentAdmArchivePolicy:
    """Return a ContentAdmArchivePolicy instance for the given repo."""
    key = repo.strip().lower()
    if key not in _policy_admins:
        _policy_admins[key] = ContentAdmArchivePolicy(_get_config(repo))
    return _policy_admins[key]


def _get_cc_admin(repo: str = "source") -> ContentAdmContentClass:
    key = repo.strip().lower()
    if key not in _cc_admins:
        _cc_admins[key] = ContentAdmContentClass(_get_config(repo))
    return _cc_admins[key]


def _get_index_admin(repo: str = "source") -> ContentAdmIndex:
    key = repo.strip().lower()
    if key not in _index_admins:
        _index_admins[key] = ContentAdmIndex(_get_config(repo))
    return _index_admins[key]


def _get_ig_admin(repo: str = "source") -> ContentAdmIndexGroup:
    key = repo.strip().lower()
    if key not in _ig_admins:
        _ig_admins[key] = ContentAdmIndexGroup(_get_config(repo))
    return _ig_admins[key]


def _get_archive_metadata(repo: str = "source") -> ContentArchiveMetadata:
    return ContentArchiveMetadata(_get_config(repo))


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINT: List available files in workspace/tmp/
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/files")
def list_files():
    """List text/report files in workspace/tmp/."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(TMP_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in (".txt", ".dat", ".prn", ".rpt", ".csv"):
            files.append({"name": f.name, "size": f.stat().st_size})
    return {"files": files}


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINT: Read file content with line/column metadata
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/files/{filename}/content")
def get_file_content(filename: str):
    """Return file content split into pages/lines for the viewer."""
    safe_name = re.sub(r'[^\w.\-]', '_', filename)
    filepath = TMP_DIR / safe_name
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {safe_name}")

    MAX_BYTES = 12 * 1024  # 12 KB limit

    raw = filepath.read_bytes()[:MAX_BYTES]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    if text.startswith("\ufeff"):
        text = text[1:]

    pages_raw = text.split("\f")
    pages = []
    for p in pages_raw:
        if p.strip():
            lines = p.split("\n")
            if lines and not lines[-1].strip():
                lines = lines[:-1]
            pages.append(lines)

    return {
        "filename": safe_name,
        "total_pages": len(pages),
        "total_lines": sum(len(p) for p in pages),
        "pages": [{"page_number": i + 1, "lines": p} for i, p in enumerate(pages)],
    }


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINT: Extract field values (preview / validation)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/extract")
def extract_fields(req: ExtractRequest):
    """Extract field values from the first 3 pages of the file."""
    safe_name = re.sub(r'[^\w.\-]', '_', req.filename)
    safe_folder = re.sub(r'[^\w.\-]', '_', req.folder)
    filepath = WORKSPACE_ROOT / safe_folder / safe_name
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {safe_folder}/{safe_name}")

    try:
        text = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = filepath.read_text(encoding="latin-1")

    if text.startswith("\ufeff"):
        text = text[1:]

    pages = [p for p in text.split("\f") if p.strip()][:3]

    results = []
    for field in req.fields:
        entry = {
            "name": field.name,
            "line": field.line,
            "column": field.column,
            "length": field.length,
            "format": field.format,
            "values": [],
        }

        for page_idx, page_text in enumerate(pages):
            lines = page_text.split("\n")
            line_idx = field.line - 1
            raw_value = ""
            value = ""

            if 0 <= line_idx < len(lines):
                line = lines[line_idx]
                col_start = field.column - 1

                if col_start < len(line):
                    if field.length > 0:
                        raw_value = line[col_start:col_start + field.length]
                    else:
                        rest = line[col_start:]
                        space_idx = rest.find(" ")
                        raw_value = rest[:space_idx] if space_idx >= 0 else rest
                    value = raw_value.strip()

            entry["values"].append({
                "page": page_idx + 1,
                "value": value,
                "raw": raw_value,
            })

        results.append(entry)

    return {"fields": results, "pages_scanned": len(pages)}


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINT: List existing archiving policies (via contentedge/lib)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/policies")
def list_archiving_policies(repo: str = "source"):
    """List archiving policies from the Mobius repository."""
    try:
        admin = _get_policy_admin(repo)
        items = admin.list_archiving_policies()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Mobius API error: {e}")

    policies = []
    for it in items:
        policies.append({
            "name": it.get("name", ""),
            "version": it.get("version", ""),
            "description": it.get("description") or it.get("details") or "",
        })
    return {"count": len(policies), "policies": policies}


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINT: Generate (build) archiving policy JSON
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/policies/generate")
def generate_policy(config: PolicyConfig):
    """Build Mobius-format policy JSON and save to workspace/tmp/."""
    policy_json = _build_policy_json(config)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    output_file = TMP_DIR / f"{config.policy_name}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(policy_json, f, indent=2, ensure_ascii=False)

    return {
        "policy_name": config.policy_name,
        "output_file": str(output_file),
        "field_count": len(config.fields),
        "section_fields": config.mapping.section_fields,
        "version_field": config.mapping.version_field,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINT: Register policy in Mobius (via contentedge/lib)
# ═══════════════════════════════════════════════════════════════════════════

class RegisterPolicyRequest(BaseModel):
    policy_name: str
    repo: str = "source"

@app.post("/api/policies/register")
def register_policy(req: RegisterPolicyRequest):
    """Register a previously generated policy in the Mobius repository."""
    policy_file = TMP_DIR / f"{req.policy_name}.json"
    if not policy_file.is_file():
        raise HTTPException(status_code=404, detail=f"Policy file not found: {req.policy_name}.json")

    try:
        admin = _get_policy_admin(req.repo)
        status_code = admin.import_archiving_policy(str(policy_file), req.policy_name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Mobius API error: {e}")

    if status_code == 409:
        return {"status": "exists", "message": f"Policy '{req.policy_name}' already exists."}
    elif 200 <= status_code < 300:
        return {"status": "registered", "policy_name": req.policy_name}
    else:
        raise HTTPException(status_code=502, detail=f"Mobius returned status {status_code}")


# ═══════════════════════════════════════════════════════════════════════════
# LOAD FILES — List workspace subdirectories
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/folders")
def list_folders():
    """List subdirectories inside workspace/ that contain files."""
    folders = []
    for d in sorted(WORKSPACE_ROOT.iterdir()):
        if d.is_dir() and d.name not in ("conf", "exports"):
            files_count = sum(1 for f in d.iterdir() if f.is_file())
            folders.append({"name": d.name, "files_count": files_count})
    return {"folders": folders}


@app.get("/api/folders/{folder}/files")
def list_folder_files(folder: str):
    """List files in a workspace subdirectory."""
    safe_name = re.sub(r'[^\w.\-]', '_', folder)
    folder_path = WORKSPACE_ROOT / safe_name
    if not folder_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Folder not found: {safe_name}")

    files = []
    for f in sorted(folder_path.iterdir()):
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "ext": f.suffix.lstrip(".").upper(),
            })
    return {"folder": safe_name, "files": files}


@app.get("/api/folders/{folder}/files/{filename}/content")
def get_folder_file_content(folder: str, filename: str):
    """Return file content from a workspace subfolder, split into pages/lines."""
    safe_folder = re.sub(r'[^\w.\-]', '_', folder)
    safe_name = re.sub(r'[^\w.\-]', '_', filename)
    filepath = WORKSPACE_ROOT / safe_folder / safe_name
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {safe_folder}/{safe_name}")

    MAX_BYTES = 12 * 1024

    raw = filepath.read_bytes()[:MAX_BYTES]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    if text.startswith("\ufeff"):
        text = text[1:]

    pages_raw = text.split("\f")
    pages = []
    for p in pages_raw:
        if p.strip():
            lines = p.split("\n")
            if lines and not lines[-1].strip():
                lines = lines[:-1]
            pages.append(lines)

    return {
        "filename": safe_name,
        "folder": safe_folder,
        "total_pages": len(pages),
        "total_lines": sum(len(p) for p in pages),
        "pages": [{"page_number": i + 1, "lines": p} for i, p in enumerate(pages)],
    }


# ═══════════════════════════════════════════════════════════════════════════
# DATA DIRECTORY — Browse /data for acreate file selection
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/data/folders")
def list_data_folders():
    """List subdirectories inside /data (non-recursive, top level)."""
    if not DATA_ROOT.is_dir():
        return {"folders": []}
    folders = []
    for d in sorted(DATA_ROOT.iterdir()):
        if d.is_dir():
            files_count = 0
            subdirs_count = 0
            with os.scandir(d) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        files_count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        subdirs_count += 1
            folders.append({"name": d.name, "files_count": files_count, "subdirs_count": subdirs_count})
    return {"folders": folders}


@app.get("/api/data/folders/{subpath:path}/children")
def list_data_subfolders(subpath: str):
    """List subdirectories inside /data/<subpath>."""
    safe_parts = [re.sub(r'[^\w.\- ]', '_', p) for p in subpath.split("/") if p]
    folder_path = DATA_ROOT.joinpath(*safe_parts) if safe_parts else DATA_ROOT
    if not folder_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Folder not found: {subpath}")
    resolved = folder_path.resolve()
    if not str(resolved).startswith(str(DATA_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    folders = []
    for d in sorted(folder_path.iterdir()):
        if d.is_dir():
            files_count = 0
            subdirs_count = 0
            with os.scandir(d) as entries:
                for entry in entries:
                    if entry.is_file(follow_symlinks=False):
                        files_count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        subdirs_count += 1
            folders.append({"name": d.name, "files_count": files_count, "subdirs_count": subdirs_count})
    return {"folders": folders, "parent": subpath}


@app.get("/api/data/folders/{subpath:path}/files")
def list_data_files(subpath: str):
    """List files inside /data/<subpath>."""
    safe_parts = [re.sub(r'[^\w.\- ]', '_', p) for p in subpath.split("/") if p]
    folder_path = DATA_ROOT.joinpath(*safe_parts) if safe_parts else DATA_ROOT
    if not folder_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Folder not found: {subpath}")
    resolved = folder_path.resolve()
    if not str(resolved).startswith(str(DATA_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    files = []
    for f in sorted(folder_path.iterdir()):
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "ext": f.suffix.lstrip(".").upper(),
            })
    return {"folder": subpath, "files": files}


# ═══════════════════════════════════════════════════════════════════════════
# LOAD FILES — Validate policy (check REPORT_LABEL, patch if missing)
# ═══════════════════════════════════════════════════════════════════════════

class ValidatePolicyRequest(BaseModel):
    policy_name: str
    content_class: str

# Canonical REPORT_LABEL field template — identical to what _build_policy_json generates
_REPORT_LABEL_TEMPLATE = {
    "name": "REPORT_LABEL",
    "type": "string",
    "levelType": "header1",
    "allowBlank": False,
    "useRetainedValue": False,
    "parsingInfo": {
        "position": {"left": 1.0, "right": 20.0, "top": 1.0, "bottom": 0.0},
        "format": "",
        "minLength": 0, "maxLength": 0, "minValue": "", "maxValue": "",
        "terminator": "\n",
        "matchValuesUsage": "", "matchValues": [], "useWildCard": False,
        "discardIncompleteWords": True,
    },
    "outputInfo": {
        "hide": False, "date_pattern": 0, "sequence": 0, "display_length": 0,
        "alignment": "L", "outputFormat": "",
        "changeCaseTo": "", "removeSpaces": "", "padChar": "",
        "minLength": 0, "maxLength": 0,
        "useLookupTable": True,
        "lookupTable": [],            # value inserted at runtime
        "useThousandSeparator": "O",
    },
    "dependencies": [],
    "isExternal": False,
}

# REPORT_ID field-group template
_REPORT_ID_GROUP_TEMPLATE = {
    "name": "REPORT_ID",
    "retainFieldValues": True,
    "isDefault": False,
    "hide": False,
    "fieldRefs": [
        {"ruleName": "$Default$", "fieldName": "REPORT_LABEL",
         "optional": False, "hideDuplicateValues": False}
    ],
    "usage": "1",
    "requiredOccurrence": None,
    "stopIfMissing": False,
    "useLocationIndex": False,
    "scope": None,
    "filter": None,
    "sort": None,
    "consolidateMatchingRows": False,
    "includeHiddenFields": False,
    "aggregationTotalTag": "Total",
}


def _policy_has_report_label(policy_json: dict) -> bool:
    """Check if any rule in the policy has a REPORT_LABEL field."""
    for rule in policy_json.get("rules", []):
        for field in rule.get("fields", []):
            if field.get("name") == "REPORT_LABEL":
                return True
    return False


def _patch_report_label(policy_json: dict, content_class: str) -> dict:
    """Add REPORT_LABEL field + REPORT_ID group to a policy JSON."""
    import copy
    patched = copy.deepcopy(policy_json)

    # Build the REPORT_LABEL field with the correct lookupTable value
    rl_field = copy.deepcopy(_REPORT_LABEL_TEMPLATE)
    rl_field["outputInfo"]["lookupTable"] = [
        {"name": "ASGLookupTableDefault", "value": content_class}
    ]

    # Add REPORT_LABEL field to the first (usually only) rule
    if patched.get("rules"):
        patched["rules"][0]["fields"].append(rl_field)

    # Add REPORT_ID fieldGroup if not already present
    groups = patched.get("fieldGroups", [])
    has_report_id = any(g.get("name") == "REPORT_ID" for g in groups)
    if not has_report_id:
        groups.insert(0, copy.deepcopy(_REPORT_ID_GROUP_TEMPLATE))
        patched["fieldGroups"] = groups

    # Ensure pageRange is set
    if not patched.get("pageRange"):
        patched["pageRange"] = "All"

    return patched


@app.post("/api/archive/validate-policy")
def validate_policy_for_archive(req: ValidatePolicyRequest):
    """Download the archiving policy and check REPORT_LABEL (read-only).

    If missing, save a patched copy locally as AP_<CC>_<TS>_api.json
    and warn the user — but NEVER modify or delete the policy in Mobius
    (API-imported policies lose internal state and stop working).
    """
    if not req.content_class.strip():
        raise HTTPException(status_code=400, detail="content_class is required")

    try:
        admin = _get_policy_admin("source")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Mobius: {e}")

    # 1. Download the full policy
    policy_json = admin.get_archiving_policy(req.policy_name)
    if policy_json is None:
        raise HTTPException(status_code=404,
                            detail=f"Policy '{req.policy_name}' not found in Mobius")

    # 2. Check REPORT_LABEL
    if _policy_has_report_label(policy_json):
        return {
            "status": "ok",
            "message": "Policy is ready (REPORT_LABEL present).",
            "policy_name": req.policy_name,
            "patched": False,
        }

    # 3. REPORT_LABEL missing — save a patched copy locally for reference
    import copy
    patched = _patch_report_label(copy.deepcopy(policy_json), req.content_class.strip())

    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    new_name = f"AP_{req.content_class.strip()}_{ts}_api"
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    output_file = TMP_DIR / f"{new_name}.json"
    patched["name"] = new_name
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(patched, f, indent=2, ensure_ascii=False)

    return {
        "status": "missing_report_label",
        "message": (f"Policy '{req.policy_name}' is missing REPORT_LABEL. "
                    f"A patched copy was saved as {new_name}.json. "
                    f"Please import it via the ContentEdge UI."),
        "policy_name": req.policy_name,
        "patched": False,
        "saved_file": new_name + ".json",
    }


# ═══════════════════════════════════════════════════════════════════════════
# LOAD FILES — Archive files into Mobius
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/archive")
def archive_files(req: ArchiveFilesRequest):
    """Archive files from a workspace folder into Mobius using the given policy."""
    safe_folder = re.sub(r'[^\w.\-]', '_', req.folder)
    folder_path = WORKSPACE_ROOT / safe_folder
    if not folder_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Folder not found: {safe_folder}")

    try:
        archiver = ContentArchivePolicy(_get_config("source"))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot connect to Mobius: {e}")

    results = {"archived": 0, "failed": 0, "errors": []}

    for filename in req.files:
        safe_file = re.sub(r'[^\w.\-]', '_', filename)
        filepath = folder_path / safe_file
        if not filepath.is_file():
            results["failed"] += 1
            results["errors"].append(f"File not found: {safe_file}")
            continue

        try:
            status = archiver.archive_policy(str(filepath), req.policy_name)

            if status and 200 <= status < 300:
                results["archived"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(f"{safe_file}: HTTP {status}")
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"{safe_file}: {str(e)}")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# MIGRATE — List objects on source or target
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/migrate/{object_type}")
def list_objects(object_type: str, repo: str = "source"):
    """List objects of the given type on source or target."""
    try:
        items = _list_objects(object_type, repo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Mobius API error: {e}")

    normalized = []
    for it in items:
        item_id = it.get("id") or ""
        item_name = it.get("name") or ""
        # For content classes, id is the operational key (e.g. "AC001")
        # and name is the description (e.g. "AC001 is a shipped sample")
        primary = item_id or item_name
        description = item_name if item_id else ""
        normalized.append({"name": primary, "description": description, "raw": it})

    return {"count": len(normalized), "items": normalized}


def _get_cc_nav_folder_id(config, cc_id: str):
    """Find the navigation objectId for a content class (to check versions).
    
    Returns the objectId if found, None otherwise.
    """
    # Keep this aligned with ContentClassNavigator (working path in contentedge/lib)
    NAV_ACCEPT = 'application/vnd.asg-mobius-navigation.v1+json'
    
    headers = deepcopy(config.headers)
    headers['Accept'] = NAV_ACCEPT
    
    # 1. Find the 'Content Classes' root folder
    try:
        url = f"{config.repo_url}/repositories/{config.repo_id}/children?limit=200"
        r = requests.get(url, headers=headers, verify=False, timeout=5)
        if r.status_code != 200:
            return None
        cc_root_id = None
        for item in r.json().get('items', []):
            name = str(item.get('name', '')).strip().lower()
            if name == 'content classes':
                cc_root_id = item.get('objectId')
                break
        if not cc_root_id:
            return None
        
        # 2. Locate the specific CC folder
        locate_url = (
            f"{config.repo_url}/folders/{cc_root_id}/children"
            f"?limit=1&locate={cc_id}"
        )
        r2 = requests.get(locate_url, headers=headers, verify=False, timeout=5)
        if r2.status_code != 200:
            return None
        for item in r2.json().get('items', []):
            if str(item.get('name', '')).strip() == cc_id:
                return item.get('objectId')
        return None
    except Exception:
        return None


def _cc_has_versions(config, cc_nav_oid: str) -> bool:
    """Check if a content class has any archived versions."""
    NAV_ACCEPT = 'application/vnd.asg-mobius-navigation.v1+json'
    
    try:
        headers = deepcopy(config.headers)
        headers['Accept'] = NAV_ACCEPT
        url = f"{config.repo_url}/folders/{cc_nav_oid}/children?limit=1"
        r = requests.get(url, headers=headers, verify=False, timeout=5)
        if r.status_code != 200:
            return False
        items = r.json().get('items', [])
        return len(items) > 0
    except Exception:
        return False


def _filter_content_classes_with_versions(content_classes: list, config) -> list:
    """Filter content classes to only include those with at least one version."""
    if not content_classes:
        return []

    NAV_ACCEPT = 'application/vnd.asg-mobius-navigation.v1+json'
    headers = deepcopy(config.headers)
    headers['Accept'] = NAV_ACCEPT

    # Resolve the "Content Classes" root once instead of once per content class.
    root_url = f"{config.repo_url}/repositories/{config.repo_id}/children?limit=200"
    r = requests.get(root_url, headers=headers, verify=False, timeout=5)
    if r.status_code != 200:
        return []

    cc_root_id = None
    for item in r.json().get('items', []):
        name = str(item.get('name', '')).strip().lower()
        if name == 'content classes':
            cc_root_id = item.get('objectId')
            break

    if not cc_root_id:
        return []

    def _has_versions(cc: dict) -> dict | None:
        cc_id = str(cc.get('id', '')).strip()
        if not cc_id:
            return None

        locate_url = (
            f"{config.repo_url}/folders/{cc_root_id}/children"
            f"?limit=1&locate={cc_id}"
        )
        r2 = requests.get(locate_url, headers=headers, verify=False, timeout=4)
        if r2.status_code != 200:
            return None

        cc_folder_id = None
        for item in r2.json().get('items', []):
            if str(item.get('name', '')).strip() == cc_id:
                cc_folder_id = item.get('objectId')
                break
        if not cc_folder_id:
            return None

        versions_url = f"{config.repo_url}/folders/{cc_folder_id}/children?limit=1"
        r3 = requests.get(versions_url, headers=headers, verify=False, timeout=4)
        if r3.status_code != 200:
            return None

        return cc if r3.json().get('items', []) else None

    filtered = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for result in ex.map(_has_versions, content_classes):
            if result is not None:
                filtered.append(result)

    # Return strict filtered result only.
    return filtered


def _list_objects(object_type: str, repo: str) -> list:
    """Dispatch to the correct admin class list method."""
    if object_type == "archiving_policies":
        return _get_policy_admin(repo).list_archiving_policies()
    elif object_type == "content_classes":
        # Performance/stability mode: do not verify versions; return all content classes.
        return _get_cc_admin(repo).list_content_classes()
    elif object_type == "indexes":
        return _get_index_admin(repo).list_indexes()
    elif object_type == "index_groups":
        return _get_ig_admin(repo).list_index_groups()
    else:
        raise ValueError(f"Unknown object type: {object_type}")


# ═══════════════════════════════════════════════════════════════════════════
# MIGRATE — Transfer objects from source to target
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/migrate")
def migrate_objects(req: MigrateRequest):
    """Export objects from source and import them to target."""
    results = {"migrated": 0, "skipped": 0, "failed": 0, "errors": []}

    try:
        if req.object_type == "archiving_policies":
            _migrate_policies(req, results)
        elif req.object_type == "content_classes":
            _migrate_content_classes(req, results)
        elif req.object_type == "indexes":
            _migrate_indexes(req, results)
        elif req.object_type == "index_groups":
            _migrate_index_groups(req, results)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown object type: {req.object_type}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Migration error: {e}")

    return results


def _migrate_policies(req: MigrateRequest, results: dict):
    source_admin = _get_policy_admin("source")
    target_admin = _get_policy_admin("target")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Export all matching policies from source
        source_admin.export_archiving_policies("*", tmpdir)

        for name in req.names:
            policy_file = Path(tmpdir) / f"{name}.json"
            if not policy_file.is_file():
                results["failed"] += 1
                results["errors"].append(f"{name}: not found in source export")
                continue

            # Check if exists on target
            if not req.replace_existing and target_admin.verify_archiving_policy(name):
                results["skipped"] += 1
                results["errors"].append(f"{name}: already exists on target (skipped)")
                continue

            # Delete on target if replacing
            if req.replace_existing and target_admin.verify_archiving_policy(name):
                target_admin.delete_archiving_policy(name)

            status = target_admin.import_archiving_policy(str(policy_file), name)
            if status and 200 <= status < 300:
                results["migrated"] += 1
            elif status == 409:
                results["skipped"] += 1
                results["errors"].append(f"{name}: already exists (409)")
            else:
                results["failed"] += 1
                results["errors"].append(f"{name}: import returned HTTP {status}")


def _migrate_content_classes(req: MigrateRequest, results: dict):
    source_admin = _get_cc_admin("source")
    target_admin = _get_cc_admin("target")

    with tempfile.TemporaryDirectory() as tmpdir:
        exported_file = source_admin.export_content_classes("*", tmpdir)
        if not exported_file or not Path(exported_file).is_file():
            results["failed"] += len(req.names)
            results["errors"].append("Failed to export content classes from source")
            return

        with open(exported_file, "r", encoding="utf-8") as f:
            all_classes = json.load(f)

        for name in req.names:
            cc = next((c for c in all_classes if c.get("id") == name or c.get("name") == name), None)
            if not cc:
                results["failed"] += 1
                results["errors"].append(f"{name}: not found in source export")
                continue

            cc_id = cc.get("id", name)
            if not req.replace_existing and target_admin.verify_content_class(cc_id):
                results["skipped"] += 1
                results["errors"].append(f"{cc_id}: already exists on target (skipped)")
                continue

            if req.replace_existing and target_admin.verify_content_class(cc_id):
                target_admin.delete_content_class(cc_id)

            status = target_admin.import_content_class(cc)
            if status and 200 <= status < 300:
                results["migrated"] += 1
            elif status == 409:
                results["skipped"] += 1
                results["errors"].append(f"{cc_id}: already exists (409)")
            else:
                results["failed"] += 1
                results["errors"].append(f"{cc_id}: import returned HTTP {status}")


def _migrate_indexes(req: MigrateRequest, results: dict):
    source_admin = _get_index_admin("source")
    target_admin = _get_index_admin("target")

    with tempfile.TemporaryDirectory() as tmpdir:
        exported_file = source_admin.export_indexes("*", tmpdir)
        if not exported_file or not Path(exported_file).is_file():
            results["failed"] += len(req.names)
            results["errors"].append("Failed to export indexes from source")
            return

        with open(exported_file, "r", encoding="utf-8") as f:
            all_indexes = json.load(f)

        for name in req.names:
            idx = next((i for i in all_indexes if i.get("id") == name or i.get("name") == name), None)
            if not idx:
                results["failed"] += 1
                results["errors"].append(f"{name}: not found in source export")
                continue

            idx_id = idx.get("id", name)
            if not req.replace_existing and target_admin.verify_index(idx_id):
                results["skipped"] += 1
                results["errors"].append(f"{idx_id}: already exists on target (skipped)")
                continue

            if req.replace_existing and target_admin.verify_index(idx_id):
                target_admin.delete_index(idx_id)

            status = target_admin.import_index(idx)
            if status and 200 <= status < 300:
                results["migrated"] += 1
            elif status == 409:
                results["skipped"] += 1
                results["errors"].append(f"{idx_id}: already exists (409)")
            else:
                results["failed"] += 1
                results["errors"].append(f"{idx_id}: import returned HTTP {status}")


def _migrate_index_groups(req: MigrateRequest, results: dict):
    source_admin = _get_ig_admin("source")
    target_admin = _get_ig_admin("target")

    with tempfile.TemporaryDirectory() as tmpdir:
        exported_file = source_admin.export_index_groups("*", tmpdir)
        if not exported_file or not Path(exported_file).is_file():
            results["failed"] += len(req.names)
            results["errors"].append("Failed to export index groups from source")
            return

        with open(exported_file, "r", encoding="utf-8") as f:
            all_groups = json.load(f)

        for name in req.names:
            ig = next((g for g in all_groups if g.get("id") == name or g.get("name") == name), None)
            if not ig:
                results["failed"] += 1
                results["errors"].append(f"{name}: not found in source export")
                continue

            ig_id = ig.get("id", name)
            if not req.replace_existing and target_admin.verify_index_group(ig_id):
                results["skipped"] += 1
                results["errors"].append(f"{ig_id}: already exists on target (skipped)")
                continue

            if req.replace_existing and target_admin.verify_index_group(ig_id):
                target_admin.delete_index_group(ig_id)

            status = target_admin.import_index_group(ig)
            if status and 200 <= status < 300:
                results["migrated"] += 1
            elif status == 409:
                results["skipped"] += 1
                results["errors"].append(f"{ig_id}: already exists (409)")
            else:
                results["failed"] += 1
                results["errors"].append(f"{ig_id}: import returned HTTP {status}")


# ═══════════════════════════════════════════════════════════════════════════
# MIGRATE via vdrdbxml — Prepare XML + submit plan
# ═══════════════════════════════════════════════════════════════════════════

VDRDBXML_FILES_DIR = _APP_ROOT / "worker" / "files"


def _vdr_timestamp() -> str:
    """Timestamp used in vdrdbxml artifacts: YYYY-MM-DD.HH.mm.ss."""
    return datetime.now().strftime("%Y-%m-%d.%H.%M.%S")


def _build_selected_definitions_xml(
    content_classes: list[str],
    indexes: list[str],
    index_groups: list[str],
    archiving_policies: list[str],
) -> str:
    """Build a VDRNET_DB_MASS_UPDATE XML for the selected items."""
    lines = ['<?xml version="1.0" ?>']
    lines.append('<VDRNET_DB_MASS_UPDATE VDRNET_VERSION="4.1">')
    lines.append('')
    for cc in content_classes:
        lines.append(f'<REPORT action="get" outAction="add/modify">')
        lines.append(f' <REPORT_ID>{cc}</REPORT_ID>')
        lines.append(f'</REPORT>')
        lines.append('')
    for idx in indexes:
        lines.append(f'<TOPIC action="get" outAction="add/modify">')
        lines.append(f' <TOPIC_ID>{idx}</TOPIC_ID>')
        lines.append(f'</TOPIC>')
        lines.append('')
    for ig in index_groups:
        lines.append(f'<TOPIC_GROUP action="get" outAction="add/modify">')
        lines.append(f' <TOPIC_GROUP_ID>{ig}</TOPIC_GROUP_ID>')
        lines.append(f'</TOPIC_GROUP>')
        lines.append('')
    for pol in archiving_policies:
        lines.append(f'<POLICY action="get" outAction="add/modify">')
        lines.append(f' <POLICY_NAME>{pol}</POLICY_NAME>')
        lines.append(f'</POLICY>')
        lines.append('')
    lines.append('</VDRNET_DB_MASS_UPDATE>')
    return '\n'.join(lines)


@app.post("/api/migrate/prepare-xml")
def migrate_prepare_xml(req: MigrateVdrdbxmlRequest):
    """Prepare timestamped vdrdbxml XML files in /workspace/export-import and return plan steps."""
    import re as _re
    import shutil

    safe_worker = _re.sub(r'[^a-zA-Z0-9_-]', '', req.worker)
    EXPORT_IMPORT_DIR.mkdir(parents=True, exist_ok=True)

    ts = _vdr_timestamp()
    base_name = f"vdrdbxml_{safe_worker}_{ts}"

    worker_base = "/workspace/export-import"

    if req.mode == "all":
        # Copy template XML to export-import directory with timestamped filename
        src = VDRDBXML_FILES_DIR / "get_all_definitions.xml"
        if not src.is_file():
            raise HTTPException(status_code=500, detail="get_all_definitions.xml not found in image")
        xml_filename = f"{base_name}_get_all_definitions.xml"
        dest = EXPORT_IMPORT_DIR / xml_filename
        shutil.copy2(str(src), str(dest))
    elif req.mode == "specific":
        total = len(req.content_classes) + len(req.indexes) + len(req.index_groups) + len(req.archiving_policies)
        if total == 0:
            raise HTTPException(status_code=400, detail="No items selected for specific migration")
        xml_content = _build_selected_definitions_xml(
            req.content_classes, req.indexes, req.index_groups, req.archiving_policies,
        )
        xml_filename = f"{base_name}_get_selected_definitions.xml"
        dest = EXPORT_IMPORT_DIR / xml_filename
        dest.write_text(xml_content, encoding="utf-8")
    else:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {req.mode}")

    export_out_filename = f"{base_name}_export_out.xml"
    import_out_filename = f"{base_name}_import_out.xml"

    # Load vdrdbxml template (use request override or env default)
    template = req.template.strip() if req.template.strip() else os.environ.get(
        "VDRDBXML_TEMPLATE",
        "vdrdbxml -s {REPO_NAME} -u {SERVER_USER} -f {XML_INPUT_FILE_PATH} -out {XML_OUTPUT_FILE_PATH} -v 2"
    )

    # Resolve repo credentials for SOURCE (export) and TARGET (import)
    source_cfg = mrc_repo_config("source")
    target_cfg = mrc_repo_config("target")

    def _resolve(tpl, cfg, in_path, out_path):
        return (tpl
            .replace("{REPO_NAME}", cfg["repo_name"])
            .replace("{SERVER_USER}", cfg["server_user"])
            .replace("{SERVER_PASS}", cfg["server_pass"])
            .replace("{XML_INPUT_FILE_PATH}", in_path)
            .replace("{XML_OUTPUT_FILE_PATH}", out_path)
        )

    export_cmd = _resolve(template, source_cfg,
        f"{worker_base}/{xml_filename}", f"{worker_base}/{export_out_filename}")
    import_cmd = _resolve(template, target_cfg,
        f"{worker_base}/{export_out_filename}", f"{worker_base}/{import_out_filename}")

    return {
        "ok": True,
        "xml_file": f"{worker_base}/{xml_filename}",
        "export_out_file": f"{worker_base}/{export_out_filename}",
        "import_out_file": f"{worker_base}/{import_out_filename}",
        "steps": [
            {"repo": "SOURCE", "operation": "vdrdbxml", "command": export_cmd},
            {"repo": "TARGET", "operation": "vdrdbxml", "command": import_cmd},
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
# REMOVE DEFINITIONS — Prepare list files + plan steps
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/remove-definitions/prepare")
def remove_definitions_prepare(req: RemoveDefinitionsRequest):
    """Write list files to the worker's tasks dir and return rm-definitions plan steps."""
    import re as _re

    safe_worker = _re.sub(r'[^a-zA-Z0-9_-]', '', req.worker)
    tasks_dir = WORKSPACE_ROOT / safe_worker / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    repo = req.repo.upper()
    if repo not in ("SOURCE", "TARGET"):
        raise HTTPException(status_code=400, detail=f"Invalid repo: {req.repo}")

    worker_base = f"/workspace/{safe_worker}/tasks"

    # Map: (object_type_label, list_of_ids, filename)
    # Use .lst extension so the worker doesn't treat these as task step files
    categories = [
        ("ARCHIVING_POLICY", req.archiving_policies, "rm_archiving_policies.lst"),
        ("CONTENT_CLASS", req.content_classes, "rm_content_classes.lst"),
        ("INDEX_GROUP", req.index_groups, "rm_index_groups.lst"),
        ("INDEX", req.indexes, "rm_indexes.lst"),
    ]

    steps = []
    files_written = []

    for obj_type, ids, filename in categories:
        if not ids:
            continue
        # Write list file
        list_path = tasks_dir / filename
        list_path.write_text("\n".join(ids) + "\n", encoding="utf-8")
        files_written.append(filename)
        # Build command
        cmd = f"{obj_type} {worker_base}/{filename}"
        steps.append({
            "repo": repo,
            "operation": "rm-definitions",
            "command": cmd,
        })

    if not steps:
        raise HTTPException(status_code=400, detail="No items selected for removal")

    return {
        "ok": True,
        "files": files_written,
        "steps": steps,
    }


# ═══════════════════════════════════════════════════════════════════════════
# INTERNAL: Build Mobius-format archiving policy JSON
# ═══════════════════════════════════════════════════════════════════════════

def _build_policy_json(config: PolicyConfig) -> dict:
    """Build a complete Mobius v3.0 archiving policy JSON from the UI config."""

    # ── documentInfo ──
    document_info = {
        "documentID": None,
        "useAllSections": False,
        "useLastVersion": False,
        "parsingInfo": {
            "dataType": "Text",
            "charSet": "ASCII",
            "pageBreak": {"type": "FORMFEED", "fixedPageLength": 0, "markers": None, "columns": None},
            "lineBreak": {"type": "CRLF", "fixedLineLength": 0},
            "jdlResource": None, "jdeResource": None,
            "useJslPageSettings": False, "propagateTleRecords": False,
            "externalResources": None, "columnDelimiter": None, "textEnclosure": None,
            "alfFormat": 0, "processHiddenText": False, "useOCR": False,
            "filepath": f"workspace/{config.source_folder}/{config.source_file}",
            "lastModified": None,
        },
    }

    # ── fields ──
    fields = []
    for f in config.fields:
        f_type = "string"
        fmt = f.format or ""
        if fmt and any(p in fmt.upper() for p in ("DD", "MM", "YY")):
            f_type = "date"

        right = float(f.column + f.length - 1) if f.length > 0 else 0.0

        field = {
            "name": f.name,
            "type": f_type,
            "levelType": "header1",
            "allowBlank": False,
            "useRetainedValue": False,
            "parsingInfo": {
                "position": {"left": float(f.column), "right": right, "top": float(f.line), "bottom": 0.0},
                "format": fmt,
                "minLength": 0, "maxLength": 0, "minValue": "", "maxValue": "",
                "terminator": " ",
                "matchValuesUsage": "", "matchValues": [], "useWildCard": False,
                "discardIncompleteWords": True,
            },
            "outputInfo": {
                "hide": False, "date_pattern": 0, "sequence": 0, "display_length": 0,
                "alignment": "L",
                "outputFormat": "YYYYMMDD" if (f_type == "date" and f.name == config.mapping.version_field) else "",
                "changeCaseTo": "", "removeSpaces": "", "padChar": "",
                "minLength": 0, "maxLength": 0,
                "useLookupTable": False, "lookupTable": [],
                "useThousandSeparator": "O",
            },
            "dependencies": [],
            "isExternal": False,
        }
        fields.append(field)

    # ── auto REPORT_LABEL field (for REPORT_ID group) ──
    fields.append({
        "name": "REPORT_LABEL",
        "type": "string",
        "levelType": "header1",
        "allowBlank": False,
        "useRetainedValue": False,
        "parsingInfo": {
            "position": {"left": 1.0, "right": 20.0, "top": 1.0, "bottom": 0.0},
            "format": "",
            "minLength": 0, "maxLength": 0, "minValue": "", "maxValue": "",
            "terminator": "\n",
            "matchValuesUsage": "", "matchValues": [], "useWildCard": False,
            "discardIncompleteWords": True,
        },
        "outputInfo": {
            "hide": False, "date_pattern": 0, "sequence": 0, "display_length": 0,
            "alignment": "L", "outputFormat": "",
            "changeCaseTo": "", "removeSpaces": "", "padChar": "",
            "minLength": 0, "maxLength": 0,
            "useLookupTable": True,
            "lookupTable": [{"name": "ASGLookupTableDefault", "value": config.content_class}],
            "useThousandSeparator": "O",
        },
        "dependencies": [],
        "isExternal": False,
    })

    # ── fieldGroups ──
    def _make_group(name: str, usage: str, field_names: list[str]) -> dict:
        return {
            "name": name, "retainFieldValues": True, "isDefault": False, "hide": False,
            "fieldRefs": [
                {"ruleName": "$Default$", "fieldName": fn, "optional": False, "hideDuplicateValues": False}
                for fn in field_names
            ],
            "usage": usage,
            "requiredOccurrence": None, "stopIfMissing": False, "useLocationIndex": False,
            "scope": None, "filter": None, "sort": None,
            "consolidateMatchingRows": False, "includeHiddenFields": False,
            "aggregationTotalTag": "Total",
        }

    field_groups = [
        _make_group("REPORT_ID", "1", ["REPORT_LABEL"]),
    ]
    if config.mapping.section_fields:
        field_groups.append(_make_group("Group_SECTION", "2", config.mapping.section_fields))
    if config.mapping.version_field:
        field_groups.append(_make_group("Group_VERSION", "5", [config.mapping.version_field]))

    # ── complete policy ──
    return {
        "name": config.policy_name,
        "version": "3.0",
        "scope": "page",
        "pageRange": "All",
        "keepBlankRows": True,
        "keepAnsiCCBlankRows": False,
        "textOnlyMode": False,
        "decimalSeparator": None,
        "enableCalculatedFields": False,
        "calculatedFields": None,
        "enableAggregation": False,
        "rules": [{
            "name": "$Default$", "type": "Region", "ruleid": 1,
            "mask": "", "positionByMask": False, "enabled": True,
            "region": {
                "position": None, "stretchHeight": False, "stretchWidth": False,
                "startAnchor": None, "endAnchor": None,
                "wordSpacingThreshold": 0.0, "lineSpacingThreshold": 35.0,
            },
            "fields": fields,
        }],
        "fieldGroups": field_groups,
        "pageBindInfo": {"scaleFactorX": 1.0, "scaleFactorY": 1.0, "offsetX": 0.0, "offsetY": 0.0},
        "ruleMatchLists": [],
        "regionBindInfoList": [],
        "sorts": [],
        "enableEnhancedFieldLevelJoining": False,
        "defaultDateComponentOrder": "M/D/Y",
        "cutoffForTwoDigitYear": 1980,
        "requireMatchForFieldExtraction": True,
        "sampleFile": None,
        "documentInfo": document_info,
        "description": f"Archiving policy {config.policy_name}",
        "locationIndexScope": None,
        "metadataFields": {"fields": [], "values": []},
        "compatibility": 0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════════════════════════
@app.get("/api/repos")
def list_repos():
    """List available repositories (source is always available; target if configured)."""
    repos = ["source"]
    try:
        status = _repo_runtime_status("target")
        if status.get("active"):
            repos.append("target")
    except Exception:
        pass
    return {"repos": repos}


@app.get("/api/policies/generated")
def list_generated_policies():
    """List generated policy JSON files in workspace/tmp/."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(TMP_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() == ".json":
            files.append({"name": f.stem, "filename": f.name, "size": f.stat().st_size})
    return {"policies": files}


@app.get("/api/policies/exists")
def policy_exists(name: str, repo: str = "source"):
    """Check if a policy with the given name exists in the repository."""
    try:
        admin = _get_policy_admin(repo)
        items = admin.list_archiving_policies()
        exists = any(p.get("name", "").lower() == name.lower() for p in items)
        return {"name": name, "repo": repo, "exists": exists}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Mobius API error: {e}")

@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/api/agent/info")
def agent_info():
    """Expose agent chat endpoints for the global UI shortcut."""
    anythingllm_port = int(os.environ.get("ANYTHINGLLM_PORT", "3001"))
    agent_port = int(os.environ.get("AGENT_PORT", "8000"))

    def _is_agent_active() -> bool:
        # When running inside docker compose, service DNS name is preferred.
        # Fallback to localhost for non-compose/local runs.
        candidates = [
            f"http://agent-api:{agent_port}/health",
            f"http://localhost:{agent_port}/health",
        ]
        for url in candidates:
            try:
                with urllib.request.urlopen(url, timeout=1.5) as resp:
                    if int(getattr(resp, "status", 0)) == 200:
                        return True
            except (urllib.error.URLError, TimeoutError, ValueError):
                continue
        return False

    return {
        "enabled": _is_agent_active(),
        "anythingllm_port": anythingllm_port,
        "agent_api_port": agent_port,
    }


# ═══════════════════════════════════════════════════════════════════════════
# WORKERS — heartbeat discovery + plan submission
# ═══════════════════════════════════════════════════════════════════════════

_HEARTBEAT_MAX_AGE_SECONDS = 60
_HEARTBEAT_BUSY_MAX_AGE_SECONDS = 600  # 10 min — allow for long-running tasks

@app.get("/api/workers")
def list_workers():
    """Discover active workers by scanning workspace/*/status.json."""
    workers = []
    now = datetime.now()
    for child in sorted(WORKSPACE_ROOT.iterdir()):
        status_file = child / "status.json"
        if not status_file.is_file():
            continue
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            hb = datetime.fromisoformat(data.get("last_heartbeat", ""))
            age = (now - hb).total_seconds()
            pending = data.get("pending_tasks", 0) + data.get("pending_plans", 0)
            if age < _HEARTBEAT_MAX_AGE_SECONDS:
                data["alive"] = True
                data["busy"] = pending > 0
            elif pending > 0 and age < _HEARTBEAT_BUSY_MAX_AGE_SECONDS:
                data["alive"] = True
                data["busy"] = True
            else:
                data["alive"] = False
                data["busy"] = False
            data["age_seconds"] = round(age, 1)
            workers.append(data)
        except Exception:
            continue
    return workers


@app.get("/api/workers/{worker}/xml-files")
def list_worker_xml_files(worker: str):
    """List .xml files in a worker's workspace directory (recursive)."""
    import re as _re
    safe = _re.sub(r'[^a-zA-Z0-9_-]', '', worker)
    worker_dir = WORKSPACE_ROOT / safe
    if not worker_dir.is_dir():
        return {"files": []}
    files = []
    for f in sorted(worker_dir.rglob("*.xml")):
        rel = f.relative_to(worker_dir)
        files.append({
            "name": str(rel).replace("\\", "/"),
            "path": f"/workspace/{safe}/{str(rel).replace(chr(92), '/')}",
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return {"files": files}


@app.get("/api/workers/{worker}/tasks")
def list_worker_tasks(worker: str):
    """List task files for a given worker (done, error, debug, pending)."""
    import re as _re
    safe = _re.sub(r'[^a-zA-Z0-9_-]', '', worker)
    tasks_dir = WORKSPACE_ROOT / safe / "tasks"
    if not tasks_dir.is_dir():
        return []
    results = []
    for f in sorted(tasks_dir.iterdir()):
        if f.is_file():
            results.append({
                "name": f.name,
                "suffix": f.suffix,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    return results


@app.get("/api/workers/{worker}/logs")
def list_worker_logs(worker: str):
    """List log files for a given worker."""
    import re as _re
    safe = _re.sub(r'[^a-zA-Z0-9_-]', '', worker)
    logs_dir = WORKSPACE_ROOT / safe / "logs"
    if not logs_dir.is_dir():
        return []
    results = []
    for f in sorted(logs_dir.iterdir()):
        if f.is_file():
            results.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    return results


@app.get("/api/workers/{worker}/logs/{filename}")
def read_worker_log(worker: str, filename: str):
    """Read the content of a specific log file."""
    import re as _re
    safe_worker = _re.sub(r'[^a-zA-Z0-9_-]', '', worker)
    safe_file = _re.sub(r'[^a-zA-Z0-9_.\-]', '', filename)
    log_path = WORKSPACE_ROOT / safe_worker / "logs" / safe_file
    if not log_path.is_file():
        raise HTTPException(status_code=404, detail="Log file not found")
    return {"filename": safe_file, "content": log_path.read_text(encoding="utf-8", errors="replace")}


@app.get("/api/workers/{worker}/log-tail")
def tail_worker_log(worker: str, lines: int = 80):
    """Return the last N lines of the worker's main worker.log file."""
    import re as _re
    safe_worker = _re.sub(r'[^a-zA-Z0-9_-]', '', worker)
    log_path = WORKSPACE_ROOT / safe_worker / "logs" / "worker.log"
    if not log_path.is_file():
        return {"worker": safe_worker, "lines": [], "total_lines": 0}

    lines = max(1, min(lines, 500))
    all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = all_lines[-lines:]
    return {"worker": safe_worker, "lines": tail, "total_lines": len(all_lines)}


@app.post("/api/workers/plan")
def submit_plan(req: SubmitPlanRequest):
    """Write a plan CSV to the worker's plan directory."""
    import re as _re
    safe_worker = _re.sub(r'[^a-zA-Z0-9_-]', '', req.worker)
    plan_dir = WORKSPACE_ROOT / safe_worker / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _re.sub(r'[^a-zA-Z0-9_.\-]', '', req.plan_name)
    if not safe_name:
        safe_name = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if not safe_name.endswith('.csv'):
        safe_name += '.csv'

    plan_path = plan_dir / safe_name
    lines = ["REPO,OPERATION,COMMAND"]
    for step in req.steps:
        repo = step.repo.upper()
        if repo not in ("SOURCE", "TARGET"):
            raise HTTPException(status_code=400, detail=f"Invalid REPO: {step.repo}")
        op = step.operation.lower()
        if op not in ("acreate", "vdrdbxml", "adelete", "rm-definitions"):
            raise HTTPException(status_code=400, detail=f"Invalid OPERATION: {step.operation}")
        lines.append(f"{repo},{op},{step.command}")

    plan_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "file": str(plan_path), "steps": len(req.steps)}


# ═══════════════════════════════════════════════════════════════════════════
# MobiusRemoteCLI — repo config + adelete template
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/mrc/repo-config")
def mrc_repo_config(repo: str = "source"):
    """Return non-sensitive repo config values for command template substitution."""
    prefix = "CE_TARGET_" if repo.lower() in ("target", "secondary") else "CE_SOURCE_"
    repo_name = os.environ.get(f"{prefix}REPO_NAME", "")
    server_user = os.environ.get(f"{prefix}REPO_SERVER_USER", "")
    server_pass = os.environ.get(f"{prefix}REPO_SERVER_PASS", "")
    repo_url = os.environ.get(f"{prefix}REPO_URL", "")
    return {
        "repo": repo,
        "repo_name": repo_name,
        "server_user": server_user,
        "server_pass": server_pass,
        "repo_url": repo_url,
        "active": bool(repo_url and repo_name),
    }


@app.get("/api/mrc/repos-status")
def mrc_repos_status():
    """Return active status for both SOURCE and TARGET repos."""
    return {
        "source": _repo_runtime_status("source"),
        "target": _repo_runtime_status("target"),
    }


@app.get("/api/mrc/adelete-template")
def mrc_adelete_template():
    """Return the ADELETE_TEMPLATE from environment."""
    template = os.environ.get(
        "ADELETE_TEMPLATE",
        "adelete -s {REPO_NAME} -u {SERVER_USER} -r {CONTENT_CLASS} -c -n -y ALL -o"
    )
    return {"template": template}


@app.get("/api/mrc/acreate-template")
def mrc_acreate_template():
    """Return the ACREATE_TEMPLATE from environment."""
    template = os.environ.get(
        "ACREATE_TEMPLATE",
        "acreate -f {FILE_PATH} -s {REPO_NAME} -u {SERVER_USER} -r {CONTENT_CLASS} -c {POLICY_NAME} -v 2"
    )
    return {"template": template}


@app.get("/api/mrc/acreate-list-template")
def mrc_acreate_list_template():
    """Return the ACREATE_LIST_TEMPLATE from environment (list mode)."""
    template = os.environ.get(
        "ACREATE_LIST_TEMPLATE",
        "acreate -f {FILE_PATH} -s {REPO_NAME} -u {SERVER_USER} -v 2"
    )
    return {"template": template}


@app.get("/api/mrc/vdrdbxml-template")
def mrc_vdrdbxml_template():
    """Return the VDRDBXML_TEMPLATE from environment."""
    template = os.environ.get(
        "VDRDBXML_TEMPLATE",
        "vdrdbxml -s {REPO_NAME} -u {SERVER_USER} -f {XML_INPUT_FILE_PATH} -out {XML_OUTPUT_FILE_PATH} -v 2"
    )
    return {"template": template}


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATE LST FILES — Parse and validate .lst / archive-list files
# ═══════════════════════════════════════════════════════════════════════════

class ValidateLstRequest(BaseModel):
    files: list[str]       # full paths like "/data/folder/file.lst" or "workspace_folder/file.lst"
    source: str            # "data" or "workspace"
    folder_path: str       # folder containing the .lst files
    repo: str = "source"   # repository to check indexes against


def _resolve_lst_file_path(file_path: str, source: str, folder_path: str) -> Path:
    """Resolve the actual filesystem path for an .lst file."""
    if source == "data":
        # file_path comes as "/data/folder/file.lst" — strip the /data/ prefix
        rel = file_path
        if rel.startswith("/data/"):
            rel = rel[6:]  # strip "/data/"
        elif rel.startswith("/"):
            rel = rel[1:]
        return DATA_ROOT / rel
    else:
        return WORKSPACE_ROOT / file_path


def _parse_lst_content(content: str) -> list[dict]:
    """Parse an LST file into a list of document entries.

    Each entry starts with a REPORT-ID= line and contains FILE=, TOPIC-ID= lines.
    Returns a list of dicts with keys: report_id, version, file_path, file_type,
    section, encoding, topics (list of {id, item}).
    """
    entries = []
    current = None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("REPORT-ID="):
            # Save previous entry
            if current is not None:
                entries.append(current)
            # Parse header: REPORT-ID=Name, VERSION=xxx (optional)
            current = {"report_id": "", "version": "", "file_path": "", "file_type": "",
                        "section": "", "encoding": "", "topics": [], "raw_lines": [raw_line]}
            parts = [p.strip() for p in line.split(",")]
            for part in parts:
                if part.startswith("REPORT-ID="):
                    current["report_id"] = part[len("REPORT-ID="):]
                elif part.startswith("VERSION="):
                    current["version"] = part[len("VERSION="):]

        elif line.startswith("FILE=") and current is not None:
            current["raw_lines"].append(raw_line)
            parts = [p.strip() for p in line.split(",")]
            for part in parts:
                if part.startswith("FILE="):
                    current["file_path"] = part[len("FILE="):]
                elif part.startswith("TYPE="):
                    current["file_type"] = part[len("TYPE="):]
                elif part.startswith("SECTION="):
                    current["section"] = part[len("SECTION="):]
                elif part.startswith("ENCODING="):
                    current["encoding"] = part[len("ENCODING="):]

        elif line.startswith("TOPIC-ID=") and current is not None:
            current["raw_lines"].append(raw_line)
            parts = [p.strip() for p in line.split(",")]
            topic_id = ""
            topic_item = ""
            for part in parts:
                if part.startswith("TOPIC-ID="):
                    topic_id = part[len("TOPIC-ID="):]
                elif part.startswith("TOPIC-ITEM="):
                    topic_item = part[len("TOPIC-ITEM="):]
            if topic_id:
                current["topics"].append({"id": topic_id, "item": topic_item})

        elif current is not None:
            current["raw_lines"].append(raw_line)

    if current is not None:
        entries.append(current)

    return entries


@app.post("/api/mrc/validate-lst")
def validate_lst_files(req: ValidateLstRequest):
    """Validate .lst archive-list files before adding to acreate plan.

    Checks:
    1. Format: REPORT-ID is required, VERSION is optional
    2. FILE= referenced files must exist; if not, tries lst file's own directory
    3. TOPIC-ID names are validated against indexes and index groups
    """
    # Load available indexes and index groups for validation
    try:
        raw_indexes = _list_objects("indexes", req.repo)
        index_names = {(it.get("id") or it.get("name", "")).lower() for it in raw_indexes}
    except Exception:
        index_names = set()

    try:
        raw_igs = _list_objects("index_groups", req.repo)
        ig_names = {(it.get("id") or it.get("name", "")).lower() for it in raw_igs}
        # Also collect member topic IDs from inside each index group
        ig_member_names = set()
        # Build mapping: member_id (lower) -> list of (group_name, set_of_all_member_ids)
        ig_member_to_group: dict[str, list[tuple[str, set[str]]]] = {}
        for ig in raw_igs:
            ig_id = ig.get("id") or ig.get("name", "")
            group_members = set()
            for topic in ig.get("topics", []):
                tid = (topic.get("id") or "").lower()
                if tid:
                    ig_member_names.add(tid)
                    group_members.add(tid)
            # Map each member to its group
            for m in group_members:
                ig_member_to_group.setdefault(m, []).append((ig_id, group_members))
    except Exception:
        ig_names = set()
        ig_member_names = set()
        ig_member_to_group = {}

    all_known_names = index_names | ig_names | ig_member_names
    results = []

    for file_rel in req.files:
        file_result = {
            "file": file_rel,
            "valid": True,
            "errors": [],
            "warnings": [],
            "fixes": [],
            "entries": [],
        }

        # Resolve absolute path
        abs_path = _resolve_lst_file_path(file_rel, req.source, req.folder_path)
        if not abs_path.is_file():
            file_result["valid"] = False
            file_result["errors"].append(f"LST file not found: {abs_path}")
            results.append(file_result)
            continue

        lst_dir = abs_path.parent

        # Read content
        try:
            raw = abs_path.read_bytes()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content = raw.decode("latin-1")
            if content.startswith("\ufeff"):
                content = content[1:]
        except Exception as e:
            file_result["valid"] = False
            file_result["errors"].append(f"Cannot read file: {e}")
            results.append(file_result)
            continue

        # Parse entries
        entries = _parse_lst_content(content)
        if not entries:
            file_result["valid"] = False
            file_result["errors"].append("No valid entries found (missing REPORT-ID= lines)")
            results.append(file_result)
            continue

        needs_rewrite = False
        new_lines = []

        for entry in entries:
            entry_info = {
                "report_id": entry["report_id"],
                "file_path": entry["file_path"],
                "file_ok": True,
                "file_fixed": False,
                "unknown_topics": [],
            }

            # Validate REPORT-ID
            if not entry["report_id"]:
                file_result["errors"].append("Entry missing REPORT-ID")
                file_result["valid"] = False

            # Validate FILE= exists
            ref_file = Path(entry["file_path"])
            if entry["file_path"]:
                if not ref_file.is_file():
                    # Try using the LST file's own directory
                    alt_path = lst_dir / ref_file.name
                    if alt_path.is_file():
                        old_path = entry["file_path"]
                        entry["_original_file"] = old_path
                        entry["file_path"] = str(alt_path)
                        entry_info["file_path"] = str(alt_path)
                        entry_info["file_fixed"] = True
                        file_result["fixes"].append(
                            f"FILE path changed: {old_path} → {alt_path}"
                        )
                        needs_rewrite = True
                    else:
                        entry_info["file_ok"] = False
                        file_result["errors"].append(
                            f"FILE not found: {entry['file_path']} (also tried {alt_path})"
                        )
                        file_result["valid"] = False
            else:
                entry_info["file_ok"] = False
                file_result["errors"].append("Entry missing FILE= path")
                file_result["valid"] = False

            # Validate TOPIC-IDs against indexes / index groups
            for topic in entry["topics"]:
                if topic["id"].lower() not in all_known_names:
                    entry_info["unknown_topics"].append(topic["id"])
                    file_result["warnings"].append(
                        f"TOPIC-ID '{topic['id']}' not found in indexes or index groups"
                    )

            # Validate index group completeness: if any member of an IG is
            # present, ALL members of that IG must be present in the entry.
            present_topics = {t["id"].lower() for t in entry["topics"]}
            checked_groups: set[str] = set()
            for topic in entry["topics"]:
                tid = topic["id"].lower()
                if tid in ig_member_to_group:
                    for ig_name, ig_members in ig_member_to_group[tid]:
                        if ig_name in checked_groups:
                            continue
                        checked_groups.add(ig_name)
                        missing = ig_members - present_topics
                        if missing:
                            missing_list = ", ".join(sorted(missing))
                            file_result["errors"].append(
                                f"Index group '{ig_name}' is incomplete: "
                                f"found member '{topic['id']}' but missing: {missing_list}"
                            )
                            file_result["valid"] = False

            entry_info["topic_count"] = len(entry["topics"])
            file_result["entries"].append(entry_info)

        # Rewrite the file if FILE= paths were fixed
        if needs_rewrite:
            try:
                rewritten = []
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("FILE="):
                        # Rebuild the FILE= line with corrected paths
                        parts = [p.strip() for p in stripped.split(",")]
                        new_parts = []
                        for part in parts:
                            if part.startswith("FILE="):
                                # Find the matching entry to get the fixed path
                                old_val = part[len("FILE="):]
                                for ent in entries:
                                    orig_ref = Path(old_val)
                                    if ent.get("_original_file") == old_val or orig_ref.name == Path(ent["file_path"]).name:
                                        new_parts.append(f"FILE={ent['file_path']}")
                                        break
                                else:
                                    new_parts.append(part)
                            else:
                                new_parts.append(part)
                        rewritten.append(", ".join(new_parts))
                    else:
                        rewritten.append(line)
                abs_path.write_text("\n".join(rewritten), encoding="utf-8")
            except Exception as e:
                file_result["warnings"].append(f"Could not rewrite file with fixed paths: {e}")

        results.append(file_result)

    return {
        "results": results,
        "index_count": len(index_names),
        "index_group_count": len(ig_names),
        "ig_member_count": len(ig_member_names),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8500)

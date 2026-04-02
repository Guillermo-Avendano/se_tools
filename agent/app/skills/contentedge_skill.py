"""ContentEdge skill — interact with the ContentEdge content repository directly.

Calls the ContentEdge Python library (contentedge/lib) in-process,
eliminating the MCP server overhead (SSE connections, handshakes,
double serialization, inter-container networking).
"""

import base64
import json
import os
import re
import time
import asyncio
from copy import deepcopy
from functools import partial
from typing import Any

import redis as sync_redis
import requests
import structlog
from langchain_core.tools import tool

from app.config import settings
from app.skills.base import SkillBase, SkillContext, WORKSPACE_ROOT, _load_prompt_file

logger = structlog.get_logger(__name__)


def _disabled_tool_response(tool_name: str) -> str:
    """Return a standard disabled response for agent-only tools."""
    return json.dumps(
        {
            "success": False,
            "disabled": True,
            "tool": tool_name,
            "message": "This operation is disabled in agent-api and handled by MobiusRemoteCLI (se_ce_tools).",
        },
        ensure_ascii=False,
    )

# ── Response formatting helpers ────────────────────────────────────────────

def _format_content_classes(classes: list, mode: str = "detailed") -> str:
    """Format content classes in simple or detailed mode."""
    if not classes:
        return "No content classes found."

    mode = (mode or "detailed").strip().lower()
    if mode == "simple":
        lines = ["| ID | Name |", "|---|---|"]
    else:
        lines = ["| ID | Name | Description |", "|---|---|---|"]

    for cc in classes:
        cc_id = cc.get("id", "").strip()
        cc_name = cc.get("name", "").strip()
        cc_desc = cc.get("description", "").strip()
        cc_desc = cc_desc.replace("|", "\\|") if cc_desc else ""
        if len(cc_desc) > 80:
            cc_desc = cc_desc[:77] + "..."

        if mode == "simple":
            lines.append(f"| `{cc_id}` | {cc_name} |")
        else:
            lines.append(f"| `{cc_id}` | {cc_name} | {cc_desc} |")
    
    return "\n".join(lines)


def _format_indexes(indexes: list, mode: str = "detailed") -> str:
    """Format indexes in simple or detailed mode."""
    if not indexes:
        return "No indexes found."

    mode = (mode or "detailed").strip().lower()
    if mode == "simple":
        lines = ["| ID | Name |", "|---|---|"]
    else:
        lines = [
            "| ID | Name | Data Type | Dimension | Format | Description |",
            "|---|---|---|---|---|---|",
        ]

    for idx in indexes:
        idx_name = idx.get("name", "").strip()
        idx_id = idx.get("id", "").strip()
        idx_dtype = idx.get("dataType", "").strip()
        idx_dim = str(idx.get("dimension", "")).strip()
        idx_fmt = str(idx.get("format", "")).strip()
        idx_desc = idx.get("description", "").strip()
        idx_desc = idx_desc.replace("|", "\\|") if idx_desc else ""
        if len(idx_desc) > 60:
            idx_desc = idx_desc[:57] + "..."

        if mode == "simple":
            lines.append(f"| `{idx_id}` | {idx_name} |")
        else:
            lines.append(
                f"| `{idx_id}` | {idx_name} | {idx_dtype} | {idx_dim} | {idx_fmt} | {idx_desc} |"
            )
    
    return "\n".join(lines)


def _format_index_groups(groups: list, mode: str = "detailed") -> str:
    """Format index groups in simple or detailed mode.

    Detailed mode renders one row per member index so users can see exactly
    which index belongs to which group.
    """
    if not groups:
        return "No index groups found."

    mode = (mode or "detailed").strip().lower()
    if mode == "simple":
        lines = ["| Group ID | Group Name | Members |", "|---|---|---|"]
    else:
        lines = [
            "| Group ID | Group Name | Index ID | Index Name | Data Type | Dimension | Format | Description |",
            "|---|---|---|---|---|---|---|---|",
        ]

    for grp in groups:
        grp_name = grp.get("group_name", "").strip()
        grp_id = grp.get("group_id", "").strip()
        grp_desc = grp.get("description", "").strip()
        members = grp.get("indexes", [])

        if mode == "simple":
            lines.append(f"| `{grp_id}` | {grp_name} | {len(members)} |")
            continue

        grp_desc = grp_desc.replace("|", "\\|") if grp_desc else ""
        if len(grp_desc) > 50:
            grp_desc = grp_desc[:47] + "..."

        if not members:
            lines.append(f"| `{grp_id}` | {grp_name} |  |  |  |  |  | {grp_desc} |")
            continue

        for member in members:
            idx_id = (member.get("id") or "").strip()
            idx_name = (member.get("name") or "").strip()
            idx_dtype = (member.get("dataType") or "").strip()
            idx_dim = str(member.get("dimension", "")).strip()
            idx_fmt = str(member.get("format", "")).strip()
            idx_desc = (member.get("description") or "").strip().replace("|", "\\|")
            if len(idx_desc) > 50:
                idx_desc = idx_desc[:47] + "..."
            lines.append(
                f"| `{grp_id}` | {grp_name} | `{idx_id}` | {idx_name} | {idx_dtype} | {idx_dim} | {idx_fmt} | {idx_desc or grp_desc} |"
            )
    
    return "\n".join(lines)


def _format_archiving_policies(policies: list, mode: str = "detailed") -> str:
    """Format archiving policies in simple or detailed mode."""
    if not policies:
        return "No archiving policies found."

    mode = (mode or "detailed").strip().lower()
    if mode == "simple":
        lines = ["| Policy ID | Policy Name |", "|---|---|"]
    else:
        lines = ["| Policy ID | Policy Name | Version | Description |", "|---|---|---|---|"]

    for pol in policies:
        pol_id = (pol.get("id") or pol.get("name") or "").strip()
        pol_name = pol.get("name", "").strip()
        pol_ver = str(pol.get("version", "")).strip()
        pol_desc = pol.get("description", "").strip()
        pol_desc = pol_desc.replace("|", "\\|") if pol_desc else ""
        if len(pol_desc) > 70:
            pol_desc = pol_desc[:67] + "..."

        if mode == "simple":
            lines.append(f"| `{pol_id}` | {pol_name} |")
        else:
            lines.append(f"| `{pol_id}` | {pol_name} | {pol_ver} | {pol_desc} |")
    
    return "\n".join(lines)


def _topic_dimension(topic: dict[str, Any]) -> str:
    """Extract a best-effort dimension/length from a topic payload."""
    for key in ("length", "maxLength", "size", "dimension", "displayLength"):
        value = topic.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _topic_format(topic: dict[str, Any]) -> str:
    """Extract a best-effort format/mask from a topic payload."""
    for key in ("format", "outputFormat", "dateFormat", "mask", "editMask"):
        value = topic.get(key)
        if value not in (None, ""):
            return str(value)
    return ""

# ── Redis sync client for version cache ────────────────────────────────────

_sync_redis_client: sync_redis.Redis | None = None

_VERSION_CACHE_TTL = 300  # 5 minutes


def _get_sync_redis() -> sync_redis.Redis:
    """Return a shared sync Redis client (lazy singleton)."""
    global _sync_redis_client
    if _sync_redis_client is None:
        _sync_redis_client = sync_redis.from_url(
            settings.redis_url, decode_responses=True,
        )
    return _sync_redis_client


def _version_cache_key(content_class: str, version_from: str | None, version_to: str | None) -> str:
    cc = content_class.strip().upper()
    vf = version_from or ""
    vt = version_to or ""
    return f"ce:versions:{cc}:{vf}:{vt}"


# ── ContentEdge configuration ──────────────────────────────────────────────

_ce_config = None  # Lazily initialized ContentConfig instance (SOURCE)
_ce_target_config = None  # Lazily initialized ContentConfig instance (TARGET)


def _get_ce_config():
    """Return (or initialize) the ContentConfig singleton."""
    global _ce_config
    if _ce_config is not None:
        return _ce_config

    import sys
    # Add contentedge/ to sys.path so `lib.*` imports work
    ce_root = os.path.join(os.path.dirname(__file__), "..", "..", "contentedge")
    ce_root = os.path.normpath(ce_root)
    if ce_root not in sys.path:
        sys.path.insert(0, ce_root)

    from lib.content_config import ContentConfig

    # Prefer settings path (workspace/conf/), fallback to contentedge/conf/
    yaml_path = settings.contentedge_yaml
    if not os.path.exists(yaml_path):
        yaml_path = os.path.join(ce_root, "conf", "repository_source.yaml")

    # Patch YAML from env vars (same logic the MCP server used)
    _patch_yaml_from_env(yaml_path, "CE_SOURCE_")

    _ce_config = ContentConfig(yaml_path)
    logger.info("contentedge.config_loaded",
                repo=_ce_config.repo_name, url=_ce_config.base_url)
    return _ce_config


def _get_target_config():
    """Return (or initialize) the TARGET ContentConfig singleton."""
    global _ce_target_config
    if _ce_target_config is not None:
        return _ce_target_config

    # Ensure sys.path has contentedge/ (may already be done by _get_ce_config)
    _get_ce_config()
    from lib.content_config import ContentConfig

    yaml_path = settings.contentedge_target_yaml
    if not os.path.exists(yaml_path):
        # Fallback: try contentedge/conf/
        ce_root = os.path.join(os.path.dirname(__file__), "..", "..", "contentedge")
        yaml_path = os.path.normpath(os.path.join(ce_root, "conf", "repository_target.yaml"))

    if not os.path.exists(yaml_path):
        raise FileNotFoundError(f"TARGET YAML not found: {yaml_path}")

    _patch_yaml_from_env(yaml_path, "CE_TARGET_")
    _ce_target_config = ContentConfig(yaml_path)
    logger.info("contentedge.target_config_loaded",
                repo=_ce_target_config.repo_name, url=_ce_target_config.base_url)
    return _ce_target_config


def _get_services_api():
    """Return a ContentAdmServicesApi facade (SOURCE + TARGET)."""
    from lib.content_adm_services_api import ContentAdmServicesApi

    source_config = _get_ce_config()
    target_config = _get_target_config()

    # ContentAdmServicesApi expects YAML paths
    source_yaml = source_config.config_file
    target_yaml = target_config.config_file

    return ContentAdmServicesApi(source_yaml, target_yaml)


def _repo_info(config, label: str) -> str:
    """Return a short summary string for a repository config."""
    return f"{label}: {config.repo_name} @ {config.base_url}"


def _resolve_config(repo: str = "source"):
    """Resolve repository config by alias.

    Accepted aliases:
    - SOURCE: source, primary, primario
    - TARGET: target, secondary, secundario
    """
    key = (repo or "source").strip().lower()
    if key in {"target", "secondary", "secundario"}:
        return _get_target_config(), "target"
    if key in {"source", "primary", "primario"}:
        return _get_ce_config(), "source"
    raise ValueError("repo must be one of: source|primary|primario|target|secondary|secundario")


def _patch_yaml_from_env(yaml_path: str, prefix: str) -> None:
    """Overwrite YAML connection params from environment variables."""
    import yaml as _yaml

    env_map = {
        "REPO_URL": "repo_url",
        "REPO_NAME": "repo_name",
        "REPO_USER": "repo_user",
        "REPO_PASS": "repo_pass",
        "REPO_SERVER_USER": "repo_server_user",
        "REPO_SERVER_PASS": "repo_server_pass",
    }
    updates = {}
    for env_suffix, yaml_key in env_map.items():
        val = os.environ.get(f"{prefix}{env_suffix}", "")
        if val:
            updates[yaml_key] = val

    if not updates:
        return

    with open(yaml_path, "r") as f:
        config = _yaml.safe_load(f) or {}
    repo = config.setdefault("repository", {})
    repo.update(updates)
    with open(yaml_path, "w") as f:
        _yaml.dump(config, f, sort_keys=False)

    logger.info("contentedge.yaml_patched", keys=list(updates.keys()))


def _check_repository_active(config) -> str | None:
    """Verify the Content Repository is reachable. Returns error JSON or None."""
    try:
        url = f"{config.repo_url}/repositories"
        headers = {"Authorization": f"Basic {config.encoded_credentials}"}
        resp = requests.get(url, headers=headers, verify=False, timeout=15)
        resp.raise_for_status()
        return None
    except requests.exceptions.ConnectionError:
        return json.dumps({"error": f"Cannot connect to Content Repository at {config.base_url}."})
    except requests.exceptions.Timeout:
        return json.dumps({"error": f"Connection to Content Repository timed out."})
    except requests.exceptions.HTTPError as exc:
        return json.dumps({"error": f"Content Repository returned HTTP {exc.response.status_code}."})
    except Exception as exc:
        return json.dumps({"error": f"Failed to verify Content Repository: {exc}"})


# ── Blocking helpers (run in executor to keep event loop free) ─────────────

def _sync_search(constraints: list[dict], conjunction: str, repo: str = "source") -> dict:
    """Execute search_documents synchronously via the CE lib."""
    from lib.content_search import IndexSearch, ContentSearch

    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    search = IndexSearch(conjunction=conjunction)
    for c in constraints:
        idx = c.get("index_name", "")
        op = c.get("operator", "EQ")
        val = c.get("value", "")
        if not idx:
            return {"error": "Each constraint must have 'index_name'."}
        search.add_constraint(index_name=idx, operator=op, index_value=val)

    searcher = ContentSearch(config)
    object_ids = searcher.search_index(search)
    return {"count": len(object_ids), "object_ids": object_ids}


def _sync_smart_chat(question: str, document_ids: list[str] | None, conversation_id: str, repo: str = "source") -> dict:
    """Execute smart_chat synchronously via the CE lib."""
    from lib.content_smart_chat import ContentSmartChat

    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    chat_client = ContentSmartChat(config)
    result = chat_client.smart_chat(
        user_query=question,
        document_ids=document_ids,
        conversation=conversation_id,
    )
    return {
        "success": True,
        "answer": result.answer,
        "conversation_id": result.conversation,
        "matching_document_ids": result.object_ids,
    }


def _sync_get_document_url(object_id: str, repo: str = "source") -> dict:
    """Execute retrieve_document synchronously via the CE lib."""
    from lib.content_document import ContentDocument

    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    doc_client = ContentDocument(config)
    viewer_url = doc_client.retrieve_document(object_id)
    return {"success": True, "viewer_url": viewer_url}


def _sync_list_content_classes(repo: str = "source") -> list[dict]:
    """List content classes synchronously via the CE admin REST API."""
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    headers = deepcopy(config.headers)
    headers["Accept"] = (
        "application/vnd.asg-mobius-admin-reports.v3+json,"
        "application/vnd.asg-mobius-admin-reports.v2+json,"
        "application/vnd.asg-mobius-admin-reports.v1+json"
    )
    tm = str(int(time.time() * 1000))
    url = f"{config.repo_admin_url}/reports?limit=200&reportid=*&timestamp={tm}"
    resp = requests.get(url, headers=headers, verify=False, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return [
        {"id": it.get("id", ""), "name": it.get("name", ""), "description": it.get("details", "")}
        for it in data.get("items", [])
    ]


def _sync_list_indexes(repo: str = "source") -> dict:
    """List indexes and index groups synchronously via the CE admin REST API."""
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    tm = str(int(time.time() * 1000))

    # Index groups
    hg = deepcopy(config.headers)
    hg["Accept"] = "application/vnd.asg-mobius-admin-topic-groups.v1+json"
    groups_url = f"{config.repo_admin_url}/topicgroups?limit=200&groupid=*&timestamp={tm}"
    rg = requests.get(groups_url, headers=hg, verify=False, timeout=30)
    rg.raise_for_status()
    groups_data = rg.json().get("items", [])

    grouped_ids = set()
    index_groups = []
    for g in groups_data:
        topics = [
            {
                "id": t.get("id", ""),
                "name": t.get("name", ""),
                "dataType": t.get("dataType", "Character"),
                "description": t.get("details", "") or t.get("description", ""),
                "dimension": _topic_dimension(t),
                "format": _topic_format(t),
            }
            for t in g.get("topics", [])
        ]
        for t in topics:
            grouped_ids.add(t["id"])
        index_groups.append({
            "group_id": g.get("id", ""),
            "group_name": g.get("name", ""),
            "description": g.get("details", "") or g.get("description", ""),
            "mandatory_note": "ALL indexes in this group must be provided when archiving.",
            "indexes": topics,
        })

    # Individual indexes
    ht = deepcopy(config.headers)
    ht["Accept"] = "application/vnd.asg-mobius-admin-topics.v1+json"
    topics_url = f"{config.repo_admin_url}/topics?limit=200&topicid=*&timestamp={tm}"
    rt = requests.get(topics_url, headers=ht, verify=False, timeout=30)
    rt.raise_for_status()
    topics_data = rt.json().get("items", [])

    individual = [
        {
            "id": it.get("id", ""),
            "name": it.get("name", ""),
            "description": it.get("details", "") or it.get("description", ""),
            "dataType": it.get("dataType", "Character"),
            "dimension": _topic_dimension(it),
            "format": _topic_format(it),
        }
        for it in topics_data if it.get("id", "") not in grouped_ids
    ]

    return {"index_groups": index_groups, "individual_indexes": individual}


def _normalize_identifier(value: str) -> str:
    """Normalize identifiers for case-insensitive comparisons."""
    return (value or "").strip().lower()


def _sanitize_index_group_id(value: str) -> str:
    """Build a ContentEdge-safe index-group identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", (value or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:50]


def _sync_find_index_group(identifier: str, repo: str = "source") -> dict:
    """Find an index group by ID or name in a repository."""
    data = _sync_list_indexes(repo)
    if data.get("error"):
        return data

    needle = _normalize_identifier(identifier)
    for group in data.get("index_groups", []):
        if needle in {
            _normalize_identifier(group.get("group_id", "")),
            _normalize_identifier(group.get("group_name", "")),
        }:
            return {
                "success": True,
                "exists": True,
                "repo": repo,
                "group": group,
            }

    return {
        "success": True,
        "exists": False,
        "repo": repo,
        "identifier": identifier,
    }


def _sync_fetch_topics(repo: str = "source") -> list[dict] | dict:
    """Fetch raw topic definitions for index-group creation."""
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    headers = deepcopy(config.headers)
    headers["Accept"] = "application/vnd.asg-mobius-admin-topics.v1+json"
    tm = str(int(time.time() * 1000))
    url = f"{config.repo_admin_url}/topics?limit=200&topicid=*&timestamp={tm}"
    response = requests.get(url, headers=headers, verify=False, timeout=30)
    response.raise_for_status()
    return response.json().get("items", [])


def _match_topic_reference(reference: str, topics: list[dict]) -> dict | None:
    """Match a topic by ID or name."""
    needle = _normalize_identifier(reference)
    for topic in topics:
        if needle in {
            _normalize_identifier(topic.get("id", "")),
            _normalize_identifier(topic.get("name", "")),
        }:
            return topic
    return None


def _sync_create_index_group(group_definition: dict | str, repo: str = "target") -> dict:
    """Create an index group from a structured definition using existing topics."""
    if isinstance(group_definition, str):
        group_definition = json.loads(group_definition)

    if not isinstance(group_definition, dict):
        raise ValueError("group_definition must be a dictionary")

    group_id = (group_definition.get("group_id") or group_definition.get("id") or "").strip()
    group_name = (group_definition.get("group_name") or group_definition.get("name") or group_id).strip()
    member_refs = group_definition.get("member_references") or group_definition.get("member_index_ids") or []
    if not isinstance(member_refs, list):
        raise ValueError("member_references must be a list")

    if not group_id:
        group_id = _sanitize_index_group_id(group_name)
    if not group_id:
        raise ValueError("An index group ID or name is required")

    existing = _sync_find_index_group(group_id, repo)
    if existing.get("error"):
        return existing
    if existing.get("exists"):
        return {
            "success": True,
            "created": False,
            "exists": True,
            "repo": repo,
            "group_id": group_id,
            "group_name": group_name,
            "message": f"Index group '{group_id}' already exists.",
            "group": existing.get("group"),
        }

    raw_topics = _sync_fetch_topics(repo)
    if isinstance(raw_topics, dict) and raw_topics.get("error"):
        return raw_topics

    matched_topics = []
    missing_refs = []
    for ref in member_refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        topic = _match_topic_reference(ref, raw_topics)
        if topic is None:
            missing_refs.append(ref)
            continue
        matched_topics.append(topic)

    if missing_refs:
        return {
            "success": False,
            "created": False,
            "repo": repo,
            "group_id": group_id,
            "group_name": group_name,
            "missing_references": missing_refs,
            "message": "Some member indexes were not found in the repository.",
        }

    if not matched_topics:
        return {
            "success": False,
            "created": False,
            "repo": repo,
            "group_id": group_id,
            "group_name": group_name,
            "message": "No member indexes were provided for the new index group.",
        }

    from lib.content_adm_index import Topic
    from lib.content_adm_index_group import ContentAdmIndexGroup, IndexGroup

    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    index_group = IndexGroup(id=group_id, name=group_name)
    index_group.scope = group_definition.get("scope", "Page")
    for topic_data in matched_topics:
        index_group.addTopic(Topic.from_dict(topic_data))

    adm = ContentAdmIndexGroup(config)
    status = adm.create_index_group(index_group)
    if 200 <= status < 300:
        return {
            "success": True,
            "created": True,
            "repo": repo,
            "group_id": group_id,
            "group_name": group_name,
            "member_ids": [topic.get("id", "") for topic in matched_topics],
            "status": status,
        }

    response = {
        "success": False,
        "created": False,
        "repo": repo,
        "group_id": group_id,
        "group_name": group_name,
        "member_ids": [topic.get("id", "") for topic in matched_topics],
        "status": status,
        "message": f"ContentEdge returned status {status} while creating index group '{group_id}'.",
    }
    if status == 500:
        number_topics = [topic.get("id", "") for topic in matched_topics if topic.get("dataType") == "Number"]
        if number_topics:
            response["manual_required"] = {
                "reason": f"Number-type topics {number_topics} can trigger a Mobius server error.",
            }
    return response


def _validate_metadata_indexes(metadata: dict[str, str]) -> str | None:
    """Validate metadata keys against the cached index data.

    Returns an error message string if validation fails, or None if OK.
    Checks:
    1. Every metadata key must be a known index (or SECTION which is always allowed).
    2. If a metadata key belongs to a compound index group, ALL members of that
       group must be present in the metadata.
    """
    idx_data = _ce_index_data_cache
    if not idx_data:
        return None  # No cache available — skip validation

    # Build lookup structures
    all_index_ids: set[str] = set()
    # Map: index_id → list of group dicts it belongs to
    index_to_groups: dict[str, list[dict]] = {}

    for g in idx_data.get("index_groups", []):
        member_ids = [t.get("id", "") for t in g.get("indexes", [])]
        for mid in member_ids:
            all_index_ids.add(mid)
            index_to_groups.setdefault(mid, []).append(g)

    for ix in idx_data.get("individual_indexes", []):
        all_index_ids.add(ix.get("id", ""))

    # SECTION is a system-level metadata, always allowed
    system_indexes = {"SECTION"}

    # 1. Check that every provided key is a known index
    unknown = [k for k in metadata if k not in all_index_ids and k not in system_indexes]
    if unknown:
        return (f"Unknown index(es): {', '.join(unknown)}. "
                f"Valid indexes: {', '.join(sorted(all_index_ids))}")

    # 2. Check compound group completeness
    for key in metadata:
        if key in system_indexes:
            continue
        for group in index_to_groups.get(key, []):
            group_member_ids = [t.get("id", "") for t in group.get("indexes", [])]
            missing = [mid for mid in group_member_ids if mid not in metadata and mid not in system_indexes]
            if missing:
                return (f"Index '{key}' belongs to group '{group.get('group_id', '')}'. "
                        f"ALL members of the group must be provided. "
                        f"Missing: {', '.join(missing)}")

    return None


def _sync_archive_documents(content_class: str, files: list[str], metadata: dict[str, str], sections: list[str] | None, repo: str = "source") -> dict:
    """Archive documents synchronously via the CE lib."""
    from lib.content_archive_metadata import ArchiveDocument, ArchiveDocumentCollection, ContentArchiveMetadata

    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    # Validate metadata indexes against the repository schema
    validation_err = _validate_metadata_indexes(metadata)
    if validation_err:
        return {"error": validation_err}

    work_dir = os.environ.get("CE_WORK_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "contentedge", "files"))
    workspace_dir = str(WORKSPACE_ROOT)
    allowed_roots = [os.path.normpath(work_dir), os.path.normpath(workspace_dir)]

    if sections and len(sections) != len(files):
        return {"error": "Length of 'sections' must match length of 'files'."}

    collection = ArchiveDocumentCollection()
    resolved_paths = []

    for idx, rel_path in enumerate(files):
        # Resolve: "workspace/..." paths against AGENT_WORKSPACE, others against CE_WORK_DIR
        if rel_path.startswith("workspace/") or rel_path.startswith("workspace\\"):
            abs_path = os.path.join(workspace_dir, rel_path[len("workspace/"):])
        elif os.path.isabs(rel_path):
            abs_path = rel_path
        else:
            abs_path = os.path.join(work_dir, rel_path)
        abs_path = os.path.normpath(abs_path)
        if not any(abs_path.startswith(root) for root in allowed_roots):
            return {"error": f"File '{rel_path}' is outside the allowed directories."}
        if not os.path.isfile(abs_path):
            return {"error": f"File not found: '{rel_path}'"}
        doc = ArchiveDocument(content_class, abs_path)
        if sections:
            doc.set_section(sections[idx])
        for name, value in metadata.items():
            doc.add_metadata(name, str(value))
        collection.add_document(doc)
        resolved_paths.append(abs_path)

    archiver = ContentArchiveMetadata(config)
    status_code = archiver.archive_metadata(collection)

    results = [{"file": os.path.basename(p), "content_class": content_class, "status": status_code} for p in resolved_paths]
    return {"success": status_code in (200, 201), "status": status_code, "archived": results}


def _sync_get_versions(report_id: str, version_from: str, version_to: str, repo: str = "source") -> dict:
    """Get document versions synchronously via the CE lib."""
    from lib.content_class_navigator import ContentClassNavigator

    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    navigator = ContentClassNavigator(config)
    col = navigator.get_versions(report_id, version_from, version_to)
    return {"report_id": report_id, "versions": col}


def _sync_search_archiving_policies(name: str, withcontent: bool, limit: int, repo: str = "source") -> dict:
    """Search archiving policies via the Mobius Admin REST API."""
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    headers = deepcopy(config.headers)
    headers["Accept"] = "application/vnd.asg-mobius-admin-archiving-policies.v1+json"

    tm = str(int(time.time() * 1000))
    params = f"?limit={limit}&timestamp={tm}"
    if name:
        params += f"&name={name}"
    if withcontent:
        params += "&withcontent=true"

    url = f"{config.repo_admin_url}/archivingpolicies{params}"
    resp = requests.get(url, headers=headers, verify=False, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    policies = []
    for it in data.get("items", []):
        policies.append({
            "name": it.get("name", ""),
            "version": it.get("version", ""),
            "description": it.get("description") or it.get("details") or "",
        })

    # Cache policy names in Redis so delete can use them without re-querying
    if policies:
        try:
            r = _get_sync_redis()
            cache_key = f"ce:policies:search:{name or '*'}"
            policy_names = [p["name"] for p in policies]
            r.set(cache_key, json.dumps(policy_names), ex=_VERSION_CACHE_TTL)
            logger.info("  \U0001f4e6 Cached %d policy names in Redis key=%s",
                        len(policy_names), cache_key)
        except Exception as e:
            logger.warning("  \u26a0 Failed to cache policy names in Redis: %s", e)

    return {"count": len(policies), "policies": policies}


def _sync_create_archiving_policy(policy_data: dict, repo: str = "source") -> dict:
    """Create an archiving policy via the Mobius Admin REST API."""
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    if not policy_data.get("name"):
        return {"error": "Policy 'name' is required."}

    headers = deepcopy(config.headers)
    headers["Accept"] = "application/vnd.asg-mobius-admin-archiving-policy.v1+json"
    headers["Content-Type"] = "application/vnd.asg-mobius-admin-archiving-policy.v1+json"

    url = f"{config.repo_admin_url}/archivingpolicies"
    resp = requests.post(url, headers=headers, json=policy_data, verify=False, timeout=30)
    resp.raise_for_status()
    result = resp.json()

    return {
        "success": True,
        "name": result.get("name", policy_data["name"]),
        "version": result.get("version", ""),
    }


def _sync_get_archiving_policy(name: str, repo: str = "source") -> dict:
    """Retrieve a single archiving policy by name via the Mobius Admin REST API."""
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    if not name:
        return {"error": "Policy 'name' is required."}

    headers = deepcopy(config.headers)
    headers["Accept"] = "application/vnd.asg-mobius-admin-archiving-policy.v1+json"

    url = f"{config.repo_admin_url}/archivingpolicies/{name}"
    resp = requests.get(url, headers=headers, verify=False, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _sync_export_archiving_policy(name: str, repo: str = "source") -> dict:
    """Retrieve an archiving policy and save it as JSON in workspace/archiving_policies/."""
    policy = _sync_get_archiving_policy(name, repo)
    if "error" in policy:
        return policy

    # Remove HATEOAS links — not useful for export
    policy.pop("links", None)

    output_dir = WORKSPACE_ROOT / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{name}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2, ensure_ascii=False)

    return {
        "success": True,
        "name": name,
        "file": str(output_file),
        "keys": list(policy.keys()),
    }


def _build_policy_json(name: str, spec: dict) -> dict:
    """Build a Mobius-format archiving policy JSON from a simplified spec.

    The spec dict contains:
      - description (str): policy description
      - source_file (str): original source file path (informational)
      - documentInfo (dict): dataType, charSet, pageBreak, lineBreak
      - fields (list[dict]): field definitions with name, type, levelType,
            left, right, top, bottom, format, outputFormat, minLength, maxLength,
            terminator, allowBlank, discardIncompleteWords
      - fieldGroups (list[dict]): group definitions with name, usage (int), fields (list[str])
    """
    # ── documentInfo ──
    di = spec.get("documentInfo", {})
    document_info = {
        "documentID": None,
        "useAllSections": False,
        "useLastVersion": False,
        "parsingInfo": {
            "dataType": di.get("dataType", "Text"),
            "charSet": di.get("charSet", "ASCII"),
            "pageBreak": {
                "type": di.get("pageBreak", "FORMFEED"),
                "fixedPageLength": 0,
                "markers": None,
                "columns": None,
            },
            "lineBreak": {
                "type": di.get("lineBreak", "CRLF"),
                "fixedLineLength": 0,
            },
            "jdlResource": None,
            "jdeResource": None,
            "useJslPageSettings": False,
            "propagateTleRecords": False,
            "externalResources": None,
            "columnDelimiter": None,
            "textEnclosure": None,
            "alfFormat": 0,
            "processHiddenText": False,
            "useOCR": False,
            "filepath": spec.get("source_file", "") or "sample.txt",
            "lastModified": None,
        }
    }

    # ── fields ──
    fields = []
    for fs in spec.get("fields", []):
        field = {
            "name": fs["name"],
            "type": fs.get("type", "string"),
            "levelType": fs.get("levelType", "header1"),
            "allowBlank": fs.get("allowBlank", False),
            "useRetainedValue": fs.get("useRetainedValue", False),
            "parsingInfo": {
                "position": {
                    "left": float(fs.get("left", 1)),
                    # Auto-correct: if right==left the model likely forgot the end column;
                    # set right=0 so Mobius reads to the terminator instead of 1 char.
                    "right": float(0 if fs.get("right", 0) == fs.get("left", 1) else fs.get("right", 0)),
                    "top": float(fs.get("top", 0)),
                    "bottom": float(fs.get("bottom", 0)),
                },
                "format": fs.get("format", ""),
                "minLength": fs.get("minLength", 0),
                "maxLength": fs.get("maxLength", 0),
                "minValue": "",
                "maxValue": "",
                "terminator": fs.get("terminator", " "),
                "matchValuesUsage": "",
                "matchValues": [],
                "useWildCard": False,
                "discardIncompleteWords": fs.get("discardIncompleteWords", True),
            },
            "outputInfo": {
                "hide": fs.get("hide", False),
                "date_pattern": 0,
                "sequence": 0,
                "display_length": 0,
                "alignment": "L",
                "outputFormat": fs.get("outputFormat", ""),
                "changeCaseTo": "",
                "removeSpaces": "",
                "padChar": "",
                "minLength": 0,
                "maxLength": 0,
                "useLookupTable": False,
                "lookupTable": None,
                "useThousandSeparator": "O",
                "replacementValue": None,
            },
            "dependencies": [],
            "isExternal": False,
        }
        fields.append(field)

    # ── fieldGroups ──
    field_groups = []
    for gs in spec.get("fieldGroups", []):
        fg = {
            "name": gs["name"],
            "retainFieldValues": gs.get("retainFieldValues", True),
            "isDefault": False,
            "hide": False,
            "fieldRefs": [],
            "usage": str(gs.get("usage", 3)),
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
        for field_name in gs.get("fields", []):
            fg["fieldRefs"].append({
                "ruleName": "$Default$",
                "fieldName": field_name,
                "optional": gs.get("optional", False),
                "hideDuplicateValues": False,
            })
        field_groups.append(fg)

    # ── auto-generate REPORT_ID group if not already present ──
    # Uses a REPORT_LABEL field that extracts a label near the VERSION_ID date
    # field and maps it to the content class via lookupTable (ASGLookupTableDefault).
    has_report_id = any(str(fg.get("usage", "")) == "1" for fg in field_groups)
    report_label_spec = spec.get("report_label")

    # Also check: if model created a usage=1 group but no corresponding REPORT_LABEL field,
    # we need to create the field. Determine the content_class from any existing usage=1 group name
    # or from the policy description.
    existing_field_names = {f["name"] for f in fields}
    if has_report_id:
        # Check if the referenced field actually exists
        for fg in field_groups:
            if str(fg.get("usage", "")) == "1":
                for ref in fg.get("fieldRefs", []):
                    ref_name = ref.get("fieldName", "")
                    if ref_name and ref_name not in existing_field_names:
                        # Field is referenced but doesn't exist — need to auto-create it
                        has_report_id = False  # trigger auto-generation below
                        # Try to determine content_class from the spec description
                        desc = spec.get("description", "")
                        cc = "UNKNOWN"
                        for word in desc.split():
                            if word.isupper() and len(word) >= 3 and word.isalnum():
                                cc = word
                                break
                        if not report_label_spec:
                            report_label_spec = {"left": 1, "right": 20, "top": 1, "content_class": cc}
                        break

    if not has_report_id and not report_label_spec:
        # No report_label at all — auto-generate a catch-all REPORT_LABEL
        # Determine content_class from spec description or field group names
        desc = spec.get("description", "")
        cc = "UNKNOWN"
        for word in desc.split():
            if word.isupper() and len(word) >= 3 and word.isalnum():
                cc = word
                break
        report_label_spec = {"left": 1, "right": 20, "top": 1, "content_class": cc}

    if not has_report_id and report_label_spec:
        # Remove any orphan usage=1 groups the model may have created without fields
        field_groups = [fg for fg in field_groups if str(fg.get("usage", "")) != "1"]

        rl_field = {
            "name": "REPORT_LABEL",
            "type": "string",
            "levelType": report_label_spec.get("levelType", "header1"),
            "allowBlank": report_label_spec.get("allowBlank", False),
            "useRetainedValue": False,
            "parsingInfo": {
                "position": {
                    "left": float(report_label_spec.get("left", 1)),
                    "right": float(report_label_spec.get("right", 20)),
                    "top": float(report_label_spec.get("top", 0)),
                    "bottom": float(report_label_spec.get("bottom", 0)),
                },
                "format": report_label_spec.get("format", ""),
                "minLength": report_label_spec.get("minLength", 0),
                "maxLength": report_label_spec.get("maxLength", 0),
                "minValue": "",
                "maxValue": "",
                "terminator": report_label_spec.get("terminator", "\n"),
                "matchValuesUsage": "",
                "matchValues": [],
                "useWildCard": False,
                "discardIncompleteWords": True,
            },
            "outputInfo": {
                "hide": False,
                "date_pattern": 0,
                "sequence": 0,
                "display_length": 0,
                "alignment": "L",
                "outputFormat": "",
                "changeCaseTo": "",
                "removeSpaces": "",
                "padChar": "",
                "minLength": 0,
                "maxLength": 0,
                "useLookupTable": True,
                "lookupTable": [
                    {"name": "ASGLookupTableDefault", "value": report_label_spec.get("content_class", "UNKNOWN")},
                ],
                "useThousandSeparator": "O",
                "replacementValue": None,
            },
            "dependencies": [],
            "isExternal": False,
        }
        fields.append(rl_field)
        field_groups.insert(0, {
            "name": "REPORT_ID",
            "retainFieldValues": True,
            "isDefault": False,
            "hide": False,
            "fieldRefs": [{
                "ruleName": "$Default$",
                "fieldName": "REPORT_LABEL",
                "optional": False,
                "hideDuplicateValues": False,
            }],
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
        })

    # ── enforce outputFormat for VERSION_ID date fields ──
    version_fields = set()
    for fg in field_groups:
        if fg["usage"] == "5":
            version_fields.update(r["fieldName"] for r in fg["fieldRefs"])
    if version_fields:
        for field in fields:
            if field["name"] in version_fields and field["type"] == "date":
                field["outputInfo"]["outputFormat"] = "YYYYMMDD"

    # ── complete policy ──
    return {
        "name": name,
        "version": "3.0",
        "scope": "page",
        "keepBlankRows": True,
        "keepAnsiCCBlankRows": False,
        "textOnlyMode": False,
        "decimalSeparator": None,
        "enableCalculatedFields": False,
        "calculatedFields": None,
        "enableAggregation": False,
        "rules": [{
            "name": "$Default$",
            "type": "Region",
            "ruleid": 1,
            "mask": "",
            "positionByMask": False,
            "enabled": True,
            "region": {
                "position": None,
                "stretchHeight": False,
                "stretchWidth": False,
                "startAnchor": None,
                "endAnchor": None,
                "wordSpacingThreshold": 0.0,
                "lineSpacingThreshold": 35.0,
            },
            "fields": fields,
        }],
        "fieldGroups": field_groups,
        "pageBindInfo": {
            "scaleFactorX": 1.0,
            "scaleFactorY": 1.0,
            "offsetX": 0.0,
            "offsetY": 0.0,
        },
        "ruleMatchLists": [],
        "regionBindInfoList": [],
        "sorts": [],
        "enableEnhancedFieldLevelJoining": False,
        "defaultDateComponentOrder": "M/D/Y",
        "cutoffForTwoDigitYear": 1980,
        "requireMatchForFieldExtraction": True,
        "sampleFile": None,
        "documentInfo": document_info,
        "description": spec.get("description", ""),
        "locationIndexScope": None,
        "metadataFields": {"fields": [], "values": []},
        "compatibility": 0,
    }


def _extract_sample_values(spec: dict, policy: dict) -> list[dict]:
    """Extract field values from the first 3 pages of the source file.

    Reads the source file, splits by FORMFEED into pages, and for each field
    defined in the policy extracts the value at the configured position from
    each of the first 3 pages.

    Returns a list of dicts {field_name, type, position, page_N_value, ...}
    """
    source_file = spec.get("source_file", "")
    if not source_file:
        return []

    # Resolve path
    workspace_dir = str(WORKSPACE_ROOT)
    work_dir = os.environ.get("CE_WORK_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "contentedge", "files"))

    if source_file.startswith("workspace/") or source_file.startswith("workspace\\"):
        abs_path = os.path.join(workspace_dir, source_file[len("workspace/"):])
    elif os.path.isabs(source_file):
        abs_path = source_file
    else:
        abs_path = os.path.join(work_dir, source_file)
    abs_path = os.path.normpath(abs_path)

    if not os.path.isfile(abs_path):
        return []

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(abs_path, "r", encoding="latin-1") as f:
                content = f.read()
        except Exception:
            return []
    except Exception:
        return []

    # Split into pages by FORMFEED
    pages = content.split("\f")
    # Take at most 3 non-empty pages
    pages = [p for p in pages if p.strip()][:3]
    if not pages:
        return []

    # Get fields from the policy rules
    all_fields = []
    for rule in policy.get("rules", []):
        all_fields.extend(rule.get("fields", []))

    results = []
    for field in all_fields:
        pi = field.get("parsingInfo", {})
        pos = pi.get("position", {})
        left = int(pos.get("left", 1))
        right = int(pos.get("right", 0))
        # Auto-correct: right==left means model forgot end column → use terminator
        if right == left:
            right = 0
        top = int(pos.get("top", 0))  # 1-based line number; 0=detail/all lines
        terminator = pi.get("terminator", " ")

        entry = {
            "field_name": field.get("name", ""),
            "type": field.get("type", "string"),
            "levelType": field.get("levelType", ""),
            "position": f"left={left}, right={right}, top={top}",
        }

        def _extract_from_line(line_text: str) -> str:
            """Extract value from a single line using left/right/terminator."""
            if not line_text:
                return ""
            start = left - 1  # convert to 0-based
            if start >= len(line_text):
                return ""
            if right > 0:
                val = line_text[start:right]
            else:
                rest = line_text[start:]
                if terminator and terminator in rest:
                    val = rest[:rest.index(terminator)]
                else:
                    val = rest
            return val.strip()

        for page_idx, page_text in enumerate(pages):
            lines = page_text.split("\n")
            if top > 0 and top <= len(lines):
                line = lines[top - 1]
            elif top == 0 and lines:
                # Detail line: use first data line (skip empty)
                line = next((l for l in lines if l.strip()), "")
            else:
                line = ""

            value = _extract_from_line(line)

            # Auto-correct: if extraction is empty and top>0, try nearby lines
            # (model often picks wrong line for multi-line headers)
            if not value and top > 0:
                for try_top in (top + 1, top - 1, top + 2):
                    if 1 <= try_top <= len(lines):
                        value = _extract_from_line(lines[try_top - 1])
                        if value:
                            # Update the position entry to show corrected line
                            if page_idx == 0:
                                entry["position"] = f"left={left}, right={right}, top={try_top} (auto-corrected from {top})"
                            break

            entry[f"page_{page_idx + 1}_value"] = value

        results.append(entry)

    return results


def _sync_generate_archiving_policy(name: str, spec: dict) -> dict:
    """Generate an archiving policy JSON from a spec, save to workspace, and return a preview.

    Does NOT register the policy in Mobius. The agent must present the preview
    to the user and call _sync_register_archiving_policy after confirmation.
    """
    if not name:
        return {"error": "Policy 'name' is required."}

    # Build the full Mobius-format policy JSON
    policy = _build_policy_json(name, spec)

    # Save to workspace/tmp/
    output_dir = WORKSPACE_ROOT / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{name}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2, ensure_ascii=False)

    logger.info("  >> Policy JSON saved to %s", output_file)

    # Cache the full policy JSON in Redis so register can read it directly
    cache_key = f"ce:policy:generated:{name}"
    try:
        r = _get_sync_redis()
        r.set(cache_key, json.dumps(policy, ensure_ascii=False), ex=_VERSION_CACHE_TTL)
        logger.info("  \U0001f4e6 Cached generated policy JSON in Redis key=%s", cache_key)
    except Exception as e:
        logger.warning("  \u26a0 Failed to cache generated policy in Redis: %s", e)

    # Build field detail summary
    usage_labels = {"1": "REPORT_ID", "2": "SECTION_ID", "3": "TOPIC", "5": "VERSION_ID"}

    fields_detail = []
    for rule in policy.get("rules", []):
        for f in rule.get("fields", []):
            pi = f.get("parsingInfo", {})
            pos = pi.get("position", {})
            oi = f.get("outputInfo", {})
            fields_detail.append({
                "name": f.get("name", ""),
                "type": f.get("type", "string"),
                "levelType": f.get("levelType", ""),
                "left": pos.get("left"),
                "right": pos.get("right"),
                "top": pos.get("top"),
                "bottom": pos.get("bottom"),
                "format": pi.get("format", ""),
                "outputFormat": oi.get("outputFormat", ""),
                "terminator": pi.get("terminator", ""),
                "useLookupTable": oi.get("useLookupTable", False),
                "lookupTable": oi.get("lookupTable"),
            })

    # Group summary with detailed usage
    groups_detail = []
    report_id_value = None
    for fg in policy.get("fieldGroups", []):
        u = str(fg.get("usage", "3"))
        label = usage_labels.get(u, f"usage={u}")
        field_refs = [r.get("fieldName", "") for r in fg.get("fieldRefs", [])]
        groups_detail.append({
            "group_name": fg.get("name", ""),
            "usage": u,
            "usage_label": label,
            "fields": field_refs,
        })
        if u == "1":
            # Determine report_id value from the field's lookupTable
            for ref_name in field_refs:
                for fd in fields_detail:
                    if fd["name"] == ref_name and fd.get("lookupTable"):
                        for lt_entry in fd["lookupTable"]:
                            report_id_value = lt_entry.get("value", "")
                            break
                    if report_id_value:
                        break

    # Extract sample values from source file (first 3 pages)
    sample_values = _extract_sample_values(spec, policy)

    # Auto-correct top positions in the policy JSON if extraction found a better line
    for sv in sample_values:
        pos_str = sv.get("position", "")
        if "auto-corrected from" in pos_str:
            # Parse the corrected top value
            import re
            m = re.search(r"top=(\d+) \(auto-corrected from (\d+)\)", pos_str)
            if m:
                corrected_top = float(m.group(1))
                original_top = float(m.group(2))
                fname = sv["field_name"]
                for rule in policy.get("rules", []):
                    for f in rule.get("fields", []):
                        if f.get("name") == fname:
                            cur_top = f["parsingInfo"]["position"].get("top")
                            if cur_top == original_top:
                                f["parsingInfo"]["position"]["top"] = corrected_top
                                logger.info("  >> Auto-corrected top for %s: %s → %s", fname, original_top, corrected_top)

    # Re-save policy with corrected positions
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(policy, f, indent=2, ensure_ascii=False)

    # Update Redis cache with corrected policy
    try:
        r = _get_sync_redis()
        r.set(cache_key, json.dumps(policy, ensure_ascii=False), ex=_VERSION_CACHE_TTL)
    except Exception:
        pass

    # Identify section and version values from samples
    section_fields = set()
    version_fields = set()
    for fg in policy.get("fieldGroups", []):
        u = str(fg.get("usage", "3"))
        refs = [r.get("fieldName", "") for r in fg.get("fieldRefs", [])]
        if u == "2":
            section_fields.update(refs)
        elif u == "5":
            version_fields.update(refs)

    section_samples = [s for s in sample_values if s["field_name"] in section_fields]
    version_samples = [s for s in sample_values if s["field_name"] in version_fields]

    # Build a pre-formatted user-friendly preview message
    preview_lines = [f"Policy **{name}** generated (NOT yet registered in Mobius)."]

    # Show SECTION and VERSION prominently at the top
    def _sample_vals(samples):
        """Return comma-separated extracted values from first 3 pages."""
        parts = []
        for s in samples:
            for i in range(1, 4):
                v = s.get(f"page_{i}_value", "")
                if v:
                    parts.append(v)
        return ", ".join(parts) if parts else "(empty)"

    if section_samples:
        preview_lines.append(f"\n**SECTION =** {_sample_vals(section_samples)}")
    if version_samples:
        preview_lines.append(f"**VERSION =** {_sample_vals(version_samples)}")
    if report_id_value and report_id_value != "(not determined)":
        preview_lines.append(f"**Content Class (REPORT_ID) =** {report_id_value}")

    preview_lines.append("\n**Fields:**")
    for fd in fields_detail:
        if fd['name'] == 'REPORT_LABEL':
            continue
        line = f"- {fd['name']} ({fd['type']}) — left={fd['left']}, right={fd['right']}, top={fd['top']}"
        if fd.get("format"):
            line += f", format={fd['format']}"
        if fd.get("outputFormat"):
            line += f", outputFormat={fd['outputFormat']}"
        # Show extracted values inline
        matching = [s for s in sample_values if s["field_name"] == fd["name"]]
        if matching:
            vals = [matching[0].get(f"page_{i}_value", "") for i in range(1, 4) if matching[0].get(f"page_{i}_value")]
            if vals:
                line += f" → extracted: [{', '.join(vals)}]"
        preview_lines.append(line)

    preview_lines.append("\n**Do you want to proceed? If you confirm, the policy will be registered and the file will be archived automatically.**")
    preview_lines.append(f"\nIMPORTANT: Show this preview to the user. When they confirm, call `contentedge_register_archiving_policy(name='{name}')` then `contentedge_archive_using_policy`. Do NOT call contentedge_generate_archiving_policy again.")

    preview_message = "\n".join(preview_lines)

    return preview_message


def _sync_register_archiving_policy(name: str, repo: str = "source") -> dict:
    """Register a previously generated archiving policy in Mobius.

    Fast path: reads the policy JSON from Redis cache (set by generate).
    Slow path: reads from workspace/archiving_policies/<name>.json.
    POSTs it to the Content Repository. If name already exists, creates with
    a timestamp suffix.
    """
    from datetime import datetime

    if not name:
        return {"error": "Policy 'name' is required."}

    output_dir = WORKSPACE_ROOT / "tmp"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Fast path: try Redis cache first
    policy = None
    cache_key = f"ce:policy:generated:{name}"
    try:
        r = _get_sync_redis()
        raw = r.get(cache_key)
        if raw:
            policy = json.loads(raw)
            r.delete(cache_key)  # consume one-shot
            logger.info("  \U0001f4e6 Cache HIT: policy '%s' from Redis", name)
    except Exception as e:
        logger.warning("  \u26a0 Redis cache read failed for policy: %s", e)

    # Slow path: read from file
    if policy is None:
        logger.info("  \U0001f4e6 Cache MISS: reading policy '%s' from file", name)
        policy_file = output_dir / f"{name}.json"

        if not policy_file.exists():
            return {"error": f"Policy file not found: {policy_file}. Generate it first with contentedge_generate_archiving_policy."}

        with open(policy_file, "r", encoding="utf-8") as f:
            policy = json.load(f)

    actual_name = name
    try:
        create_result = _sync_create_archiving_policy(policy)
        if "error" in create_result:
            raise requests.exceptions.HTTPError(response=type("R", (), {"status_code": 409, "text": create_result["error"]})())
        logger.info("  >> Policy registered in Mobius: %s", create_result)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status == 409 or "already exists" in str(getattr(e.response, 'text', '')).lower():
            # ── Policy already exists — check if it's usable as-is ──
            reuse_existing = False
            try:
                existing = _sync_get_archiving_policy(name, repo)
                if isinstance(existing, dict) and "error" not in existing:
                    # 1) Verify REPORT_ID content class mapping matches
                    report_ok = False
                    for fg in existing.get("fieldGroups", []):
                        if str(fg.get("usage", "")) == "1":
                            for ref in fg.get("fieldRefs", []):
                                fname = ref.get("fieldName", "")
                                for rule in existing.get("rules", []):
                                    for fld in rule.get("fields", []):
                                        if fld.get("name") == fname:
                                            lt = fld.get("outputInfo", {}).get("lookupTable") or []
                                            # Check new policy's intended content class
                                            new_cc = None
                                            for nfg in policy.get("fieldGroups", []):
                                                if str(nfg.get("usage", "")) == "1":
                                                    for nref in nfg.get("fieldRefs", []):
                                                        nfname = nref.get("fieldName", "")
                                                        for nr in policy.get("rules", []):
                                                            for nf in nr.get("fields", []):
                                                                if nf.get("name") == nfname:
                                                                    nlt = nf.get("outputInfo", {}).get("lookupTable") or []
                                                                    if nlt:
                                                                        new_cc = nlt[0].get("value", "").upper()
                                                            if new_cc:
                                                                break
                                                    if new_cc:
                                                        break
                                            if new_cc:
                                                has_cc = any(entry.get("value", "").upper() == new_cc for entry in lt)
                                                if has_cc:
                                                    report_ok = True
                                            break
                                break
                            break
                    if not report_ok:
                        logger.info("  >> Existing policy '%s' has wrong REPORT_ID mapping", name)
                    else:
                        # 2) Verify field extraction using the source file
                        source_file = existing.get("documentInfo", {}).get("filepath", "")
                        if not source_file:
                            # Fallback: get from new policy
                            source_file = policy.get("documentInfo", {}).get("filepath", "")
                        if source_file:
                            spec_for_extract = {"source_file": source_file}
                            samples = _extract_sample_values(spec_for_extract, existing)
                            non_empty = sum(
                                1 for s in samples
                                if s.get("field_name", "") != "REPORT_LABEL"
                                and any(s.get(f"page_{i}_value") for i in range(1, 4))
                            )
                            total_check = sum(1 for s in samples if s.get("field_name", "") != "REPORT_LABEL")
                            if total_check > 0 and non_empty == total_check:
                                reuse_existing = True
                                logger.info("  ✅ Existing policy '%s' is valid — REPORT_ID OK, all %d fields extract correctly",
                                            name, non_empty)
                                sample_preview = "; ".join(
                                    f"{s['field_name']}={s.get('page_1_value', '')}"
                                    for s in samples if s.get("field_name", "") != "REPORT_LABEL"
                                )
                                logger.info("     Samples: %s", sample_preview)
                            else:
                                logger.info("  >> Existing policy '%s' field extraction: %d/%d OK — creating new version",
                                            name, non_empty, total_check)
                        else:
                            logger.info("  >> No source file in existing policy '%s' — creating new version", name)
            except Exception as ex:
                logger.warning("  ⚠ Could not verify existing policy '%s': %s", name, ex)

            if reuse_existing:
                actual_name = name
            else:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                actual_name = f"{name}_{ts}"
                logger.info("  >> Policy '%s' already exists, creating as '%s'", name, actual_name)
                policy["name"] = actual_name
                new_file = output_dir / f"{actual_name}.json"
                with open(new_file, "w", encoding="utf-8") as f:
                    json.dump(policy, f, indent=2, ensure_ascii=False)
                try:
                    create_result = _sync_create_archiving_policy(policy, repo)
                    if "error" in create_result:
                        return {
                            "success": False,
                            "name": actual_name,
                            "file": str(new_file),
                            "error": f"Retry also failed: {create_result['error']}",
                        }
                    logger.info("  >> Policy registered in Mobius as '%s'", actual_name)
                except requests.exceptions.HTTPError as e2:
                    s2 = e2.response.status_code if e2.response is not None else "unknown"
                    b2 = e2.response.text[:300] if e2.response is not None else ""
                    return {
                        "success": False,
                        "name": actual_name,
                        "file": str(new_file),
                        "error": f"Retry failed (HTTP {s2}): {b2}",
                    }
        else:
            body = e.response.text[:300] if e.response is not None else ""
            return {
                "success": False,
                "name": name,
                "error": f"Registration failed (HTTP {status}): {body}",
            }

    # Store original→registered mapping in Redis so archive can resolve it
    try:
        r = _get_sync_redis()
        r.set(f"ce:policy:registered:{name}", actual_name, ex=_VERSION_CACHE_TTL)
        if actual_name != name:
            r.set(f"ce:policy:registered:{actual_name}", actual_name, ex=_VERSION_CACHE_TTL)
        logger.info("  📌 Stored registered mapping: '%s' → '%s'", name, actual_name)
    except Exception as e:
        logger.warning("  ⚠ Failed to store registered mapping: %s", e)

    return {
        "success": True,
        "name": actual_name,
        "original_name": name,
        "registered_in_mobius": True,
        "message": f"Policy '{actual_name}' registered in ContentEdge repository successfully.",
    }


def _sync_modify_archiving_policy(name: str, policy_data: dict, repo: str = "source") -> dict:
    """Modify an existing archiving policy via the Mobius Admin REST API."""
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    if not name:
        return {"error": "Policy 'name' is required."}

    headers = deepcopy(config.headers)
    headers["Accept"] = "application/vnd.asg-mobius-admin-archiving-policy.v1+json"
    headers["Content-Type"] = "application/vnd.asg-mobius-admin-archiving-policy.v1+json"

    url = f"{config.repo_admin_url}/archivingpolicies/{name}"
    resp = requests.put(url, headers=headers, json=policy_data, verify=False, timeout=30)
    resp.raise_for_status()
    result = resp.json()

    return {
        "success": True,
        "name": result.get("name", name),
        "version": result.get("version", ""),
    }


def _sync_delete_archiving_policy(name: str, repo: str = "source") -> dict:
    """Delete an archiving policy by name via the Mobius Admin REST API.

    Supports a special name '__from_cache__' that reads the list of policy names
    from the last search cached in Redis and deletes them all.
    """
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    if not name:
        return {"error": "Policy 'name' is required."}

    headers = deepcopy(config.headers)
    headers["Accept"] = "*/*"

    url = f"{config.repo_admin_url}/archivingpolicies/{name}"
    resp = requests.delete(url, headers=headers, verify=False, timeout=30)
    resp.raise_for_status()

    # Clean up any cached search that included this policy
    try:
        r = _get_sync_redis()
        for key in r.scan_iter("ce:policies:search:*"):
            r.delete(key)
    except Exception:
        pass

    return {"success": True, "name": name, "deleted": True}


def _navigate_to_cc_folder(content_class: str, repo: str = "source") -> dict:
    """Navigate the repository tree to find a content class folder.

    Returns dict with 'folder_id' and 'name' on success, or 'error' key on failure.
    """
    NAV_ACCEPT = "application/vnd.asg-mobius-navigation.v3+json"
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    headers = deepcopy(config.headers)
    headers["Accept"] = NAV_ACCEPT

    # Step 1: Get repository root children to find "Content Classes" folder
    url = f"{config.repo_url}/repositories/{config.repo_id}/children"
    resp = requests.get(url, headers=headers, verify=False, timeout=60)
    resp.raise_for_status()
    root_items = resp.json().get("items", [])
    cc_folder = None
    for item in root_items:
        if item.get("objectTypeId") == "vdr:reportRoot":
            cc_folder = item
            break
    if not cc_folder:
        return {"error": "Content Classes folder not found in repository root."}

    # Step 2: List content classes inside that folder
    cc_folder_id = cc_folder["objectId"]
    url2 = f"{config.repo_url}/folders/{cc_folder_id}/children"
    resp2 = requests.get(url2, headers=headers, verify=False, timeout=60)
    resp2.raise_for_status()
    cc_items = resp2.json().get("items", [])
    target_folder = None
    for item in cc_items:
        if item.get("name", "").strip().upper() == content_class.strip().upper():
            target_folder = item
            break
    if not target_folder:
        available = [it.get("name", "").strip() for it in cc_items]
        return {"error": f"Content class '{content_class}' not found. Available: {available}"}

    return {"folder_id": target_folder["objectId"], "name": target_folder.get("name", "").strip()}


def _parse_date_bounds(version_from: str | None, version_to: str | None):
    """Parse ISO date strings into datetime objects for range filtering."""
    from datetime import datetime, timezone
    dt_from = None
    dt_to = None
    if version_from:
        dt_from = datetime.fromisoformat(
            version_from.replace("Z", "+00:00") if "T" in version_from
            else version_from + "T00:00:00+00:00"
        )
    if version_to:
        dt_to = datetime.fromisoformat(
            version_to.replace("Z", "+00:00") if "T" in version_to
            else version_to + "T23:59:59+00:00"
        )
    return dt_from, dt_to


def _version_in_range(metadata: dict, dt_from, dt_to) -> bool:
    """Check if a version's ReportVersionID falls within the date range."""
    from datetime import datetime
    ver_str = metadata.get("ReportVersionID", "")
    if not ver_str:
        return False
    try:
        ver_dt = datetime.fromisoformat(ver_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt_from and ver_dt < dt_from:
        return False
    if dt_to and ver_dt > dt_to:
        return False
    return True


def _sync_list_content_class_versions(
    content_class: str,
    version_from: str | None = None,
    version_to: str | None = None,
    repo: str = "source",
) -> dict:
    """List versions (documents) under a content class using the navigation API.

    Flow: repo root → Content Classes folder → content_class folder → versions.
    Supports optional date range filtering on ReportVersionID metadata.
    Uses limit=500 per page; reports hasMoreItems if the repository has more.
    """
    nav = _navigate_to_cc_folder(content_class, repo)
    if "error" in nav:
        return nav

    target_id = nav["folder_id"]
    config = _get_ce_config()
    headers = deepcopy(config.headers)
    headers["Accept"] = "application/vnd.asg-mobius-navigation.v3+json"

    dt_from, dt_to = _parse_date_bounds(version_from, version_to)

    url = f"{config.repo_url}/folders/{target_id}/children?limit=500"
    resp = requests.get(url, headers=headers, verify=False, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items", [])
    has_more = data.get("hasMoreItems", False)

    result_versions = []
    for v in items:
        meta = {m["keyName"]: m["keyValue"] for m in v.get("metadata", [])}
        if (dt_from or dt_to) and not _version_in_range(meta, dt_from, dt_to):
            continue
        result_versions.append({
            "objectId": v.get("objectId"),
            "name": v.get("name", "").strip(),
            "path": v.get("path", ""),
            "objectTypeId": v.get("objectTypeId", ""),
            "metadata": meta,
        })

    PREVIEW_LIMIT = 10  # Max versions to return to the LLM for user preview

    result = {
        "content_class": content_class.strip().upper(),
        "count": len(result_versions),
        "hasMoreItems": has_more,
        "versions": result_versions[:PREVIEW_LIMIT],
    }
    if len(result_versions) > PREVIEW_LIMIT:
        result["showing"] = PREVIEW_LIMIT
        result["message"] = (
            f"Showing first {PREVIEW_LIMIT} of {len(result_versions)} versions. "
            f"All {len(result_versions)} will be deleted if confirmed."
        )

    # Cache ALL version objectIds in Redis so delete_content_class_versions can
    # skip re-navigation and delete directly from cached IDs.
    # Only cache if we got ALL items (no pagination needed), otherwise the
    # delete tool must use the slow path with batch-of-30 pagination.
    if result_versions and not has_more:
        try:
            cache_key = _version_cache_key(content_class, version_from, version_to)
            r = _get_sync_redis()
            r.set(cache_key, json.dumps(result_versions, ensure_ascii=False), ex=_VERSION_CACHE_TTL)
            logger.info("  📦 Cached %d version IDs in Redis key=%s (TTL=%ds)",
                        len(result_versions), cache_key, _VERSION_CACHE_TTL)
        except Exception as e:
            logger.warning("  ⚠ Failed to cache versions in Redis: %s", e)
    elif has_more:
        logger.info("  📦 NOT caching versions (hasMoreItems=true, delete will use batch-of-30 pagination)")

    return result


def _sync_delete_document(document_id: str, repo: str = "source") -> dict:
    """Delete a document from the repository by its objectId.

    Uses: DELETE {repo_url}/repositories/{repo_id}/documents?documentid={document_id}

    SAFETY: Before deleting, verifies the objectId corresponds to a DOCUMENT
    (not a FOLDER) by inspecting the encoded objectId. This prevents accidental
    deletion of container objects (content classes, versions, etc.).
    """
    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    if not document_id:
        return {"error": "document_id is required."}

    # SAFETY: Reject objectIds that are clearly FOLDER types based on encoded content.
    # Mobius ENC() objectIds contain base64-encoded metadata including folderType/objectTypeId.
    # Known folder type markers: vdr:reportRoot, vdr:report, vdr:reportVersion
    _id_upper = document_id.upper()
    folder_markers = ["VKRSONJLCG9YDFJVB3Q",   # vdr:reportRoot (base64)
                      "VKRSONCWBWXKZXJ",         # vdr:report folder type prefix
                      "DMRYONJLCG9YDA"]            # vdr:report (another encoding)
    # More reliable: check if the objectId decodes to contain folder type indicators
    if document_id.startswith("ENC("):
        import base64
        try:
            inner = document_id[4:-1] if document_id.endswith(")") else document_id[4:]
            # Add padding if needed
            padded = inner + "=" * (4 - len(inner) % 4) if len(inner) % 4 else inner
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
            # Check for folder type markers in decoded content
            if any(marker in decoded for marker in
                   ["vdr:reportRoot", "vdr:report.", "folderType14", "folderType10"]):
                logger.error("  🛑 BLOCKED: Attempted to delete a FOLDER objectId "
                             "(decoded contains folder type marker): %s", decoded[:200])
                return {"error": "SAFETY: Refused to delete — objectId is a FOLDER, not a DOCUMENT.",
                        "document_id": document_id[:60]}
        except Exception:
            pass  # If we can't decode, proceed with the delete — the server will validate

    headers = deepcopy(config.headers)
    headers["Accept"] = "*/*"
    url = f"{config.repo_url}/repositories/{config.repo_id}/documents?documentid={document_id}"
    logger.debug("  >> DELETE document: %s", document_id[:80])
    resp = requests.delete(url, headers=headers, verify=False, timeout=60)
    if resp.status_code in (200, 204):
        return {"success": True, "document_id": document_id, "status_code": resp.status_code}
    if resp.status_code == 422:
        # Distinguish multi-section archive (can't delete) from already-deleted
        body = resp.text or ""
        if "section count" in body.lower():
            return {"success": False, "document_id": document_id, "status_code": 422,
                    "error": "multi_section_version",
                    "note": "Version has multiple sections — cannot delete individual sections via REST API"}
        # Other 422 (e.g. document already deleted or gone)
        return {"success": True, "document_id": document_id, "status_code": 422, "note": "already deleted"}
    resp.raise_for_status()
    return {"success": True, "document_id": document_id, "status_code": resp.status_code}


def _sync_delete_documents_by_ids(object_ids: list[str], repo: str = "source") -> dict:
    """Delete multiple documents by their objectIds."""
    if not object_ids:
        return {"deleted": 0, "errors": 0, "total": 0, "message": "No document IDs provided."}

    deleted = 0
    errors = 0
    error_details = []
    for oid in object_ids:
        try:
            r = _sync_delete_document(oid, repo)
            if r.get("success"):
                deleted += 1
            else:
                errors += 1
                error_details.append({"objectId": oid[:40], "detail": "Delete returned unsuccessful"})
        except Exception as e:
            errors += 1
            error_details.append({"objectId": oid[:40], "detail": str(e)})

    result = {"deleted": deleted, "errors": errors, "total": len(object_ids)}
    if error_details:
        result["error_details"] = error_details
    return result


def _delete_version_sections(config, headers: dict, version: dict) -> dict:
    """Navigate into a version folder, find section documents, and delete them.

    SAFETY: Only deletes items whose baseTypeId is 'DOCUMENT'. Items with
    baseTypeId 'FOLDER' are skipped to prevent accidental deletion of
    container objects (content class folders, version folders, etc.).

    Multi-section handling:
    - Single-section versions: DELETE the section directly → 204 (success)
    - Multi-section versions: DELETE of an individual section returns 422
      ("section count doesn't match the archive") because all sections
      belong to a single archive and cannot be deleted individually.
      These are reported as status='skipped_multi_section'.

    Returns dict with status='deleted', 'skipped_multi_section', or 'error'.
    """
    version_oid = version.get("objectId")
    v_name = version.get("name", "").strip()
    try:
        url = f"{config.repo_url}/folders/{version_oid}/children"
        resp = requests.get(url, headers=headers, verify=False, timeout=60)
        resp.raise_for_status()
        sections = resp.json().get("items", [])
        if not sections:
            return {"name": v_name, "status": "error", "detail": "No sections found in version"}

        # SAFETY: filter to only DOCUMENT items — never delete FOLDER items
        doc_sections = []
        skipped = []
        for sec in sections:
            base_type = sec.get("baseTypeId", "UNKNOWN")
            if base_type == "DOCUMENT":
                doc_sections.append(sec)
            else:
                skipped.append({"name": sec.get("name", ""), "baseTypeId": base_type,
                                "objectTypeId": sec.get("objectTypeId", "")})
                logger.warning("  ⚠ SKIPPED non-DOCUMENT item in version '%s': "
                               "name='%s' baseTypeId='%s' objectTypeId='%s'",
                               v_name, sec.get("name", ""), base_type,
                               sec.get("objectTypeId", ""))

        if not doc_sections:
            return {"name": v_name, "status": "error",
                    "detail": f"No DOCUMENT items found in version (found {len(skipped)} non-DOCUMENT items)"}

        is_multi_section = len(doc_sections) > 1

        # Try deleting the first section
        first_sec = doc_sections[0]
        first_doc_id = first_sec.get("objectId")
        first_sec_name = first_sec.get("name", "").strip()
        logger.info("  >> Deleting section '%s' (baseTypeId=DOCUMENT) from version '%s' (sections=%d)",
                    first_sec_name, v_name, len(doc_sections))

        del_url = f"{config.repo_url}/repositories/{config.repo_id}/documents?documentid={first_doc_id}"
        del_resp = requests.delete(del_url, headers=config.headers, verify=False, timeout=60)

        if del_resp.status_code in (200, 204):
            # Single-section delete succeeded — for multi-section archives,
            # remaining sections are gone too (the whole archive is deleted)
            return {"name": v_name, "status": "deleted",
                    "sections_deleted": len(doc_sections),
                    "skipped": len(skipped)}

        if del_resp.status_code == 422 and is_multi_section:
            # Multi-section archive: REST API cannot delete individual sections.
            # The 422 error "section count doesn't match the archive" means
            # the server requires all sections to be deleted as a unit, which
            # is not supported via this REST endpoint.
            logger.warning("  ⚠ Version '%s' has %d sections — cannot delete via REST API (422)",
                           v_name, len(doc_sections))
            return {"name": v_name, "status": "skipped_multi_section",
                    "sections": len(doc_sections),
                    "detail": "Multi-section archive cannot be deleted via REST API (422)"}

        # Other error
        body = del_resp.text[:300] if del_resp.text else ""
        return {"name": v_name, "status": "error",
                "detail": f"HTTP {del_resp.status_code}: {body}"}

    except Exception as e:
        return {"name": v_name, "status": "error", "detail": str(e)}


def _sync_delete_content_class_versions(
    content_class: str,
    version_from: str | None = None,
    version_to: str | None = None,
    repo: str = "source",
) -> dict:
    """Delete versions under a content class, using cached objectIDs when available.

    Fast path (Redis cache hit): The previous list_content_class_versions call
    cached the version objectIDs. We iterate over them and delete their section
    documents directly — no tree re-navigation needed.

    Slow path (cache miss): Navigate the tree in batches of 30, as before.

    Navigation hierarchy: Content Classes → class → versions → sections (DOCUMENT).
    The DELETE API requires the section objectId (baseTypeId=DOCUMENT), not the
    version folder objectId.
    """
    NAV_ACCEPT = "application/vnd.asg-mobius-navigation.v3+json"

    config, _ = _resolve_config(repo)
    headers = deepcopy(config.headers)
    headers["Accept"] = NAV_ACCEPT

    # ── Fast path: try Redis cache ──────────────────────────────────────
    cached_versions = None
    cache_key = _version_cache_key(content_class, version_from, version_to)
    try:
        r = _get_sync_redis()
        raw = r.get(cache_key)
        if raw:
            cached_versions = json.loads(raw)
            r.delete(cache_key)  # consume the cache (one-shot)
            logger.info("  📦 Cache HIT: %d versions from Redis key=%s",
                        len(cached_versions), cache_key)
    except Exception as e:
        logger.warning("  ⚠ Redis cache read failed: %s", e)

    if cached_versions:
        total_deleted = 0
        total_errors = 0
        total_skipped_multi = 0
        details = []
        for v in cached_versions:
            result = _delete_version_sections(config, headers, v)
            if result.get("status") == "deleted":
                total_deleted += 1
            elif result.get("status") == "skipped_multi_section":
                total_skipped_multi += 1
            else:
                total_errors += 1
            details.append(result)
        return {
            "content_class": content_class,
            "deleted": total_deleted,
            "errors": total_errors,
            "skipped_multi_section": total_skipped_multi,
            "batches_processed": 1,
            "source": "redis_cache",
            "details": details,
        }

    # ── Slow path: navigate tree in batches of 30 ──────────────────────
    logger.info("  📦 Cache MISS: navigating tree for content class '%s'", content_class)
    BATCH_SIZE = 30

    nav = _navigate_to_cc_folder(content_class, repo)
    if "error" in nav:
        return nav

    target_id = nav["folder_id"]

    dt_from, dt_to = _parse_date_bounds(version_from, version_to)
    use_date_filter = dt_from is not None or dt_to is not None

    total_deleted = 0
    total_errors = 0
    total_skipped_multi = 0
    details = []
    batch_number = 0

    while True:
        batch_number += 1
        # Always fetch the first BATCH_SIZE items (deleted ones disappear)
        url = f"{config.repo_url}/folders/{target_id}/children?limit={BATCH_SIZE}"
        resp = requests.get(url, headers=headers, verify=False, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        versions = data.get("items", [])

        if not versions:
            break

        # SAFETY: verify items are version folders (vdr:reportVersion), not other types
        to_delete = []
        stop_after_batch = False
        for v in versions:
            obj_type = v.get("objectTypeId", "")
            base_type = v.get("baseTypeId", "")
            if obj_type != "vdr:reportVersion":
                logger.warning("  ⚠ SKIPPED non-version item in content class '%s': "
                               "name='%s' objectTypeId='%s' baseTypeId='%s'",
                               content_class, v.get("name", ""), obj_type, base_type)
                continue
            if use_date_filter:
                meta = {m["keyName"]: m["keyValue"] for m in v.get("metadata", [])}
                if not _version_in_range(meta, dt_from, dt_to):
                    stop_after_batch = True
                    continue
            to_delete.append(v)

        if not to_delete:
            break

        # Delete each version's section documents
        for v in to_delete:
            result = _delete_version_sections(config, headers, v)
            if result.get("status") == "deleted":
                total_deleted += 1
            elif result.get("status") == "skipped_multi_section":
                total_skipped_multi += 1
            else:
                total_errors += 1
            details.append(result)

        logger.info("  >> Batch %d: processed %d versions (%d deleted, %d multi-section skipped)",
                    batch_number, len(to_delete),
                    sum(1 for d in details[-len(to_delete):] if d.get("status") == "deleted"),
                    sum(1 for d in details[-len(to_delete):] if d.get("status") == "skipped_multi_section"))

        if stop_after_batch or len(versions) < BATCH_SIZE:
            break

    return {
        "content_class": content_class,
        "deleted": total_deleted,
        "errors": total_errors,
        "skipped_multi_section": total_skipped_multi,
        "batches_processed": batch_number,
        "source": "tree_navigation",
        "details": details,
    }


def _sync_archive_using_policy(policy_name: str, file_path: str, repo: str = "source", content_class: str | None = None) -> dict:
    """Archive a document using an archiving policy via the Mobius REST API.

    The policy must already exist in the repository. The API uses multipart/mixed
    to send the policy reference + file content in a single request.
    Supports TXT and PDF files.

    If the policy's REPORT_ID field (usage=1) does not have a lookupTable
    mapping to the given content_class, a new policy copy is created with
    the name AP_<content_class>_<timestamp> that includes the mapping.
    """
    from datetime import datetime

    config, _ = _resolve_config(repo)
    repo_err = _check_repository_active(config)
    if repo_err:
        return json.loads(repo_err)

    if not policy_name:
        return {"error": "Policy name is required."}
    if not content_class:
        return {"error": "Content class is required."}

    # Auto-resolve original name → registered name from Redis
    try:
        r = _get_sync_redis()
        registered = r.get(f"ce:policy:registered:{policy_name}")
        if registered:
            resolved = registered.decode() if isinstance(registered, bytes) else registered
            if resolved != policy_name:
                logger.info("  📌 Resolved policy '%s' → registered '%s'", policy_name, resolved)
                policy_name = resolved
    except Exception as e:
        logger.warning("  ⚠ Redis lookup for registered name failed: %s", e)

    # Validate content class exists in the repository
    classes = _sync_list_content_classes(repo)
    if isinstance(classes, dict) and "error" in classes:
        return {"error": f"Cannot validate content class: {classes['error']}"}
    valid_ids = {cc.get("id", "").upper() for cc in classes} if isinstance(classes, list) else set()
    valid_names = {cc.get("name", "").upper() for cc in classes} if isinstance(classes, list) else set()
    if content_class.upper() not in valid_ids and content_class.upper() not in valid_names:
        available = ", ".join(sorted(cc.get("id", "") for cc in classes)) if isinstance(classes, list) else "unknown"
        return {"error": f"Content class '{content_class}' does not exist in the repository. Available: {available}"}

    # ── Fetch policy and ensure content class mapping ──
    try:
        policy_data = _sync_get_archiving_policy(policy_name, repo)
    except Exception as e:
        return {"error": f"Cannot fetch policy '{policy_name}': {e}"}
    if isinstance(policy_data, dict) and "error" in policy_data:
        return {"error": f"Cannot fetch policy '{policy_name}': {policy_data['error']}"}

    # Find the REPORT_ID group (usage=1) and its referenced field
    actual_policy_name = policy_name
    report_field_name = None
    report_rule_name = None
    for fg in policy_data.get("fieldGroups", []):
        if str(fg.get("usage", "")) == "1":
            for ref in fg.get("fieldRefs", []):
                report_field_name = ref.get("fieldName")
                report_rule_name = ref.get("ruleName")
                break
            break

    # Check if the field already has the content class in its lookupTable
    needs_update = False
    if report_field_name:
        for rule in policy_data.get("rules", []):
            if report_rule_name and rule.get("name") != report_rule_name:
                continue
            for field in rule.get("fields", []):
                if field.get("name") == report_field_name:
                    oi = field.get("outputInfo", {})
                    lt = oi.get("lookupTable") or []
                    has_cc = any(
                        entry.get("value", "").upper() == content_class.upper()
                        for entry in lt
                    )
                    if not has_cc:
                        needs_update = True
                        # Set useLookupTable and add entries
                        oi["useLookupTable"] = True
                        oi["lookupTable"] = [
                            {"name": "ASGLookupTableDefault", "value": content_class},
                        ]
                        field["outputInfo"] = oi
                    break
            if needs_update:
                break
    else:
        # No REPORT_ID group at all — inject one using the first field of the first rule
        rules = policy_data.get("rules", [])
        if rules and rules[0].get("fields"):
            first_rule = rules[0]
            first_field = first_rule["fields"][0]
            # Add lookupTable to existing first field
            oi = first_field.get("outputInfo", {})
            oi["useLookupTable"] = True
            oi["lookupTable"] = [
                {"name": "ASGLookupTableDefault", "value": content_class},
            ]
            first_field["outputInfo"] = oi
            # Add REPORT_ID field group referencing this field
            policy_data.setdefault("fieldGroups", []).insert(0, {
                "name": "REPORT_ID",
                "retainFieldValues": True,
                "isDefault": False,
                "hide": False,
                "fieldRefs": [{
                    "ruleName": first_rule["name"],
                    "fieldName": first_field["name"],
                    "optional": False,
                    "hideDuplicateValues": False,
                }],
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
            })
            needs_update = True
            logger.info("  >> Policy '%s' has no REPORT_ID group, injecting one with content class '%s'",
                         policy_name, content_class)

    if needs_update:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_name = f"AP_{content_class}_{ts}"
        policy_data["name"] = new_name
        policy_data.pop("links", None)
        logger.info("  >> Policy '%s' missing content class '%s', creating '%s'",
                     policy_name, content_class, new_name)
        try:
            create_result = _sync_create_archiving_policy(policy_data, repo)
            if isinstance(create_result, dict) and "error" in create_result:
                return {"error": f"Failed to create updated policy '{new_name}': {create_result['error']}"}
            logger.info("  >> Updated policy registered: %s", new_name)
        except Exception as e:
            return {"error": f"Failed to create updated policy '{new_name}': {e}"}
        # Save locally too
        output_dir = WORKSPACE_ROOT / "tmp"
        output_dir.mkdir(parents=True, exist_ok=True)
        with open(output_dir / f"{new_name}.json", "w", encoding="utf-8") as f:
            json.dump(policy_data, f, indent=2, ensure_ascii=False)
        actual_policy_name = new_name

    # Resolve file path
    workspace_dir = str(WORKSPACE_ROOT)
    work_dir = os.environ.get("CE_WORK_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "contentedge", "files"))
    allowed_roots = [os.path.normpath(work_dir), os.path.normpath(workspace_dir)]

    if file_path.startswith("workspace/") or file_path.startswith("workspace\\"):
        abs_path = os.path.join(workspace_dir, file_path[len("workspace/"):])
    elif os.path.isabs(file_path):
        abs_path = file_path
    else:
        abs_path = os.path.join(work_dir, file_path)
    abs_path = os.path.normpath(abs_path)

    if not any(abs_path.startswith(root) for root in allowed_roots):
        return {"error": f"File '{file_path}' is outside the allowed directories."}
    if not os.path.isfile(abs_path):
        return {"error": f"File not found: '{file_path}'"}

    ext = os.path.splitext(abs_path)[1].upper().lstrip(".")
    boundary = "boundaryString"

    metadata_json = {"objects": [{"policies": [actual_policy_name]}]}
    metadata_str = json.dumps(metadata_json, indent=4)

    if ext in ("TXT", "SYS", "LOG"):
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                file_content = f.read()
        except UnicodeDecodeError:
            with open(abs_path, "r", encoding="latin-1") as f:
                file_content = f.read()
        content_type_part = "Content-Type: archive/file"
        file_body = file_content
    elif ext == "PDF":
        with open(abs_path, "rb") as f:
            file_body = base64.b64encode(f.read()).decode("utf-8")
        content_type_part = "Content-Type: application/pdf\nContent-Transfer-Encoding: base64"
    else:
        return {"error": f"Unsupported file type '{ext}'. Only TXT, SYS, LOG, PDF are supported."}

    body_parts = [
        f"--{boundary}",
        "Content-Type: application/vnd.asg-mobius-archive-write-policy.v2+json",
        "",
        metadata_str,
        f"--{boundary}",
        content_type_part,
        "",
        file_body,
        "",
        f"--{boundary}--",
    ]
    body = "\n".join(body_parts)

    headers = deepcopy(config.headers)
    headers["Content-Type"] = f"multipart/mixed; TYPE=policy; boundary={boundary}"
    headers["Accept"] = "application/vnd.asg-mobius-archive-write-status.v2+json"

    url = f"{config.repo_url}/repositories/{config.repo_id}/documents?returnids=true"
    resp = requests.post(url, headers=headers, data=body, verify=False, timeout=120)

    success = resp.status_code in (200, 201)
    result = {
        "success": success,
        "status_code": resp.status_code,
        "policy_name": actual_policy_name,
        "original_policy": policy_name,
        "content_class": content_class,
        "file": os.path.basename(abs_path),
    }
    if needs_update:
        result["warning"] = (
            f"A new policy '{actual_policy_name}' was created from '{policy_name}' "
            f"with content class '{content_class}' added to its lookup table."
        )
    if success:
        try:
            result["response"] = resp.json()
        except Exception:
            result["response_text"] = resp.text[:500]
    else:
        result["error"] = resp.text[:500]

    return result


# ── Async wrapper (offloads blocking I/O to thread pool) ──────────────────

async def _run_sync(func, *args):
    """Run a blocking function in an executor to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args))

async def contentedge_search(
    constraints: str,
    conjunction: str = "AND",
    repo: str = "source",
) -> str:
    """Search for documents in ContentEdge by index values.

    Use this to find documents matching a specific customer, date, etc.
    Returns a list of objectIds that can be passed to contentedge_smart_chat.

    Args:
        constraints: JSON array of search constraints.
                     Each element: {"index_name":"...", "operator":"EQ", "value":"..."}.
                     Example: [{"index_name":"CUST_ID","operator":"EQ","value":"1000"}]
        conjunction: How to combine constraints — "AND" or "OR". Default "AND".
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_search")
    logger.info("     constraints=%s  conjunction=%s  repo=%s", constraints[:200], conjunction, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        parsed = json.loads(constraints)
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON in constraints — {e}"
    try:
        result = await _run_sync(_sync_search, parsed, conjunction, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("contentedge_search.error", error=str(e))
        return f"Error calling ContentEdge search: {e}"


async def contentedge_smart_chat(
    question: str,
    document_ids: str = "[]",
    conversation_id: str = "",
    repo: str = "source",
) -> str:
    """Ask a question to ContentEdge Smart Chat AI about documents in the repository.

    Two modes:
    1. Repository-wide: pass document_ids as "[]" to query ALL documents.
    2. Scoped: pass a JSON array of objectIds (from contentedge_search) to
       limit the question to specific documents.

    For follow-up questions pass the conversation_id from the previous response.

    Args:
        question: The question to ask about the documents.
        document_ids: JSON array of objectIds, e.g. '["abc","def"]'. Use "[]" for repository-wide.
        conversation_id: conversation_id from a prior call to continue the conversation.
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_smart_chat")
    logger.info("     question=%s  repo=%s", question[:200], repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        ids = json.loads(document_ids)
    except json.JSONDecodeError:
        ids = []
    try:
        result = await _run_sync(_sync_smart_chat, question, ids if ids else None, conversation_id, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("contentedge_smart_chat.error", error=str(e))
        return f"Error calling ContentEdge Smart Chat: {e}"


async def contentedge_get_document_url(object_id: str, repo: str = "source") -> str:
    """Get a viewer URL to open a ContentEdge document in the browser.

    Call this for each document objectId returned by Smart Chat to provide
    clickable links to the user.

    Args:
        object_id: The encrypted objectId of the document.
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_get_document_url")
    logger.info("     object_id=%s  repo=%s", object_id[:60], repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_get_document_url, object_id, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("contentedge_get_document_url.error", error=str(e))
        return f"Error getting document URL: {e}"


async def contentedge_list_content_classes(repo: str = "source") -> str:
    """List all available Content Classes in the ContentEdge repository.

    Args:
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_list_content_classes")
    logger.info("     repo=%s", repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_list_content_classes, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("contentedge_list_content_classes.error", error=str(e))
        return f"Error listing content classes: {e}"


async def contentedge_list_indexes(repo: str = "source") -> str:
    """List all available indexes and index groups in the ContentEdge repository.

    Args:
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_list_indexes")
    logger.info("     repo=%s", repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_list_indexes, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("contentedge_list_indexes.error", error=str(e))
        return f"Error listing indexes: {e}"


async def contentedge_verify_index_group(identifier: str, repo: str = "source") -> str:
    """Verify whether an index group exists by ID or name."""
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_verify_index_group")
    logger.info("     identifier=%s  repo=%s", identifier, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_find_index_group, identifier, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("contentedge_verify_index_group.error", error=str(e))
        return f"Error verifying index group: {e}"


async def contentedge_create_index_group(group_definition: str, repo: str = "target") -> str:
    """Create an index group from a JSON definition using existing repository indexes."""
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_create_index_group")
    logger.info("     repo=%s", repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_create_index_group, group_definition, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("contentedge_create_index_group.error", error=str(e))
        return f"Error creating index group: {e}"


async def contentedge_archive_documents(
    content_class: str,
    files: str,
    metadata: str,
    sections: str = "[]",
    repo: str = "source",
) -> str:
    """Archive one or more documents into the ContentEdge repository.

    Args:
        content_class: Content class name (e.g. "AC001", "LISTFILE").
        files: JSON array of file paths. Accepts:
               - Relative paths resolved against CE working directory (e.g. "report.pdf")
               - Paths prefixed with "workspace/" resolved against the agent workspace
                 (e.g. "workspace/knowledge/doc.pdf")
        metadata: JSON object of index name-value pairs (e.g. '{"CUST_ID":"3000"}').
                  Index names are validated against the repository schema.
                  If an index belongs to a compound group, ALL members must be provided.
        sections: Optional JSON array of section names (one per file). Default "[]".
        repo: Repository to use — "source" (default) or "target".
    """
    return _disabled_tool_response("contentedge_archive_documents")


async def contentedge_get_versions(
    report_id: str,
    version_from: str,
    version_to: str,
    repo: str = "source",
) -> str:
    """Get document version history for a report within a date range.

    Args:
        report_id: Report identifier (e.g. "AC2020").
        version_from: Start date in format yyyymmddHHMMSS (e.g. "20220401000000").
        version_to: End date in format yyyymmddHHMMSS (e.g. "20220801000000").
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_get_versions")
    logger.info("     report_id=%s  from=%s  to=%s  repo=%s", report_id, version_from, version_to, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_get_versions, report_id, version_from, version_to, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("contentedge_get_versions.error", error=str(e))
        return f"Error getting versions: {e}"


async def contentedge_search_archiving_policies(
    name: str = "*",
    withcontent: bool = False,
    limit: int = 200,
    repo: str = "source",
) -> str:
    """Search for archiving policies in the ContentEdge repository.

    Returns a list of policies matching the name filter.
    Use '*' or a partial name with '*' for wildcard matching.

    Args:
        name: Policy name or pattern with '*' for wildcards (e.g. "SAMPLE*"). Default "*" returns all.
        withcontent: If true, return full policy data for each match. Default false (names only).
        limit: Maximum number of policies to return. Default 200.
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_search_archiving_policies")
    logger.info("     name=%s  withcontent=%s  limit=%s  repo=%s", name, withcontent, limit, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_search_archiving_policies, name, withcontent, limit, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("contentedge_search_archiving_policies.error", error=str(e))
        return f"Error searching archiving policies: {e}"


async def contentedge_create_archiving_policy(
    name: str,
    policy_json: str = "{}",
    repo: str = "source",
) -> str:
    """Create a new archiving policy in the ContentEdge repository.

    The policy name must be unique (max 251 alphanumeric characters).

    Args:
        name: Unique policy name (e.g. "MY_NEW_POLICY").
        policy_json: Optional JSON string with additional policy properties.
                     Supported properties: policyType, version, details, sampleFile,
                     fileParsingInfo (dataType, charSet, pageBreak, lineBreak),
                     fieldGroups, rules.
                     Example: '{"details": "Monthly report policy", "fileParsingInfo": {"dataType": "PDF"}}'
        repo: Repository to use — "source" (default) or "target".
    """
    return _disabled_tool_response("contentedge_create_archiving_policy")


async def contentedge_get_archiving_policy(name: str, repo: str = "source") -> str:
    """Retrieve the full details of a specific archiving policy by name.

    Returns the complete policy definition including rules, fieldGroups,
    fileParsingInfo, scope, sorts, etc.

    Args:
        name: The exact policy name (e.g. "AC001_POLICY").
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_get_archiving_policy")
    logger.info("     name=%s  repo=%s", name, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_get_archiving_policy, name, repo)
        return json.dumps(result, ensure_ascii=False)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        body = e.response.text[:500] if e.response is not None else ""
        logger.error("contentedge_get_archiving_policy.http_error", status=status, body=body)
        return f"Error retrieving archiving policy (HTTP {status}): {body}"
    except Exception as e:
        logger.error("contentedge_get_archiving_policy.error", error=str(e))
        return f"Error retrieving archiving policy: {e}"


async def contentedge_modify_archiving_policy(
    name: str,
    policy_json: str,
    repo: str = "source",
) -> str:
    """Modify an existing archiving policy in the ContentEdge repository.

    Sends a PUT request with the updated policy definition. You should first
    retrieve the current policy with contentedge_get_archiving_policy, modify
    the desired fields, and pass the full updated JSON here.

    Args:
        name: The exact policy name to modify (e.g. "AC001_POLICY").
        policy_json: JSON string with the full updated policy definition.
                     Must include all fields you want to keep — this replaces
                     the entire policy.
        repo: Repository to use — "source" (default) or "target".
    """
    return _disabled_tool_response("contentedge_modify_archiving_policy")


async def contentedge_export_archiving_policy(name: str, repo: str = "source") -> str:
    """Export an archiving policy to a JSON file in workspace/archiving_policies/.

    Retrieves the full policy definition from the ContentEdge repository and
    saves it as workspace/archiving_policies/<name>.json.
    Useful for backup, review, or offline editing before re-importing.

    Args:
        name: The exact policy name to export (e.g. "AC001_POLICY").
        repo: Repository to use — "source" (default) or "target".
    """
    return _disabled_tool_response("contentedge_export_archiving_policy")


async def contentedge_delete_archiving_policy(name: str, repo: str = "source") -> str:
    """Delete an archiving policy from the ContentEdge repository.

    IMPORTANT: The agent MUST first call contentedge_search_archiving_policies
    or contentedge_get_archiving_policy to show the user which policy will be
    deleted, and get explicit confirmation BEFORE calling this tool.
    Permanently removes the named policy. This cannot be undone.

    Args:
        name: The exact policy name to delete (e.g. "TEST_POLICY").
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_delete_archiving_policy")
    logger.info("     name=%s  repo=%s", name, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_delete_archiving_policy, name, repo)
        logger.info("  ✅ RESULT: delete_archiving_policy → %s", json.dumps(result))
        return json.dumps(result, ensure_ascii=False)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        body = e.response.text[:500] if e.response is not None else ""
        logger.error("contentedge_delete_archiving_policy.http_error", status=status, body=body)
        return f"Error deleting archiving policy (HTTP {status}): {body}"
    except Exception as e:
        logger.error("contentedge_delete_archiving_policy.error", error=str(e))
        return f"Error deleting archiving policy: {e}"


async def contentedge_generate_archiving_policy(
    name: str,
    policy_spec_json: Any,
    repo: str = "source",
) -> str:
    """Generate a Mobius archiving policy JSON and return a PREVIEW for user confirmation.

    Builds a complete Mobius-format archiving policy JSON file and saves it
    to workspace/archiving_policies/<name>.json. Does NOT register the policy
    in Mobius yet. Returns a detailed preview including:
    - All field definitions with their positions and configuration
    - REPORT_ID value (content class mapping)
    - SECTION_ID and VERSION_ID extracted values from the first 3 pages of the source file
    - Sample extracted values for every field from the first 3 pages

    IMPORTANT: The agent MUST present this preview to the user and get explicit
    confirmation BEFORE calling contentedge_register_archiving_policy to create
    the policy in the ContentEdge repository.

    POSITION SYSTEM (1-based columns, 1-based lines within each page):
    - left: START column (1-based). E.g. left=9 means extraction starts at column 9.
    - right: END column (1-based, inclusive). E.g. to extract "4022" from cols 9-12, set left=9, right=12.
      Set right=0 to read from left until the next terminator (usually a space).
      IMPORTANT: If the user says "extract X from column N", compute right = N + len(X) - 1.
    - top: line number within page (1=first line, 2=second, etc.; 0=detail/data lines)
    - bottom: 0 always for header fields
    - levelType: "header1" for per-page header fields

    FIELD GROUP USAGES:
    - usage=1: REPORT ID — identifies the report/content class
    - usage=2: SECTION ID — section identifier (max 20 chars when concatenated)
    - usage=3: TOPIC — must match an existing repository index name
    - usage=5: VERSION ID — version/date identifier

    Args:
        name: Policy name (e.g. "ST32L1_POLICY").
        policy_spec_json: JSON string (or dict) with the policy specification containing:
            - description (str): policy description
            - source_file (str): original source file path (informational)
            - documentInfo (dict): {dataType, charSet, pageBreak, lineBreak}
            - fields (list): field definitions, each with:
                name, type (string|date|number), levelType, left, right, top,
                bottom, format (input format e.g. "MM/DD/YYYY"),
                outputFormat (e.g. "YYYYMMDD"), minLength, maxLength, terminator
            - fieldGroups (list): group definitions, each with:
                name, usage (1|2|3|5), fields (list of field names)
    """
    return _disabled_tool_response("contentedge_generate_archiving_policy")


async def contentedge_register_archiving_policy(
    name: str,
    repo: str = "source",
) -> str:
    """Register a previously generated archiving policy in the ContentEdge repository.

    Call this ONLY after the user has reviewed and confirmed the preview from
    contentedge_generate_archiving_policy. Reads the saved policy JSON from
    workspace/archiving_policies/<name>.json and registers it in Mobius.

    Args:
        name: The policy name as returned by contentedge_generate_archiving_policy.
        repo: Repository to use — "source" (default) or "target".
    """
    return _disabled_tool_response("contentedge_register_archiving_policy")


async def contentedge_archive_using_policy(
    policy_name: str,
    file_path: str,
    repo: str = "source",
    content_class: str | None = None,
) -> str:
    """Archive a document into ContentEdge using an archiving policy.

    The policy defines how the file is parsed: which fields to extract,
    their positions, the content class, sections, version, etc.
    The policy must already exist in the repository (create it first with
    contentedge_create_archiving_policy if needed).

    Validates that the content class exists in the repository before archiving.
    Supports TXT and PDF files. File paths follow the same rules as
    contentedge_archive_documents.

    Args:
        policy_name: Name of an existing archiving policy (e.g. "CO17_POLICY").
        file_path: Path to the file to archive. Accepts:
                   - Relative paths resolved against CE working directory (e.g. "report.txt")
                   - Paths prefixed with "workspace/" (e.g. "workspace/tmp/CO17.TXT")
        repo: Repository to use — "source" (default) or "target".
        content_class: Optional content class override (e.g. "AC001"). If not provided,
                      will be extracted from the policy's REPORT_ID field mapping.
    """
    return _disabled_tool_response("contentedge_archive_using_policy")


async def contentedge_list_content_class_versions(
    content_class: str,
    version_from: str = "",
    version_to: str = "",
    repo: str = "source",
) -> str:
    """List versions (documents) under a content class for preview before deletion.

    Use this tool BEFORE any delete operation on content class versions to show
    the user what will be affected and get confirmation.

    Returns the list of versions with their objectIds, names, and metadata.
    Supports optional date range filtering on ReportVersionID.

    Args:
        content_class: The content class ID (e.g. "AC002").
        version_from: Optional start date (inclusive, ISO format e.g. "2026-12-12"). Empty = no lower bound.
        version_to: Optional end date (inclusive, ISO format e.g. "2026-12-25"). Empty = no upper bound.
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_list_content_class_versions")
    logger.info("     content_class=%s  version_from=%s  version_to=%s  repo=%s", content_class, version_from, version_to, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(
            _sync_list_content_class_versions,
            content_class,
            version_from or None,
            version_to or None,
            repo,
        )
        logger.info("  ✅ RESULT: list_content_class_versions → count=%s",
                     result.get("count", "?"))
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ RESULT: list_content_class_versions error", error=str(e))
        return f"Error listing content class versions: {e}"


async def contentedge_delete_documents_by_ids(
    object_ids: str,
    repo: str = "source",
) -> str:
    """Delete multiple documents from the ContentEdge repository by their objectIds.

    IMPORTANT: The agent MUST always present the list of documents to the user
    and get explicit confirmation BEFORE calling this tool.

    Use this after contentedge_search to delete specific documents the user
    has confirmed for deletion.

    Args:
        object_ids: JSON array of objectIds to delete, e.g. '["abc123", "def456"]'.
        repo: Repository to use — "source" (default) or "target".
    """
    return _disabled_tool_response("contentedge_delete_documents_by_ids")


async def contentedge_delete_document(
    document_id: str,
    repo: str = "source",
) -> str:
    """Delete a single document/version from the ContentEdge repository.

    IMPORTANT: The agent MUST always ask the user for confirmation before
    calling this tool. Present what will be deleted and wait for explicit approval.

    Uses the document's objectId (as returned by search or navigation).

    Args:
        document_id: The encrypted objectId of the document to delete.
        repo: Repository to use — "source" (default) or "target".
    """
    return _disabled_tool_response("contentedge_delete_document")


async def contentedge_delete_content_class_versions(
    content_class: str,
    version_from: str = "",
    version_to: str = "",
    repo: str = "source",
) -> str:
    """Delete versions (documents) under a content class in batches of 30, optionally filtered by date range.

    IMPORTANT: The agent MUST first call contentedge_list_content_class_versions to
    preview what will be deleted, present the results to the user, and get explicit
    confirmation BEFORE calling this tool.

    Fetches 30 versions at a time, deletes their section documents, then fetches
    the next 30 (since deleted items are removed), repeating until done.
    Without date filters, deletes ALL versions.

    Args:
        content_class: The content class ID (e.g. "AC002").
        version_from: Optional start date (inclusive, ISO format e.g. "2026-12-12"). Empty = no lower bound.
        version_to: Optional end date (inclusive, ISO format e.g. "2026-12-25"). Empty = no upper bound.
        repo: Repository to use — "source" (default) or "target".
    """
    return _disabled_tool_response("contentedge_delete_content_class_versions")


async def contentedge_delete_search_results(
    constraints: list[dict],
    conjunction: str = "AND",
    repo: str = "source",
) -> str:
    """Search for documents by index values and delete all matching results.

    IMPORTANT: The agent MUST first call contentedge_search to preview the matching
    documents, present the count and details to the user, and get explicit
    confirmation BEFORE calling this tool.

    First performs a search using the given constraints, then deletes every
    document returned.

    Args:
        constraints: List of search constraints. Each dict must have:
            - index_name (str): index name (e.g. "DEPT", "CONTENT_CLASS")
            - operator (str): comparison operator (EQ, NE, GT, LT, GE, LE, LIKE)
            - value (str): value to match
        conjunction: How to combine constraints — "AND" (default) or "OR".
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_delete_search_results")
    logger.info("     constraints=%s  conjunction=%s  repo=%s", constraints, conjunction, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        search_result = await _run_sync(_sync_search, constraints, conjunction, repo)
        if "error" in search_result:
            return json.dumps(search_result, ensure_ascii=False)

        object_ids = search_result.get("object_ids", [])
        if not object_ids:
            result = {"deleted": 0, "errors": 0, "message": "No documents matched the search."}
            logger.info("  ✅ RESULT: delete_search_results → %s", json.dumps(result))
            return json.dumps(result, ensure_ascii=False)

        deleted = 0
        errors = 0
        for oid in object_ids:
            try:
                r = await _run_sync(_sync_delete_document, oid, repo)
                if r.get("success"):
                    deleted += 1
                else:
                    errors += 1
            except Exception:
                errors += 1

        result = {"deleted": deleted, "errors": errors, "total_found": len(object_ids)}
        logger.info("  ✅ RESULT: delete_search_results → %s", json.dumps(result))
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ RESULT: delete_search_results error", error=str(e))
        return f"Error deleting search results: {e}"


# ── Sync helpers for export/import ────────────────────────────────────────

_EXPORT_BASE = os.path.join(WORKSPACE_ROOT, "exports")


def _sync_export_all(repo: str = "source") -> dict:
    """Export all admin objects from SOURCE to workspace/export_<timestamp>/."""
    api = _get_services_api()
    export_dir = api.export_all(base_dir=os.path.join(WORKSPACE_ROOT))
    src = _get_ce_config()
    return {
        "success": True,
        "source": f"{src.repo_name} @ {src.base_url}",
        "export_dir": export_dir,
    }


def _sync_export_content_classes(filter_pattern: str, repo: str = "source") -> dict:
    """Export content classes from SOURCE matching filter."""
    from lib.content_adm_services_api import ContentAdmServicesApi
    config, _ = _resolve_config(repo)
    os.makedirs(_EXPORT_BASE, exist_ok=True)
    from lib.content_adm_content_class import ContentAdmContentClass
    adm_repo = ContentAdmContentClass(config)
    file_path = adm_repo.export_content_classes(filter_pattern, _EXPORT_BASE)
    if file_path:
        with open(file_path) as f:
            count = len(json.load(f))
        return {"success": True, "repo": f"{config.repo_name} @ {config.base_url}",
                "file": file_path, "count": count, "filter": filter_pattern}
    return {"success": True, "repo": f"{config.repo_name} @ {config.base_url}",
            "count": 0, "filter": filter_pattern, "message": "No matching content classes found."}


def _sync_export_indexes(filter_pattern: str, repo: str = "source") -> dict:
    """Export indexes from SOURCE matching filter."""
    config, _ = _resolve_config(repo)
    os.makedirs(_EXPORT_BASE, exist_ok=True)
    from lib.content_adm_index import ContentAdmIndex
    adm_repo = ContentAdmIndex(config)
    file_path = adm_repo.export_indexes(filter_pattern, _EXPORT_BASE)
    if file_path:
        with open(file_path) as f:
            count = len(json.load(f))
        return {"success": True, "repo": f"{config.repo_name} @ {config.base_url}",
                "file": file_path, "count": count, "filter": filter_pattern}
    return {"success": True, "repo": f"{config.repo_name} @ {config.base_url}",
            "count": 0, "filter": filter_pattern, "message": "No matching indexes found."}


def _sync_export_index_groups(filter_pattern: str, repo: str = "source") -> dict:
    """Export index groups from SOURCE matching filter."""
    config, _ = _resolve_config(repo)
    os.makedirs(_EXPORT_BASE, exist_ok=True)
    from lib.content_adm_index_group import ContentAdmIndexGroup
    adm_repo = ContentAdmIndexGroup(config)
    file_path = adm_repo.export_index_groups(filter_pattern, _EXPORT_BASE)
    if file_path:
        with open(file_path) as f:
            count = len(json.load(f))
        return {"success": True, "repo": f"{config.repo_name} @ {config.base_url}",
                "file": file_path, "count": count, "filter": filter_pattern}
    return {"success": True, "repo": f"{config.repo_name} @ {config.base_url}",
            "count": 0, "filter": filter_pattern, "message": "No matching index groups found."}


def _sync_import_all(export_dir: str, repo: str = "target") -> dict:
    """Import all admin objects from export directory into the chosen repo."""
    from lib.content_adm_services_api import ContentAdmServicesApi

    # The library always imports into its "target" config.
    # When the user picks a repo we set that repo as the target.
    if repo == "source":
        src_config = _get_target_config()   # swap: source becomes the "export" side
        tgt_config = _get_ce_config()       # and "source" repo becomes the import target
    else:
        src_config = _get_ce_config()
        tgt_config = _get_target_config()

    api = ContentAdmServicesApi(src_config.config_file, tgt_config.config_file)
    results = api.import_all(export_dir)
    return {
        "success": True,
        "target": f"{tgt_config.repo_name} @ {tgt_config.base_url}",
        "export_dir": export_dir,
        "results": results,
    }


def _sync_import_content_classes(file_path: str, repo: str = "target") -> dict:
    """Import content classes from a JSON file into the chosen repo."""
    if repo == "source":
        tgt_config = _get_ce_config()
    else:
        tgt_config = _get_target_config()

    repo_err = _check_repository_active(tgt_config)
    if repo_err:
        return json.loads(repo_err)

    from lib.content_adm_content_class import ContentAdmContentClass
    adm = ContentAdmContentClass(tgt_config)
    counts = adm.import_content_classes(file_path)
    return {
        "success": True,
        "target": f"{tgt_config.repo_name} @ {tgt_config.base_url}",
        "file": file_path,
        "results": counts,
    }


def _sync_import_indexes(file_path: str, repo: str = "target") -> dict:
    """Import indexes from a JSON file into the chosen repo."""
    if repo == "source":
        tgt_config = _get_ce_config()
    else:
        tgt_config = _get_target_config()

    repo_err = _check_repository_active(tgt_config)
    if repo_err:
        return json.loads(repo_err)

    from lib.content_adm_index import ContentAdmIndex
    adm = ContentAdmIndex(tgt_config)
    counts = adm.import_indexes(file_path)
    return {
        "success": True,
        "target": f"{tgt_config.repo_name} @ {tgt_config.base_url}",
        "file": file_path,
        "results": counts,
    }


def _sync_import_index_groups(file_path: str, repo: str = "target") -> dict:
    """Import index groups from a JSON file into the chosen repo."""
    if repo == "source":
        tgt_config = _get_ce_config()
    else:
        tgt_config = _get_target_config()

    repo_err = _check_repository_active(tgt_config)
    if repo_err:
        return json.loads(repo_err)

    from lib.content_adm_index_group import ContentAdmIndexGroup
    adm = ContentAdmIndexGroup(tgt_config)
    counts = adm.import_index_groups(file_path)
    return {
        "success": True,
        "target": f"{tgt_config.repo_name} @ {tgt_config.base_url}",
        "file": file_path,
        "results": counts,
    }


async def contentedge_import_content_classes(file_path: str, repo: str = "target") -> str:
    """Import content classes from a previously exported JSON file into a repository.

    IMPORTANT — CONFIRMATION REQUIRED:
    The agent MUST show the user:
    - The destination repository name and URL
    - The file contents (number of content classes)
    - Ask: "This will import N content classes into REPO (name @ URL). Proceed?"
    - ONLY call this tool AFTER the user confirms.

    Objects that already exist on the destination are skipped (409).

    Args:
        file_path: Path to the JSON file (e.g. "workspace/exports/content_class_20260318_150316.json").
        repo: Repository to import INTO — "target" (default) or "source".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_import_content_classes")
    logger.info("     file_path=%s  repo=%s", file_path, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_import_content_classes, file_path, repo)
        logger.info("  ✅ RESULT: import_content_classes → %s", json.dumps(result, ensure_ascii=False)[:500])
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ RESULT: import_content_classes error", error=str(e))
        return f"Error importing content classes: {e}"


async def contentedge_import_indexes(file_path: str, repo: str = "target") -> str:
    """Import indexes from a previously exported JSON file into a repository.

    IMPORTANT — CONFIRMATION REQUIRED:
    The agent MUST show the user:
    - The destination repository name and URL
    - The file contents (number of indexes)
    - Ask: "This will import N indexes into REPO (name @ URL). Proceed?"
    - ONLY call this tool AFTER the user confirms.

    Objects that already exist on the destination are skipped (409).

    Args:
        file_path: Path to the JSON file (e.g. "workspace/exports/indexes_20260318_150316.json").
        repo: Repository to import INTO — "target" (default) or "source".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_import_indexes")
    logger.info("     file_path=%s  repo=%s", file_path, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_import_indexes, file_path, repo)
        logger.info("  ✅ RESULT: import_indexes → %s", json.dumps(result, ensure_ascii=False)[:500])
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ RESULT: import_indexes error", error=str(e))
        return f"Error importing indexes: {e}"


async def contentedge_import_index_groups(file_path: str, repo: str = "target") -> str:
    """Import index groups from a previously exported JSON file into a repository.

    IMPORTANT — CONFIRMATION REQUIRED:
    The agent MUST show the user:
    - The destination repository name and URL
    - The file contents (number of index groups)
    - Ask: "This will import N index groups into REPO (name @ URL). Proceed?"
    - ONLY call this tool AFTER the user confirms.

    Objects that already exist on the destination are skipped (409).

    Args:
        file_path: Path to the JSON file (e.g. "workspace/exports/index_groups_20260318_150316.json").
        repo: Repository to import INTO — "target" (default) or "source".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_import_index_groups")
    logger.info("     file_path=%s  repo=%s", file_path, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_import_index_groups, file_path, repo)
        logger.info("  ✅ RESULT: import_index_groups → %s", json.dumps(result, ensure_ascii=False)[:500])
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ RESULT: import_index_groups error", error=str(e))
        return f"Error importing index groups: {e}"


async def contentedge_repo_info() -> str:
    """Show information about the configured SOURCE and TARGET repositories.

    Returns the repository name and URL for both SOURCE (primary) and TARGET (secondary).
    Call this when the user asks about the repository configuration or connection status.
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_repo_info")
    logger.info("══════════════════════════════════════════════════════")
    info = {}
    try:
        src = _get_ce_config()
        err = _check_repository_active(src)
        info["source"] = {
            "name": src.repo_name,
            "url": src.base_url,
            "status": "active" if err is None else "unreachable",
        }
    except Exception as e:
        info["source"] = {"error": str(e)}
    try:
        tgt = _get_target_config()
        err = _check_repository_active(tgt)
        info["target"] = {
            "name": tgt.repo_name,
            "url": tgt.base_url,
            "status": "active" if err is None else "unreachable",
        }
    except Exception as e:
        info["target"] = {"error": str(e)}
    return json.dumps(info, ensure_ascii=False)


async def contentedge_export_content_classes(filter: str = "*", repo: str = "source") -> str:
    """Export content classes from the SOURCE repository to a JSON file.

    Always shows the SOURCE repository URL. Use filter to narrow results:
    - "*" for all, "AC*" for names starting with AC, "AC001" for exact match.

    Args:
        filter: Wildcard filter for content class IDs (default "*" = all).
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_export_content_classes")
    logger.info("     filter=%s  repo=%s", filter, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_export_content_classes, filter, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ export_content_classes error", error=str(e))
        return f"Error exporting content classes: {e}"


async def contentedge_export_indexes(filter: str = "*", repo: str = "source") -> str:
    """Export indexes from the SOURCE repository to a JSON file.

    Always shows the SOURCE repository URL. Use filter to narrow results:
    - "*" for all, "Cust*" for names starting with Cust, "CustID" for exact match.

    Args:
        filter: Wildcard filter for index IDs (default "*" = all).
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_export_indexes")
    logger.info("     filter=%s  repo=%s", filter, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_export_indexes, filter, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ export_indexes error", error=str(e))
        return f"Error exporting indexes: {e}"


async def contentedge_export_index_groups(filter: str = "*", repo: str = "source") -> str:
    """Export index groups from the SOURCE repository to a JSON file.

    Always shows the SOURCE repository URL. Use filter to narrow results:
    - "*" for all, "Person*" for names starting with Person.

    Args:
        filter: Wildcard filter for index group IDs (default "*" = all).
        repo: Repository to use — "source" (default) or "target".
    """
    logger.info("\n══════════════════════════════════════════════════════")
    logger.info("  🔧 TOOL CALL: contentedge_export_index_groups")
    logger.info("     filter=%s  repo=%s", filter, repo)
    logger.info("══════════════════════════════════════════════════════")
    try:
        result = await _run_sync(_sync_export_index_groups, filter, repo)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ export_index_groups error", error=str(e))
        return f"Error exporting index groups: {e}"


async def contentedge_export_all(repo: str = "source") -> str:
    """Export all admin objects (content classes, indexes, index groups, archiving policies) from a repository to a timestamped directory.

    Creates workspace/export_<YYYYMMDD_HHMMSS>/ with subdirectories for each object type
    plus a manifest.json with metadata.

    The agent MUST show the user:
    - Repository name and URL before starting
    - The export directory path and object counts when done

    Args:
        repo: Repository to export from — "source" (default) or "target".
    """
    return _disabled_tool_response("contentedge_export_all")


async def contentedge_import_all(export_dir: str, repo: str = "target") -> str:
    """Import all admin objects from an export directory into a repository.

    IMPORTANT — CONFIRMATION REQUIRED:
    The agent MUST show the user:
    - The destination repository name and URL
    - The export directory contents (from manifest.json)
    - Ask: "This will import N content classes, N indexes, N index groups, and N archiving policies into REPO (name @ URL). Proceed?"
    - ONLY call this tool AFTER the user confirms.

    Import order: indexes → index_groups → content_classes → archiving_policies.
    Objects that already exist on the destination are skipped (409).

    Args:
        export_dir: Path to the export directory (e.g. "workspace/export_20260318_150316").
        repo: Repository to import INTO — "target" (default) or "source".
    """
    return _disabled_tool_response("contentedge_import_all")


# ── All ContentEdge tools ─────────────────────────────────────────────────

_ALL_CE_TOOLS = [
    tool(contentedge_search),
    # tool(contentedge_smart_chat),  # disabled — kept for future use
    tool(contentedge_get_document_url),
    tool(contentedge_list_content_classes),
    tool(contentedge_list_indexes),
    tool(contentedge_search_archiving_policies),
    tool(contentedge_get_archiving_policy),
    tool(contentedge_delete_archiving_policy),
    tool(contentedge_list_content_class_versions),
    tool(contentedge_delete_search_results),
    tool(contentedge_export_content_classes),
    tool(contentedge_export_indexes),
    tool(contentedge_export_index_groups),
    tool(contentedge_import_content_classes),
    tool(contentedge_import_indexes),
    tool(contentedge_import_index_groups),
    tool(contentedge_repo_info),
]


# ── Skill class ──────────────────────────────────────────────

# Module-level cache so CE metadata is fetched only once per process
_ce_classes_cache: str | None = None
_ce_indexes_cache: str | None = None
# Structured index data for validation (populated during setup)
_ce_index_data_cache: dict | None = None


class ContentEdgeSkill(SkillBase):
    name = "ContentEdge"
    description = "Interact with the ContentEdge content repository for document management."
    version = "2.1.0"
    prompt_file = "contentedge.md"

    def __init__(self):
        self._content_classes_text: str = ""
        self._indexes_text: str = ""

    async def setup(self, context: SkillContext) -> None:
        """Pre-load content classes and indexes (cached after first call)."""
        global _ce_classes_cache, _ce_indexes_cache

        if _ce_classes_cache is not None:
            self._content_classes_text = _ce_classes_cache
            self._indexes_text = _ce_indexes_cache or ""
            logger.info("contentedge.metadata_from_cache")
            return

        try:
            classes = await _run_sync(_sync_list_content_classes, "source")
            if isinstance(classes, list) and classes:
                lines = []
                for cc in classes:
                    cc_id = cc.get('id', '')
                    cc_name = cc.get('name', '').strip()
                    desc = cc.get("description", "").strip()
                    # Filter out internal template notes (not useful for users)
                    if desc and "%" in desc:
                        desc = ""
                    # Show id prominently; add name only if different from id
                    if cc_name and cc_name != cc_id:
                        line = f"- `{cc_id}` — {cc_name}"
                    else:
                        line = f"- `{cc_id}`"
                    if desc:
                        line += f" ({desc})"
                    lines.append(line)
                self._content_classes_text = "\n".join(lines)
            else:
                self._content_classes_text = "Could not load content classes."
        except Exception as e:
            logger.warning("contentedge.preload_classes_error", error=str(e))
            self._content_classes_text = "Content classes unavailable."

        try:
            idx_data = await _run_sync(_sync_list_indexes, "source")
            if isinstance(idx_data, dict):
                # Cache structured data for index validation in archive_documents
                global _ce_index_data_cache
                _ce_index_data_cache = idx_data

                lines = []
                for g in idx_data.get("index_groups", []):
                    g_id = g.get('group_id', '')
                    g_name = g.get('group_name', '')
                    if g_name and g_name != g_id:
                        lines.append(f"- **Group `{g_id}`** — {g_name} (all required when archiving)")
                    else:
                        lines.append(f"- **Group `{g_id}`** (all required when archiving)")
                    for t in g.get("indexes", []):
                        t_id = t.get('id', '')
                        t_name = t.get('name', '')
                        dtype = t.get('dataType', '')
                        if t_name and t_name != t_id:
                            lines.append(f"  - `{t_id}` — {t_name} [{dtype}]")
                        else:
                            lines.append(f"  - `{t_id}` [{dtype}]")
                for ix in idx_data.get("individual_indexes", []):
                    ix_id = ix.get('id', '')
                    ix_name = ix.get('name', '')
                    desc = ix.get("description", "").strip()
                    dtype = ix.get('dataType', '')
                    if ix_name and ix_name != ix_id:
                        line = f"- `{ix_id}` — {ix_name} [{dtype}]"
                    else:
                        line = f"- `{ix_id}` [{dtype}]"
                    if desc:
                        line += f" ({desc})"
                    lines.append(line)
                self._indexes_text = "\n".join(lines) if lines else "No indexes found."
            else:
                self._indexes_text = "Could not load indexes."
        except Exception as e:
            logger.warning("contentedge.preload_indexes_error", error=str(e))
            self._indexes_text = "Indexes unavailable."

        # Persist in module-level cache
        _ce_classes_cache = self._content_classes_text
        _ce_indexes_cache = self._indexes_text

    def get_tools(self) -> list:
        return _ALL_CE_TOOLS

    def get_prompt_fragment(self) -> str:
        base = _load_prompt_file(self.prompt_file)
        base = base.replace("{content_classes}", self._content_classes_text or "Not loaded yet.")
        base = base.replace("{indexes}", self._indexes_text or "Not loaded yet.")
        # Inject repo info
        try:
            src = _get_ce_config()
            base = base.replace("{source_url}", src.base_url or "Not configured")
            base = base.replace("{source_name}", src.repo_name or "Not configured")
        except Exception:
            base = base.replace("{source_url}", "Not configured")
            base = base.replace("{source_name}", "Not configured")
        try:
            tgt = _get_target_config()
            base = base.replace("{target_url}", tgt.base_url or "Not configured")
            base = base.replace("{target_name}", tgt.repo_name or "Not configured")
        except Exception:
            base = base.replace("{target_url}", "Not configured")
            base = base.replace("{target_name}", "Not configured")
        return base

    def get_routing_hint(self) -> str:
        return (
            "If the question is about content classes, indexes, or documents in the repository → answer from the ContentEdge info below; "
            "if about a person/entity that might exist in DB AND ContentEdge → follow CRITICAL WORKFLOW (SQL + Smart Chat + document links)"
        )

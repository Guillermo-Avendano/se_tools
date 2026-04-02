"""ContentEdge LangGraph implementation with 5 domain-specific nodes.

Domains:
1. Archiving Policy: export, import, generate, list, delete
2. Indexes: export, import, create, delete
3. Index Groups: export, import, generate, list, delete
4. Content Classes: export, import, generate, list, delete
5. Documents: Archive using policy/metadata, delete, list versions, search by index
"""

import json
import structlog
from typing import TypedDict, List, Dict, Any, Literal, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.skills.contentedge_skill import (
    # Archiving Policy tools (read-only)
    contentedge_search_archiving_policies,
    contentedge_get_archiving_policy,
    # Response formatting helpers
    _format_content_classes,
    _format_indexes,
    _format_index_groups,
    _format_archiving_policies,
    contentedge_delete_archiving_policy,
    
    # Index tools
    contentedge_list_indexes,
    contentedge_export_indexes,
    contentedge_import_indexes,
    
    # Index Group tools
    contentedge_create_index_group,
    contentedge_export_index_groups,
    contentedge_import_index_groups,
    contentedge_verify_index_group,
    
    # Content Class tools
    contentedge_list_content_classes,
    contentedge_export_content_classes,
    contentedge_import_content_classes,
    contentedge_list_content_class_versions,
    contentedge_get_versions,
    
    # Document tools (read-only)
    contentedge_search,
    contentedge_smart_chat,
    contentedge_get_document_url,
    
    # Info
    contentedge_repo_info,
)

from app.agent.planning_system import (
    plan_contentedge_operation,
    format_planning_confirmation,
    PlanningState,
    metadata_validator
)

logger = structlog.get_logger(__name__)


class ContentEdgeState(TypedDict):
    """State for ContentEdge LangGraph workflow."""
    question: str
    intent: str
    domain: str
    parameters: Dict[str, Any]
    results: Dict[str, Any]
    formatted_results: str  # Formatted markdown output
    context: str
    tools_used: List[str]
    execution_path: List[str]
    # Planning state
    planning_state: Optional[PlanningState]
    confirmation_received: bool
    operation_confirmed: bool


def _safe_json_loads(value: Any) -> Any:
    """Decode JSON strings when possible; otherwise return the original value."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return value


def _resolve_operation(state: ContentEdgeState, question_lower: str) -> str:
    """Resolve the requested operation using planning first, then question heuristics."""
    planning_state = state.get("planning_state") or {}
    operation = str(planning_state.get("operation") or "").strip().lower()
    if operation:
        return operation
    if any(term in question_lower for term in ["create", "crear", "generate", "add", "make"]):
        return "create"
    if any(term in question_lower for term in ["delete", "borrar", "remove"]):
        return "delete"
    if any(term in question_lower for term in ["export"]):
        return "export"
    if any(term in question_lower for term in ["import"]):
        return "import"
    if any(term in question_lower for term in ["exist", "exists", "existe", "check", "verify"]):
        return "verify"
    return "list"


def _get_visual_index_group_candidate(state: ContentEdgeState) -> dict[str, Any]:
    """Return the best-effort index group candidate extracted from visual context."""
    visual_context = (state.get("parameters") or {}).get("visual_context") or {}
    candidate = visual_context.get("index_group_candidate") or {}
    if candidate.get("present"):
        return candidate
    return {}


def _format_index_group_action_results(results: dict[str, Any]) -> str:
    """Render verify/create results for index-group management flows."""
    sections: list[str] = []

    verify = _safe_json_loads(results.get("verify"))
    if isinstance(verify, dict):
        if verify.get("exists"):
            group = verify.get("group") or {}
            sections.append(
                "**Index Group Check:**\n\n"
                f"Index group `{group.get('group_id', verify.get('identifier', ''))}` already exists"
                f" in {str(verify.get('repo', '')).upper()}."
            )
        elif verify.get("success"):
            sections.append(
                "**Index Group Check:**\n\n"
                f"Index group `{verify.get('identifier', '')}` was not found"
                f" in {str(verify.get('repo', '')).upper()}."
            )
        elif verify.get("message"):
            sections.append(f"**Index Group Check:**\n\n{verify.get('message')}")

    create = _safe_json_loads(results.get("create"))
    if isinstance(create, dict):
        if create.get("created"):
            member_ids = create.get("member_ids") or []
            members_line = ", ".join(member_ids) if member_ids else "No member indexes reported"
            sections.append(
                "**Index Group Creation:**\n\n"
                f"Created index group `{create.get('group_id', '')}` in {str(create.get('repo', '')).upper()} "
                f"with members: {members_line}."
            )
        elif create.get("exists"):
            sections.append(f"**Index Group Creation:**\n\n{create.get('message', 'Index group already exists.')}")
        elif create.get("message"):
            sections.append(f"**Index Group Creation:**\n\n{create.get('message')}")
        if create.get("missing_references"):
            sections.append(
                "**Missing Indexes:**\n\n"
                + ", ".join(create.get("missing_references") or [])
            )
        manual_required = create.get("manual_required") or {}
        if manual_required.get("reason"):
            sections.append(f"**Manual Follow-up:**\n\n{manual_required.get('reason')}")

    visual_context = results.get("visual_context") or {}
    summary = visual_context.get("summary")
    if summary:
        sections.append(f"**Visual Evidence:**\n\n{summary}")

    return "\n\n".join(section for section in sections if section).strip() or "Operation completed."


def _format_execution_results(results: Dict[str, Any], category: str, response_mode: str = "detailed") -> str:
    """Format execution results into structured markdown based on operation category."""
    if not results:
        return "No results to display."
    
    formatted_parts = []
    
    try:
        # Parse string values from JSON if needed
        parsed_results = {}
        for key, value in results.items():
            if isinstance(value, str):
                try:
                    parsed_results[key] = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    parsed_results[key] = value
            else:
                parsed_results[key] = value
        
        if category == "archiving_policy":
            # Format archiving policies list
            for key, value in parsed_results.items():
                if key != "error" and isinstance(value, dict):
                    policies = value.get("policies") or value.get("items") or []
                    if policies:
                        formatted_parts.append(f"**Archiving Policies ({len(policies)} found):**\n\n")
                        formatted_parts.append(_format_archiving_policies(policies, mode=response_mode))
                elif key != "error" and isinstance(value, list):
                    formatted_parts.append(f"**Archiving Policies ({len(value)} found):**\n\n")
                    formatted_parts.append(_format_archiving_policies(value, mode=response_mode))
                elif key == "error":
                    formatted_parts.append(f"❌ Error: {value}")
        
        elif category == "indexes":
            # Format indexes list  
            for key, value in parsed_results.items():
                if key != "error" and isinstance(value, dict):
                    # Handle both "individual_indexes" and "indexes" keys
                    indexes = value.get("individual_indexes") or value.get("indexes") or []
                    if indexes:
                        formatted_parts.append(f"**Indexes ({len(indexes)} found):**\n\n")
                        formatted_parts.append(_format_indexes(indexes, mode=response_mode))
                elif key != "error" and isinstance(value, list):
                    formatted_parts.append(f"**Indexes ({len(value)} found):**\n\n")
                    formatted_parts.append(_format_indexes(value, mode=response_mode))
                elif key == "error":
                    formatted_parts.append(f"❌ Error: {value}")
        
        elif category == "index_groups":
            # Format index groups list
            for key, value in parsed_results.items():
                if key != "error" and isinstance(value, dict):
                    # Handle both "index_groups" and "groups" keys
                    groups = value.get("index_groups") or value.get("groups") or []
                    if groups:
                        formatted_parts.append(f"**Index Groups ({len(groups)} found):**\n\n")
                        formatted_parts.append(_format_index_groups(groups, mode=response_mode))
                elif key != "error" and isinstance(value, list):
                    formatted_parts.append(f"**Index Groups ({len(value)} found):**\n\n")
                    formatted_parts.append(_format_index_groups(value, mode=response_mode))
                elif key == "error":
                    formatted_parts.append(f"❌ Error: {value}")
        
        elif category == "content_classes":
            # Format content classes list
            for key, value in parsed_results.items():
                if key != "error" and isinstance(value, list):
                    formatted_parts.append(f"**Content Classes ({len(value)} found):**\n\n")
                    formatted_parts.append(_format_content_classes(value, mode=response_mode))
                elif key == "error":
                    formatted_parts.append(f"❌ Error: {value}")
    
    except Exception as e:
        logger.warning("format_results_error", error=str(e), category=category, results=str(results))
        return f"Results: {json.dumps(parsed_results if 'parsed_results' in locals() else results, ensure_ascii=False)}"
    
    return "\n\n".join(formatted_parts) if formatted_parts else "Operation completed."


def extract_parameters_from_question(question: str, domain: str) -> Dict[str, Any]:
    """Extract relevant parameters from the user's question based on domain."""
    question_lower = question.lower()
    params = {"question": question}

    # Output mode selection: simple vs detailed
    if any(k in question_lower for k in ["simple", "brief", "short", "summary", "id and name", "id/name", "only id", "solo id", "solo id y nombre"]):
        params["response_mode"] = "simple"
    elif any(k in question_lower for k in ["detailed", "detail", "full", "complete", "with details"]):
        params["response_mode"] = "detailed"
    else:
        params["response_mode"] = "detailed"
    
    # Common parameters
    if "source" in question_lower:
        params["repo"] = "source"
    elif "target" in question_lower or "destino" in question_lower:
        params["repo"] = "target"
    else:
        params["repo"] = "source"
    
    # Domain-specific parameter extraction
    if domain == "archiving_policy":
        if "export" in question_lower:
            if "policy" in question_lower:
                # Extract policy name from question
                words = question.split()
                for i, word in enumerate(words):
                    if word.lower() in ["policy", "política"]:
                        if i + 1 < len(words):
                            params["name"] = words[i + 1]
                            break
        elif "create" in question_lower or "generate" in question_lower:
            params["name"] = "generated_policy"
            params["policy_json"] = "{}"
        elif "delete" in question_lower or "borrar" in question_lower:
            # Extract policy name to delete
            words = question.split()
            for i, word in enumerate(words):
                if word.lower() in ["policy", "política"]:
                    if i + 1 < len(words):
                        params["name"] = words[i + 1]
                        break
    
    elif domain == "indexes":
        if "export" in question_lower:
            params["filter"] = "*"
        elif "import" in question_lower:
            params["file_path"] = "imported_indexes.json"
    
    elif domain == "index_groups":
        if "export" in question_lower:
            params["filter"] = "*"
        elif "import" in question_lower:
            params["file_path"] = "imported_index_groups.json"
    
    elif domain == "content_classes":
        if "export" in question_lower:
            params["filter"] = "*"
        elif "import" in question_lower:
            params["file_path"] = "imported_content_classes.json"
        elif "versions" in question_lower or "versiones" in question_lower:
            # Extract content class name
            words = question.split()
            for i, word in enumerate(words):
                if word.lower() in ["class", "clase"]:
                    if i + 1 < len(words):
                        params["content_class"] = words[i + 1]
                        break
    
    elif domain == "documents":
        if "archive" in question_lower or "archivar" in question_lower:
            if "policy" in question_lower:
                params["policy_name"] = "default_policy"
                params["file_path"] = "document.txt"
            else:
                params["content_class"] = "DOCUMENT"
                params["files"] = "[]"
                params["metadata"] = "{}"
        elif "search" in question_lower or "buscar" in question_lower:
            params["constraints"] = "[]"
            params["conjunction"] = "AND"
        elif "delete" in question_lower or "borrar" in question_lower:
            params["object_ids"] = "[]"
    
    return params


async def planning_node(state: ContentEdgeState) -> ContentEdgeState:
    """Planning node for ContentEdge operations with validation."""
    logger.info("planning_node.started", question=state["question"])
    
    try:
        # Create operation plan
        planning_state = await plan_contentedge_operation(state["question"])
        
        # Store planning state
        state["planning_state"] = planning_state
        state["confirmation_received"] = False
        state["operation_confirmed"] = False
        
        # Set domain and intent if planning succeeded
        if planning_state["category"]:
            state["domain"] = planning_state["category"]
            state["intent"] = planning_state["operation"]
        
        # Format confirmation message
        confirmation_message = format_planning_confirmation(planning_state)
        state["context"] = confirmation_message
        
        logger.info("planning_node.completed", 
                   category=planning_state.get("category"),
                   operation=planning_state.get("operation"),
                   confirmation_required=planning_state.get("confirmation_required"))
        
    except Exception as e:
        logger.error("planning_node.error", error=str(e))
        state["context"] = f"❌ **Planning Error:** {str(e)}"
        state["domain"] = "error"
        state["intent"] = "planning_failed"
    
    state["execution_path"].append("planning_node")
    return state


async def confirmation_node(state: ContentEdgeState) -> ContentEdgeState:
    """Process user confirmation for ContentEdge operations."""
    logger.info("confirmation_node.started", question=state["question"])
    
    question_lower = state["question"].lower()
    planning_state = state.get("planning_state")
    
    if not planning_state:
        state["context"] = "❌ **Error:** No planning state available. Please restart."
        state["domain"] = "error"
        state["execution_path"].append("confirmation_node")
        return state
    
    # Check for confirmation keywords
    if any(word in question_lower for word in ["confirm", "yes", "proceed", "continue"]):
        state["operation_confirmed"] = True
        state["confirmation_received"] = True
        state["context"] = "✅ **Operation confirmed. Executing now...**"
        logger.info("confirmation_node.confirmed", 
                   category=planning_state.get("category"),
                   operation=planning_state.get("operation"))
    
    elif any(word in question_lower for word in ["cancel", "no", "abort", "stop"]):
        state["operation_confirmed"] = False
        state["confirmation_received"] = True
        state["context"] = "❌ **Operation cancelled by user.**"
        logger.info("confirmation_node.cancelled")
    
    else:
        # Still waiting for confirmation
        state["context"] = planning_state.get("context", "⏳ **Waiting for confirmation...**")
    
    state["execution_path"].append("confirmation_node")
    return state


def contentedge_router(state: ContentEdgeState) -> str:
    """Route to appropriate node based on planning and confirmation state."""
    planning_state = state.get("planning_state")
    
    # If no planning state, go to planning first
    if not planning_state:
        return "planning_node"
    
    # If planning failed, end with error
    if planning_state.get("category") == "error":
        return END
    
    # If confirmation required but not received, wait for confirmation
    if planning_state.get("confirmation_required") and not state.get("confirmation_received"):
        return "confirmation_node"
    
    # If operation cancelled, end
    if state.get("confirmation_received") and not state.get("operation_confirmed"):
        return END
    
    # If confirmed or no confirmation needed, route to execution node
    category = planning_state.get("category")
    
    if category == "archiving_policy":
        return "archiving_policy_node"
    elif category == "indexes":
        return "indexes_node"
    elif category == "index_groups":
        return "index_groups_node"
    elif category == "content_classes":
        return "content_classes_node"
    elif category == "documents":
        return "documents_node"
    else:
        return "general_query_node"


async def archiving_policy_node(state: ContentEdgeState) -> ContentEdgeState:
    """Handle archiving policy operations."""
    logger.info("archiving_policy_node.started", question=state["question"])
    
    question = state["question"].lower()
    params = extract_parameters_from_question(state["question"], "archiving_policy")
    results = {}
    tools_used = []
    
    try:
        if "export" in question or "list" in question:
            result = await contentedge_search_archiving_policies(
                name="*", 
                withcontent=False, 
                limit=200, 
                repo=params["repo"]
            )
            results["list"] = result
            tools_used.append("contentedge_search_archiving_policies")
        
        elif "delete" in question:
            if "name" in params:
                result = await contentedge_delete_archiving_policy(
                    name=params["name"], 
                    repo=params["repo"]
                )
                results["delete"] = result
                tools_used.append("contentedge_delete_archiving_policy")
        
        elif "list" in question:
            result = await contentedge_search_archiving_policies(
                name="*", 
                withcontent=False, 
                limit=200, 
                repo=params["repo"]
            )
            results["list"] = result
            tools_used.append("contentedge_search_archiving_policies")
        
        else:
            # Default: list policies
            result = await contentedge_search_archiving_policies(
                name="*", 
                withcontent=False, 
                limit=200, 
                repo=params["repo"]
            )
            results["default"] = result
            tools_used.append("contentedge_search_archiving_policies")
    
    except Exception as e:
        logger.error("archiving_policy_node.error", error=str(e))
        results["error"] = str(e)
    
    # Format results into structured markdown
    formatted_results = _format_execution_results(results, "archiving_policy", params.get("response_mode", "detailed"))
    state["results"] = results
    state["formatted_results"] = formatted_results
    state["tools_used"] = tools_used
    state["execution_path"].append("archiving_policy_node")
    
    logger.info("archiving_policy_node.completed", 
                tools_used=tools_used, 
                results_count=len(results))
    
    return state


async def indexes_node(state: ContentEdgeState) -> ContentEdgeState:
    """Handle index operations."""
    logger.info("indexes_node.started", question=state["question"])
    
    question = state["question"].lower()
    params = extract_parameters_from_question(state["question"], "indexes")
    results = {}
    tools_used = []
    
    try:
        if "export" in question:
            result = await contentedge_export_indexes(
                filter=params["filter"], 
                repo=params["repo"]
            )
            results["export"] = result
            tools_used.append("contentedge_export_indexes")
        
        elif "import" in question:
            result = await contentedge_import_indexes(
                file_path=params["file_path"], 
                repo=params["repo"]
            )
            results["import"] = result
            tools_used.append("contentedge_import_indexes")
        
        elif "create" in question or "crear" in question:
            result = "Index creation requires specific index definition parameters"
            results["create"] = result
        
        elif "delete" in question or "borrar" in question:
            result = "Index deletion requires specific index identification"
            results["delete"] = result
        
        else:
            # Default: list indexes
            result = await contentedge_list_indexes(repo=params["repo"])
            results["list"] = result
            tools_used.append("contentedge_list_indexes")
    
    except Exception as e:
        logger.error("indexes_node.error", error=str(e))
        results["error"] = str(e)
    
    # Format results into structured markdown
    formatted_results = _format_execution_results(results, "indexes", params.get("response_mode", "detailed"))
    state["results"] = results
    state["formatted_results"] = formatted_results
    state["tools_used"] = tools_used
    state["execution_path"].append("indexes_node")
    
    logger.info("indexes_node.completed", 
                tools_used=tools_used, 
                results_count=len(results))
    
    return state


async def index_groups_node(state: ContentEdgeState) -> ContentEdgeState:
    """Handle index group operations."""
    logger.info("index_groups_node.started", question=state["question"])
    
    question = state["question"].lower()
    params = extract_parameters_from_question(state["question"], "index_groups")
    results = {}
    tools_used = []
    operation = _resolve_operation(state, question)
    visual_candidate = _get_visual_index_group_candidate(state)
    
    try:
        if operation == "export":
            result = await contentedge_export_index_groups(
                filter=params["filter"], 
                repo=params["repo"]
            )
            results["export"] = result
            tools_used.append("contentedge_export_index_groups")
        
        elif operation == "import":
            result = await contentedge_import_index_groups(
                file_path=params["file_path"], 
                repo=params["repo"]
            )
            results["import"] = result
            tools_used.append("contentedge_import_index_groups")
        
        elif operation in {"create", "verify"} or "if not exist" in question or "si no existe" in question:
            if visual_candidate:
                identifier = visual_candidate.get("group_id") or visual_candidate.get("group_name") or ""
                results["visual_context"] = {
                    "summary": (state.get("parameters") or {}).get("visual_context", {}).get("summary", "")
                }
            else:
                identifier = ""

            if not identifier:
                results["verify"] = {
                    "success": False,
                    "message": "I could not determine a concrete index group ID or name from the image or the question.",
                }
            else:
                verify_result = await contentedge_verify_index_group(identifier=identifier, repo=params["repo"])
                results["verify"] = verify_result
                tools_used.append("contentedge_verify_index_group")

                verify_data = _safe_json_loads(verify_result)
                should_create = operation == "create" or "if not exist" in question or "si no existe" in question
                if should_create and isinstance(verify_data, dict) and not verify_data.get("exists"):
                    if not visual_candidate:
                        results["create"] = {
                            "success": False,
                            "message": "Creation requires a visible index group definition with member indexes.",
                        }
                    else:
                        create_payload = {
                            "group_id": visual_candidate.get("group_id") or visual_candidate.get("group_name") or "",
                            "group_name": visual_candidate.get("group_name") or visual_candidate.get("group_id") or "",
                            "member_references": visual_candidate.get("member_references") or [],
                            "scope": "Page",
                        }
                        create_result = await contentedge_create_index_group(
                            group_definition=json.dumps(create_payload, ensure_ascii=False),
                            repo=params["repo"],
                        )
                        results["create"] = create_result
                        tools_used.append("contentedge_create_index_group")
        
        elif operation == "delete":
            result = "Index group deletion requires specific group identification"
            results["delete"] = result
        
        elif operation == "list" or "list" in question or "lista" in question:
            # Get indexes which include index groups
            result = await contentedge_list_indexes(repo=params["repo"])
            results["list"] = result
            tools_used.append("contentedge_list_indexes")
        
        else:
            # Default: list index groups
            result = await contentedge_list_indexes(repo=params["repo"])
            results["default"] = result
            tools_used.append("contentedge_list_indexes")
    
    except Exception as e:
        logger.error("index_groups_node.error", error=str(e))
        results["error"] = str(e)
    
    # Format results into structured markdown
    if "verify" in results or "create" in results:
        formatted_results = _format_index_group_action_results(results)
    else:
        formatted_results = _format_execution_results(results, "index_groups", params.get("response_mode", "detailed"))
    state["results"] = results
    state["formatted_results"] = formatted_results
    state["tools_used"] = tools_used
    state["execution_path"].append("index_groups_node")
    
    logger.info("index_groups_node.completed", 
                tools_used=tools_used, 
                results_count=len(results))
    
    return state


async def content_classes_node(state: ContentEdgeState) -> ContentEdgeState:
    """Handle content class operations."""
    logger.info("content_classes_node.started", question=state["question"])
    
    question = state["question"].lower()
    params = extract_parameters_from_question(state["question"], "content_classes")
    results = {}
    tools_used = []
    
    try:
        if "export" in question:
            result = await contentedge_export_content_classes(
                filter=params["filter"], 
                repo=params["repo"]
            )
            results["export"] = result
            tools_used.append("contentedge_export_content_classes")
        
        elif "import" in question:
            result = await contentedge_import_content_classes(
                file_path=params["file_path"], 
                repo=params["repo"]
            )
            results["import"] = result
            tools_used.append("contentedge_import_content_classes")
        
        elif "generate" in question or "generar" in question:
            result = "Content class generation requires specific class definition"
            results["generate"] = result
        
        elif "delete" in question or "borrar" in question:
            result = "Content class deletion requires specific class identification"
            results["delete"] = result
        
        elif "versions" in question or "versiones" in question:
            if "content_class" in params:
                result = await contentedge_list_content_class_versions(
                    content_class=params["content_class"],
                    repo=params["repo"]
                )
                results["versions"] = result
                tools_used.append("contentedge_list_content_class_versions")
            else:
                result = await contentedge_list_content_classes(repo=params["repo"])
                results["list"] = result
                tools_used.append("contentedge_list_content_classes")
        
        elif "list" in question or "lista" in question:
            result = await contentedge_list_content_classes(repo=params["repo"])
            results["list"] = result
            tools_used.append("contentedge_list_content_classes")
        
        else:
            # Default: list content classes
            result = await contentedge_list_content_classes(repo=params["repo"])
            results["default"] = result
            tools_used.append("contentedge_list_content_classes")
    
    except Exception as e:
        logger.error("content_classes_node.error", error=str(e))
        results["error"] = str(e)
    
    # Format results into structured markdown
    formatted_results = _format_execution_results(results, "content_classes", params.get("response_mode", "detailed"))
    state["results"] = results
    state["formatted_results"] = formatted_results
    state["tools_used"] = tools_used
    state["execution_path"].append("content_classes_node")
    
    logger.info("content_classes_node.completed", 
                tools_used=tools_used, 
                results_count=len(results))
    
    return state


async def documents_node(state: ContentEdgeState) -> ContentEdgeState:
    """Handle document operations."""
    logger.info("documents_node.started", question=state["question"])
    
    question = state["question"].lower()
    params = extract_parameters_from_question(state["question"], "documents")
    results = {}
    tools_used = []
    
    try:
        if "archive" in question or "archivar" in question:
            results["archive"] = "Archive operations are handled by MobiusRemoteCLI (se_ce_tools)."
        
        elif "delete" in question or "borrar" in question:
            results["delete"] = "Delete operations are handled by MobiusRemoteCLI (se_ce_tools)."
        
        elif "versions" in question or "versiones" in question:
            if "report_id" in params:
                result = await contentedge_get_versions(
                    report_id=params["report_id"],
                    version_from=params.get("version_from", ""),
                    version_to=params.get("version_to", ""),
                    repo=params["repo"]
                )
                results["versions"] = result
                tools_used.append("contentedge_get_versions")
        
        elif "search" in question or "buscar" in question:
            if "smart" in question or "inteligente" in question:
                result = await contentedge_smart_chat(
                    question=state["question"],
                    document_ids=params.get("document_ids", "[]"),
                    conversation_id="",
                    repo=params["repo"]
                )
                results["smart_search"] = result
                tools_used.append("contentedge_smart_chat")
            else:
                result = await contentedge_search(
                    constraints=params["constraints"],
                    conjunction=params["conjunction"],
                    repo=params["repo"]
                )
                results["index_search"] = result
                tools_used.append("contentedge_search")
        
        else:
            # Default: try smart search
            result = await contentedge_smart_chat(
                question=state["question"],
                document_ids="[]",
                conversation_id="",
                repo=params["repo"]
            )
            results["default_search"] = result
            tools_used.append("contentedge_smart_chat")
    
    except Exception as e:
        logger.error("documents_node.error", error=str(e))
        results["error"] = str(e)
    
    state["results"] = results
    state["tools_used"] = tools_used
    state["execution_path"].append("documents_node")
    
    logger.info("documents_node.completed", 
                tools_used=tools_used, 
                results_count=len(results))
    
    return state


async def general_query_node(state: ContentEdgeState) -> ContentEdgeState:
    """Handle general queries that don't fit specific domains."""
    logger.info("general_query_node.started", question=state["question"])
    
    results = {}
    tools_used = []
    
    try:
        # Try to get repository info
        result = await contentedge_repo_info()
        results["repo_info"] = result
        tools_used.append("contentedge_repo_info")
        
        # Also try smart chat as fallback
        smart_result = await contentedge_smart_chat(
            question=state["question"],
            document_ids="[]",
            conversation_id="",
            repo="source"
        )
        results["smart_chat"] = smart_result
        tools_used.append("contentedge_smart_chat")
    
    except Exception as e:
        logger.error("general_query_node.error", error=str(e))
        results["error"] = str(e)
    
    state["results"] = results
    state["tools_used"] = tools_used
    state["execution_path"].append("general_query_node")
    
    logger.info("general_query_node.completed", 
                tools_used=tools_used, 
                results_count=len(results))
    
    return state


def create_contentedge_graph() -> StateGraph:
    """Create and return ContentEdge LangGraph workflow with planning."""
    
    # Create the graph
    workflow = StateGraph(ContentEdgeState)
    
    # Add nodes
    workflow.add_node("planning_node", planning_node)
    workflow.add_node("confirmation_node", confirmation_node)
    workflow.add_node("archiving_policy_node", archiving_policy_node)
    workflow.add_node("indexes_node", indexes_node)
    workflow.add_node("index_groups_node", index_groups_node)
    workflow.add_node("content_classes_node", content_classes_node)
    workflow.add_node("documents_node", documents_node)
    workflow.add_node("general_query_node", general_query_node)
    
    # Add edges
    workflow.add_edge(START, "planning_node")
    workflow.add_conditional_edges(
        "planning_node", 
        contentedge_router,
        {
            "confirmation_node": "confirmation_node",
            "archiving_policy_node": "archiving_policy_node",
            "indexes_node": "indexes_node", 
            "index_groups_node": "index_groups_node",
            "content_classes_node": "content_classes_node",
            "documents_node": "documents_node",
            "general_query_node": "general_query_node",
            END: END
        }
    )
    
    # Confirmation node routing
    workflow.add_conditional_edges(
        "confirmation_node",
        contentedge_router,
        {
            "confirmation_node": "confirmation_node",
            "archiving_policy_node": "archiving_policy_node",
            "indexes_node": "indexes_node", 
            "index_groups_node": "index_groups_node",
            "content_classes_node": "content_classes_node",
            "documents_node": "documents_node",
            "general_query_node": "general_query_node",
            END: END
        }
    )
    
    # All execution nodes go to END
    workflow.add_edge("archiving_policy_node", END)
    workflow.add_edge("indexes_node", END)
    workflow.add_edge("index_groups_node", END)
    workflow.add_edge("content_classes_node", END)
    workflow.add_edge("documents_node", END)
    workflow.add_edge("general_query_node", END)
    
    return workflow


def compile_contentedge_app(checkpointer=None):
    """Compile the ContentEdge LangGraph application."""
    workflow = create_contentedge_graph()
    
    if checkpointer is None:
        checkpointer = MemorySaver()
    
    return workflow.compile(checkpointer=checkpointer)


# Initialize the compiled app
contentedge_app = compile_contentedge_app()

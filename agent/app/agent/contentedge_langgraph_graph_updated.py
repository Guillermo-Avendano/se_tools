async def documents_node(state: ContentEdgeState) -> ContentEdgeState:
    """Handle document operations with metadata validation for archiving."""
    logger.info("documents_node.started", question=state["question"])
    
    question = state["question"].lower()
    params = extract_parameters_from_question(state["question"], "documents")
    results = {}
    tools_used = []
    
    try:
        if "archive" in question:
            results["archive"] = "Archive operations are handled by MobiusRemoteCLI (se_ce_tools)."
        
        elif "delete" in question:
            results["delete"] = "Delete operations are handled by MobiusRemoteCLI (se_ce_tools)."
        
        elif "search" in question or "buscar" in question:
            result = await contentedge_search(
                constraints=params.get("constraints", "[]"),
                conjunction=params.get("conjunction", "AND"),
                repo=params["repo"]
            )
            results["search"] = result
            tools_used.append("contentedge_search")
        
        elif "list" in question and "version" in question:
            result = await contentedge_get_versions(
                object_id=params.get("object_id", ""),
                repo=params["repo"]
            )
            results["list_versions"] = result
            tools_used.append("contentedge_get_versions")
        
        elif "url" in question:
            result = await contentedge_get_document_url(
                object_id=params.get("object_id", ""),
                repo=params["repo"]
            )
            results["get_url"] = result
            tools_used.append("contentedge_get_document_url")
        
        else:
            # Default: search
            result = await contentedge_search(
                constraints=params.get("constraints", "[]"),
                conjunction=params.get("conjunction", "AND"),
                repo=params["repo"]
            )
            results["default"] = result
            tools_used.append("contentedge_search")
    
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

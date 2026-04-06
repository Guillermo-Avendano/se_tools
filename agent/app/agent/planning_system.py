"""Planning system for ContentEdge operations with prerequisites validation.

This system provides:
1. Category identification from user requests
2. Prerequisites validation for each operation
3. User confirmation flow
4. Intelligent cache management
5. Operation execution planning
"""

import json
import structlog
from typing import Dict, List, Optional, Any, TypedDict
from enum import Enum

logger = structlog.get_logger(__name__)


class OperationCategory(Enum):
    """ContentEdge operation categories."""
    ARCHIVING_POLICY = "archiving_policy"
    INDEXES = "indexes"
    INDEX_GROUPS = "index_groups"
    CONTENT_CLASSES = "content_classes"
    DOCUMENTS = "documents"


class PrerequisiteType(Enum):
    """Types of prerequisites for operations."""
    CACHE_VALID = "cache_valid"
    CACHE_REFRESH = "cache_refresh"
    REPO_ACCESS = "repo_access"
    AUTH_VALID = "auth_valid"
    CONFIG_COMPLETE = "config_complete"


class PlanningState(TypedDict):
    """State for planning system."""
    user_request: str
    category: Optional[str]
    operation: Optional[str]
    prerequisites: List[Dict[str, Any]]
    validation_results: Dict[str, bool]
    confirmation_required: bool
    execution_plan: Optional[Dict[str, Any]]
    cache_actions: List[str]


class PrerequisiteValidator:
    """Validates prerequisites for ContentEdge operations."""
    
    def __init__(self):
        self.cache_expiry = {
            OperationCategory.ARCHIVING_POLICY: 300,  # 5 minutes
            OperationCategory.INDEXES: 300,
            OperationCategory.INDEX_GROUPS: 300,
            OperationCategory.CONTENT_CLASSES: 300,
            OperationCategory.DOCUMENTS: 300,
        }
    
    async def validate_cache_prerequisites(
        self, 
        category: OperationCategory, 
        operation: str
    ) -> Dict[str, Any]:
        """Validate cache prerequisites for given category and operation."""
        results = {}
        
        # Check if we need cached data
        list_operations = ["list", "get", "show", "retrieve"]
        create_operations = ["create", "generate", "add", "new"]
        
        if any(op in operation.lower() for op in list_operations):
            # Need valid cache for listing operations
            results["cache_valid"] = await self._check_cache_validity(category)
            results["cache_refresh_needed"] = not results["cache_valid"]
        
        elif any(op in operation.lower() for op in create_operations):
            # Need to refresh cache after creation
            results["cache_refresh_needed"] = True
        
        return results
    
    async def _check_cache_validity(self, category: OperationCategory) -> bool:
        """Check if cached data is still valid."""
        # This would integrate with actual cache system
        # For now, return True (assuming cache is valid)
        return True
    
    async def validate_repo_access(self, repo_type: str = "source") -> Dict[str, Any]:
        """Validate repository access credentials."""
        results = {}
        
        # Check environment variables
        if repo_type == "source":
            required_vars = [
                "CE_SOURCE_REPO_URL", "CE_SOURCE_REPO_USER", "CE_SOURCE_REPO_PASS"
            ]
        else:
            required_vars = [
                "CE_TARGET_REPO_URL", "CE_TARGET_REPO_USER", "CE_TARGET_REPO_PASS"
            ]
        
        import os
        missing_vars = []
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        results["auth_valid"] = len(missing_vars) == 0
        results["missing_vars"] = missing_vars
        
        return results


class MetadataValidator:
    """Validates metadata for ContentEdge archive operations."""
    
    def __init__(self):
        self.logger = structlog.get_logger(f"{__name__}.MetadataValidator")
    
    async def validate_archive_using_policy_prerequisites(
        self, 
        content_class_name: str,
        archiving_policy_name: str,
        file_path: Optional[str] = None,
        path_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """Archive-using-policy validations are disabled in agent-api."""
        _ = (content_class_name, archiving_policy_name, file_path, path_filter)
        return {
            "all_valid": False,
            "disabled": True,
            "validation_summary": (
                "Archive using policy validations are disabled in agent-api. "
                "Use MobiusRemoteCLI (se_ce_tools) for this operation."
            ),
        }
    
    async def _validate_archiving_policy_with_content_class(
        self, 
        policy_name: str, 
        content_class_name: str
    ) -> Dict[str, Any]:
        """Check if archiving policy exists and contains the specified content class."""
        try:
            from app.skills.contentedge_skill import contentedge_get_archiving_policy
            
            result = await contentedge_get_archiving_policy(name=policy_name)
            
            if isinstance(result, str):
                try:
                    import json
                    policy_data = json.loads(result)
                    
                    # Check if policy contains content class reference
                    contains_content_class = self._policy_contains_content_class(
                        policy_data, content_class_name
                    )
                    
                    return {
                        "contains_content_class": contains_content_class,
                        "policy_name": policy_name,
                        "target_content_class": content_class_name,
                        "policy_content": policy_data,
                        "policy_exists": True
                    }
                except json.JSONDecodeError:
                    pass
            
            return {
                "contains_content_class": False,
                "policy_name": policy_name,
                "target_content_class": content_class_name,
                "policy_exists": False,
                "error": "Could not retrieve or parse archiving policy"
            }
            
        except Exception as e:
            self.logger.error("policy_validation.error", error=str(e))
            return {
                "contains_content_class": False,
                "policy_name": policy_name,
                "target_content_class": content_class_name,
                "policy_exists": False,
                "error": str(e)
            }
    
    def _policy_contains_content_class(
        self, 
        policy_data: Dict[str, Any], 
        content_class_name: str
    ) -> bool:
        """Check if policy data contains reference to the content class."""
        content_class_lower = content_class_name.lower()
        
        # Check various fields where content class might be referenced
        policy_str = json.dumps(policy_data).lower()
        
        # Direct content class reference
        if content_class_lower in policy_str:
            return True
        
        # Check in common policy fields
        if "content_classes" in policy_data:
            content_classes = policy_data.get("content_classes", [])
            if isinstance(content_classes, list):
                for cc in content_classes:
                    if isinstance(cc, dict):
                        cc_name = cc.get("name", "").lower()
                        if cc_name == content_class_lower:
                            return True
                    elif isinstance(cc, str) and cc.lower() == content_class_lower:
                        return True
        
        # Check in document info
        if "document_info" in policy_data:
            doc_info = policy_data.get("document_info", {})
            if isinstance(doc_info, dict):
                doc_class = doc_info.get("content_class", "").lower()
                if doc_class == content_class_lower:
                    return True
        
        return False
    
    async def _validate_path_filter(self, path_filter: str) -> Dict[str, Any]:
        """Validate path filter and find matching files."""
        try:
            import os
            import glob
            from pathlib import Path
            
            # Extract directory and pattern
            path_obj = Path(path_filter)
            if path_obj.is_dir():
                directory = str(path_obj)
                pattern = "*"  # All files
            else:
                directory = str(path_obj.parent)
                pattern = path_obj.name
            
            # Validate directory exists
            if not os.path.exists(directory):
                return {
                    "valid": False,
                    "path_filter": path_filter,
                    "directory": directory,
                    "pattern": pattern,
                    "error": "Directory does not exist"
                }
            
            # Find matching files
            full_pattern = os.path.join(directory, pattern)
            matching_files = glob.glob(full_pattern)
            
            # Limit to 50 files for display
            files_to_process = matching_files[:50]
            
            return {
                "valid": len(matching_files) > 0,
                "path_filter": path_filter,
                "directory": directory,
                "pattern": pattern,
                "total_matches": len(matching_files),
                "files_to_process": files_to_process,
                "truncated": len(matching_files) > 50
            }
            
        except Exception as e:
            return {
                "valid": False,
                "path_filter": path_filter,
                "error": str(e)
            }
    
    async def generate_archiving_policy(
        self, 
        content_class_name: str
    ) -> Dict[str, Any]:
        """Disabled — policy generation is handled by MobiusRemoteCLI (se_ce_tools)."""
        return {
            "success": False,
            "error": "Policy generation is handled by MobiusRemoteCLI (se_ce_tools)."
        }
    
    def _create_policy_validation_summary(self, validation_results: Dict[str, Any]) -> str:
        """Create validation summary for archive with policy operations."""
        summary_lines = []
        
        # Content class validation
        cc_validation = validation_results.get("content_class", {})
        if cc_validation.get("exists", False):
            summary_lines.append(f"✅ Content class '{cc_validation.get('content_class_name')}' exists")
        else:
            error = cc_validation.get("error", "Not found")
            summary_lines.append(f"❌ Content class '{cc_validation.get('content_class_name')}' not found: {error}")
        
        # Archiving policy validation
        policy_validation = validation_results.get("archiving_policy", {})
        if policy_validation.get("policy_exists", False):
            if policy_validation.get("contains_content_class", False):
                summary_lines.append(f"✅ Policy '{policy_validation.get('policy_name')}' contains content class reference")
            else:
                summary_lines.append(f"⚠️ Policy '{policy_validation.get('policy_name')}' exists but doesn't reference content class")
                summary_lines.append(f"   💡 Auto-generation available: AP_{policy_validation.get('target_content_class')}_AGN_<timestamp>")
        else:
            summary_lines.append(f"❌ Policy '{policy_validation.get('policy_name')}' not found")
            summary_lines.append(f"   💡 Auto-generation available: AP_{policy_validation.get('target_content_class')}_AGN_<timestamp>")
        
        # File validation
        if "file_validation" in validation_results:
            file_val = validation_results["file_validation"]
            if file_val.get("exists", False):
                summary_lines.append(f"✅ File '{file_val.get('file_path')}' exists")
            else:
                error = file_val.get("error", "Not found")
                summary_lines.append(f"❌ File '{file_val.get('file_path')}' not found: {error}")
        
        # Path filter validation
        if "path_filter_validation" in validation_results:
            path_val = validation_results["path_filter_validation"]
            if path_val.get("valid", False):
                summary_lines.append(f"✅ Path filter '{path_val.get('path_filter')}' matches {path_val.get('total_matches')} files")
                if path_val.get("truncated", False):
                    summary_lines.append(f"   📋 Showing first 50 of {path_val.get('total_matches')} files")
                summary_lines.append(f"   📁 Files to process: {len(path_val.get('files_to_process', []))}")
            else:
                error = path_val.get("error", "No matches")
                summary_lines.append(f"❌ Path filter '{path_val.get('path_filter')}' failed: {error}")
        
        # Overall status
        if validation_results.get("all_valid", False):
            summary_lines.append("\n🔴 **VALIDATION FAILED** - Operation cannot proceed")
        elif validation_results.get("needs_policy_generation", False):
            summary_lines.append("\n⚠️ **POLICY GENERATION NEEDED** - Confirm to proceed")
        else:
            summary_lines.append("\n🟢 **VALIDATION PASSED** - Ready to archive")
        
        return "\n".join(summary_lines)

    async def _validate_content_class_exists(self, content_class_name: str) -> Dict[str, Any]:
        """Check if content class exists in repository."""
        try:
            from app.skills.contentedge_skill import contentedge_list_content_classes
            
            result = await contentedge_list_content_classes(limit=1000)
            
            # Parse result to check if content class exists
            if isinstance(result, str):
                try:
                    import json
                    classes_data = json.loads(result)
                    if isinstance(classes_data, dict) and "policies" in classes_data:
                        existing_classes = [
                            policy.get("name", "").lower() 
                            for policy in classes_data["policies"]
                        ]
                        exists = content_class_name.lower() in existing_classes
                        return {
                            "exists": exists,
                            "content_class_name": content_class_name,
                            "available_classes": existing_classes[:10]  # Show first 10
                        }
                except json.JSONDecodeError:
                    pass
            
            return {
                "exists": False,
                "content_class_name": content_class_name,
                "error": "Could not validate content class existence"
            }
            
        except Exception as e:
            self.logger.error("content_class_validation.error", error=str(e))
            return {
                "exists": False,
                "content_class_name": content_class_name,
                "error": str(e)
            }

    def _create_simple_validation_summary(self, validation_results: Dict[str, Any]) -> str:
        """Create simple validation summary for archive operations."""
        summary_lines = []
        
        # File validation (for archive with path operations)
        if "file_validation" in validation_results:
            file_val = validation_results["file_validation"]
            if file_val.get("exists", False):
                summary_lines.append(f"✅ File '{file_val.get('file_path')}' exists")
            else:
                error = file_val.get("error", "Not found")
                summary_lines.append(f"❌ File '{file_val.get('file_path')}' not found: {error}")
        
        # Content class validation
        if "content_class" in validation_results:
            cc_validation = validation_results["content_class"]
            if cc_validation.get("exists", False):
                summary_lines.append(f"✅ Content class '{cc_validation.get('content_class_name')}' exists")
            else:
                error = cc_validation.get("error", "Not found")
                summary_lines.append(f"❌ Content class '{cc_validation.get('content_class_name')}' not found: {error}")
        
        # Overall status
        if validation_results.get("all_valid", False):
            summary_lines.append("\n🔴 **VALIDATION FAILED** - Operation cannot proceed")
        else:
            summary_lines.append("\n🟢 **VALIDATION PASSED** - Ready to archive")
        
        return "\n".join(summary_lines)


class OperationPlanner:
    """Plans ContentEdge operations with validation and confirmation."""
    
    def __init__(self):
        self.validator = PrerequisiteValidator()
        self.category_keywords = {
            OperationCategory.ARCHIVING_POLICY: [
                "policy", "policies", "archiving", "archiving policy"
            ],
            OperationCategory.INDEXES: [
                "index", "indexes", "indices"
            ],
            OperationCategory.INDEX_GROUPS: [
                "index group", "index groups", "group of indexes"
            ],
            OperationCategory.CONTENT_CLASSES: [
                "content class", "content classes", "class", "classes"
            ],
            OperationCategory.DOCUMENTS: [
                "document", "documents", "archive", "search", "delete"
            ]
        }
    
    async def identify_category(self, user_request: str) -> Optional[OperationCategory]:
        """Identify operation category from user request."""
        request_lower = user_request.lower()

        # Priority heuristic: if user references both group and index concepts,
        # route to index groups even when generic index keywords are also present.
        if ("group" in request_lower or "grupo" in request_lower) and (
            "index" in request_lower or "indice" in request_lower or "índice" in request_lower
        ):
            return OperationCategory.INDEX_GROUPS
        
        # Score each category based on keyword matches
        category_scores = {}
        for category, keywords in self.category_keywords.items():
            score = sum(1 for keyword in keywords if keyword in request_lower)
            if score > 0:
                category_scores[category] = score
        
        # Return category with highest score
        if category_scores:
            return max(category_scores, key=category_scores.get)
        
        return None
    
    async def plan_operation(
        self, 
        user_request: str
    ) -> PlanningState:
        """Create complete operation plan with validation."""
        logger.info("planning.started", request=user_request[:100])
        
        # Identify category
        category = await self.identify_category(user_request)
        
        # Determine operation type
        operation = self._extract_operation_type(user_request)
        
        # Validate prerequisites
        validation_results = {}
        prerequisites = []
        
        if category:
            # Cache validation
            cache_validation = await self.validator.validate_cache_prerequisites(
                category, operation
            )
            validation_results.update(cache_validation)
            prerequisites.extend([
                {
                    "type": PrerequisiteType.CACHE_VALID,
                    "description": "Valid cache data available",
                    "status": cache_validation.get("cache_valid", False)
                }
            ])
            
            if cache_validation.get("cache_refresh_needed"):
                prerequisites.append({
                    "type": PrerequisiteType.CACHE_REFRESH,
                    "description": "Cache will be refreshed after operation",
                    "status": "pending"
                })
            
            # Repository access validation
            repo_validation = await self.validator.validate_repo_access()
            validation_results.update(repo_validation)
            prerequisites.append({
                "type": PrerequisiteType.REPO_ACCESS,
                "description": "Repository access credentials configured",
                "status": repo_validation.get("auth_valid", False)
            })
        
        # Determine if confirmation is needed
        confirmation_required = self._requires_confirmation(operation)
        
        # Create execution plan
        execution_plan = None
        if validation_results.get("auth_valid", False):
            logger.warning("planning.auth_failed", missing=validation_results.get("missing_vars", []))
        else:
            execution_plan = await self._create_execution_plan(category, operation, user_request)
        
        # Determine cache actions
        cache_actions = self._determine_cache_actions(category, operation, validation_results)
        
        planning_state: PlanningState = {
            "user_request": user_request,
            "category": category.value if category else None,
            "operation": operation,
            "prerequisites": prerequisites,
            "validation_results": validation_results,
            "confirmation_required": confirmation_required,
            "execution_plan": execution_plan,
            "cache_actions": cache_actions
        }
        
        logger.info("planning.completed", 
                   category=planning_state["category"],
                   operation=operation,
                   confirmation_required=confirmation_required)
        
        return planning_state
    
    def _detect_archive_with_policy(self, user_request: str) -> bool:
        """Detect if user wants to archive using archiving policy."""
        request_lower = user_request.lower()
        
        # Keywords that indicate archiving with policy
        policy_keywords = [
            "archiving policy", "policy", "política de archivado", "política",
            "using policy", "con política", "con policy"
        ]
        
        # Keywords that indicate archiving
        archive_keywords = [
            "archive", "archivar", "almacenar", "store", "save", "guardar"
        ]
        
        # Check for content class specification
        content_class_keywords = [
            "content class", "content clase", "clase de contenido", "category"
        ]
        
        # Check if request contains all three types of keywords
        has_policy_keyword = any(keyword in request_lower for keyword in policy_keywords)
        has_archive_keyword = any(keyword in request_lower for keyword in archive_keywords)
        has_content_class_keyword = any(keyword in request_lower for keyword in content_class_keywords)
        
        return has_policy_keyword and has_archive_keyword and has_content_class_keyword
    
    def _extract_archiving_policy_from_request(self, user_request: str) -> Optional[str]:
        """Extract archiving policy name from user request."""
        import re
        
        # Pattern to match policy names
        patterns = [
            r"policy[:\s]+([a-zA-Z0-9_]+)",
            r"política[:\s]+([a-zA-Z0-9_]+)",
            r"archiving\s+policy[:\s]+([a-zA-Z0-9_]+)",
            r"política\s+de\s+archivado[:\s]+([a-zA-Z0-9_]+)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, user_request.lower())
            if match:
                return match.group(1)
        
        return None
    
    def _extract_path_filter_from_request(self, user_request: str) -> Optional[str]:
        """Extract path filter from user request."""
        import re
        
        # Pattern to match paths with wildcards
        patterns = [
            r"([/\\][^\s]+\*[^\\s]*)",  # Paths with * wildcard
            r"([/\\][^\s]+\?[^\\s]*)",  # Paths with ? wildcard
            r"([/\\][^\s]+\[[^\]]+\][^\\s]*)"  # Paths with [] patterns
        ]
        
        for pattern in patterns:
            match = re.search(pattern, user_request)
            if match:
                return match.group(1)
        
        return None
    
    def _detect_archive_with_file_path(self, user_request: str) -> bool:
        """Detect if user wants to archive a specific file with path."""
        request_lower = user_request.lower()
        
        # Keywords that indicate archiving with file path
        archive_keywords = [
            "almacenar este documento", "store this document", "archive this document",
            "guardar este archivo", "save this file", "almacenar archivo"
        ]
        
        # Check for path indicators
        path_indicators = [
            "workspace/", "./", "/", "\\", ":", "~", "home/", "users/"
        ]
        
        # Check if request contains archive keywords AND path indicators
        has_archive_keyword = any(keyword in request_lower for keyword in archive_keywords)
        has_path_indicator = any(indicator in user_request for indicator in path_indicators)
        
        return has_archive_keyword and has_path_indicator
    
    def _extract_file_path_from_request(self, user_request: str) -> Optional[str]:
        """Extract file path from user request."""
        import re
        import os
        
        # Pattern to match file paths after keywords
        patterns = [
            r"almacenar\s+(?:este\s+)?documento[:\s]+(.+)",
            r"store\s+(?:this\s+)?document[:\s]+(.+)",
            r"archive\s+(?:this\s+)?document[:\s]+(.+)",
            r"guardar\s+(?:este\s+)?archivo[:\s]+(.+)",
            r"save\s+(?:this\s+)?file[:\s]+(.+)",
            r"almacenar\s+archivo[:\s]+(.+)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, user_request, re.IGNORECASE)
            if match:
                file_path = match.group(1).strip()
                # Clean up quotes if present
                file_path = file_path.strip('"\'')
                return file_path
        
        return None
    
    def _validate_file_exists(self, file_path: Optional[str]) -> Dict[str, Any]:
        """Check if file exists in the workspace."""
        if not file_path:
            return {
                "exists": False,
                "file_path": "",
                "error": "No file path provided"
            }
        
        try:
            import os
            # Try to resolve the path relative to workspace
            workspace_root = os.getenv("WORKSPACE_ROOT", "/app/workspace")
            full_path = os.path.join(workspace_root, file_path)
            
            exists = os.path.exists(full_path)
            return {
                "exists": exists,
                "file_path": file_path,
                "full_path": full_path,
                "is_file": os.path.isfile(full_path) if exists else False,
                "is_directory": os.path.isdir(full_path) if exists else False
            }
            
        except Exception as e:
            return {
                "exists": False,
                "file_path": file_path,
                "error": str(e)
            }
    
    def _extract_content_class_from_request(self, user_request: str) -> Optional[str]:
        """Extract content class name from user request."""
        # Look for content class patterns
        patterns = [
            r"content[_\s-]*class[:\s]+([a-zA-Z0-9_]+)",
            r"content[_\s-]*clase[:\s]+([a-zA-Z0-9_]+)",
            r"clase[:\s]+([a-zA-Z0-9_]+)",
            r"category[:\s]+([a-zA-Z0-9_]+)"
        ]
        
        import re
        for pattern in patterns:
            match = re.search(pattern, user_request.lower())
            if match:
                return match.group(1)
        
        return None
    
    def _extract_operation_type(self, user_request: str) -> str:
        """Extract operation type from user request."""
        request_lower = user_request.lower()

        def _has_keyword(keyword: str) -> bool:
            # Single-word keywords should match whole words only, so "get"
            # does not match "target".
            if " " in keyword or "-" in keyword:
                return keyword in request_lower
            import re
            return re.search(rf"\b{re.escape(keyword)}\b", request_lower) is not None
        
        operation_patterns = {
            "create": ["create", "generate", "add", "new", "make"],
            "delete": ["delete", "remove", "del", "destroy"],
            "export": ["export", "save", "download"],
            "import": ["import", "load", "upload"],
            "search": ["search", "find", "query", "lookup"],
            "archive": ["archive", "store", "save"],
            "list": ["list", "show", "get", "retrieve", "display"],
        }

        # Existence checks combined with an explicit create intent should still
        # resolve to create, not list/verify.
        if _has_keyword("create") and (
            "if not exist" in request_lower
            or "if it doesn't exist" in request_lower
            or "if it does not exist" in request_lower
            or "si no existe" in request_lower
        ):
            return "create"
        
        for operation, keywords in operation_patterns.items():
            if any(_has_keyword(keyword) for keyword in keywords):
                return operation
        
        return "unknown"
    
    def _requires_confirmation(self, operation: str) -> bool:
        """Determine if operation requires user confirmation."""
        # High-risk operations require confirmation
        high_risk_operations = ["delete", "remove", "destroy", "del"]
        
        return any(risk in operation.lower() for risk in high_risk_operations)
    
    async def _create_execution_plan(
        self, 
        category: Optional[OperationCategory], 
        operation: str, 
        user_request: str
    ) -> Dict[str, Any]:
        """Create detailed execution plan."""
        if not category:
            return {"error": "Could not determine operation category"}
        
        plan = {
            "category": category.value,
            "operation": operation,
            "user_request": user_request,
            "steps": [],
            "estimated_duration": self._estimate_duration(category, operation),
            "tools_needed": self._get_required_tools(category, operation)
        }
        
        # Add specific steps based on category and operation
        if category == OperationCategory.CONTENT_CLASSES and operation == "list":
            plan["steps"] = [
                "Check content classes cache validity",
                "Retrieve content classes from repository",
                "Update local cache with retrieved data",
                "Return formatted list to user"
            ]
        elif category == OperationCategory.INDEXES and operation == "list":
            plan["steps"] = [
                "Check indexes cache validity", 
                "Retrieve indexes from repository",
                "Update local cache with retrieved data",
                "Return formatted list to user"
            ]
        elif category == OperationCategory.ARCHIVING_POLICY and operation == "list":
            plan["steps"] = [
                "Check archiving policies cache validity",
                "Retrieve policies from repository", 
                "Update local cache with retrieved data",
                "Return formatted list to user"
            ]
        elif category == OperationCategory.INDEX_GROUPS and operation == "list":
            plan["steps"] = [
                "Check index groups cache validity",
                "Retrieve index groups from repository",
                "Update local cache with retrieved data", 
                "Return formatted list to user"
            ]
        else:
            plan["steps"] = [
                "Validate prerequisites",
                "Execute operation using appropriate ContentEdge tools",
                "Update cache if needed",
                "Return results to user"
            ]
        
        return plan
    
    def _estimate_duration(self, category: OperationCategory, operation: str) -> str:
        """Estimate operation duration."""
        # Simple estimation based on operation complexity
        base_durations = {
            "list": "5-10 seconds",
            "create": "10-30 seconds", 
            "delete": "5-15 seconds",
            "search": "10-60 seconds",
            "export": "30-120 seconds",
            "import": "30-120 seconds"
        }
        
        return base_durations.get(operation, "10-30 seconds")
    
    def _get_required_tools(self, category: OperationCategory, operation: str) -> List[str]:
        """Get list of required tools for operation."""
        tool_mapping = {
            OperationCategory.CONTENT_CLASSES: {
                "list": ["contentedge_list_content_classes"],
                "create": ["contentedge_generate_content_class"],
                "delete": ["contentedge_delete_content_class"]
            },
            OperationCategory.INDEXES: {
                "list": ["contentedge_list_indexes"],
                "create": ["contentedge_create_index"],
                "delete": ["contentedge_delete_index"]
            },
            OperationCategory.ARCHIVING_POLICY: {
                "list": ["contentedge_search_archiving_policies"],
                "delete": ["contentedge_delete_archiving_policy"]
            },
            OperationCategory.INDEX_GROUPS: {
                "list": ["contentedge_list_index_groups"],
                "create": ["contentedge_generate_index_group"],
                "delete": ["contentedge_delete_index_group"]
            },
            OperationCategory.DOCUMENTS: {
                "search": ["contentedge_search"]
            }
        }
        
        return tool_mapping.get(category, {}).get(operation, [])
    
    def _determine_cache_actions(
        self, 
        category: Optional[OperationCategory], 
        operation: str, 
        validation_results: Dict[str, Any]
    ) -> List[str]:
        """Determine cache actions needed."""
        actions = []
        
        if not category:
            return actions
        
        # Refresh cache after create operations
        if operation in ["create", "generate", "add"]:
            actions.append(f"Refresh {category.value} cache after creation")
        
        # Refresh cache after delete operations  
        if operation in ["delete", "remove"]:
            actions.append(f"Refresh {category.value} cache after deletion")
        
        # Load cache if invalid and listing
        if operation in ["list", "get", "show"] and not validation_results.get("cache_valid", True):
            actions.append(f"Load {category.value} from repository")
        
        return actions


# Global planner and validator instances
planner = OperationPlanner()
metadata_validator = MetadataValidator()


async def plan_contentedge_operation(user_request: str) -> PlanningState:
    """Plan a ContentEdge operation with full validation."""
    return await planner.plan_operation(user_request)


def format_planning_confirmation(state: PlanningState) -> str:
    """Format planning state for user confirmation."""
    if not state["category"]:
        return "❌ **Unable to determine operation category.** Please specify what you want to do (e.g., 'list content classes', 'create index')."
    
    if not state["validation_results"].get("auth_valid", False):
        missing_vars = state["validation_results"].get("missing_vars", [])
        return f"❌ **Configuration Error:** Missing environment variables: {', '.join(missing_vars)}"
    
    lines = []
    lines.append(f"🎯 **Operation Plan:** {state['operation'].title()} {state['category'].replace('_', ' ').title()}")
    lines.append("")
    
    # Prerequisites status
    lines.append("📋 **Prerequisites Check:**")
    for prereq in state["prerequisites"]:
        status_icon = "✅" if prereq["status"] else "❌"
        lines.append(f"  {status_icon} {prereq['description']}")
    
    lines.append("")
    
    # Execution plan
    if state["execution_plan"]:
        plan = state["execution_plan"]
        lines.append("📝 **Execution Plan:**")
        lines.append(f"  • Estimated duration: {plan['estimated_duration']}")
        lines.append(f"  • Tools needed: {', '.join(plan['tools_needed'])}")
        lines.append("")
        lines.append("  **Steps:**")
        for i, step in enumerate(plan['steps'], 1):
            lines.append(f"  {i}. {step}")
    
    lines.append("")
    
    # Confirmation prompt
    if state["confirmation_required"]:
        lines.append("⚠️ **This operation requires confirmation.**")
        lines.append("Type 'confirm' to proceed or 'cancel' to abort.")
    else:
        lines.append("✅ **Ready to execute.** Type 'proceed' to continue.")
    
    return "\n".join(lines)

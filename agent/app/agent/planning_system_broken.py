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
    
    def _extract_operation_type(self, user_request: str) -> str:
        """Extract operation type from user request."""
        request_lower = user_request.lower()
        
        operation_patterns = {
            "list": ["list", "show", "get", "retrieve", "display"],
            "create": ["create", "generate", "add", "new", "make"],
            "delete": ["delete", "remove", "del", "destroy"],
            "export": ["export", "save", "download"],
            "import": ["import", "load", "upload"],
            "search": ["search", "find", "query", "lookup"],
            "archive": ["archive", "store", "save"]
        }
        
        for operation, keywords in operation_patterns.items():
            if any(keyword in request_lower for keyword in keywords):
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


class MetadataValidator:
    """Validates metadata for ContentEdge archive operations."""
    
    def __init__(self):
        self.logger = structlog.get_logger(f"{__name__}.MetadataValidator")
    
    async def validate_archive_using_metadata_prerequisites(
        self, 
        content_class_name: str,
        archiving_policy_name: str = "",
        index_name: Optional[str] = None,
        index_group_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Validate prerequisites for archive using metadata operation."""
        validation_results = {}
        
        # Simple validation - just check content class exists
        content_class_validation = await self._validate_content_class_exists(content_class_name)
        validation_results["content_class"] = content_class_validation
        
        # Overall validation status
        validation_results["all_valid"] = content_class_validation.get("exists", False)
        
        validation_results["validation_summary"] = self._create_simple_validation_summary(validation_results)
        
        self.logger.info("archive_validation.completed", 
                       content_class=content_class_name,
                       all_valid=validation_results["all_valid"])
        
        return validation_results


    def _create_simple_validation_summary(self, validation_results: Dict[str, Any]) -> str:
        """Create simple validation summary for archive operations."""
        summary_lines = []
        
        # Content class validation
        cc_validation = validation_results.get("content_class", {})
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
    
            from app.skills.contentedge_skill import contentedge_list_indexes
            
            result = await contentedge_list_indexes()
            
            if isinstance(result, str):
                try:
                    import json
                    indexes_data = json.loads(result)
                    if isinstance(indexes_data, dict) and "indexes" in indexes_data:
                        existing_indexes = [
                            idx.get("name", "").lower() 
                            for idx in indexes_data["indexes"]
                        ]
                        exists = index_name.lower() in existing_indexes
                        
                        return {
                            "exists": exists,
                            "index_name": index_name,
                            "available_indexes": existing_indexes[:10]
                        }
                except json.JSONDecodeError:
                    pass
            
            return {
                "exists": False,
                "index_name": index_name,
                "error": "Could not validate index existence"
            }
            
        except Exception as e:
            return {
                "exists": False,
                "index_name": index_name,
                "error": str(e)
            }
    
    async def _validate_index_group(self, index_group_name: str) -> Dict[str, Any]:
        """Validate index group exists and is suitable."""
        try:
            from app.skills.contentedge_skill import contentedge_list_index_groups
            
            result = await contentedge_list_index_groups()
            
            # For index groups, we'd need to implement the listing function
            # For now, assume validation passes
            return {
                "exists": True,  # Placeholder
                "index_group_name": index_group_name,
                "note": "Index group validation not fully implemented"
            }
            
        except Exception as e:
            return {
                "exists": False,
                "index_group_name": index_group_name,
                "error": str(e)
            }
    
    def _create_validation_summary(self, validation_results: Dict[str, Any]) -> str:
    """Create human-readable validation summary."""
        summary_lines = []
        
        # Content class validation
        cc_validation = validation_results.get("content_class", {})
        if cc_validation.get("exists", False):
            summary_lines.append(f"✅ Content class '{cc_validation.get('content_class_name')}' exists")
        else:
            error = cc_validation.get("error", "Not found")
            summary_lines.append(f"❌ Content class '{cc_validation.get('content_class_name')}' not found: {error}")
        
        # Policy validation
        policy_validation = validation_results.get("archiving_policy", {})
        if policy_validation.get("contains_content_class", False):
            summary_lines.append(f"✅ Policy '{policy_validation.get('policy_name')}' contains content class reference")
        else:
            error = policy_validation.get("error", "No content class reference")
            summary_lines.append(f"❌ Policy '{policy_validation.get('policy_name')}' error: {error}")
        
        # Index validation with detailed information
        index_validation = validation_results.get("index", {})
        if index_validation.get("valid", False):
            summary_lines.append("❌ Index configuration issues:")
            for warning in index_validation.get("warnings", []):
                summary_lines.append(f"   ⚠️  {warning}")
            
            # Add index details if available
            if "details" in index_validation:
                details = index_validation["details"]
                if "index_definition" in details:
                    summary_lines.append(f"   📋 Index definition: {details['index_definition']}")
                if "format_validation" in details:
                    format_val = details["format_validation"]
                    if not format_val.get("valid", False):
                        summary_lines.append(f"   ❌ Format validation failed:")
                        for fmt_warning in format_val.get("warnings", []):
                            summary_lines.append(f"      • {fmt_warning}")
        
        elif validation_results.get("index_values", {}):
            # Index values validation (for metadata operations)
            values_validation = validation_results["index_values"]
            if values_validation.get("valid", False):
                summary_lines.append("❌ Index values validation issues:")
                for warning in values_validation.get("warnings", []):
                    summary_lines.append(f"   ⚠️  {warning}")
            else:
                summary_lines.append("✅ Index values format and size validation passed")
        
        else:
            summary_lines.append("✅ Index configuration valid")
        
        # Overall status
        if validation_results.get("all_valid", False):
            summary_lines.append("\n🔴 **VALIDATION FAILED** - Operation cannot proceed")
        else:
            summary_lines.append("\n🟢 **VALIDATION PASSED** - Ready to archive")
        
        return "\n".join(summary_lines)


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

import re

# Funciones que deben tener @tool
tools_to_decorate = [
    "contentedge_search",
    "contentedge_get_document_url",
    "contentedge_list_content_classes",
    "contentedge_list_indexes",
    "contentedge_search_archiving_policies",
    "contentedge_get_archiving_policy",
    "contentedge_delete_archiving_policy",
    "contentedge_list_content_class_versions",
    "contentedge_delete_search_results",
    "contentedge_export_content_classes",
    "contentedge_export_indexes",
    "contentedge_export_index_groups",
    "contentedge_import_content_classes",
    "contentedge_import_indexes",
    "contentedge_import_index_groups",
    "contentedge_repo_info",
]

with open('agent/app/skills/contentedge_skill.py', 'r', encoding='utf-8') as f:
    content = f.read()

for tool_name in tools_to_decorate:
    # Find the function definition
    pattern = rf'^(async def {tool_name}\()'
    # Check if it already has @tool
    before_pattern = rf'@tool\s+async def {tool_name}\('
    
    if re.search(before_pattern, content, re.MULTILINE):
        print(f"  ✓ {tool_name} already has @tool")
        continue
    
    # Add @tool decorator
    replacement = rf'@tool\n\1'
    new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    
    if count > 0:
        content = new_content
        print(f"  + {tool_name}: added @tool")
    else:
        print(f"  ✗ {tool_name}: not found")

with open('agent/app/skills/contentedge_skill.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\n✓ Done")

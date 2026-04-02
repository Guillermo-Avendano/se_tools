#!/usr/bin/env python3
"""Test script for archive with archiving policy validation."""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.agent.planning_system import plan_contentedge_operation, format_planning_confirmation

async def test_archive_with_policy():
    """Test archive with archiving policy detection and validation."""
    print("🧪 Testing Archive with Archiving Policy Validation")
    print("=" * 70)
    
    test_requests = [
        "archive con content class Invoice y archiving policy InvoicePolicy el archivo workspace/data/invoice.pdf",
        "archivar con content class Report usando archiving policy ReportPolicy path /workspace/AC001/AC*.txt",
        "almacenar con content class Contract y policy ContractPolicy el archivo workspace/files/contract.docx",
        "store con content class Document y archiving policy DocumentPolicy el archivo /tmp/document.txt",
        "archive con content class MissingClass y archiving policy MissingPolicy path /workspace/TEST/*.pdf",
        "archive con content class Invoice y archiving policy NonExistentPolicy el archivo invoice.txt"
    ]
    
    for request in test_requests:
        print(f"\n📝 Request: '{request}'")
        print("-" * 60)
        
        try:
            # Plan the operation
            planning_state = await plan_contentedge_operation(request)
            
            # Display results
            print(f"Category: {planning_state.get('category', 'Unknown')}")
            print(f"Operation: {planning_state.get('operation', 'Unknown')}")
            print(f"Confirmation Required: {planning_state.get('confirmation_required', False)}")
            
            # Show validation details
            validation_results = planning_state.get("validation_results", {})
            
            if "content_class" in validation_results:
                cc_val = validation_results["content_class"]
                print(f"Content Class: {cc_val.get('content_class_name', 'N/A')}")
                print(f"Content Class exists: {cc_val.get('exists', False)}")
            
            if "archiving_policy" in validation_results:
                policy_val = validation_results["archiving_policy"]
                print(f"Archiving Policy: {policy_val.get('policy_name', 'N/A')}")
                print(f"Policy exists: {policy_val.get('policy_exists', False)}")
                print(f"Contains content class: {policy_val.get('contains_content_class', False)}")
            
            if "file_validation" in validation_results:
                file_val = validation_results["file_validation"]
                print(f"File: {file_val.get('file_path', 'N/A')}")
                print(f"File exists: {file_val.get('exists', False)}")
            
            if "path_filter_validation" in validation_results:
                path_val = validation_results["path_filter_validation"]
                print(f"Path filter: {path_val.get('path_filter', 'N/A')}")
                print(f"Total matches: {path_val.get('total_matches', 0)}")
                print(f"Files to process: {len(path_val.get('files_to_process', []))}")
                if path_val.get('files_to_process'):
                    print(f"Sample files: {path_val['files_to_process'][:3]}")
            
            if validation_results.get("needs_policy_generation", False):
                print(f"🔧 Policy generation needed")
            
            # Show confirmation message
            confirmation_msg = format_planning_confirmation(planning_state)
            print("\nConfirmation Message:")
            print(confirmation_msg)
            
        except Exception as e:
            print(f"❌ Error: {str(e)}")
        
        print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_archive_with_policy())

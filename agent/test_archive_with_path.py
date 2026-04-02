#!/usr/bin/env python3
"""Test script for archive with file path validation."""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.agent.planning_system import plan_contentedge_operation, format_planning_confirmation

async def test_archive_with_path():
    """Test archive with file path detection and validation."""
    print("🧪 Testing Archive with File Path Validation")
    print("=" * 60)
    
    test_requests = [
        "almacenar este documento workspace/data/invoice.pdf con content class Invoice",
        "store this document ./reports/monthly.xlsx con content class Report",
        "archive this document workspace/files/contract.docx con content class Contract",
        "guardar este archivo /tmp/temp.txt con content class TempFile",
        "almacenar archivo workspace/nonexistent.txt con content class Missing",
        "almacenar este documento sin path con content class Invoice"
    ]
    
    for request in test_requests:
        print(f"\n📝 Request: '{request}'")
        print("-" * 50)
        
        try:
            # Plan the operation
            planning_state = await plan_contentedge_operation(request)
            
            # Display results
            print(f"Category: {planning_state.get('category', 'Unknown')}")
            print(f"Operation: {planning_state.get('operation', 'Unknown')}")
            print(f"Confirmation Required: {planning_state.get('confirmation_required', False)}")
            
            # Show validation details
            validation_results = planning_state.get("validation_results", {})
            if "file_validation" in validation_results:
                file_val = validation_results["file_validation"]
                print(f"File: {file_val.get('file_path', 'N/A')}")
                print(f"File exists: {file_val.get('exists', False)}")
                print(f"Full path: {file_val.get('full_path', 'N/A')}")
            
            # Show confirmation message
            confirmation_msg = format_planning_confirmation(planning_state)
            print("\nConfirmation Message:")
            print(confirmation_msg)
            
        except Exception as e:
            print(f"❌ Error: {str(e)}")
        
        print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(test_archive_with_path())

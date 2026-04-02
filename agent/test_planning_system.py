#!/usr/bin/env python3
"""Test script for ContentEdge planning system."""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.agent.planning_system import plan_contentedge_operation, format_planning_confirmation

async def test_planning_system():
    """Test the planning system with various requests."""
    print("🧪 Testing ContentEdge Planning System")
    print("=" * 60)
    
    test_requests = [
        "list content classes",
        "create new index", 
        "delete archiving policy",
        "search documents",
        "export index groups",
        "generate archiving policy",
        "invalid request"
    ]
    
    for request in test_requests:
        print(f"\n📝 Request: '{request}'")
        print("-" * 40)
        
        try:
            # Plan the operation
            planning_state = await plan_contentedge_operation(request)
            
            # Display results
            print(f"Category: {planning_state.get('category', 'Unknown')}")
            print(f"Operation: {planning_state.get('operation', 'Unknown')}")
            print(f"Confirmation Required: {planning_state.get('confirmation_required', False)}")
            
            # Show confirmation message
            confirmation_msg = format_planning_confirmation(planning_state)
            print("\nConfirmation Message:")
            print(confirmation_msg)
            
        except Exception as e:
            print(f"❌ Error: {str(e)}")
        
        print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(test_planning_system())

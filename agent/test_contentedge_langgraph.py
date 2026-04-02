#!/usr/bin/env python3
"""Test script for ContentEdge LangGraph implementation."""

import asyncio
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.agent.contentedge_langgraph_graph import (
    contentedge_app, 
    ContentEdgeState,
    contentedge_router
)


async def test_domain_routing():
    """Test domain routing function."""
    print("🧪 Testing Domain Routing")
    print("=" * 50)
    
    test_questions = [
        ("list policies", "archiving_policy"),
        ("export indexes", "indexes"),
        ("import index groups", "index_groups"),
        ("list content classes", "content_classes"),
        ("archive document", "documents"),
        ("general question", "general"),
    ]
    
    for question, expected_domain in test_questions:
        state = ContentEdgeState(
            question=question,
            intent="",
            domain="",
            parameters={},
            results={},
            context="",
            tools_used=[],
            execution_path=[]
        )
        
        # Call router and get the node name
        node_name = contentedge_router(state)
        actual_domain = state["domain"]
        
        status = "✅" if actual_domain == expected_domain else "❌"
        print(f"{status} '{question}' -> {actual_domain} (expected: {expected_domain})")
        print(f"    Router returned: {node_name}")


async def test_contentedge_graph():
    """Test the complete ContentEdge LangGraph."""
    print("\n🚀 Testing ContentEdge LangGraph")
    print("=" * 50)
    
    test_questions = [
        "list archiving policies",
        "export indexes", 
        "list content classes",
        "search documents",
    ]
    
    for question in test_questions:
        print(f"\n📝 Question: {question}")
        print("-" * 30)
        
        try:
            # Initialize state
            initial_state = ContentEdgeState(
                question=question,
                intent="",
                domain="",
                parameters={},
                results={},
                context="",
                tools_used=[],
                execution_path=[]
            )
            
            # Configure thread ID
            thread_config = {"configurable": {"thread_id": "test_session"}}
            
            # Invoke the graph
            result = await contentedge_app.ainvoke(
                initial_state,
                config=thread_config
            )
            
            # Display results
            print(f"🎯 Domain: {result.get('domain')}")
            print(f"🛠️  Tools Used: {result.get('tools_used', [])}")
            print(f"📊 Execution Path: {result.get('execution_path', [])}")
            
            results = result.get('results', {})
            if results:
                print("📋 Results:")
                for operation, result_data in results.items():
                    print(f"  • {operation}: {str(result_data)[:100]}...")
            else:
                print("⚠️  No results returned")
                
        except Exception as e:
            print(f"❌ Error: {str(e)}")


async def test_integration_with_core():
    """Test integration with the core agent system."""
    print("\n🔗 Testing Core Integration")
    print("=" * 50)
    
    try:
        from app.agent.core import ask_agent, _is_contentedge_question
        
        # Test routing function
        contentedge_questions = [
            "list archiving policies",
            "export indexes from source",
            "archive document with policy",
        ]
        
        general_questions = [
            "what is the weather today?",
            "tell me a joke",
            "explain quantum physics",
        ]
        
        print("🎯 ContentEdge Routing:")
        for q in contentedge_questions:
            is_ce = _is_contentedge_question(q)
            status = "✅" if is_ce else "❌"
            print(f"  {status} '{q}' -> ContentEdge: {is_ce}")
        
        print("\n🌐 General Routing:")
        for q in general_questions:
            is_ce = _is_contentedge_question(q)
            status = "✅" if not is_ce else "❌"
            print(f"  {status} '{q}' -> General: {not is_ce}")
            
    except Exception as e:
        print(f"❌ Integration test failed: {str(e)}")


async def main():
    """Run all tests."""
    print("🧪 ContentEdge LangGraph Test Suite")
    print("=" * 60)
    
    await test_domain_routing()
    await test_contentedge_graph()
    await test_integration_with_core()
    
    print("\n✅ Test Suite Completed")


if __name__ == "__main__":
    asyncio.run(main())

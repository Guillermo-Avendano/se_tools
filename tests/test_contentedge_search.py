"""Test: contentedge_search — search documents by index values."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_search


async def main():
    print("=== Test 1: Search by CUST_ID ===")
    constraints = json.dumps([
        {"index_name": "CUST_ID", "operator": "EQ", "value": "1000"}
    ])
    result = await contentedge_search.ainvoke({
        "constraints": constraints, "conjunction": "AND", "repo": "source"
    })
    print(result)
    print()

    print("=== Test 2: Search with wildcard ===")
    constraints = json.dumps([
        {"index_name": "CUST_ID", "operator": "LIKE", "value": "*100*"}
    ])
    result = await contentedge_search.ainvoke({
        "constraints": constraints, "conjunction": "AND", "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

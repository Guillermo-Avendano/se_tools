"""Test: contentedge_delete_search_results — search and delete matching documents."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_delete_search_results


async def main():
    print("=== Delete search results ===")
    print("WARNING: This will delete documents!")
    constraints = json.dumps([
        {"index_name": "CUST_ID", "operator": "EQ", "value": "TEST_DELETE"}
    ])
    result = await contentedge_delete_search_results.ainvoke({
        "constraints": constraints,
        "conjunction": "AND",
        "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

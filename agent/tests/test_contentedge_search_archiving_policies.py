"""Test: contentedge_search_archiving_policies — search/list archiving policies."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_search_archiving_policies


async def main():
    print("=== Test 1: List all archiving policies ===")
    result = await contentedge_search_archiving_policies.ainvoke({
        "name_filter": "*", "repo": "source"
    })
    print(result)
    print()

    print("=== Test 2: Search with prefix ===")
    result = await contentedge_search_archiving_policies.ainvoke({
        "name_filter": "AC*", "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

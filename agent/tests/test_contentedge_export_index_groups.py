"""Test: contentedge_export_index_groups — export index groups to JSON."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_export_index_groups


async def main():
    print("=== Test 1: Export all index groups from SOURCE ===")
    result = await contentedge_export_index_groups.ainvoke({
        "filter": "*", "repo": "source"
    })
    print(result)
    print()

    print("=== Test 2: Export from TARGET ===")
    result = await contentedge_export_index_groups.ainvoke({
        "filter": "*", "repo": "target"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

"""Test: contentedge_export_indexes — export indexes to JSON."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_export_indexes


async def main():
    print("=== Test 1: Export all indexes from SOURCE ===")
    result = await contentedge_export_indexes.ainvoke({
        "filter": "*", "repo": "source"
    })
    print(result)
    print()

    print("=== Test 2: Export with prefix filter CUST* ===")
    result = await contentedge_export_indexes.ainvoke({
        "filter": "CUST*", "repo": "source"
    })
    print(result)
    print()

    print("=== Test 3: Export from TARGET ===")
    result = await contentedge_export_indexes.ainvoke({
        "filter": "*", "repo": "target"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

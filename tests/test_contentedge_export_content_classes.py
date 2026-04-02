"""Test: contentedge_export_content_classes — export content classes to JSON."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_export_content_classes


async def main():
    print("=== Test 1: Export all content classes from SOURCE ===")
    result = await contentedge_export_content_classes.ainvoke({
        "filter": "*", "repo": "source"
    })
    print(result)
    print()

    print("=== Test 2: Export with prefix filter AC* ===")
    result = await contentedge_export_content_classes.ainvoke({
        "filter": "AC*", "repo": "source"
    })
    print(result)
    print()

    print("=== Test 3: Export single content class AC001 ===")
    result = await contentedge_export_content_classes.ainvoke({
        "filter": "AC001", "repo": "source"
    })
    print(result)
    print()

    print("=== Test 4: Export from TARGET ===")
    result = await contentedge_export_content_classes.ainvoke({
        "filter": "*", "repo": "target"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

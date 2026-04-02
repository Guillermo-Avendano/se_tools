"""Test: contentedge_list_content_class_versions — list versions under a content class."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_list_content_class_versions


async def main():
    print("=== Test 1: List all versions for AC001 ===")
    result = await contentedge_list_content_class_versions.ainvoke({
        "content_class": "AC001",
        "version_from": "",
        "version_to": "",
        "repo": "source"
    })
    print(result[:2000] if len(result) > 2000 else result)
    print()

    print("=== Test 2: List versions with date filter ===")
    result = await contentedge_list_content_class_versions.ainvoke({
        "content_class": "AC001",
        "version_from": "2020-01-01",
        "version_to": "2026-12-31",
        "repo": "source"
    })
    print(result[:2000] if len(result) > 2000 else result)


if __name__ == "__main__":
    asyncio.run(main())

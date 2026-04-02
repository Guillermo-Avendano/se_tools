"""Test: contentedge_get_versions — get content class versions info."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_list_content_class_versions


async def main():
    print("=== Get versions for AC001 ===")
    result = await contentedge_list_content_class_versions.ainvoke({
        "content_class": "AC001",
        "version_from": "",
        "version_to": "",
        "repo": "source"
    })
    print(result[:2000] if len(result) > 2000 else result)


if __name__ == "__main__":
    asyncio.run(main())

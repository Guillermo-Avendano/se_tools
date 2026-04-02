"""Test: contentedge_delete_content_class_versions — delete versions under a content class."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_delete_content_class_versions


async def main():
    print("=== Delete versions for TST_CC01 (all dates) ===")
    print("WARNING: This will delete versions!")
    result = await contentedge_delete_content_class_versions.ainvoke({
        "content_class": "TST_CC01",
        "version_from": "",
        "version_to": "",
        "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

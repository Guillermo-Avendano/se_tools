"""Test: contentedge_create_archiving_policy — create a new archiving policy."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_create_archiving_policy


async def main():
    print("=== Create a test archiving policy ===")
    result = await contentedge_create_archiving_policy.ainvoke({
        "name": "TEST_POLICY_AUTO",
        "content_class_id": "AC001",
        "rules_json": json.dumps([]),
        "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

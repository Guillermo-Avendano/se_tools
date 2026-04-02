"""Test: contentedge_modify_archiving_policy — update an existing policy."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_modify_archiving_policy


async def main():
    print("=== Modify archiving policy ===")
    # First retrieve the current policy, modify it, then PUT it back
    # This is a placeholder — adjust policy_json to a valid full definition
    result = await contentedge_modify_archiving_policy.ainvoke({
        "name": "TEST_POLICY_AUTO",
        "policy_json": json.dumps({"description": "Updated by test"}),
        "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

"""Test: contentedge_get_archiving_policy — retrieve policy details by name."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_get_archiving_policy


async def main():
    policy_name = "AC001_POLICY"
    print(f"=== Get archiving policy: {policy_name} ===")
    result = await contentedge_get_archiving_policy.ainvoke({
        "name": policy_name, "repo": "source"
    })
    print(result[:2000] if len(result) > 2000 else result)


if __name__ == "__main__":
    asyncio.run(main())

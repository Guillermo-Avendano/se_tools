"""Test: contentedge_register_archiving_policy — register a previously generated policy."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_register_archiving_policy


async def main():
    print("=== Register archiving policy ===")
    print("NOTE: A policy must have been generated first (cached in Redis)")
    result = await contentedge_register_archiving_policy.ainvoke({
        "policy_name": "TEST_GEN_POLICY",
        "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

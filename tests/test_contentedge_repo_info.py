"""Test: contentedge_repo_info — show SOURCE and TARGET repository info."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_repo_info


async def main():
    print("=== Repository Info ===")
    result = await contentedge_repo_info.ainvoke({})
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

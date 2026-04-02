"""Test: contentedge_archive_using_policy — archive a file using an existing policy."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_archive_using_policy


async def main():
    print("=== Archive using policy ===")
    result = await contentedge_archive_using_policy.ainvoke({
        "file_path": "workspace/tmp/CO17-2007-10-08.TXT",
        "policy_name": "AC001_POLICY",
        "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

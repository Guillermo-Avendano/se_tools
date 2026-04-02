"""Test: contentedge_export_all — export all admin objects to timestamped dir."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_export_all


async def main():
    print("=== Export all from SOURCE ===")
    result = await contentedge_export_all.ainvoke({"repo": "source"})
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

"""Test: contentedge_list_indexes — list and compare indexes."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_list_indexes


async def main():
    print("=== Test 1: List indexes from SOURCE ===")
    result = await contentedge_list_indexes.ainvoke({"repo": "source"})
    src = json.loads(result) if isinstance(result, str) else result
    print(json.dumps(src, indent=2)[:2000])
    print()

    print("=== Test 2: List indexes from TARGET ===")
    result = await contentedge_list_indexes.ainvoke({"repo": "target"})
    tgt = json.loads(result) if isinstance(result, str) else result
    print(json.dumps(tgt, indent=2)[:2000])


if __name__ == "__main__":
    asyncio.run(main())

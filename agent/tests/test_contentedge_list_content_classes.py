"""Test: contentedge_list_content_classes — list and compare content classes."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_list_content_classes


async def main():
    print("=== Test 1: List content classes from SOURCE ===")
    result = await contentedge_list_content_classes.ainvoke({"repo": "source"})
    src = json.loads(result) if isinstance(result, str) else result
    print(f"  Count: {len(src)}")
    print(f"  IDs: {[c['id'] for c in src]}")
    print()

    print("=== Test 2: List content classes from TARGET ===")
    result = await contentedge_list_content_classes.ainvoke({"repo": "target"})
    tgt = json.loads(result) if isinstance(result, str) else result
    print(f"  Count: {len(tgt)}")
    print(f"  IDs: {[c['id'] for c in tgt]}")
    print()

    src_ids = {c["id"] for c in src}
    tgt_ids = {c["id"] for c in tgt}
    print("=== Comparison ===")
    print(f"  In SOURCE only: {sorted(src_ids - tgt_ids) or '(none)'}")
    print(f"  In TARGET only: {sorted(tgt_ids - src_ids) or '(none)'}")
    print(f"  Common: {len(src_ids & tgt_ids)}")


if __name__ == "__main__":
    asyncio.run(main())

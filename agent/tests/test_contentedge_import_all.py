"""Test: contentedge_import_all — export from SOURCE then import to TARGET."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_export_all, contentedge_import_all


async def main():
    print("=== Step 1: Export all from SOURCE ===")
    export_result = await contentedge_export_all.ainvoke({"repo": "source"})
    data = json.loads(export_result) if isinstance(export_result, str) else export_result
    print(f"  Export: {data}")
    print()

    export_dir = data.get("export_dir", "")
    if not export_dir:
        print("ERROR: no export_dir in result")
        return

    print(f"=== Step 2: Import to TARGET from {export_dir} ===")
    result = await contentedge_import_all.ainvoke({
        "export_dir": export_dir, "repo": "target"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

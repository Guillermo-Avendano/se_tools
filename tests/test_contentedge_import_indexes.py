"""Test: contentedge_import_indexes — selective import of indexes."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import (
    contentedge_export_indexes,
    contentedge_import_indexes,
)


async def main():
    print("=== Step 1: Export indexes from SOURCE ===")
    export_result = await contentedge_export_indexes.ainvoke({
        "filter": "*", "repo": "source"
    })
    data = json.loads(export_result) if isinstance(export_result, str) else export_result
    print(f"  Exported: {data.get('count', 0)} indexes")
    file_path = data.get("file", "")
    if not file_path:
        print("ERROR: no file in export result")
        return
    print(f"  File: {file_path}")
    print()

    print("=== Step 2: Import indexes to TARGET ===")
    result = await contentedge_import_indexes.ainvoke({
        "file_path": file_path, "repo": "target"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

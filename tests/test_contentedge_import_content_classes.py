"""Test: contentedge_import_content_classes — selective import of content classes."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import (
    contentedge_export_content_classes,
    contentedge_import_content_classes,
)


async def main():
    print("=== Step 1: Export content classes from SOURCE ===")
    export_result = await contentedge_export_content_classes.ainvoke({
        "filter": "*", "repo": "source"
    })
    data = json.loads(export_result) if isinstance(export_result, str) else export_result
    print(f"  Exported: {data.get('count', 0)} content classes")
    file_path = data.get("file", "")
    if not file_path:
        print("ERROR: no file in export result")
        return
    print(f"  File: {file_path}")
    print()

    print("=== Step 2: Import content classes to TARGET ===")
    result = await contentedge_import_content_classes.ainvoke({
        "file_path": file_path, "repo": "target"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

"""Test: contentedge_archive_documents — archive files with metadata."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_archive_documents


async def main():
    print("=== Archive a document with metadata ===")
    result = await contentedge_archive_documents.ainvoke({
        "file_path": "workspace/tmp/CO17-2007-10-08.TXT",
        "content_class": "AC001",
        "metadata": json.dumps({"SECTION": "TEST01"}),
        "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

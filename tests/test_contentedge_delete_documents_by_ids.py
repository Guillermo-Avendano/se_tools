"""Test: contentedge_delete_documents_by_ids — delete multiple documents."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_delete_documents_by_ids


async def main():
    # Replace with valid objectIds from your repository
    object_ids = ["REPLACE_ID_1", "REPLACE_ID_2"]
    print(f"=== Delete documents: {object_ids} ===")
    result = await contentedge_delete_documents_by_ids.ainvoke({
        "object_ids": json.dumps(object_ids), "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

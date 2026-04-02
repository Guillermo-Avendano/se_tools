"""Test: contentedge_get_document_url — get viewer URL for a document."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_get_document_url


async def main():
    # Replace with a valid objectId from your repository
    object_id = "REPLACE_WITH_VALID_OBJECT_ID"
    print(f"=== Get document URL for objectId: {object_id} ===")
    result = await contentedge_get_document_url.ainvoke({
        "object_id": object_id, "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

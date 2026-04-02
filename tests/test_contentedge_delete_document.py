"""Test: contentedge_delete_document — delete a single document by objectId."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
from app.skills.contentedge_skill import contentedge_delete_document


async def main():
    # Replace with a valid objectId from your repository
    object_id = "REPLACE_WITH_VALID_OBJECT_ID"
    print(f"=== Delete document: {object_id} ===")
    result = await contentedge_delete_document.ainvoke({
        "object_id": object_id, "repo": "source"
    })
    print(result)


if __name__ == "__main__":
    asyncio.run(main())

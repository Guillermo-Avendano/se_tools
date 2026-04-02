"""Test: contentedge_generate_archiving_policy — generate policy from spec (preview only)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import asyncio
import json
from app.skills.contentedge_skill import contentedge_generate_archiving_policy


async def main():
    print("=== Generate archiving policy (preview) ===")
    spec = {
        "policy_name": "TEST_GEN_POLICY",
        "file_path": "workspace/tmp/CO17-2007-10-08.TXT",
        "fields": [
            {
                "name": "SECTION_FIELD",
                "usage": 2,
                "type": "string",
                "left": 9,
                "right": 12,
                "top": 1,
            }
        ],
        "fieldGroups": [],
        "documentInfo": {
            "dataType": "Text",
            "charSet": "ASCII",
            "pageBreak": "FORMFEED",
            "lineBreak": "CRLF",
        },
        "report_label": {"left": 1, "right": 4, "top": 1, "content_class": "AC001"},
    }
    result = await contentedge_generate_archiving_policy.ainvoke({
        "policy_name": "TEST_GEN_POLICY",
        "file_path": "workspace/tmp/CO17-2007-10-08.TXT",
        "policy_spec_json": json.dumps(spec),
    })
    print(result[:3000] if len(result) > 3000 else result)


if __name__ == "__main__":
    asyncio.run(main())

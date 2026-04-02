import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()

from app.agent import contentedge_langgraph_graph as graph_module


def _state(question: str, visual_context: dict | None = None) -> dict:
    return {
        "question": question,
        "intent": "create",
        "domain": "index_groups",
        "parameters": {"visual_context": visual_context} if visual_context else {},
        "results": {},
        "formatted_results": "",
        "context": "",
        "tools_used": [],
        "execution_path": [],
        "planning_state": {"operation": "create", "category": "index_groups"},
        "confirmation_received": True,
        "operation_confirmed": True,
    }


@pytest.mark.asyncio
async def test_index_groups_node_creates_from_visual_context(monkeypatch):
    async def fake_verify(identifier: str, repo: str = "source") -> str:
        assert identifier == "Document"
        assert repo == "source"
        return json.dumps({"success": True, "exists": False, "identifier": identifier, "repo": repo})

    async def fake_create(group_definition: str, repo: str = "source") -> str:
        payload = json.loads(group_definition)
        assert payload["group_id"] == "Document"
        assert payload["member_references"] == ["Cust_Name", "Cust_Addr"]
        return json.dumps(
            {
                "success": True,
                "created": True,
                "repo": repo,
                "group_id": payload["group_id"],
                "member_ids": payload["member_references"],
            }
        )

    monkeypatch.setattr(graph_module, "contentedge_verify_index_group", fake_verify)
    monkeypatch.setattr(graph_module, "contentedge_create_index_group", fake_create)

    result = await graph_module.index_groups_node(
        _state(
            "Can you see if this index group exists and if not create it?",
            {
                "summary": "The image shows a group labeled Document with two visible indexes.",
                "index_group_candidate": {
                    "present": True,
                    "group_id": "Document",
                    "group_name": "Document",
                    "member_references": ["Cust_Name", "Cust_Addr"],
                },
            },
        )
    )

    assert "contentedge_verify_index_group" in result["tools_used"]
    assert "contentedge_create_index_group" in result["tools_used"]
    assert "Created index group `Document`" in result["formatted_results"]


@pytest.mark.asyncio
async def test_index_groups_node_requires_identifiable_visual_group(monkeypatch):
    async def fake_verify(identifier: str, repo: str = "source") -> str:
        raise AssertionError("verify should not be called without an identifiable group")

    monkeypatch.setattr(graph_module, "contentedge_verify_index_group", fake_verify)

    result = await graph_module.index_groups_node(
        _state(
            "Can you see if this index group exists and if not create it?",
            {
                "summary": "The screenshot contains document metadata values only.",
                "index_group_candidate": {
                    "present": False,
                    "group_id": "",
                    "group_name": "",
                    "member_references": [],
                    "reason": "No explicit index-group schema is visible.",
                },
            },
        )
    )

    assert "could not determine a concrete index group" in result["formatted_results"].lower()

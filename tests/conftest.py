"""Shared test bootstrap — loads .env and adjusts paths for local execution.

Usage: Put this at the top of every test file:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from tests.conftest import setup; setup()
"""

import os
import sys


def setup():
    """Load .env and configure paths for running tests outside Docker."""
    project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    # Load .env (same file that docker-compose uses)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(project_root, ".env"), override=True)
    except ImportError:
        pass  # Inside Docker, dotenv is available but .env vars are already set

    # Override Docker-only paths so the app works locally
    os.environ.setdefault("AGENT_WORKSPACE", os.path.join(project_root, "workspace"))
    os.environ.setdefault("CE_WORK_DIR", os.path.join(project_root, "contentedge", "files"))
    os.environ["CONTENTEDGE_YAML"] = os.path.join(project_root, "workspace", "conf", "repository_source.yaml")
    os.environ["CONTENTEDGE_TARGET_YAML"] = os.path.join(project_root, "workspace", "conf", "repository_target.yaml")

    # Ensure project root and contentedge/lib are importable
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    ce_root = os.path.join(project_root, "contentedge")
    if ce_root not in sys.path:
        sys.path.insert(0, ce_root)

    # Change working directory to project root (workspace/ paths are relative)
    os.chdir(project_root)

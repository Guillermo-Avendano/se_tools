#!/usr/bin/env python3
"""
Remove definitions from a ContentEdge repository.

Usage:
    python rm_definitions.py <OBJECT_TYPE> <LIST_FILE>

OBJECT_TYPE: CONTENT_CLASS | INDEX | INDEX_GROUP | ARCHIVING_POLICY
LIST_FILE:   Path to a text file with one ID per line.

For CONTENT_CLASS objects, verifies that no archived versions exist
before deletion. If versions are found, the content class is skipped
and an error is logged.

Environment variables (set by the worker for the active REPO):
    CE_SOURCE_REPO_URL / CE_TARGET_REPO_URL
    CE_SOURCE_REPO_NAME / CE_TARGET_REPO_NAME
    ... (see worker.py get_repo_env)

The REPO to operate on is passed via the REPO env var (SOURCE or TARGET),
set by the worker before invoking this script.
"""

import json
import os
import sys
import logging
import requests
from copy import deepcopy
from pathlib import Path
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('rm_definitions')

# ---------------------------------------------------------------------------
# ContentEdge library imports
# ---------------------------------------------------------------------------
CE_ROOT = Path('/app/contentedge')
if str(CE_ROOT) not in sys.path:
    sys.path.insert(0, str(CE_ROOT))

WORKSPACE_ROOT = Path(os.environ.get('WORKSPACE_ROOT', '/workspace'))
CONF_DIR = WORKSPACE_ROOT / 'conf'

NAV_ACCEPT = 'application/vnd.asg-mobius-navigation.v3+json'


def _get_config(repo: str):
    """Load ContentConfig for the given repo alias."""
    from lib.content_config import ContentConfig
    is_target = repo.upper() == 'TARGET'
    yaml_name = 'repository_target.yaml' if is_target else 'repository_source.yaml'
    yaml_path = str(CONF_DIR / yaml_name)
    if not os.path.exists(yaml_path):
        yaml_path = str(CE_ROOT / 'conf' / yaml_name)
    return ContentConfig(yaml_path)


def _get_cc_nav_folder_id(config, cc_id: str):
    """Find the navigation objectId for a content class (to check versions).

    Returns the objectId if found, None otherwise.
    """
    headers = deepcopy(config.headers)
    headers['Accept'] = NAV_ACCEPT

    # 1. Find the 'Content Classes' root folder
    url = f"{config.repo_url}/repositories/{config.repo_id}/children?limit=1"
    r = requests.get(url, headers=headers, verify=False)
    if r.status_code != 200:
        return None
    cc_root_id = None
    for item in r.json().get('items', []):
        if item.get('name') == 'Content Classes':
            cc_root_id = item.get('objectId')
            break
    if not cc_root_id:
        return None

    # 2. Locate the specific CC folder
    locate_url = (
        f"{config.repo_url}/folders/{cc_root_id}/children"
        f"?limit=1&locate={cc_id}"
    )
    r2 = requests.get(locate_url, headers=headers, verify=False)
    if r2.status_code != 200:
        return None
    for item in r2.json().get('items', []):
        if str(item.get('name', '')).strip() == cc_id:
            return item.get('objectId')
    return None


def _cc_has_versions(config, cc_nav_oid: str) -> bool:
    """Check if a content class has any archived versions."""
    headers = deepcopy(config.headers)
    headers['Accept'] = NAV_ACCEPT
    url = f"{config.repo_url}/folders/{cc_nav_oid}/children?limit=1"
    r = requests.get(url, headers=headers, verify=False)
    if r.status_code != 200:
        return False
    items = r.json().get('items', [])
    return len(items) > 0


def delete_content_classes(config, ids: list[str]) -> dict:
    """Delete content classes, checking for versions first."""
    from lib.content_adm_content_class import ContentAdmContentClass
    admin = ContentAdmContentClass(config)

    results = {'deleted': 0, 'skipped_versions': 0, 'not_found': 0, 'errors': 0, 'details': []}

    for cc_id in ids:
        cc_id = cc_id.strip()
        if not cc_id:
            continue

        # Check if exists
        if not admin.verify_content_class(cc_id):
            logger.warning(f"Content class '{cc_id}' not found — skipping")
            results['not_found'] += 1
            results['details'].append(f"{cc_id}: not found")
            continue

        # Check for versions via navigation API
        nav_oid = _get_cc_nav_folder_id(config, cc_id)
        if nav_oid and _cc_has_versions(config, nav_oid):
            logger.error(
                f"Content class '{cc_id}' has archived versions — "
                f"cannot delete. Remove versions first."
            )
            results['skipped_versions'] += 1
            results['details'].append(f"{cc_id}: has versions — skipped")
            continue

        # Delete
        status = admin.delete_content_class(cc_id)
        if status and 200 <= status < 300:
            logger.info(f"Deleted content class '{cc_id}'")
            results['deleted'] += 1
            results['details'].append(f"{cc_id}: deleted")
        else:
            logger.error(f"Failed to delete content class '{cc_id}': HTTP {status}")
            results['errors'] += 1
            results['details'].append(f"{cc_id}: delete failed (HTTP {status})")

    return results


def delete_indexes(config, ids: list[str]) -> dict:
    """Delete indexes by ID."""
    from lib.content_adm_index import ContentAdmIndex
    admin = ContentAdmIndex(config)

    results = {'deleted': 0, 'not_found': 0, 'errors': 0, 'details': []}

    for idx_id in ids:
        idx_id = idx_id.strip()
        if not idx_id:
            continue

        if not admin.verify_index(idx_id):
            logger.warning(f"Index '{idx_id}' not found — skipping")
            results['not_found'] += 1
            results['details'].append(f"{idx_id}: not found")
            continue

        status = admin.delete_index(idx_id)
        if status and 200 <= status < 300:
            logger.info(f"Deleted index '{idx_id}'")
            results['deleted'] += 1
            results['details'].append(f"{idx_id}: deleted")
        else:
            logger.error(f"Failed to delete index '{idx_id}': HTTP {status}")
            results['errors'] += 1
            results['details'].append(f"{idx_id}: delete failed (HTTP {status})")

    return results


def delete_index_groups(config, ids: list[str]) -> dict:
    """Delete index groups by ID."""
    from lib.content_adm_index_group import ContentAdmIndexGroup
    admin = ContentAdmIndexGroup(config)

    results = {'deleted': 0, 'not_found': 0, 'errors': 0, 'details': []}

    for ig_id in ids:
        ig_id = ig_id.strip()
        if not ig_id:
            continue

        if not admin.verify_index_group(ig_id):
            logger.warning(f"Index group '{ig_id}' not found — skipping")
            results['not_found'] += 1
            results['details'].append(f"{ig_id}: not found")
            continue

        status = admin.delete_index_group(ig_id)
        if status and 200 <= status < 300:
            logger.info(f"Deleted index group '{ig_id}'")
            results['deleted'] += 1
            results['details'].append(f"{ig_id}: deleted")
        else:
            logger.error(f"Failed to delete index group '{ig_id}': HTTP {status}")
            results['errors'] += 1
            results['details'].append(f"{ig_id}: delete failed (HTTP {status})")

    return results


def delete_archiving_policies(config, ids: list[str]) -> dict:
    """Delete archiving policies by name."""
    from lib.content_adm_archive_policy import ContentAdmArchivePolicy
    admin = ContentAdmArchivePolicy(config)

    results = {'deleted': 0, 'not_found': 0, 'errors': 0, 'details': []}

    for ap_name in ids:
        ap_name = ap_name.strip()
        if not ap_name:
            continue

        if not admin.verify_archiving_policy(ap_name):
            logger.warning(f"Archiving policy '{ap_name}' not found — skipping")
            results['not_found'] += 1
            results['details'].append(f"{ap_name}: not found")
            continue

        status = admin.delete_archiving_policy(ap_name)
        if status and 200 <= status < 300:
            logger.info(f"Deleted archiving policy '{ap_name}'")
            results['deleted'] += 1
            results['details'].append(f"{ap_name}: deleted")
        else:
            logger.error(f"Failed to delete archiving policy '{ap_name}': HTTP {status}")
            results['errors'] += 1
            results['details'].append(f"{ap_name}: delete failed (HTTP {status})")

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

HANDLERS = {
    'CONTENT_CLASS': delete_content_classes,
    'INDEX': delete_indexes,
    'INDEX_GROUP': delete_index_groups,
    'ARCHIVING_POLICY': delete_archiving_policies,
}


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <OBJECT_TYPE> <LIST_FILE>")
        print(f"  OBJECT_TYPE: {', '.join(HANDLERS.keys())}")
        print(f"  LIST_FILE: text file with one ID per line")
        sys.exit(1)

    object_type = sys.argv[1].upper()
    list_file = sys.argv[2]

    if object_type not in HANDLERS:
        logger.error(f"Unknown object type: {object_type}. Must be one of: {', '.join(HANDLERS.keys())}")
        sys.exit(1)

    list_path = Path(list_file)
    if not list_path.is_file():
        logger.error(f"List file not found: {list_file}")
        sys.exit(1)

    ids = [line.strip() for line in list_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not ids:
        logger.warning(f"List file is empty: {list_file}")
        sys.exit(0)

    # Determine repo from environment (set by the worker)
    repo = os.environ.get('REPO', 'TARGET')
    logger.info(f"Operation: Remove {object_type} definitions from {repo}")
    logger.info(f"Items: {len(ids)} — {', '.join(ids)}")

    config = _get_config(repo)

    handler = HANDLERS[object_type]
    results = handler(config, ids)

    logger.info(f"Results: {json.dumps(results, indent=2)}")

    # Exit with error code if any failures
    total_errors = results.get('errors', 0) + results.get('skipped_versions', 0)
    sys.exit(1 if total_errors > 0 else 0)


if __name__ == '__main__':
    main()

"""
Clean TARGET repository — delete all versions, content classes,
index groups, indexes, and archiving policies.

Order:
  1. Delete versions for each content class (navigation REST API)
  2. Delete content classes (admin REST API)
  3. Delete index groups (admin REST API)
  4. Delete indexes (admin REST API)
  5. Delete archiving policies (admin REST API)

Known limitation:
  Multi-section versions (archives with >1 section) cannot be deleted
  via the REST API — the server returns 422 "section count doesn't match
  the archive". These are reported as 'skipped_multi_section'.
"""
import sys, os, json, time, logging, requests
from copy import deepcopy
from dotenv import load_dotenv

# Setup paths
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from lib.content_adm_services_api import ContentAdmServicesApi

SOURCE_YAML = os.path.join(os.path.dirname(__file__), '..', 'conf', 'repository_source.yaml')
TARGET_YAML = os.path.join(os.path.dirname(__file__), '..', 'conf', 'repository_target.yaml')

NAV_ACCEPT = 'application/vnd.asg-mobius-navigation.v3+json'


def get_content_classes_folder_id(config):
    """Get the objectId of the 'Content Classes' root folder."""
    headers = deepcopy(config.headers)
    headers['Accept'] = NAV_ACCEPT
    url = f"{config.repo_url}/repositories/{config.repo_id}/children?limit=1"
    r = requests.get(url, headers=headers, verify=False)
    if r.status_code == 200:
        for item in r.json().get('items', []):
            if item.get('name') == 'Content Classes':
                return item.get('objectId')
    return None


def get_all_cc_nav_folders(config, cc_folder_id):
    """Iterate ALL children of the Content Classes root folder.

    Returns a dict mapping stripped folder name → objectId.
    This avoids the locate= approach which fails when CC names have
    trailing spaces or other formatting differences.
    """
    headers = deepcopy(config.headers)
    headers['Accept'] = NAV_ACCEPT
    result = {}
    offset = 0
    limit = 100
    while True:
        url = f"{config.repo_url}/folders/{cc_folder_id}/children?limit={limit}&offset={offset}"
        r = requests.get(url, headers=headers, verify=False)
        if r.status_code != 200:
            logger.warning(f"  Failed to list CC children at offset {offset}: {r.status_code}")
            break
        items = r.json().get('items', [])
        if not items:
            break
        for item in items:
            name = str(item.get('name', '')).strip()
            result[name] = item.get('objectId')
        offset += len(items)
        if len(items) < limit:
            break
    return result


def delete_versions_for_content_class(config, report_object_id, cc_id):
    """Delete all versions (and their sections) of a content class.

    Structure: CC → versions (vdr:reportVersion/FOLDER) → sections (vdr:reportSection/DOCUMENT)

    For single-section versions: DELETE the section → 204 (success).
    For multi-section versions: DELETE returns 422 → skip and report.

    Returns dict with keys: deleted, skipped_multi_section, errors
    """
    headers = deepcopy(config.headers)
    headers['Accept'] = NAV_ACCEPT

    stats = {'deleted': 0, 'skipped_multi_section': 0, 'errors': 0}

    limit = 200
    while True:
        ver_url = f"{config.repo_url}/folders/{report_object_id}/children?limit={limit}"
        r2 = requests.get(ver_url, headers=headers, verify=False)
        if r2.status_code != 200:
            logger.warning(f"  Versions request failed for '{cc_id}': {r2.status_code}")
            break

        versions = r2.json().get('items', [])
        if not versions:
            break

        any_deleted_this_round = False
        for v in versions:
            v_name = str(v.get('name', '')).strip()
            v_oid = v.get('objectId', '')
            v_type = v.get('objectTypeId', '')

            # SAFETY: only process version folders
            if v_type != 'vdr:reportVersion':
                logger.warning(f"    SKIPPED non-version '{v_name}' ({v_type})")
                continue

            # Get children (sections/documents) inside this version
            sec_url = f"{config.repo_url}/folders/{v_oid}/children?limit=200"
            r3 = requests.get(sec_url, headers=headers, verify=False)
            if r3.status_code != 200:
                logger.warning(f"    Could not list sections for version '{v_name}': {r3.status_code}")
                stats['errors'] += 1
                continue

            sections = r3.json().get('items', [])
            # Filter to DOCUMENT items only
            doc_sections = [s for s in sections if s.get('baseTypeId') == 'DOCUMENT']

            if not doc_sections:
                logger.warning(f"    Version '{v_name}' has no DOCUMENT sections")
                stats['errors'] += 1
                continue

            is_multi = len(doc_sections) > 1

            # Try deleting the first section
            first_sec = doc_sections[0]
            del_url = (f"{config.repo_url}/repositories/{config.repo_id}"
                       f"/documents?documentid={first_sec.get('objectId', '')}")
            rd = requests.delete(del_url, headers=config.headers, verify=False)

            if 200 <= rd.status_code < 300:
                stats['deleted'] += 1
                any_deleted_this_round = True
                logger.debug(f"    Deleted version '{v_name}' ({len(doc_sections)} sections)")
            elif rd.status_code == 422 and is_multi:
                stats['skipped_multi_section'] += 1
                logger.info(f"    SKIPPED multi-section version '{v_name}' "
                            f"({len(doc_sections)} sections, 422)")
            else:
                stats['errors'] += 1
                body = rd.text[:200] if rd.text else ''
                logger.warning(f"    Failed version '{v_name}': {rd.status_code} {body}")

        # If we got fewer than limit, or nothing was deleted, stop
        if len(versions) < limit or not any_deleted_this_round:
            break

    return stats


def main():
    print("=" * 70)
    print("  CLEANUP TARGET REPOSITORY")
    print("=" * 70)

    api = ContentAdmServicesApi(SOURCE_YAML, TARGET_YAML)
    target_cfg = api.target_config
    print(f"\nTARGET: {target_cfg.base_url}")
    print(f"Repo ID: {target_cfg.repo_id}\n")

    # ── Step 1: Delete versions ──────────────────────────────────────
    print("-" * 70)
    print("STEP 1: Delete versions for each content class")
    print("-" * 70)

    cc_folder_id = get_content_classes_folder_id(target_cfg)
    if not cc_folder_id:
        print("ERROR: Could not find 'Content Classes' folder")
        return

    # Build navigation map: stripped name → objectId (iterate all children)
    nav_map = get_all_cc_nav_folders(target_cfg, cc_folder_id)
    print(f"  Navigation CC folders found: {len(nav_map)}")

    from lib.content_adm_content_class import ContentAdmContentClass
    cc_mgr = ContentAdmContentClass(target_cfg)
    cc_list = cc_mgr.list_content_classes()
    print(f"  Admin CC definitions found:  {len(cc_list)}")

    total_deleted = 0
    total_skipped_multi = 0
    total_errors = 0
    total_not_found = 0

    for cc in cc_list:
        cc_id = cc.get('id', '').strip()
        # Match admin CC id to navigation folder (strip both sides)
        report_oid = nav_map.get(cc_id)
        if not report_oid:
            print(f"  '{cc_id}' — not found in navigation (no versions)")
            total_not_found += 1
            continue

        stats = delete_versions_for_content_class(target_cfg, report_oid, cc_id)
        d = stats['deleted']
        s = stats['skipped_multi_section']
        e = stats['errors']
        total_deleted += d
        total_skipped_multi += s
        total_errors += e
        status_parts = []
        if d: status_parts.append(f"{d} deleted")
        if s: status_parts.append(f"{s} skipped(multi-section)")
        if e: status_parts.append(f"{e} errors")
        status_str = ", ".join(status_parts) if status_parts else "0 versions"
        print(f"  '{cc_id}' — {status_str}")

    print(f"\nVersion delete summary:")
    print(f"  Deleted:              {total_deleted}")
    print(f"  Skipped multi-section: {total_skipped_multi}")
    print(f"  Errors:               {total_errors}")
    print(f"  Not found in nav:     {total_not_found}\n")

    # ── Step 2: Delete content classes ───────────────────────────────
    print("-" * 70)
    print("STEP 2: Delete content classes")
    print("-" * 70)
    result = api.delete_all_content_classes()
    print(f"Result: {result}\n")

    # ── Step 3: Delete index groups ──────────────────────────────────
    print("-" * 70)
    print("STEP 3: Delete index groups")
    print("-" * 70)
    result = api.delete_all_index_groups()
    print(f"Result: {result}\n")

    # ── Step 4: Delete indexes ───────────────────────────────────────
    print("-" * 70)
    print("STEP 4: Delete indexes")
    print("-" * 70)
    result = api.delete_all_indexes()
    print(f"Result: {result}\n")

    # ── Step 5: Delete archiving policies ────────────────────────────
    print("-" * 70)
    print("STEP 5: Delete archiving policies")
    print("-" * 70)
    result = api.delete_all_archiving_policies()
    print(f"Result: {result}\n")

    # ── Verify ───────────────────────────────────────────────────────
    print("=" * 70)
    print("  VERIFICATION — remaining objects on TARGET")
    print("=" * 70)
    remaining_cc = api.list_target_content_classes()
    remaining_ig = api.list_target_index_groups()
    remaining_idx = api.list_target_indexes()
    remaining_ap = api.list_target_archiving_policies()
    print(f"  Content classes:    {len(remaining_cc)}")
    print(f"  Index groups:       {len(remaining_ig)}")
    print(f"  Indexes:            {len(remaining_idx)}")
    print(f"  Archiving policies: {len(remaining_ap)}")
    print("=" * 70)
    print("  CLEANUP COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()

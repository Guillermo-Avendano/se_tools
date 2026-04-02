"""Test: Delete ALL definitions from TARGET repository.

⚠️  DESTRUCTIVE — This will permanently remove all content classes, indexes,
    index groups, and archiving policies from the TARGET repository.

    Order: archiving policies → content classes → index groups → indexes
    (reverse dependency order)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.conftest import setup; setup()
import sys
import json
from app.skills.contentedge_skill import (
    _get_ce_config,
    _get_target_config,
    _sync_list_content_classes,
    _sync_list_indexes,
)


def main():
    # Show what's in TARGET before deleting
    print("=" * 60)
    print("  DELETE ALL DEFINITIONS FROM TARGET")
    print("=" * 60)

    tgt_config = _get_target_config()
    print(f"\n  Target: {tgt_config.repo_name} @ {tgt_config.base_url}")
    print()

    # List current contents
    tgt_cc = _sync_list_content_classes("target")
    tgt_idx = _sync_list_indexes("target")
    tgt_idx_list = tgt_idx.get("indexes", []) if isinstance(tgt_idx, dict) else []
    tgt_groups = tgt_idx.get("index_groups", []) if isinstance(tgt_idx, dict) else []

    print(f"  Content classes:  {len(tgt_cc)}")
    print(f"  Indexes:          {len(tgt_idx_list)}")
    print(f"  Index groups:     {len(tgt_groups)}")
    print()

    if not tgt_cc and not tgt_idx_list and not tgt_groups:
        print("  TARGET is already empty — nothing to delete.")
        return

    # Confirmation
    print("  ⚠️  This will PERMANENTLY delete all the above from TARGET.")
    answer = input("  Type 'DELETE' to confirm: ").strip()
    if answer != "DELETE":
        print("  Aborted.")
        return

    print()

    # Get library classes for direct deletion
    from lib.content_adm_archive_policy import ContentAdmArchivePolicy
    from lib.content_adm_content_class import ContentAdmContentClass
    from lib.content_adm_index_group import ContentAdmIndexGroup
    from lib.content_adm_index import ContentAdmIndex

    # 1. Delete archiving policies
    print("  [1/4] Deleting archiving policies...")
    try:
        ap = ContentAdmArchivePolicy(tgt_config)
        ap_result = ap.delete_all_archiving_policies()
        print(f"         {ap_result}")
    except Exception as e:
        print(f"         Error: {e}")

    # 2. Delete content classes
    print("  [2/4] Deleting content classes...")
    try:
        cc = ContentAdmContentClass(tgt_config)
        cc_result = cc.delete_all_content_classes()
        print(f"         {cc_result}")
    except Exception as e:
        print(f"         Error: {e}")

    # 3. Delete index groups
    print("  [3/4] Deleting index groups...")
    try:
        ig = ContentAdmIndexGroup(tgt_config)
        ig_result = ig.delete_all_index_groups()
        print(f"         {ig_result}")
    except Exception as e:
        print(f"         Error: {e}")

    # 4. Delete indexes
    print("  [4/4] Deleting indexes...")
    try:
        idx = ContentAdmIndex(tgt_config)
        idx_result = idx.delete_all_indexes()
        print(f"         {idx_result}")
    except Exception as e:
        print(f"         Error: {e}")

    print()
    print("  Done. TARGET has been cleaned.")

    # Verify
    tgt_cc2 = _sync_list_content_classes("target")
    print(f"\n  Remaining content classes: {len(tgt_cc2)}")


if __name__ == "__main__":
    main()

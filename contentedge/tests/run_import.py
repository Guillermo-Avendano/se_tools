"""
Step 2: Import all admin objects from an export directory into TARGET.

Usage:
    python contentedge/tests/run_import.py                          # auto-detect latest export
    python contentedge/tests/run_import.py workspace/export_20260318_180000  # specific dir

Import order: indexes → index_groups → content_classes → archiving_policies
Objects that already exist are skipped (409).
"""
import sys, os, glob, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from dotenv import load_dotenv
load_dotenv('.env')

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

from lib.content_adm_services_api import ContentAdmServicesApi

SOURCE_YAML = os.path.join('workspace', 'conf', 'repository_source.yaml')
TARGET_YAML = os.path.join('workspace', 'conf', 'repository_target.yaml')


def find_latest_export(base_dir="workspace"):
    """Find the most recent export_* directory."""
    dirs = sorted(glob.glob(os.path.join(base_dir, "export_*")))
    if not dirs:
        return None
    return dirs[-1]


# Determine export directory
if len(sys.argv) > 1:
    export_dir = sys.argv[1]
else:
    export_dir = find_latest_export()

if not export_dir or not os.path.isdir(export_dir):
    print(f"ERROR: Export directory not found: {export_dir}")
    print("Usage: python run_import.py [export_dir]")
    sys.exit(1)

# Show manifest
manifest_path = os.path.join(export_dir, "manifest.json")
if os.path.exists(manifest_path):
    with open(manifest_path) as f:
        manifest = json.load(f)
    print("=" * 60)
    print(f"  IMPORT {export_dir} → TARGET")
    print("=" * 60)
    print(f"  Exported at:          {manifest.get('exported_at')}")
    print(f"  Source:               {manifest.get('source_url')}")
    print(f"  Content classes:      {manifest.get('content_classes')}")
    print(f"  Indexes:              {manifest.get('indexes')}")
    print(f"  Index groups:         {manifest.get('index_groups')}")
    print(f"  Archiving policies:   {manifest.get('archiving_policies')}")
    print()

api = ContentAdmServicesApi(SOURCE_YAML, TARGET_YAML)

print(f"TARGET: {api.target_config.base_url}")
print()

results = api.import_all(export_dir)

print()
print("=" * 60)
print("  IMPORT RESULTS")
print("=" * 60)
for obj_type, counts in results.items():
    print(f"  {obj_type:25s} {counts}")
print()

# Verify
print("Verification — objects on TARGET:")
print(f"  Content classes:    {len(api.list_target_content_classes())}")
print(f"  Index groups:       {len(api.list_target_index_groups())}")
print(f"  Indexes:            {len(api.list_target_indexes())}")
print(f"  Archiving policies: {len(api.list_target_archiving_policies())}")
print()
print("Done.")

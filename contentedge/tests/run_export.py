"""
Step 1: Export all admin objects from SOURCE to workspace/export_<timestamp>/

Usage:
    python contentedge/tests/run_export.py

Creates a directory like workspace/export_20260318_180000/ with:
    content_classes/    — content_class_*.json
    indexes/            — indexes_*.json
    index_groups/       — index_groups_*.json
    archiving_policies/ — {name}.json (one per policy)
    manifest.json       — metadata about the export
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from dotenv import load_dotenv
load_dotenv('.env')

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

from lib.content_adm_services_api import ContentAdmServicesApi

SOURCE_YAML = os.path.join('workspace', 'conf', 'repository_source.yaml')

# Only need SOURCE for export — no target_yaml needed
api = ContentAdmServicesApi(SOURCE_YAML)

print("=" * 60)
print("  EXPORT SOURCE → workspace/export_<timestamp>")
print("=" * 60)
print()

export_dir = api.export_all(base_dir="workspace")

print()
print(f"Export directory: {export_dir}")
print()

# Show contents
for root, dirs, files in os.walk(export_dir):
    level = root.replace(export_dir, '').count(os.sep)
    indent = '  ' * level
    print(f"{indent}{os.path.basename(root)}/")
    sub_indent = '  ' * (level + 1)
    for f in sorted(files):
        size = os.path.getsize(os.path.join(root, f))
        print(f"{sub_indent}{f}  ({size:,} bytes)")

print()
print("Done. Use run_import.py to import into TARGET.")

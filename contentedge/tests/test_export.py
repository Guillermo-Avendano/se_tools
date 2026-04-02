"""
Export demo — Exports content classes, index groups, indexes and archiving
policies from the SOURCE repository.

Usage:
    cd c:\Rocket\agent
    python -m contentedge.tests.test_export

All exports are saved to  contentedge/output/
"""
import os
import sys
import logging

# ── Ensure contentedge/ is on sys.path ──────────────────────────────────
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ce_root = os.path.join(_root, "contentedge")
if _ce_root not in sys.path:
    sys.path.insert(0, _ce_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(_root, ".env"))

from lib.content_adm_services_api import ContentAdmServicesApi

# ── Logging ─────────────────────────────────────────────────────────────
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s  %(levelname)-8s  %(name)s  %(message)s',
)
log = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────
source_yaml = os.path.join(_ce_root, "conf", "repository_source.yaml")
target_yaml = os.path.join(_ce_root, "conf", "repository_target.yaml")
output_dir  = os.path.join(_ce_root, "output")
os.makedirs(output_dir, exist_ok=True)

# ── Initialise (only SOURCE is connected) ───────────────────────────────
adm = ContentAdmServicesApi(source_yaml, target_yaml)

# Use empty string as filter → get ALL items (wildcard is appended automatically)
FILTER = ""

# ── 1. Export Content Classes ───────────────────────────────────────────
print("\n" + "=" * 60)
print("  1. Exporting Content Classes")
print("=" * 60)
result = adm.export_content_classes(FILTER, output_dir)
print(f"  → {result}\n" if result else "  → (no data or error)\n")

# ── 2. Export Index Groups ──────────────────────────────────────────────
print("=" * 60)
print("  2. Exporting Index Groups")
print("=" * 60)
result = adm.export_index_groups(FILTER, output_dir)
print(f"  → {result}\n" if result else "  → (no data or error)\n")

# ── 3. Export Individual Indexes ────────────────────────────────────────
print("=" * 60)
print("  3. Exporting Individual Indexes")
print("=" * 60)
result = adm.export_indexes(FILTER, output_dir)
print(f"  → {result}\n" if result else "  → (no data or error)\n")

# ── 4. Export Archiving Policies ────────────────────────────────────────
print("=" * 60)
print("  4. Exporting Archiving Policies")
print("=" * 60)
adm.export_archiving_policies(FILTER, output_dir)
# Policies are saved as individual files (one per policy)
policy_files = [f for f in os.listdir(output_dir) if f.endswith('.json') and not f.startswith(('content_class_', 'index_groups_', 'indexes_'))]
print(f"  → {len(policy_files)} policy file(s) in {output_dir}\n")

# ── Summary ─────────────────────────────────────────────────────────────
print("=" * 60)
print("  Export complete. Files in:")
print(f"    {output_dir}")
print("=" * 60)
for f in sorted(os.listdir(output_dir)):
    size = os.path.getsize(os.path.join(output_dir, f))
    print(f"    {f:50s}  {size:>8,} bytes")

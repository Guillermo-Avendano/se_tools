"""
Create demo — Creates content classes, individual indexes and index groups
on the SOURCE repository.

Usage:
    cd c:\Rocket\agent
    python -m contentedge.tests.test_create

NOTE: This test creates objects directly on SOURCE for testing purposes.
      In production, creates/imports should go to TARGET via ContentAdmServicesApi.
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

from lib.content_adm_services_api import _patch_yaml_from_env
from lib.content_config import ContentConfig
from lib.content_adm_content_class import ContentAdmContentClass
from lib.content_adm_index import ContentAdmIndex, Topic
from lib.content_adm_index_group import ContentAdmIndexGroup, IndexGroup

# ── Logging ─────────────────────────────────────────────────────────────
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s  %(levelname)-8s  %(name)s  %(message)s',
)
log = logging.getLogger(__name__)

# ── Init SOURCE config ──────────────────────────────────────────────────
source_yaml = os.path.join(_ce_root, "conf", "repository_source.yaml")
_patch_yaml_from_env(source_yaml, "CE_SOURCE_")
config = ContentConfig(source_yaml)

# ── Prefix for all test objects (easy to identify / clean up) ───────────
PREFIX = "TST_"


# ═══════════════════════════════════════════════════════════════════════
#  1. Create a Content Class
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  1. Creating Content Class")
print("=" * 60)

cc_adm = ContentAdmContentClass(config)
cc_id = f"{PREFIX}CC01"
cc_name = "Test Content Class 01"

status = cc_adm.create_content_class(cc_id, cc_name)
if status == 409:
    print(f"  Content class '{cc_id}' already exists (409) — skipping")
elif status and 200 <= status < 300:
    print(f"  Content class '{cc_id}' created successfully (HTTP {status})")
else:
    print(f"  Content class '{cc_id}' creation returned HTTP {status}")


# ═══════════════════════════════════════════════════════════════════════
#  2. Create Individual Indexes
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  2. Creating Individual Indexes")
print("=" * 60)

idx_adm = ContentAdmIndex(config)

indexes_to_create = [
    Topic(id=f"{PREFIX}IDX1", name="Test Index 1", dataType="Character", maxLength="30"),
    Topic(id=f"{PREFIX}IDX2", name="Test Index 2", dataType="Date", maxLength="30"),
    Topic(id=f"{PREFIX}IDX3", name="Test Index 3", dataType="Number", maxLength="255"),
]

for idx in indexes_to_create:
    if idx_adm.verify_index(idx.id):
        print(f"  Index '{idx.id}' already exists — skipping")
        continue
    try:
        status = idx_adm.create_index(idx)
        print(f"  Index '{idx.id}' ({idx.dataType}/{idx.maxLength}) → HTTP {status}")
    except Exception as e:
        print(f"  Index '{idx.id}' failed: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  3. Create an Index Group (with topics)
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  3. Creating Index Group")
print("=" * 60)

ig_adm = ContentAdmIndexGroup(config)

ig = IndexGroup(id=f"{PREFIX}GRP1", name="Test Group 1")
ig.addTopic(Topic(id=f"{PREFIX}IDX1", name="Test Index 1", dataType="Character", maxLength="30"))
ig.addTopic(Topic(id=f"{PREFIX}IDX2", name="Test Index 2", dataType="Date", maxLength="30"))

if ig_adm.verify_index_group(ig.id):
    print(f"  Index Group '{ig.id}' already exists — skipping")
else:
    status = ig_adm.create_index_group(ig)
    if status == 409:
        print(f"  Index Group '{ig.id}' already exists (409)")
    elif status and 200 <= status < 300:
        print(f"  Index Group '{ig.id}' created successfully (HTTP {status})")
    else:
        print(f"  Index Group '{ig.id}' creation returned HTTP {status}")


# ═══════════════════════════════════════════════════════════════════════
#  4. Verify what was created
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  4. Verification")
print("=" * 60)

print(f"  Content class '{cc_id}' exists: {cc_adm.verify_content_class(cc_id)}")
for idx in indexes_to_create:
    print(f"  Index '{idx.id}' exists: {idx_adm.verify_index(idx.id)}")
print(f"  Index Group '{ig.id}' exists: {ig_adm.verify_index_group(ig.id)}")

print("\n" + "=" * 60)
print("  Done!")
print("=" * 60)

"""Run multiple deletion passes on TARGET to handle cross-dependencies."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))
import logging; logging.disable(logging.WARNING)

from lib.content_adm_services_api import ContentAdmServicesApi

SOURCE = os.path.join(os.path.dirname(__file__), '..', 'conf', 'repository_source.yaml')
TARGET = os.path.join(os.path.dirname(__file__), '..', 'conf', 'repository_target.yaml')

api = ContentAdmServicesApi(SOURCE, TARGET)
tc = api.target_config
print(f"TARGET: {tc.base_url}")
print()

for pass_num in range(1, 5):
    print(f"=== PASS {pass_num} ===")

    r = api.delete_all_archiving_policies()
    print(f"  APs: {r}")

    r = api.delete_all_content_classes()
    print(f"  CCs: {r}")

    r = api.delete_all_index_groups()
    print(f"  IGs: {r}")

    r = api.delete_all_indexes()
    print(f"  IDX: {r}")

    ccs = api.list_target_content_classes()
    igs = api.list_target_index_groups()
    idx = api.list_target_indexes()
    aps = api.list_target_archiving_policies()
    print(f"  Remaining: CCs={len(ccs)} IGs={len(igs)} IDX={len(idx)} APs={len(aps)}")

    if len(ccs) + len(igs) + len(idx) + len(aps) == 0:
        print("*** ALL CLEAN! ***")
        break
    print()

# Final report
print()
print("=== FINAL STATE ===")
ccs = api.list_target_content_classes()
igs = api.list_target_index_groups()
idx = api.list_target_indexes()
aps = api.list_target_archiving_policies()
print(f"  CCs:  {len(ccs)}")
print(f"  IGs:  {len(igs)}")
print(f"  IDX:  {len(idx)}")
print(f"  APs:  {len(aps)}")
if ccs:
    names = [c.get('id', '?') for c in ccs]
    print(f"  Remaining CCs: {names}")
if igs:
    names = [g.get('id', '?') for g in igs]
    print(f"  Remaining IGs: {names}")
if idx:
    names = [i.get('id', '?') for i in idx]
    print(f"  Remaining IDX: {names}")
if aps:
    names = [a.get('name', '?') for a in aps]
    print(f"  Remaining APs: {names}")

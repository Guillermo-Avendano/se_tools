"""Quick script: delete all definitions from TARGET (CCs, IGs, Indexes, APs)."""
import sys, os, logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join('..', '..', '.env'))
logging.disable(logging.WARNING)

from lib.content_adm_services_api import ContentAdmServicesApi

api = ContentAdmServicesApi(
    os.path.join('..', 'conf', 'repository_source.yaml'),
    os.path.join('..', 'conf', 'repository_target.yaml'),
)
print("Connected to TARGET\n")

print("--- Deleting Content Classes ---")
r = api.delete_all_content_classes()
print(f"  {r}\n")

print("--- Deleting Index Groups ---")
r = api.delete_all_index_groups()
print(f"  {r}\n")

print("--- Deleting Indexes ---")
r = api.delete_all_indexes()
print(f"  {r}\n")

print("--- Deleting Archiving Policies ---")
r = api.delete_all_archiving_policies()
print(f"  {r}\n")

print("=== REMAINING ON TARGET ===")
cc = api.list_target_content_classes()
ig = api.list_target_index_groups()
idx = api.list_target_indexes()
ap = api.list_target_archiving_policies()
print(f"  Content classes:    {len(cc)}")
print(f"  Index groups:       {len(ig)}")
print(f"  Indexes:            {len(idx)}")
print(f"  Archiving policies: {len(ap)}")
if cc:
    ids = [c.get("id", "") for c in cc]
    print(f"  Remaining CC ids: {ids}")

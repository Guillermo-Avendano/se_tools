"""Minimal test: debug 422 on section delete."""
import sys, os, requests, json
from copy import deepcopy
from dotenv import load_dotenv

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

# Suppress most logging
import logging
logging.disable(logging.WARNING)

from lib.content_adm_services_api import _patch_yaml_from_env
from lib.content_config import ContentConfig

yaml_path = os.path.join(os.path.dirname(__file__), '..', 'conf', 'repository_target.yaml')
_patch_yaml_from_env(yaml_path, 'CE_TARGET_')
c = ContentConfig(yaml_path)

nav_h = deepcopy(c.headers)
nav_h['Accept'] = 'application/vnd.asg-mobius-navigation.v1+json'

# Get CC folder
r1 = requests.get(f"{c.repo_url}/repositories/{c.repo_id}/children?limit=1", headers=nav_h, verify=False)
cc_folder_id = None
for it in r1.json().get('items', []):
    if it.get('name') == 'Content Classes':
        cc_folder_id = it.get('objectId')
        break

# List CCs in navigation (they may have trailing spaces)
r2 = requests.get(f"{c.repo_url}/folders/{cc_folder_id}/children?limit=60", headers=nav_h, verify=False)
nav_ccs = {}
for it in r2.json().get('items', []):
    nav_ccs[str(it.get('name', '')).strip()] = it.get('objectId', '')
print(f"Nav CCs: {len(nav_ccs)}")

# Pick AutoStmt (had 422 errors)
cc_id = 'AutoStmt'
report_oid = nav_ccs.get(cc_id, '')
print(f"Report '{cc_id}' found: {bool(report_oid)}")

# Get first version
r3 = requests.get(f"{c.repo_url}/folders/{report_oid}/children?limit=1", headers=nav_h, verify=False)
ver = r3.json()['items'][0]
ver_name = ver.get('name', '')
ver_oid = ver.get('objectId', '')
print(f"Version: {ver_name}")

# Get sections
r4 = requests.get(f"{c.repo_url}/folders/{ver_oid}/children?limit=20", headers=nav_h, verify=False)
sections = r4.json().get('items', [])
print(f"Sections in version: {len(sections)}")

for i, sec in enumerate(sections[:3]):
    sec_name = sec.get('name', '')
    sec_oid = sec.get('objectId', '')
    sec_type = sec.get('objectTypeId', '')
    sec_base = sec.get('baseTypeId', '')
    print(f"\n--- Section {i}: name={sec_name} type={sec_type} base={sec_base} ---")

    # Try delete
    del_url = f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={sec_oid}"
    rd = requests.delete(del_url, headers=c.headers, verify=False)
    print(f"  DELETE status={rd.status_code}")
    print(f"  DELETE body={rd.text[:400]}")

    # Check sub-children
    r5 = requests.get(f"{c.repo_url}/folders/{sec_oid}/children?limit=10", headers=nav_h, verify=False)
    if r5.status_code == 200:
        sub = r5.json().get('items', [])
        print(f"  Sub-children: {len(sub)}")
        for sc in sub[:2]:
            print(f"    child: name={sc.get('name','')} type={sc.get('objectTypeId','')} base={sc.get('baseTypeId','')}")
            # Try deleting child
            sc_oid = sc.get('objectId', '')
            rd2 = requests.delete(
                f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={sc_oid}",
                headers=c.headers, verify=False
            )
            print(f"    DELETE child: status={rd2.status_code} body={rd2.text[:200]}")

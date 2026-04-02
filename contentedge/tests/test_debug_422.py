"""Debug 422 error on section delete — check response body and structure."""
import sys, os, requests, json
from copy import deepcopy
from dotenv import load_dotenv

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

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

# Use AutoStmt (had 422 errors — multiple sections per version)
# First list all CCs in navigation to see naming
r2 = requests.get(f"{c.repo_url}/folders/{cc_folder_id}/children?limit=60", headers=nav_h, verify=False)
nav_ccs = {str(it.get('name', '')).strip(): it.get('objectId', '') for it in r2.json().get('items', [])}
print(f"Navigation CC names (first 10): {list(nav_ccs.keys())[:10]}")

# Pick AutoStmt 
cc_id = 'AutoStmt'
report_oid = nav_ccs.get(cc_id, '')
if not report_oid:
    # Try with spaces
    for k, v in nav_ccs.items():
        if k.strip() == cc_id:
            report_oid = v
            break
print(f"\nReport '{cc_id}' objectId found: {bool(report_oid)}")

if report_oid:
    # Get first version
    r3 = requests.get(f"{c.repo_url}/folders/{report_oid}/children?limit=1", headers=nav_h, verify=False)
    versions = r3.json().get('items', [])
    if versions:
        ver = versions[0]
        ver_name = ver.get('name', '')
        ver_oid = ver.get('objectId', '')
        print(f"Version: {ver_name}")

        # Get sections
        r4 = requests.get(f"{c.repo_url}/folders/{ver_oid}/children?limit=50", headers=nav_h, verify=False)
        sections = r4.json().get('items', [])
        print(f"Sections: {len(sections)}")

        for i, sec in enumerate(sections[:3]):
            sec_name = sec.get('name', '')
            sec_oid = sec.get('objectId', '')
            sec_type = sec.get('objectTypeId', '')
            sec_base = sec.get('baseTypeId', '')
            print(f"\n  Section {i}: name={sec_name}  type={sec_type}  base={sec_base}")
            print(f"  objectId: {sec_oid[:80]}...")

            # Try delete and capture response body
            del_url = f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={sec_oid}"
            rd = requests.delete(del_url, headers=c.headers, verify=False)
            print(f"  DELETE status: {rd.status_code}")
            print(f"  DELETE body: {rd.text[:500]}")

            # Check if section has sub-children
            r5 = requests.get(f"{c.repo_url}/folders/{sec_oid}/children?limit=10", headers=nav_h, verify=False)
            if r5.status_code == 200:
                sub = r5.json().get('items', [])
                print(f"  Sub-children: {len(sub)}")
                for sc in sub[:3]:
                    sc_name = sc.get('name', '')
                    sc_type = sc.get('objectTypeId', '')
                    sc_base = sc.get('baseTypeId', '')
                    sc_oid = sc.get('objectId', '')
                    print(f"    name={sc_name}  type={sc_type}  base={sc_base}")
                    
                    # Try deleting sub-child
                    rd2 = requests.delete(
                        f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={sc_oid}",
                        headers=c.headers, verify=False
                    )
                    print(f"    DELETE sub: {rd2.status_code} {rd2.text[:200]}")

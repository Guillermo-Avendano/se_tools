"""Explore version structure and find the actual document objectId for deletion."""
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

# Use AutoApp (has versions)
cc_id = 'AutoApp'
r2 = requests.get(f"{c.repo_url}/folders/{cc_folder_id}/children?locate={cc_id}&limit=5", headers=nav_h, verify=False)
report_oid = None
for it in r2.json().get('items', []):
    if str(it.get('name', '')).strip() == cc_id:
        report_oid = it.get('objectId')
        break
print(f"Report '{cc_id}' objectId: {report_oid}")

# Get first version
r3 = requests.get(f"{c.repo_url}/folders/{report_oid}/children?limit=1", headers=nav_h, verify=False)
ver = r3.json()['items'][0]
ver_name = ver.get('name', '')
ver_oid = ver.get('objectId', '')
ver_type = ver.get('objectTypeId', '')
print(f"\nVersion: name={ver_name}  objectId={ver_oid}  type={ver_type}")
print(f"Full version item keys: {list(ver.keys())}")
print(f"Full version item: {json.dumps(ver, indent=2)[:1000]}")

# Navigate INTO the version — get its children (sections/documents)
print(f"\n--- Children of version '{ver_name}' ---")
r4 = requests.get(f"{c.repo_url}/folders/{ver_oid}/children?limit=20", headers=nav_h, verify=False)
print(f"Status: {r4.status_code}")
if r4.status_code == 200:
    children = r4.json().get('items', [])
    print(f"Children count: {len(children)}")
    for ch in children:
        ch_name = ch.get('name', '')
        ch_oid = ch.get('objectId', '')
        ch_type = ch.get('objectTypeId', '')
        ch_base = ch.get('baseTypeId', '')
        ch_isDoc = ch.get('isDocument', '')
        ch_isFolder = ch.get('isFolder', '')
        print(f"  name={ch_name}  type={ch_type}  base={ch_base}  isDoc={ch_isDoc}  objectId={ch_oid[:60]}...")

        # If it's a document, try to delete it
        if ch_base == 'DOCUMENT' or ch_isDoc:
            print(f"    Trying DELETE /documents?documentid={ch_oid[:40]}...")
            rd = requests.delete(
                f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={ch_oid}",
                headers=c.headers, verify=False
            )
            print(f"    DELETE status: {rd.status_code} body: {rd.text[:300]}")
        
        # Also navigate deeper
        r5 = requests.get(f"{c.repo_url}/folders/{ch_oid}/children?limit=5", headers=nav_h, verify=False)
        if r5.status_code == 200:
            sub_children = r5.json().get('items', [])
            print(f"    Sub-children: {len(sub_children)}")
            for sc in sub_children[:3]:
                sc_name = sc.get('name', '')
                sc_oid = sc.get('objectId', '')
                sc_type = sc.get('objectTypeId', '')
                sc_base = sc.get('baseTypeId', '')
                print(f"      name={sc_name}  type={sc_type}  base={sc_base}  oid={sc_oid[:60]}...")
else:
    print(f"Body: {r4.text[:500]}")

# Also try: DELETE the version folder itself using folders endpoint
print(f"\n--- Try DELETE version as folder ---")
del_h = deepcopy(c.headers)
# Try with different accept headers
for accept_val in ['application/vnd.asg-mobius-navigation.v1+json', 'application/json', '*/*']:
    del_h2 = deepcopy(c.headers)
    del_h2['Accept'] = accept_val
    rd = requests.delete(f"{c.repo_url}/folders/{ver_oid}", headers=del_h2, verify=False)
    print(f"  Accept={accept_val}: {rd.status_code} {rd.text[:200]}")

# Try admin endpoint for report versions
print(f"\n--- Try admin DELETE on report version ---")
adm_h = deepcopy(c.headers)
adm_h['Accept'] = 'application/vnd.asg-mobius-admin-report.v1+json'
# Try /reports/{cc_id}/versions  
for path in [f"/reports/{cc_id}/versions", f"/reports/{cc_id}/reportversions"]:
    url = c.repo_admin_url + path
    r = requests.get(url, headers=adm_h, verify=False)
    print(f"  GET {path}: {r.status_code} {r.text[:300]}")

# Try DELETE /reports/{cc_id}?deleteVersions=true or similar
print(f"\n--- Try admin DELETE with force/versions param ---")
for param in ['?force=true', '?deleteVersions=true', '?deleteReportVersions=true', '?includeVersions=true']:
    url = c.repo_admin_url + f"/reports/{cc_id}{param}"
    adm_h2 = deepcopy(c.headers)
    adm_h2['Accept'] = 'application/vnd.asg-mobius-admin-report.v1+json'
    rd = requests.delete(url, headers=adm_h2, verify=False)
    print(f"  DELETE /reports/{cc_id}{param}: {rd.status_code} {rd.text[:200]}")

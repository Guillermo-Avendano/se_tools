"""Find content classes with versions on TARGET and test delete."""
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

print(f"CC folder: {cc_folder_id}")

# List content classes via navigation
r2 = requests.get(f"{c.repo_url}/folders/{cc_folder_id}/children?limit=60", headers=nav_h, verify=False)
items = r2.json().get('items', [])
print(f"Content classes in nav: {len(items)}")

found_version = None
for it in items:
    cc_name = str(it.get('name', '')).strip()
    cc_oid = it.get('objectId', '')
    r3 = requests.get(f"{c.repo_url}/folders/{cc_oid}/children?limit=1", headers=nav_h, verify=False)
    vcount = len(r3.json().get('items', []))
    if vcount > 0:
        v = r3.json()['items'][0]
        v_name = v.get('name', '')
        v_oid = v.get('objectId', '')
        v_type = v.get('objectTypeId', '')
        print(f"  {cc_name:15s} has versions! First: name={v_name}  oid={v_oid}  type={v_type}")
        if found_version is None:
            found_version = (cc_name, v_name, v_oid, v_type)

if found_version is None:
    print("\nNo content classes with versions found — nothing to delete.")
else:
    cc_name, v_name, v_oid, v_type = found_version
    print(f"\n=== Testing DELETE on first version of '{cc_name}' ===")
    print(f"  Version: {v_name}  objectId: {v_oid}")

    # Method 1: DELETE /repositories/{id}/documents?documentid=oid
    del_url = f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={v_oid}"
    print(f"\n  Method 1: DELETE {del_url}")
    rd = requests.delete(del_url, headers=c.headers, verify=False)
    print(f"  Status: {rd.status_code}")
    print(f"  Body: {rd.text[:500]}")

    # Method 2: DELETE /folders/{oid}
    del_url2 = f"{c.repo_url}/folders/{v_oid}"
    print(f"\n  Method 2: DELETE {del_url2}")
    rd2 = requests.delete(del_url2, headers=c.headers, verify=False)
    print(f"  Status: {rd2.status_code}")
    print(f"  Body: {rd2.text[:500]}")

    # Method 3: Try with Accept header
    del_h = deepcopy(c.headers)
    del_h['Accept'] = 'application/vnd.asg-mobius-navigation.v1+json'
    del_url3 = f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={v_oid}"
    print(f"\n  Method 3: DELETE with nav Accept header {del_url3}")
    rd3 = requests.delete(del_url3, headers=del_h, verify=False)
    print(f"  Status: {rd3.status_code}")
    print(f"  Body: {rd3.text[:500]}")

    # Method 4: Try admin DELETE on content class definition
    adm_h = deepcopy(c.headers)
    adm_h['Accept'] = 'application/vnd.asg-mobius-admin-report.v1+json'
    del_url4 = f"{c.repo_admin_url}/reports/{cc_name}"
    print(f"\n  Method 4: Admin DELETE {del_url4}")
    rd4 = requests.delete(del_url4, headers=adm_h, verify=False)
    print(f"  Status: {rd4.status_code}")
    print(f"  Body: {rd4.text[:500]}")

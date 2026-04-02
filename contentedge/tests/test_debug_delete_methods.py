"""Test different approaches to delete a multi-section version."""
import sys, os, requests, json
from copy import deepcopy
from dotenv import load_dotenv
from urllib.parse import quote

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

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

# Get AutoStmt report
r2 = requests.get(f"{c.repo_url}/folders/{cc_folder_id}/children?limit=60", headers=nav_h, verify=False)
nav_ccs = {}
for it in r2.json().get('items', []):
    nav_ccs[str(it.get('name', '')).strip()] = it.get('objectId', '')

report_oid = nav_ccs.get('AutoStmt', '')

# Get first version
r3 = requests.get(f"{c.repo_url}/folders/{report_oid}/children?limit=1", headers=nav_h, verify=False)
ver = r3.json()['items'][0]
ver_name = ver.get('name', '')
ver_oid = ver.get('objectId', '')
print(f"Version: {ver_name}")
print(f"Version objectId: {ver_oid[:80]}...")

# Get ALL sections
r4 = requests.get(f"{c.repo_url}/folders/{ver_oid}/children?limit=200", headers=nav_h, verify=False)
sections = r4.json().get('items', [])
print(f"Sections: {len(sections)}")

# Build comma-separated list of section objectIds
sec_oids = [s.get('objectId', '') for s in sections]

# Method 1: POST delete with JSON body containing all section IDs
print("\n=== Method 1: DELETE with all section IDs comma-separated ===")
all_ids = ",".join(sec_oids)
del_url = f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={all_ids}"
rd1 = requests.delete(del_url, headers=c.headers, verify=False)
print(f"Status: {rd1.status_code}")
print(f"Body: {rd1.text[:400]}")

# Method 2: POST /repositories/{id}/documents with JSON body
print("\n=== Method 2: POST delete with JSON body ===")
post_h = deepcopy(c.headers)
post_h['Content-Type'] = 'application/json'
post_h['X-HTTP-Method-Override'] = 'DELETE'
body = {"documentIds": sec_oids}
rd2 = requests.post(f"{c.repo_url}/repositories/{c.repo_id}/documents", 
                     headers=post_h, json=body, verify=False)
print(f"Status: {rd2.status_code}")
print(f"Body: {rd2.text[:400]}")

# Method 3: Try with version objectId in a JSON array
print("\n=== Method 3: DELETE with version objectId (JSON body) ===")
del_h3 = deepcopy(c.headers)
del_h3['Content-Type'] = 'application/json'
body3 = [{"selected": True, "data": {"objectId": ver_oid, "objectTypeId": "vdr:reportVersion", "repositoryId": c.repo_id}}]
rd3 = requests.delete(f"{c.repo_url}/repositories/{c.repo_id}/documents",
                       headers=del_h3, json=body3, verify=False)
print(f"Status: {rd3.status_code}")
print(f"Body: {rd3.text[:400]}")

# Method 4: Pass version objectId with sectioncount param
print("\n=== Method 4: DELETE with version objectId + sectioncount ===")
for sc in [str(len(sections)), '1', '0', '*']:
    del_url4 = f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={ver_oid}&sectioncount={sc}"
    rd4 = requests.delete(del_url4, headers=c.headers, verify=False)
    print(f"  sectioncount={sc}: {rd4.status_code} {rd4.text[:200]}")

# Method 5: Delete using the navigation delete endpoint — POST with selected items
print("\n=== Method 5: POST to /repositories/{id}/batch/delete ===")
batch_h = deepcopy(c.headers)
batch_h['Content-Type'] = 'application/json'
batch_h['Accept'] = 'application/json'
batch_body = [{"objectId": ver_oid, "objectTypeId": "vdr:reportVersion", "repositoryId": c.repo_id}]
for endpoint in ["/batch/delete", "/batch"]:
    url5 = f"{c.repo_url}/repositories/{c.repo_id}{endpoint}"
    rd5 = requests.post(url5, headers=batch_h, json=batch_body, verify=False)
    print(f"  POST {endpoint}: {rd5.status_code} {rd5.text[:200]}")

# Method 6: DELETE using first section's objectId but including section count
print("\n=== Method 6: DELETE first section with sectioncount param ===")
first_sec_oid = sec_oids[0]
for sc in [str(len(sections)), '10']:
    del_url6 = f"{c.repo_url}/repositories/{c.repo_id}/documents?documentid={first_sec_oid}&sectioncount={sc}"
    rd6 = requests.delete(del_url6, headers=c.headers, verify=False)
    print(f"  sectioncount={sc}: {rd6.status_code} {rd6.text[:200]}")

# Method 7: Use report+version path to delete version  
print("\n=== Method 7: Admin DELETE on reportversion ===")
adm_h = deepcopy(c.headers)
adm_h['Accept'] = 'application/vnd.asg-mobius-admin-report.v1+json'
# Try encoded version name
ver_encoded = quote(ver_name)
for path in [f"/reports/AutoStmt/versions/{ver_encoded}", 
             f"/reportversions/{ver_oid}"]:
    url7 = c.repo_admin_url + path
    rd7 = requests.delete(url7, headers=adm_h, verify=False)
    print(f"  DELETE {path[:60]}: {rd7.status_code} {rd7.text[:200]}")

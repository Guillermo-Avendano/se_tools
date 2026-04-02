"""Probe TARGET repository — list objects and test DELETE endpoints."""
import sys, os, json, time, logging, requests
from copy import deepcopy
from dotenv import load_dotenv

# Setup
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

from lib.content_adm_services_api import _patch_yaml_from_env
from lib.content_config import ContentConfig

yaml_path = os.path.join(os.path.dirname(__file__), '..', 'conf', 'repository_target.yaml')
_patch_yaml_from_env(yaml_path, 'CE_TARGET_')
c = ContentConfig(yaml_path)
print(f"TARGET: {c.base_url}")
print(f"repo_admin_url: {c.repo_admin_url}")
print(f"repo_url (REST): {c.repo_url}")
print(f"repo_id: {c.repo_id}")

tm = str(int(time.time() * 1000))

# ── 1. List content classes ──
h = deepcopy(c.headers)
h['Accept'] = ('application/vnd.asg-mobius-admin-reports.v3+json,'
               'application/vnd.asg-mobius-admin-reports.v2+json,'
               'application/vnd.asg-mobius-admin-reports.v1+json')
url = c.repo_admin_url + f"/reports?limit=200&reportid=*&timestamp={tm}"
r = requests.get(url, headers=h, verify=False)
cc_items = r.json().get('items', [])
print(f"\n=== Content Classes on TARGET: {len(cc_items)} ===")
for it in cc_items:
    print(f"  {it.get('id',''):15s} {it.get('name','')}")

# ── 2. List index groups ──
h2 = deepcopy(c.headers)
h2['Accept'] = 'application/vnd.asg-mobius-admin-topic-groups.v1+json'
url2 = c.repo_admin_url + f"/topicgroups?limit=200&groupid=*&timestamp={tm}"
r2 = requests.get(url2, headers=h2, verify=False)
ig_items = r2.json().get('items', [])
print(f"\n=== Index Groups on TARGET: {len(ig_items)} ===")
for it in ig_items:
    print(f"  {it.get('id',''):15s} {it.get('name','')}")

# ── 3. List indexes ──
h3 = deepcopy(c.headers)
h3['Accept'] = 'application/vnd.asg-mobius-admin-topics.v1+json'
url3 = c.repo_admin_url + f"/topics?limit=200&topicid=*&timestamp={tm}"
r3 = requests.get(url3, headers=h3, verify=False)
idx_items = r3.json().get('items', [])
print(f"\n=== Indexes on TARGET: {len(idx_items)} ===")
for it in idx_items:
    print(f"  {it.get('id',''):15s} {it.get('name','')}")

# ── 4. List archiving policies ──
h4 = deepcopy(c.headers)
h4['Accept'] = 'application/vnd.asg-mobius-admin-archiving-policies.v1+json'
url4 = c.repo_admin_url + f"/archivingpolicies?limit=200&name=*&timestamp={tm}"
r4 = requests.get(url4, headers=h4, verify=False)
ap_items = r4.json().get('items', [])
print(f"\n=== Archiving Policies on TARGET: {len(ap_items)} ===")
for it in ap_items:
    print(f"  {it.get('name','')}")

# ── 5. List versions for first content class (via navigation API) ──
if cc_items:
    first_cc_id = cc_items[0].get('id', '')
    print(f"\n=== Probing versions for CC '{first_cc_id}' via navigation API ===")

    nav_h = deepcopy(c.headers)
    nav_h['Accept'] = 'application/vnd.asg-mobius-navigation.v1+json'

    # Get Content Classes folder objectId
    cc_folder_url = f"{c.repo_url}/repositories/{c.repo_id}/children?limit=1"
    r5 = requests.get(cc_folder_url, headers=nav_h, verify=False)
    cc_folder_id = None
    if r5.status_code == 200:
        for item in r5.json().get('items', []):
            if item.get('name') == 'Content Classes':
                cc_folder_id = item.get('objectId')
                print(f"  Content Classes folder objectId: {cc_folder_id}")
                break

    # Get report objectId
    if cc_folder_id:
        report_url = f"{c.repo_url}/folders/{cc_folder_id}/children?locate={first_cc_id}&limit=1"
        r6 = requests.get(report_url, headers=nav_h, verify=False)
        report_object_id = None
        if r6.status_code == 200:
            for item in r6.json().get('items', []):
                if str(item.get('name', '')).strip() == first_cc_id:
                    report_object_id = item.get('objectId')
                    print(f"  Report '{first_cc_id}' objectId: {report_object_id}")
                    break

        # List versions
        if report_object_id:
            ver_url = f"{c.repo_url}/folders/{report_object_id}/children?limit=10"
            r7 = requests.get(ver_url, headers=nav_h, verify=False)
            if r7.status_code == 200:
                versions = r7.json().get('items', [])
                print(f"  Versions found: {len(versions)}")
                for v in versions[:5]:
                    print(f"    version={v.get('name','')}  objectId={v.get('objectId','')}  type={v.get('objectTypeId','')}")
            else:
                print(f"  Versions request status: {r7.status_code}")

# ── 6. Probe DELETE on admin endpoints (dry run — just try OPTIONS or HEAD) ──
print("\n=== Probing DELETE endpoints ===")

# Try DELETE on a content class
if cc_items:
    test_cc_id = cc_items[0].get('id', '')
    del_url = c.repo_admin_url + f"/reports/{test_cc_id}"
    hd = deepcopy(c.headers)
    hd['Accept'] = 'application/vnd.asg-mobius-admin-report.v1+json'
    # Use OPTIONS to check if DELETE is allowed
    try:
        r_opt = requests.options(del_url, headers=hd, verify=False)
        print(f"  OPTIONS /reports/{test_cc_id}: {r_opt.status_code} Allow={r_opt.headers.get('Allow','N/A')}")
    except Exception as e:
        print(f"  OPTIONS /reports/{test_cc_id}: error {e}")

# Try DELETE on an index
if idx_items:
    test_idx_id = idx_items[0].get('id', '')
    del_url2 = c.repo_admin_url + f"/topics/{test_idx_id}"
    hd2 = deepcopy(c.headers)
    hd2['Accept'] = 'application/vnd.asg-mobius-admin-topic.v1+json'
    try:
        r_opt2 = requests.options(del_url2, headers=hd2, verify=False)
        print(f"  OPTIONS /topics/{test_idx_id}: {r_opt2.status_code} Allow={r_opt2.headers.get('Allow','N/A')}")
    except Exception as e:
        print(f"  OPTIONS /topics/{test_idx_id}: error {e}")

# Try DELETE on an archiving policy
if ap_items:
    test_ap_name = ap_items[0].get('name', '')
    del_url3 = c.repo_admin_url + f"/archivingpolicies/{test_ap_name}"
    hd3 = deepcopy(c.headers)
    hd3['Accept'] = 'application/vnd.asg-mobius-admin-archiving-policy.v1+json'
    try:
        r_opt3 = requests.options(del_url3, headers=hd3, verify=False)
        print(f"  OPTIONS /archivingpolicies/{test_ap_name}: {r_opt3.status_code} Allow={r_opt3.headers.get('Allow','N/A')}")
    except Exception as e:
        print(f"  OPTIONS /archivingpolicies/{test_ap_name}: error {e}")

print("\n=== Probe complete ===")

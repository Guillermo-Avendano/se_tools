import json
import requests
import urllib3
import warnings
import os
import time
from copy import deepcopy
from .content_config import ContentConfig
from .util import validate_id

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


class ContentAdmArchivePolicy:
    """Manages archiving policy definitions in ContentEdge."""

    def __init__(self, content_config):
        if not isinstance(content_config, ContentConfig):
            raise TypeError("ContentConfig class object expected")
        self.repo_admin_url = content_config.repo_admin_url
        self.logger = content_config.logger
        self.headers = deepcopy(content_config.headers)

    # ------------------------------------------------------------------
    def verify_archiving_policy(self, ap_name: str) -> bool:
        """Check whether an archiving policy with the given name exists."""
        try:
            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = 'application/vnd.asg-mobius-admin-archiving-policies.v1+json'
            tm = str(int(time.time() * 1000))
            url = self.repo_admin_url + f"/archivingpolicies?limit=5&&name={ap_name}*&timestamp={tm}"

            self.logger.debug(f"verify_archiving_policy → GET {url}")
            response = requests.get(url, headers=local_headers, verify=False)
            response.raise_for_status()
            for item in response.json().get("items", []):
                if isinstance(item, dict) and item.get("name") == ap_name:
                    return True
            return False
        except (requests.HTTPError, json.JSONDecodeError) as e:
            self.logger.error(f"verify_archiving_policy error: {e}")
            return False

    # ------------------------------------------------------------------
    def export_archiving_policies(self, ap_filter: str, output_dir: str) -> None:
        """Export archiving policies matching filter as individual JSON files."""
        try:
            if not os.path.exists(output_dir):
                raise FileNotFoundError(f"Output directory '{output_dir}' does not exist")

            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = 'application/vnd.asg-mobius-admin-archiving-policies.v1+json'
            tm = str(int(time.time() * 1000))
            url = self.repo_admin_url + f"/archivingpolicies?limit=200&&name={ap_filter}*&timestamp={tm}"

            self.logger.info(f"export_archiving_policies '{ap_filter}' → GET {url}")
            response = requests.get(url, headers=local_headers, verify=False)
            response.raise_for_status()

            items = response.json().get("items", [])
            ap_headers = deepcopy(self.headers)
            ap_headers['Accept'] = 'application/vnd.asg-mobius-admin-archiving-policy.v1+json'

            for item in items:
                name = item.get("name")
                detail_url = self.repo_admin_url + f"/archivingpolicies/{name}?timestamp={tm}"
                self.logger.info(f"Exporting policy: {name}")
                detail_resp = requests.get(detail_url, headers=ap_headers, verify=False)
                detail_resp.raise_for_status()
                self._save_policy(detail_resp.json(), name, output_dir)

        except (requests.HTTPError, json.JSONDecodeError, FileNotFoundError) as e:
            self.logger.error(f"export_archiving_policies error: {e}")

    # ------------------------------------------------------------------
    def import_archiving_policy(self, policy_path: str, policy_name: str) -> int:
        """Import an archiving policy from a JSON file.
        Returns 409 (skipped) if it already exists."""
        if not validate_id(policy_name):
            raise ValueError(f"Not valid archiving policy name: '{policy_name}'")

        if self.verify_archiving_policy(policy_name):
            self.logger.warning(f"Archiving policy '{policy_name}' already exists — skipped.")
            return 409

        url = self.repo_admin_url + "/archivingpolicies"
        local_headers = deepcopy(self.headers)
        local_headers['Content-Type'] = 'application/vnd.asg-mobius-admin-archiving-policy.v1+json'

        try:
            with open(policy_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            if isinstance(json_data, dict) and "name" in json_data:
                json_data["name"] = policy_name
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as e:
            self.logger.error(f"Error reading policy file: {e}")
            return -1

        try:
            self.logger.info(f"import_archiving_policy '{policy_name}' → POST {url}")
            response = requests.post(url, headers=local_headers,
                                     data=json.dumps(json_data, indent=2), verify=False)
            self.logger.info(f"Response: {response.status_code}")
            return response.status_code
        except requests.RequestException as e:
            self.logger.error(f"import_archiving_policy request error: {e}")
            return -1

    # ------------------------------------------------------------------
    def _save_policy(self, json_data: dict, name: str, output_dir: str) -> bool:
        """Save a single archiving policy JSON to file."""
        try:
            modified = json_data.copy()
            modified.pop("links", None)
            modified = self._clean_policy_json(modified)

            file_path = os.path.join(output_dir, name + '.json')
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(modified, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Policy '{name}' saved to: {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"_save_policy error: {e}")
            return False

    # ------------------------------------------------------------------
    @staticmethod
    def _clean_policy_json(data: dict) -> dict:
        """Remove server-only keys that should not be re-imported."""
        output = json.loads(json.dumps(data))
        for key in ['decimalSeparator', 'enableAggregation',
                     'enableEnhancedFieldLevelJoining', 'requireMatchForFieldExtraction',
                     'sampleFile', 'locationIndexScope']:
            output.pop(key, None)
        if 'documentInfo' in output:
            for key in ['documentID', 'useLastVersion', 'useAllSections']:
                output['documentInfo'].pop(key, None)
        if 'xmlParentInfoList' not in output:
            output['xmlParentInfoList'] = []
        return output

    # ------------------------------------------------------------------
    def list_archiving_policies(self) -> list:
        """Return list of archiving policy dicts from the repository."""
        local_headers = deepcopy(self.headers)
        local_headers['Accept'] = 'application/vnd.asg-mobius-admin-archiving-policies.v1+json'
        tm = str(int(time.time() * 1000))
        url = self.repo_admin_url + f"/archivingpolicies?limit=200&name=*&timestamp={tm}"
        response = requests.get(url, headers=local_headers, verify=False)
        response.raise_for_status()
        return response.json().get('items', [])

    # ------------------------------------------------------------------
    def delete_archiving_policy(self, ap_name: str) -> int:
        """Delete a single archiving policy by name. Returns HTTP status code."""
        try:
            url = self.repo_admin_url + f"/archivingpolicies/{ap_name}"
            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = '*/*'

            self.logger.info(f"delete_archiving_policy '{ap_name}' → DELETE {url}")
            response = requests.delete(url, headers=local_headers, verify=False)
            self.logger.info(f"Response: {response.status_code}")
            return response.status_code
        except Exception as e:
            self.logger.error(f"delete_archiving_policy error: {e}")
            return -1

    # ------------------------------------------------------------------
    def delete_all_archiving_policies(self) -> dict:
        """Delete all archiving policies. Returns {deleted, failed} counts."""
        items = self.list_archiving_policies()
        counts = {"deleted": 0, "failed": 0}
        for item in items:
            name = item.get('name', '')
            status = self.delete_archiving_policy(name)
            if 200 <= status < 300:
                counts["deleted"] += 1
            else:
                counts["failed"] += 1
        self.logger.info(f"delete_all_archiving_policies: {counts}")
        return counts

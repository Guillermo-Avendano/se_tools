import json
from pathlib import Path
import requests
import urllib3
import warnings
import os
from typing import Optional
from copy import deepcopy
from .content_config import ContentConfig
import time
import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


class ContentAdmContentClass:
    """Manages content class definitions in ContentEdge."""

    # ------------------------------------------------------------------
    class ContentClass:
        """Data model for a content class definition."""

        def __init__(self, id: str, name: str):
            self.id = id
            self.name = name
            self.compress = True
            self.encrypt = False
            self.deleteExpiredAuto = False
            self.type = 7
            self.description = ""
            self.details = ("Note that %REPORTID% gets truncated to 8 characters.\n"
                            "Use %REPORTID.10% to get the entire report ID.\n"
                            "Also, in general, avoid using relative paths.")
            self.ocrProcessing = True
            self.template = "/mnt/efs%PATHDELIM%%REPORTID%%PATHDELIM%%ARCHIVEDATE%%PATHDELIM%%ARCHIVETIME%%UNIQUE.2%.DAF"
            self.retentionType = "No retention"
            self.retentionBased = "Report version ID"
            self.enableMetadataIndexing = True
            self.enableContentIndexing = True
            self.redactionType = "No Redaction"
            self.securityTopic = ""
            self.characterType = "PC ANSI"
            self.daysForRetention = None
            self.daysForRetentionWithInitialFixedPeriod = None

        @classmethod
        def from_json(cls, json_data: dict) -> 'ContentAdmContentClass.ContentClass':
            inst = cls(id=json_data.get('id', ''), name=json_data.get('name', ''))
            for attr in ['compress', 'encrypt', 'deleteExpiredAuto', 'type', 'description',
                         'details', 'ocrProcessing', 'template', 'retentionType',
                         'retentionBased', 'enableMetadataIndexing', 'enableContentIndexing',
                         'redactionType', 'securityTopic', 'characterType',
                         'daysForRetention', 'daysForRetentionWithInitialFixedPeriod']:
                if attr in json_data:
                    setattr(inst, attr, json_data[attr])
            return inst

        def setEncrypt(self, encrypt: bool) -> None:
            self.encrypt = encrypt

        def to_dict(self):
            return {
                "compress": self.compress, "encrypt": self.encrypt,
                "deleteExpiredAuto": self.deleteExpiredAuto, "type": self.type,
                "description": self.description, "details": self.details,
                "ocrProcessing": self.ocrProcessing, "template": self.template,
                "retentionType": self.retentionType, "retentionBased": self.retentionBased,
                "enableMetadataIndexing": self.enableMetadataIndexing,
                "enableContentIndexing": self.enableContentIndexing,
                "redactionType": self.redactionType, "securityTopic": self.securityTopic,
                "characterType": self.characterType, "id": self.id, "name": self.name,
                "daysForRetention": self.daysForRetention,
                "daysForRetentionWithInitialFixedPeriod": self.daysForRetentionWithInitialFixedPeriod,
            }

    # ------------------------------------------------------------------
    def __init__(self, content_config):
        if not isinstance(content_config, ContentConfig):
            raise TypeError("ContentConfig class object expected")
        self.repo_admin_url = content_config.repo_admin_url
        self.logger = content_config.logger
        self.headers = deepcopy(content_config.headers)

    # ------------------------------------------------------------------
    def extract_content_classes(self, json_data, output_dir) -> Optional[str]:
        """Extract content class objects from API response and save to file."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"content_class_{timestamp}.json")

        if not isinstance(json_data, dict) or 'items' not in json_data:
            raise ValueError("Invalid JSON data: 'items' key not found")

        result = []
        for item in json_data['items']:
            result.append({
                'id': item.get('id', ''),
                'name': item.get('name', ''),
                'details': item.get('details', ''),
                'policyName': item.get('policyName', ''),
                'topicId': item.get('topicId', ''),
                'compress': item.get('compress', False),
                'encrypt': item.get('encrypt', False),
                'template': item.get('template', ''),
                'retentionType': item.get('retentionType', ''),
                'daysForRetention': item.get('daysForRetention', 0),
                'daysForRetentionWithInitialFixedPeriod': item.get('daysForRetentionWithInitialFixedPeriod', 0),
                'intermediateRetentionDays': item.get('intermediateRetentionDays', 0),
                'numberOfRecentVersions': item.get('numberOfRecentVersions', 0),
                'retentionBased': item.get('retentionBased', ''),
                'deleteExpiredAuto': item.get('deleteExpiredAuto', False),
                'enableYearEndRounding': item.get('enableYearEndRounding', False),
                'allowArchiveProcessing': item.get('allowArchiveProcessing', False),
            })

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        return output_path

    # ------------------------------------------------------------------
    def verify_content_class(self, cc_id: str) -> bool:
        """Check whether a content class with the given ID exists."""
        try:
            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = ('application/vnd.asg-mobius-admin-reports.v3+json,'
                                       'application/vnd.asg-mobius-admin-reports.v2+json,'
                                       'application/vnd.asg-mobius-admin-reports.v1+json')
            tm = str(int(time.time() * 1000))
            url = self.repo_admin_url + f"/reports?limit=5&&reportid={cc_id}&timestamp={tm}"

            self.logger.debug(f"verify_content_class → GET {url}")
            response = requests.get(url, headers=local_headers, verify=False)
            response.raise_for_status()
            for item in response.json().get("items", []):
                if item.get("id") == cc_id:
                    return True
            return False
        except (requests.HTTPError, json.JSONDecodeError) as e:
            self.logger.error(f"verify_content_class error: {e}")
            return False

    # ------------------------------------------------------------------
    def create_content_class(self, cc_id: str, cc_name: str) -> int:
        """Create a new content class. Returns HTTP status code.
        Returns 409 if it already exists."""
        try:
            if self.verify_content_class(cc_id):
                self.logger.warning(f"Content class '{cc_id}' already exists — skipped.")
                return 409

            cc_def = self.ContentClass(id=cc_id, name=cc_name)
            cc_def.setEncrypt(True)

            url = self.repo_admin_url + "/reports?sourcereportidtoclone=AC001"
            local_headers = deepcopy(self.headers)
            local_headers['Content-Type'] = 'application/vnd.asg-mobius-admin-report.v1+json'
            local_headers['accept'] = 'application/vnd.asg-mobius-admin-report.v1+json'

            self.logger.info(f"create_content_class '{cc_id}' → POST {url}")
            response = requests.post(url, headers=local_headers, json=cc_def.to_dict(), verify=False)
            self.logger.info(f"Response: {response.status_code}")
            return response.status_code

        except Exception as e:
            self.logger.error(f"create_content_class error: {e}")
            return -1

    # ------------------------------------------------------------------
    def export_content_classes(self, cc_id_filter: str, output_dir: str) -> Optional[str]:
        """Export content classes matching filter to a JSON file."""
        try:
            if not os.path.exists(output_dir):
                raise FileNotFoundError(f"Output directory '{output_dir}' does not exist")

            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = ('application/vnd.asg-mobius-admin-reports.v3+json,'
                                       'application/vnd.asg-mobius-admin-reports.v2+json,'
                                       'application/vnd.asg-mobius-admin-reports.v1+json')
            tm = str(int(time.time() * 1000))
            url = self.repo_admin_url + f"/reports?limit=200&&reportid={cc_id_filter}*&timestamp={tm}"

            self.logger.info(f"export_content_classes '{cc_id_filter}' → GET {url}")
            response = requests.get(url, headers=local_headers, verify=False)
            response.raise_for_status()

            saved_file = self.extract_content_classes(response.json(), output_dir)
            self.logger.info(f"Content classes saved to: {saved_file}")
            return saved_file

        except (requests.HTTPError, json.JSONDecodeError, FileNotFoundError, ValueError) as e:
            self.logger.error(f"export_content_classes error: {e}")
            return None

    # ------------------------------------------------------------------
    def import_content_class(self, cc_json: dict) -> int:
        """Import a single content class from a dict.
        Returns 409 (skipped) if it already exists."""
        try:
            cc_def = self.ContentClass.from_json(cc_json)
            if self.verify_content_class(cc_def.id):
                self.logger.warning(f"Content class '{cc_def.id}' already exists — skipped.")
                return 409

            cc_def.setEncrypt(True)
            url = self.repo_admin_url + "/reports?sourcereportidtoclone=AC001"
            local_headers = deepcopy(self.headers)
            local_headers['Content-Type'] = 'application/vnd.asg-mobius-admin-report.v1+json'
            local_headers['accept'] = 'application/vnd.asg-mobius-admin-report.v1+json'

            self.logger.info(f"import_content_class '{cc_def.id}' → POST {url}")
            response = requests.post(url, headers=local_headers, json=cc_def.to_dict(), verify=False)
            self.logger.info(f"Response: {response.status_code}")
            return response.status_code

        except Exception as e:
            self.logger.error(f"import_content_class error: {e}")
            return -1

    # ------------------------------------------------------------------
    def import_content_classes(self, file_path: str) -> dict:
        """Import content classes from a JSON array file.
        Returns dict with counts: {created, skipped, failed}."""
        if not Path(file_path).exists():
            raise FileNotFoundError(f"File '{file_path}' does not exist")

        with open(file_path, 'r', encoding='utf-8') as f:
            json_array = json.load(f)

        if not isinstance(json_array, list):
            raise ValueError("File does not contain a JSON array")

        counts = {"created": 0, "skipped": 0, "failed": 0}
        for item in json_array:
            status = self.import_content_class(item)
            if status == 409:
                counts["skipped"] += 1
            elif status and 200 <= status < 300:
                counts["created"] += 1
            else:
                counts["failed"] += 1
        self.logger.info(f"import_content_classes: {counts}")
        return counts

    # ------------------------------------------------------------------
    def list_content_classes(self) -> list:
        """Return list of content class dicts with 'id' and 'name' keys."""
        local_headers = deepcopy(self.headers)
        local_headers['Accept'] = ('application/vnd.asg-mobius-admin-reports.v3+json,'
                                   'application/vnd.asg-mobius-admin-reports.v2+json,'
                                   'application/vnd.asg-mobius-admin-reports.v1+json')
        tm = str(int(time.time() * 1000))
        url = self.repo_admin_url + f"/reports?limit=200&reportid=*&timestamp={tm}"
        response = requests.get(url, headers=local_headers, verify=False)
        response.raise_for_status()
        return response.json().get('items', [])

    # ------------------------------------------------------------------
    def delete_content_class(self, cc_id: str) -> int:
        """Delete a single content class by ID. Returns HTTP status code."""
        try:
            url = self.repo_admin_url + f"/reports/{cc_id}"
            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = 'application/vnd.asg-mobius-admin-report.v1+json'

            self.logger.info(f"delete_content_class '{cc_id}' → DELETE {url}")
            response = requests.delete(url, headers=local_headers, verify=False)
            self.logger.info(f"Response: {response.status_code}")
            return response.status_code
        except Exception as e:
            self.logger.error(f"delete_content_class error: {e}")
            return -1

    # ------------------------------------------------------------------
    def delete_all_content_classes(self) -> dict:
        """Delete all content classes. Returns {deleted, failed} counts."""
        items = self.list_content_classes()
        counts = {"deleted": 0, "failed": 0}
        for item in items:
            cc_id = item.get('id', '')
            status = self.delete_content_class(cc_id)
            if 200 <= status < 300:
                counts["deleted"] += 1
            else:
                counts["failed"] += 1
        self.logger.info(f"delete_all_content_classes: {counts}")
        return counts

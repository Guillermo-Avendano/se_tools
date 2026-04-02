import json
from pathlib import Path
import requests
import urllib3
import warnings
import os
from typing import List, Dict, Any, Optional
from copy import deepcopy
from .content_config import ContentConfig
import time
import datetime
from .util import validate_id

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


class Topic:
    """Represents an individual index (topic) in ContentEdge."""

    def __init__(self, id: str, name: str, dataType: str = "Character",
                 maxLength: str = "30", details: Optional[str] = None,
                 topicVersionDisplay: str = "All", allowAccess: bool = True,
                 category: str = "Document metadata", enableIndex: bool = True,
                 format: Optional[str] = None):
        if dataType not in ["Character", "Date", "Number"]:
            raise ValueError("dataType must be one of 'Character', 'Date', or 'Number'.")
        if dataType == "Character" and maxLength not in ["30", "255"]:
            raise ValueError("maxLength must be one of '30', or '255'.")
        if not validate_id(id):
            raise ValueError(f"Invalid ID: {id}. ID must be alphanumeric and can include underscores.")
        if len(id) > 50:
            raise ValueError(f"ID length must be less than 50. Current length: {len(id)}")

        self.id = id
        self.name = name
        self.details = details if details is not None else name
        self.dataType = dataType
        self.maxLength = maxLength
        self.topicVersionDisplay = topicVersionDisplay
        self.allowAccess = allowAccess
        self.category = category
        self.enableIndex = enableIndex
        self.format = format

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Topic':
        """Create a Topic instance from a dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            dataType=data.get("dataType", "Character"),
            maxLength=data.get("maxLength", "30"),
            details=data.get("details", None),
            topicVersionDisplay=data.get("topicVersionDisplay", "All"),
            allowAccess=data.get("allowAccess", True),
            category=data.get("category", "Document metadata"),
            enableIndex=data.get("enableIndex", True),
            format=data.get("format", None),
        )

    @classmethod
    def from_json(cls, json_str: str) -> 'Topic':
        """Create a Topic instance from a JSON string."""
        data = json.loads(json_str)
        if not isinstance(data, dict):
            raise ValueError("JSON must represent a dictionary")
        return cls.from_dict(data)

    def to_dict(self):
        d = {
            "id": self.id,
            "name": self.name,
            "topicVersionDisplay": self.topicVersionDisplay,
            "allowAccess": self.allowAccess,
            "dataType": self.dataType,
            "category": self.category,
        }
        if self.dataType == "Character":
            d["maxLength"] = self.maxLength
        if self.dataType == "Date" and self.format:
            d["format"] = self.format
        return d


class ContentAdmIndex:
    """Manages individual index (topic) definitions in ContentEdge."""

    def __init__(self, content_config):
        if not isinstance(content_config, ContentConfig):
            raise TypeError("ContentConfig class object expected")
        self.repo_admin_url = content_config.repo_admin_url
        self.logger = content_config.logger
        self.headers = deepcopy(content_config.headers)
        self.client_id = getattr(content_config, 'client_id', '')

    # ------------------------------------------------------------------
    def extract_indexes(self, json_data, output_dir) -> Optional[str]:
        """Extract index objects from API JSON response and save to file."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"indexes_{timestamp}.json")

        if not isinstance(json_data, dict) or 'items' not in json_data:
            raise ValueError("Invalid JSON data: 'items' key not found")

        result = []
        for item in json_data['items']:
            entry = {
                'id': item.get('id', ''),
                'name': item.get('name', ''),
                'details': item.get('details', ''),
                'topicVersionDisplay': item.get('topicVersionDisplay', 'All'),
                'allowAccess': item.get('allowAccess', True),
                'dataType': item.get('dataType', 'Character'),
                'category': item.get('category', 'Document metadata'),
            }
            if item.get('dataType', 'Character') == 'Character':
                entry['maxLength'] = item.get('maxLength', '30')
            if item.get('dataType') == 'Date' and item.get('format'):
                entry['format'] = item['format']
            result.append(entry)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        return output_path

    # ------------------------------------------------------------------
    def verify_index(self, index_id: str) -> bool:
        """Check whether an index with the given ID already exists."""
        try:
            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = 'application/vnd.asg-mobius-admin-topics.v1+json'
            tm = str(int(time.time() * 1000))
            url = self.repo_admin_url + f"/topics?limit=5&&topicid={index_id}&timestamp={tm}"

            self.logger.debug(f"verify_index → GET {url}")
            response = requests.get(url, headers=local_headers, verify=False)
            response.raise_for_status()
            for item in response.json().get("items", []):
                if item.get("id") == index_id:
                    return True
            return False
        except (requests.HTTPError, json.JSONDecodeError) as e:
            self.logger.error(f"verify_index error: {e}")
            return False

    # ------------------------------------------------------------------
    def create_index(self, index: Topic) -> int:
        """Create a single index in the repository. Returns HTTP status code."""
        local_headers = deepcopy(self.headers)
        local_headers['Content-Type'] = 'application/vnd.asg-mobius-admin-topic.v1+json'
        local_headers['Accept'] = 'application/vnd.asg-mobius-admin-topic.v1+json'
        local_headers['x-asg-coordinates'] = '0,0'
        local_headers['x-luminist-version'] = '8.0.0'
        local_headers['x-requester-app-name'] = 'MV'
        local_headers['x-requesterid'] = 'ASGClient'
        if self.client_id:
            local_headers['client-id'] = self.client_id

        url = self.repo_admin_url + "/topics"
        self.logger.info(f"create_index '{index.id}' → POST {url}")
        self.logger.debug(f"Payload: {json.dumps(index.to_dict(), indent=2)}")

        response = requests.post(url, json=index.to_dict(), headers=local_headers, verify=False)

        # If 401 with client-id, retry without it (token may be expired)
        if response.status_code == 401 and 'client-id' in local_headers:
            self.logger.warning("create_index: 401 with client-id, retrying without it")
            del local_headers['client-id']
            response = requests.post(url, json=index.to_dict(), headers=local_headers, verify=False)

        response.raise_for_status()

        data = response.json()
        if 'id' in data and data['id'] == index.id:
            self.logger.info(f"Index '{index.id}' created successfully")
            return response.status_code
        self.logger.error(f"Failed to create index '{index.id}': {data}")
        return 409

    # ------------------------------------------------------------------
    def export_indexes(self, index_id_filter: str, output_dir: str) -> Optional[str]:
        """Export indexes matching filter to a JSON file. Returns the file path."""
        try:
            if not os.path.exists(output_dir):
                raise FileNotFoundError(f"Output directory '{output_dir}' does not exist")

            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = 'application/vnd.asg-mobius-admin-topics.v1+json'
            tm = str(int(time.time() * 1000))
            url = self.repo_admin_url + f"/topics?limit=200&&topicid={index_id_filter}*&timestamp={tm}"

            self.logger.info(f"export_indexes '{index_id_filter}' → GET {url}")
            response = requests.get(url, headers=local_headers, verify=False)
            response.raise_for_status()

            saved_file = self.extract_indexes(response.json(), output_dir)
            self.logger.info(f"Indexes saved to: {saved_file}")
            return saved_file

        except (requests.HTTPError, json.JSONDecodeError, FileNotFoundError, ValueError) as e:
            self.logger.error(f"export_indexes error: {e}")
            return None

    # ------------------------------------------------------------------
    def import_index(self, index_json) -> int:
        """Import a single index from a dict or JSON string. Returns HTTP status code.
        Returns 409 (skipped) if the index already exists."""
        try:
            if isinstance(index_json, str):
                index = Topic.from_json(index_json)
            elif isinstance(index_json, dict):
                index = Topic.from_dict(index_json)
            else:
                raise ValueError("index_json must be a string or dictionary")

            if self.verify_index(index.id):
                self.logger.warning(f"Index '{index.id}' already exists — skipped.")
                return 409

            local_headers = deepcopy(self.headers)
            local_headers['Content-Type'] = 'application/vnd.asg-mobius-admin-topic.v1+json'
            local_headers['Accept'] = 'application/vnd.asg-mobius-admin-topic.v1+json'

            url = self.repo_admin_url + "/topics"
            self.logger.info(f"import_index '{index.id}' → POST {url}")
            response = requests.post(url, headers=local_headers, json=index.to_dict(), verify=False)

            # If 401 with client-id, retry without it (token may be expired)
            if response.status_code == 401 and 'client-id' in local_headers:
                self.logger.warning("import_index: 401 with client-id, retrying without it")
                del local_headers['client-id']
                response = requests.post(url, headers=local_headers, json=index.to_dict(), verify=False)

            if response.status_code != 201:
                self.logger.error(f"Failed to import index '{index.id}': {response.text}")
                return response.status_code

            data = response.json()
            table_name = data.get('tableName', '')
            if table_name:
                self.logger.info(f"Index '{index.id}' created — table: {table_name}")
            else:
                self.logger.warning(f"Index '{index.id}' returned 201 but no tableName in response")
            return response.status_code

        except Exception as e:
            self.logger.error(f"import_index error: {e}")
            return -1

    # ------------------------------------------------------------------
    def import_indexes(self, file_path: str) -> dict:
        """Import indexes from a JSON array file.
        Returns dict with counts: {created, skipped, failed}."""
        if not Path(file_path).exists():
            raise FileNotFoundError(f"File '{file_path}' does not exist")

        with open(file_path, 'r', encoding='utf-8') as f:
            json_array = json.load(f)

        if not isinstance(json_array, list):
            raise ValueError("File does not contain a JSON array")

        counts = {"created": 0, "skipped": 0, "failed": 0}
        for item in json_array:
            status = self.import_index(item)
            if status == 409:
                counts["skipped"] += 1
            elif status and 200 <= status < 300:
                counts["created"] += 1
            else:
                counts["failed"] += 1
        self.logger.info(f"import_indexes: {counts}")
        return counts

    # ------------------------------------------------------------------
    def list_indexes(self) -> list:
        """Return list of index dicts from the repository."""
        local_headers = deepcopy(self.headers)
        local_headers['Accept'] = 'application/vnd.asg-mobius-admin-topics.v1+json'
        tm = str(int(time.time() * 1000))
        url = self.repo_admin_url + f"/topics?limit=200&topicid=*&timestamp={tm}"
        response = requests.get(url, headers=local_headers, verify=False)
        response.raise_for_status()
        return response.json().get('items', [])

    # ------------------------------------------------------------------
    def delete_index(self, index_id: str) -> int:
        """Delete a single index by ID. Returns HTTP status code."""
        try:
            url = self.repo_admin_url + f"/topics/{index_id}"
            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = 'application/vnd.asg-mobius-admin-topic.v1+json'

            self.logger.info(f"delete_index '{index_id}' → DELETE {url}")
            response = requests.delete(url, headers=local_headers, verify=False)
            self.logger.info(f"Response: {response.status_code}")
            return response.status_code
        except Exception as e:
            self.logger.error(f"delete_index error: {e}")
            return -1

    # ------------------------------------------------------------------
    def delete_all_indexes(self) -> dict:
        """Delete all indexes. Returns {deleted, failed} counts."""
        items = self.list_indexes()
        counts = {"deleted": 0, "failed": 0}
        for item in items:
            idx_id = item.get('id', '')
            status = self.delete_index(idx_id)
            if 200 <= status < 300:
                counts["deleted"] += 1
            else:
                counts["failed"] += 1
        self.logger.info(f"delete_all_indexes: {counts}")
        return counts

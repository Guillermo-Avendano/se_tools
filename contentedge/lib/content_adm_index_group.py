import json
from pathlib import Path
import requests
import urllib3
import warnings
import os
from typing import List, Dict, Any, Optional
from copy import deepcopy
from .content_config import ContentConfig
from .content_adm_index import Topic
from .util import validate_id
import time
import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


class IndexGroup:
    """Represents an index group (topic group) in ContentEdge."""

    def __init__(self, id: str, name: str):
        if not validate_id(id):
            raise ValueError(f"Invalid ID: {id}. ID must be alphanumeric and can include underscores.")
        if len(id) > 50:
            raise ValueError(f"ID length must be less than 50. Current length: {len(id)}")
        self.id = id
        self.name = name
        self.scope = "Page"
        self.topics: List[Topic] = []

    def addTopic(self, topic: Topic) -> None:
        self.topics.append(topic)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IndexGroup':
        ig = cls(id=data.get("id", ""), name=data.get("name", ""))
        ig.scope = data.get("scope", "Page")
        for t in data.get("topics", []):
            ig.addTopic(Topic.from_dict(t))
        return ig

    @classmethod
    def from_json(cls, json_str: str) -> 'IndexGroup':
        data = json.loads(json_str)
        return cls.from_dict(data)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.scope,
            "topics": [t.to_dict() for t in self.topics],
        }


class ContentAdmIndexGroup:
    """Manages index group (topic group) definitions in ContentEdge."""

    def __init__(self, content_config):
        if not isinstance(content_config, ContentConfig):
            raise TypeError("ContentConfig class object expected")
        self.repo_admin_url = content_config.repo_admin_url
        self.logger = content_config.logger
        self.headers = deepcopy(content_config.headers)
        self.client_id = getattr(content_config, 'client_id', '')

    # ------------------------------------------------------------------
    def extract_index_groups(self, json_data, output_dir) -> Optional[str]:
        """Extract index group objects from API response and save to file."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"index_groups_{timestamp}.json")

        if not isinstance(json_data, dict) or 'items' not in json_data:
            raise ValueError("Invalid JSON data: 'items' key not found")

        result = []
        for item in json_data['items']:
            result.append({
                'id': item.get('id', ''),
                'name': item.get('name', ''),
                'scope': item.get('scope', ''),
                'topics': item.get('topics', []),
            })

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        return output_path

    # ------------------------------------------------------------------
    def verify_index_group(self, ig_id: str) -> bool:
        """Check whether an index group with the given ID exists."""
        try:
            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = 'application/vnd.asg-mobius-admin-topic-groups.v1+json'
            tm = str(int(time.time() * 1000))
            url = self.repo_admin_url + f"/topicgroups?limit=5&&groupid={ig_id}&timestamp={tm}"

            self.logger.debug(f"verify_index_group → GET {url}")
            response = requests.get(url, headers=local_headers, verify=False)
            response.raise_for_status()
            for item in response.json().get("items", []):
                if item.get("id") == ig_id:
                    return True
            return False
        except (requests.HTTPError, json.JSONDecodeError) as e:
            self.logger.error(f"verify_index_group error: {e}")
            return False

    # ------------------------------------------------------------------
    def create_index_group(self, index_group: IndexGroup) -> int:
        """Create a single index group. Returns HTTP status code."""
        try:
            if self.verify_index_group(index_group.id):
                self.logger.warning(f"Index Group '{index_group.id}' already exists — skipped.")
                return 409

            url = self.repo_admin_url + "/topicgroups"
            local_headers = deepcopy(self.headers)
            local_headers['Content-Type'] = 'application/vnd.asg-mobius-admin-topic-group.v1+json'
            local_headers['Accept'] = 'application/json, text/plain, */*'
            local_headers['x-asg-coordinates'] = '0,0'
            local_headers['x-luminist-version'] = '8.0.0'
            local_headers['x-requester-app-name'] = 'MV'
            local_headers['x-requesterid'] = 'ASGClient'
            if self.client_id:
                local_headers['client-id'] = self.client_id

            self.logger.info(f"create_index_group '{index_group.id}' → POST {url}")
            self.logger.debug(f"Payload: {json.dumps(index_group.to_dict(), indent=2)}")

            response = requests.post(url, json=index_group.to_dict(), headers=local_headers, verify=False)

            # If 401 with client-id, retry without it (token may be expired)
            if response.status_code == 401 and 'client-id' in local_headers:
                self.logger.warning("create_index_group: 401 with client-id, retrying without it")
                del local_headers['client-id']
                response = requests.post(url, json=index_group.to_dict(), headers=local_headers, verify=False)

            response.raise_for_status()

            data = response.json()
            if 'tableName' in data and data['tableName'].strip():
                self.logger.info(f"Index Group '{index_group.id}' created successfully")
                return response.status_code
            self.logger.error(f"Failed to create Index Group '{index_group.id}': {data}")
            return 409

        except Exception as e:
            self.logger.error(f"create_index_group error: {e}")
            return -1

    # ------------------------------------------------------------------
    def export_index_groups(self, ig_id_filter: str, output_dir: str) -> Optional[str]:
        """Export index groups matching filter to a JSON file."""
        try:
            if not os.path.exists(output_dir):
                raise FileNotFoundError(f"Output directory '{output_dir}' does not exist")

            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = 'application/vnd.asg-mobius-admin-topic-groups.v1+json'
            tm = str(int(time.time() * 1000))
            url = self.repo_admin_url + f"/topicgroups?limit=200&&groupid={ig_id_filter}*&timestamp={tm}"

            self.logger.info(f"export_index_groups '{ig_id_filter}' → GET {url}")
            response = requests.get(url, headers=local_headers, verify=False)
            response.raise_for_status()

            saved_file = self.extract_index_groups(response.json(), output_dir)
            self.logger.info(f"Index groups saved to: {saved_file}")
            return saved_file

        except (requests.HTTPError, json.JSONDecodeError, FileNotFoundError, ValueError) as e:
            self.logger.error(f"export_index_groups error: {e}")
            return None

    # ------------------------------------------------------------------
    def import_index_group(self, index_group_json) -> int:
        """Import a single index group from dict or JSON string.
        Returns 409 (skipped) if the index group already exists."""
        try:
            if isinstance(index_group_json, str):
                ig = IndexGroup.from_json(index_group_json)
            elif isinstance(index_group_json, dict):
                ig = IndexGroup.from_dict(index_group_json)
            else:
                raise ValueError("index_group_json must be a string or dictionary")

            if self.verify_index_group(ig.id):
                self.logger.warning(f"Index Group '{ig.id}' already exists — skipped.")
                return 409

            url = self.repo_admin_url + "/topicgroups"
            local_headers = deepcopy(self.headers)
            local_headers['Content-Type'] = 'application/vnd.asg-mobius-admin-topic-group.v1+json'
            local_headers['Accept'] = 'application/json, text/plain, */*'
            local_headers['x-asg-coordinates'] = '0,0'
            local_headers['x-luminist-version'] = '8.0.0'
            local_headers['x-requester-app-name'] = 'MV'
            local_headers['x-requesterid'] = 'ASGClient'
            if self.client_id:
                local_headers['client-id'] = self.client_id

            payload = ig.to_dict()

            self.logger.info(f"import_index_group '{ig.id}' → POST {url}")
            response = requests.post(url, headers=local_headers, json=payload, verify=False)

            # If 401 with client-id, retry without it (token may be expired)
            if response.status_code == 401 and 'client-id' in local_headers:
                self.logger.warning("import_index_group: 401 with client-id, retrying without it")
                del local_headers['client-id']
                response = requests.post(url, headers=local_headers, json=payload, verify=False)

            # Mobius bug: 500 when creating groups with Number topics.
            # Cannot create partial group because indexes are immutable after creation.
            if response.status_code == 500:
                num_topics = [t['id'] for t in payload.get('topics', []) if t.get('dataType') == 'Number']
                if num_topics:
                    self.logger.error(
                        f"import_index_group '{ig.id}': server 500 — likely caused by Number-type "
                        f"topics {num_topics}. This group must be created manually via Mobius UI."
                    )

            if response.status_code != 201:
                self.logger.error(f"Failed to import index group '{ig.id}': {response.text}")
                return response.status_code

            data = response.json()
            table_name = data.get('tableName', '')
            if table_name:
                self.logger.info(f"Index Group '{ig.id}' created — table: {table_name}")
            else:
                self.logger.warning(f"Index Group '{ig.id}' returned 201 but no tableName in response")
            return response.status_code

        except Exception as e:
            self.logger.error(f"import_index_group error: {e}")
            return -1

    # ------------------------------------------------------------------
    def import_index_groups(self, file_path: str) -> dict:
        """Import index groups from a JSON array file.
        Returns dict with counts: {created, skipped, failed}."""
        if not Path(file_path).exists():
            raise FileNotFoundError(f"File '{file_path}' does not exist")

        with open(file_path, 'r', encoding='utf-8') as f:
            json_array = json.load(f)

        if not isinstance(json_array, list):
            raise ValueError("File does not contain a JSON array")

        counts = {"created": 0, "skipped": 0, "failed": 0, "manual_required": []}
        for item in json_array:
            status = self.import_index_group(item)
            if status == 409:
                counts["skipped"] += 1
            elif status and 200 <= status < 300:
                counts["created"] += 1
            else:
                counts["failed"] += 1
                # Flag groups with Number topics that need manual creation
                if status == 500:
                    num_topics = [t.get('id') for t in item.get('topics', []) if t.get('dataType') == 'Number']
                    if num_topics:
                        counts["manual_required"].append({
                            "id": item.get('id'),
                            "reason": f"Number-type topics {num_topics} cause server 500. Create manually via Mobius UI."
                        })
        if not counts["manual_required"]:
            del counts["manual_required"]
        self.logger.info(f"import_index_groups: {counts}")
        return counts

    # ------------------------------------------------------------------
    def list_index_groups(self) -> list:
        """Return list of index group dicts from the repository."""
        local_headers = deepcopy(self.headers)
        local_headers['Accept'] = 'application/vnd.asg-mobius-admin-topic-groups.v1+json'
        tm = str(int(time.time() * 1000))
        url = self.repo_admin_url + f"/topicgroups?limit=200&groupid=*&timestamp={tm}"
        response = requests.get(url, headers=local_headers, verify=False)
        response.raise_for_status()
        return response.json().get('items', [])

    # ------------------------------------------------------------------
    def delete_index_group(self, ig_id: str) -> int:
        """Delete a single index group by ID. Returns HTTP status code."""
        try:
            url = self.repo_admin_url + f"/topicgroups/{ig_id}"
            local_headers = deepcopy(self.headers)
            local_headers['Accept'] = 'application/json, text/plain, */*'

            self.logger.info(f"delete_index_group '{ig_id}' → DELETE {url}")
            response = requests.delete(url, headers=local_headers, verify=False)
            self.logger.info(f"Response: {response.status_code}")
            return response.status_code
        except Exception as e:
            self.logger.error(f"delete_index_group error: {e}")
            return -1

    # ------------------------------------------------------------------
    def delete_all_index_groups(self) -> dict:
        """Delete all index groups. Returns {deleted, failed} counts."""
        items = self.list_index_groups()
        counts = {"deleted": 0, "failed": 0}
        for item in items:
            ig_id = item.get('id', '')
            status = self.delete_index_group(ig_id)
            if 200 <= status < 300:
                counts["deleted"] += 1
            else:
                counts["failed"] += 1
        self.logger.info(f"delete_all_index_groups: {counts}")
        return counts

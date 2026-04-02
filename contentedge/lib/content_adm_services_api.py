"""
ContentAdmServicesApi — Administration facade for ContentEdge.

* Exports always read from the **SOURCE** repository.
* Imports always write to the **TARGET** repository.
  The TARGET connection is validated lazily — only when an import method
  is called for the first time.
"""

import os
import json
import glob
import logging
import urllib3
import warnings
import yaml as _yaml

from datetime import datetime
from typing import Optional

from .content_config import ContentConfig
from .content_adm_archive_policy import ContentAdmArchivePolicy
from .content_adm_content_class import ContentAdmContentClass
from .content_adm_index import ContentAdmIndex, Topic
from .content_adm_index_group import ContentAdmIndexGroup, IndexGroup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

logger = logging.getLogger(__name__)


# ── Helper: patch YAML from env vars ─────────────────────────────────────

def _patch_yaml_from_env(yaml_path: str, prefix: str) -> None:
    """Overwrite YAML connection params from CE_SOURCE_* or CE_TARGET_* env vars."""
    env_map = {
        "REPO_URL": "repo_url",
        "REPO_NAME": "repo_name",
        "REPO_USER": "repo_user",
        "REPO_PASS": "repo_pass",
        "REPO_SERVER_USER": "repo_server_user",
        "REPO_SERVER_PASS": "repo_server_pass",
    }
    updates = {}
    for env_suffix, yaml_key in env_map.items():
        val = os.environ.get(f"{prefix}{env_suffix}", "")
        if val:
            updates[yaml_key] = val

    if not updates:
        return

    with open(yaml_path, "r") as f:
        config = _yaml.safe_load(f) or {}
    repo = config.setdefault("repository", {})
    repo.update(updates)
    with open(yaml_path, "w") as f:
        _yaml.dump(config, f, sort_keys=False)
    logger.info(f"YAML patched ({prefix}): {list(updates.keys())}")


class ContentAdmServicesApi:
    """
    High-level facade for ContentEdge administration operations.

    - **source_config**: always initialised (for exports and all existing operations).
    - **target_config**: initialised lazily only when an import method is called.
    """

    def __init__(self, source_yaml: str, target_yaml: Optional[str] = None):
        """
        Args:
            source_yaml: Path to the SOURCE repository YAML config.
            target_yaml: Path to the TARGET repository YAML config (optional).
                         If not provided, imports will fail with a clear error.
        """
        # ── Source (always initialised) ──
        _patch_yaml_from_env(source_yaml, "CE_SOURCE_")
        self.source_config = ContentConfig(source_yaml)
        logger.info(f"SOURCE connected: {self.source_config.repo_name} @ {self.source_config.base_url}")

        # ── Target (deferred) ──
        self._target_yaml = target_yaml
        self._target_config: Optional[ContentConfig] = None

    # ------------------------------------------------------------------
    @property
    def target_config(self) -> ContentConfig:
        """Lazy initialisation of the TARGET config — only on first import call."""
        if self._target_config is not None:
            return self._target_config

        if not self._target_yaml:
            raise RuntimeError(
                "TARGET repository YAML not configured. "
                "Set CE_TARGET_REPO_URL in .env and pass target_yaml to ContentAdmServicesApi."
            )
        _patch_yaml_from_env(self._target_yaml, "CE_TARGET_")
        self._target_config = ContentConfig(self._target_yaml)
        logger.info(f"TARGET connected: {self._target_config.repo_name} @ {self._target_config.base_url}")
        return self._target_config

    # ==================================================================
    #  EXPORTS  — always from SOURCE
    # ==================================================================

    def export_content_classes(self, cc_id_filter: str, output_dir: str) -> Optional[str]:
        """Export content classes from SOURCE matching filter."""
        repo = ContentAdmContentClass(self.source_config)
        return repo.export_content_classes(cc_id_filter, output_dir)

    def export_index_groups(self, ig_id_filter: str, output_dir: str) -> Optional[str]:
        """Export index groups from SOURCE matching filter."""
        repo = ContentAdmIndexGroup(self.source_config)
        return repo.export_index_groups(ig_id_filter, output_dir)

    def export_indexes(self, index_id_filter: str, output_dir: str) -> Optional[str]:
        """Export individual indexes from SOURCE matching filter."""
        repo = ContentAdmIndex(self.source_config)
        return repo.export_indexes(index_id_filter, output_dir)

    def export_archiving_policies(self, ap_filter: str, output_dir: str) -> None:
        """Export archiving policies from SOURCE matching filter."""
        repo = ContentAdmArchivePolicy(self.source_config)
        repo.export_archiving_policies(ap_filter, output_dir)

    # ==================================================================
    #  IMPORTS  — always to TARGET  (lazy connection)
    # ==================================================================

    def import_content_classes(self, file_path: str) -> None:
        """Import content classes from JSON file into TARGET."""
        repo = ContentAdmContentClass(self.target_config)
        repo.import_content_classes(file_path)

    def import_index_groups(self, file_path: str) -> None:
        """Import index groups from JSON file into TARGET."""
        repo = ContentAdmIndexGroup(self.target_config)
        repo.import_index_groups(file_path)

    def import_indexes(self, file_path: str) -> None:
        """Import individual indexes from JSON file into TARGET."""
        repo = ContentAdmIndex(self.target_config)
        repo.import_indexes(file_path)

    def import_archiving_policy(self, policy_path: str, policy_name: str) -> int:
        """Import a single archiving policy into TARGET."""
        repo = ContentAdmArchivePolicy(self.target_config)
        return repo.import_archiving_policy(policy_path, policy_name)

    # ==================================================================
    #  CREATE  — on TARGET
    # ==================================================================

    def create_content_class(self, cc_id: str, cc_name: str) -> int:
        """Create a new content class on TARGET."""
        repo = ContentAdmContentClass(self.target_config)
        return repo.create_content_class(cc_id, cc_name)

    def create_index_group(self, index_group: IndexGroup) -> int:
        """Create a new index group on TARGET."""
        if not isinstance(index_group, IndexGroup):
            raise TypeError("IndexGroup class object expected")
        repo = ContentAdmIndexGroup(self.target_config)
        return repo.create_index_group(index_group)

    def create_index(self, index: Topic) -> int:
        """Create a new individual index on TARGET."""
        if not isinstance(index, Topic):
            raise TypeError("Topic class object expected")
        repo = ContentAdmIndex(self.target_config)
        return repo.create_index(index)

    # ==================================================================
    #  DELETE  — on TARGET
    # ==================================================================

    def delete_content_class(self, cc_id: str) -> int:
        """Delete a content class on TARGET."""
        repo = ContentAdmContentClass(self.target_config)
        return repo.delete_content_class(cc_id)

    def delete_all_content_classes(self) -> dict:
        """Delete all content classes on TARGET."""
        repo = ContentAdmContentClass(self.target_config)
        return repo.delete_all_content_classes()

    def delete_index(self, index_id: str) -> int:
        """Delete an index on TARGET."""
        repo = ContentAdmIndex(self.target_config)
        return repo.delete_index(index_id)

    def delete_all_indexes(self) -> dict:
        """Delete all indexes on TARGET."""
        repo = ContentAdmIndex(self.target_config)
        return repo.delete_all_indexes()

    def delete_index_group(self, ig_id: str) -> int:
        """Delete an index group on TARGET."""
        repo = ContentAdmIndexGroup(self.target_config)
        return repo.delete_index_group(ig_id)

    def delete_all_index_groups(self) -> dict:
        """Delete all index groups on TARGET."""
        repo = ContentAdmIndexGroup(self.target_config)
        return repo.delete_all_index_groups()

    def delete_archiving_policy(self, ap_name: str) -> int:
        """Delete an archiving policy on TARGET."""
        repo = ContentAdmArchivePolicy(self.target_config)
        return repo.delete_archiving_policy(ap_name)

    def delete_all_archiving_policies(self) -> dict:
        """Delete all archiving policies on TARGET."""
        repo = ContentAdmArchivePolicy(self.target_config)
        return repo.delete_all_archiving_policies()

    # ==================================================================
    #  LIST  — on TARGET
    # ==================================================================

    def list_target_content_classes(self) -> list:
        """List all content classes on TARGET."""
        repo = ContentAdmContentClass(self.target_config)
        return repo.list_content_classes()

    def list_target_indexes(self) -> list:
        """List all indexes on TARGET."""
        repo = ContentAdmIndex(self.target_config)
        return repo.list_indexes()

    def list_target_index_groups(self) -> list:
        """List all index groups on TARGET."""
        repo = ContentAdmIndexGroup(self.target_config)
        return repo.list_index_groups()

    def list_target_archiving_policies(self) -> list:
        """List all archiving policies on TARGET."""
        repo = ContentAdmArchivePolicy(self.target_config)
        return repo.list_archiving_policies()

    # ==================================================================
    #  EXPORT ALL  — SOURCE → directory
    # ==================================================================

    def export_all(self, base_dir: str = "workspace") -> str:
        """Export all admin objects from SOURCE to a timestamped directory.

        Creates: {base_dir}/export_{YYYYMMDD_HHMMSS}/
            content_classes/   — content_class_*.json
            indexes/           — indexes_*.json
            index_groups/      — index_groups_*.json
            archiving_policies/ — {name}.json (one per policy)
            manifest.json      — metadata about the export

        Returns the path to the export directory.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = os.path.join(base_dir, f"export_{ts}")

        cc_dir = os.path.join(export_dir, "content_classes")
        idx_dir = os.path.join(export_dir, "indexes")
        ig_dir = os.path.join(export_dir, "index_groups")
        ap_dir = os.path.join(export_dir, "archiving_policies")

        for d in [cc_dir, idx_dir, ig_dir, ap_dir]:
            os.makedirs(d, exist_ok=True)

        logger.info(f"Exporting SOURCE → {export_dir}")

        # Content classes
        cc_file = self.export_content_classes("*", cc_dir)
        cc_count = 0
        if cc_file:
            with open(cc_file) as f:
                cc_count = len(json.load(f))
        logger.info(f"  Content classes exported: {cc_count}")

        # Indexes
        idx_file = self.export_indexes("*", idx_dir)
        idx_count = 0
        if idx_file:
            with open(idx_file) as f:
                idx_count = len(json.load(f))
        logger.info(f"  Indexes exported: {idx_count}")

        # Index groups
        ig_file = self.export_index_groups("*", ig_dir)
        ig_count = 0
        if ig_file:
            with open(ig_file) as f:
                ig_count = len(json.load(f))
        logger.info(f"  Index groups exported: {ig_count}")

        # Archiving policies (one file per policy)
        self.export_archiving_policies("*", ap_dir)
        ap_files = glob.glob(os.path.join(ap_dir, "*.json"))
        ap_count = len(ap_files)
        logger.info(f"  Archiving policies exported: {ap_count}")

        # Manifest
        manifest = {
            "exported_at": ts,
            "source_url": self.source_config.base_url,
            "source_repo_id": self.source_config.repo_id,
            "content_classes": cc_count,
            "indexes": idx_count,
            "index_groups": ig_count,
            "archiving_policies": ap_count,
        }
        manifest_path = os.path.join(export_dir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"Export complete → {export_dir}")
        return export_dir

    # ==================================================================
    #  IMPORT ALL  — directory → TARGET
    # ==================================================================

    def import_all(self, export_dir: str) -> dict:
        """Import all admin objects from an export directory into TARGET.

        Reads files from the directory structure created by export_all().
        Import order: indexes → index_groups → content_classes → archiving_policies
        (indexes must exist before index groups reference them, etc.)

        Returns summary dict with counts per type.
        """
        if not os.path.isdir(export_dir):
            raise FileNotFoundError(f"Export directory not found: {export_dir}")

        manifest_path = os.path.join(export_dir, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            logger.info(f"Importing from export_{manifest.get('exported_at', '?')} "
                        f"(source: {manifest.get('source_url', '?')})")

        results = {}

        # 1. Indexes first (index groups reference them)
        idx_dir = os.path.join(export_dir, "indexes")
        idx_files = sorted(glob.glob(os.path.join(idx_dir, "indexes_*.json"))) if os.path.isdir(idx_dir) else []
        if idx_files:
            r = self.import_indexes(idx_files[-1])  # latest file
            results["indexes"] = r
            logger.info(f"  Indexes imported: {r}")
        else:
            results["indexes"] = {"created": 0, "skipped": 0, "failed": 0, "note": "no file found"}

        # 2. Index groups (reference indexes)
        ig_dir = os.path.join(export_dir, "index_groups")
        ig_files = sorted(glob.glob(os.path.join(ig_dir, "index_groups_*.json"))) if os.path.isdir(ig_dir) else []
        if ig_files:
            r = self.import_index_groups(ig_files[-1])
            results["index_groups"] = r
            logger.info(f"  Index groups imported: {r}")
        else:
            results["index_groups"] = {"created": 0, "skipped": 0, "failed": 0, "note": "no file found"}

        # 3. Content classes (may reference index groups)
        cc_dir = os.path.join(export_dir, "content_classes")
        cc_files = sorted(glob.glob(os.path.join(cc_dir, "content_class_*.json"))) if os.path.isdir(cc_dir) else []
        if cc_files:
            r = self.import_content_classes(cc_files[-1])
            results["content_classes"] = r
            logger.info(f"  Content classes imported: {r}")
        else:
            results["content_classes"] = {"created": 0, "skipped": 0, "failed": 0, "note": "no file found"}

        # 4. Archiving policies (may reference content classes)
        ap_dir = os.path.join(export_dir, "archiving_policies")
        ap_results = {"created": 0, "skipped": 0, "failed": 0}
        if os.path.isdir(ap_dir):
            ap_files = sorted(glob.glob(os.path.join(ap_dir, "*.json")))
            for ap_file in ap_files:
                ap_name = os.path.splitext(os.path.basename(ap_file))[0]
                status = self.import_archiving_policy(ap_file, ap_name)
                if 200 <= status < 300:
                    ap_results["created"] += 1
                elif status == 409:
                    ap_results["skipped"] += 1
                else:
                    ap_results["failed"] += 1
        results["archiving_policies"] = ap_results
        logger.info(f"  Archiving policies imported: {ap_results}")

        logger.info(f"Import complete from {export_dir}")
        return results

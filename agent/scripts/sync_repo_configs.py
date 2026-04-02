#!/usr/bin/env python3
"""
Sync environment variables with repository configuration files.

This script runs on agent startup and updates the YAML configuration files
if environment variables are different from the current YAML values.
"""

import os
import sys
import yaml
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def load_yaml_config(file_path: Path) -> dict:
    """Load YAML configuration file."""
    if not file_path.exists():
        print(f"Warning: {file_path} does not exist")
        return {}
    
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return {}

def save_yaml_config(file_path: Path, config: dict):
    """Save YAML configuration file."""
    try:
        with open(file_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, indent=2)
        print(f"Updated {file_path}")
    except Exception as e:
        print(f"Error saving {file_path}: {e}")

def sync_repository_config():
    """Sync environment variables with repository YAML files."""
    workspace_dir = project_root / "workspace"
    conf_dir = workspace_dir / "conf"
    
    # Ensure directories exist
    conf_dir.mkdir(parents=True, exist_ok=True)
    
    source_yaml_path = conf_dir / "repository_source.yaml"
    target_yaml_path = conf_dir / "repository_target.yaml"
    
    # Load current YAML configs
    source_config = load_yaml_config(source_yaml_path)
    target_config = load_yaml_config(target_yaml_path)
    
    # Get environment variables
    env_vars = {
        'source': {
            'repo_url': os.getenv('CE_SOURCE_REPO_URL', ''),
            'repo_name': os.getenv('CE_SOURCE_REPO_NAME', ''),
            'repo_user': os.getenv('CE_SOURCE_REPO_USER', ''),
            'repo_pass': os.getenv('CE_SOURCE_REPO_PASS', ''),
            'repo_server_user': os.getenv('CE_SOURCE_REPO_SERVER_USER', ''),
            'repo_server_pass': os.getenv('CE_SOURCE_REPO_SERVER_PASS', ''),
        },
        'target': {
            'repo_url': os.getenv('CE_TARGET_REPO_URL', ''),
            'repo_name': os.getenv('CE_TARGET_REPO_NAME', ''),
            'repo_user': os.getenv('CE_TARGET_REPO_USER', ''),
            'repo_pass': os.getenv('CE_TARGET_REPO_PASS', ''),
            'repo_server_user': os.getenv('CE_TARGET_REPO_SERVER_USER', ''),
            'repo_server_pass': os.getenv('CE_TARGET_REPO_SERVER_PASS', ''),
        }
    }
    
    # Update source config if different
    source_repo = source_config.get('repository', {})
    source_updated = False
    
    for key, env_value in env_vars['source'].items():
        if env_value and source_repo.get(key) != env_value:
            source_repo[key] = env_value
            source_updated = True
            print(f"Source repo {key}: {source_repo.get(key)} -> {env_value}")
    
    if source_updated:
        source_config['repository'] = source_repo
        save_yaml_config(source_yaml_path, source_config)
    
    # Update target config if different
    target_repo = target_config.get('repository', {})
    target_updated = False
    
    for key, env_value in env_vars['target'].items():
        if env_value and target_repo.get(key) != env_value:
            target_repo[key] = env_value
            target_updated = True
            print(f"Target repo {key}: {target_repo.get(key)} -> {env_value}")
    
    if target_updated:
        target_config['repository'] = target_repo
        save_yaml_config(target_yaml_path, target_config)
    
    # Ensure log_level is set
    if not source_repo.get('log_level'):
        source_repo['log_level'] = 'DEBUG'
        source_updated = True
    
    if not target_repo.get('log_level'):
        target_repo['log_level'] = 'DEBUG'
        target_updated = True
    
    if source_updated:
        save_yaml_config(source_yaml_path, source_config)
    
    if target_updated:
        save_yaml_config(target_yaml_path, target_config)
    
    print("Repository configuration sync completed")

if __name__ == "__main__":
    sync_repository_config()

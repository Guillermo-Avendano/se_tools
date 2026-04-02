#!/usr/bin/env python3
"""
Worker process for executing MRC plan files.

Monitors workspace/$WORKER/plan for CSV/TXT plan files with columns:
    REPO, OPERATION, COMMAND

Valid OPERATION values: acreate, vdrdbxml, adelete, rm-definitions

For each data row, creates a self-contained .sh script in
workspace/$WORKER/tasks that can be executed independently inside the
container (bash /workspace/worker-1/tasks/step_001.sh).

Pre-requisites (created once at container startup by init_conf.sh):
  /app/conf/custom-truststore-source.jks
  /app/conf/custom-truststore-target.jks
  $HOME/asg/mobius/mobius-cli/application-source.yaml
  $HOME/asg/mobius/mobius-cli/application-target.yaml

When DEBUG=true, scripts are generated but NOT executed (dry-run mode).
"""

import json
import os
import sys
import csv
import time
import stat
import shutil
import logging
import subprocess
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
WORKER = os.environ.get('WORKER', '')
if not WORKER:
    print("ERROR: WORKER environment variable is not set")
    sys.exit(1)

WORKSPACE = Path('/workspace')
WORKER_DIR = WORKSPACE / WORKER
LOGS_DIR = WORKER_DIR / 'logs'
PLAN_DIR = WORKER_DIR / 'plan'
TASKS_DIR = WORKER_DIR / 'tasks'

MRC_PATH = Path('/app/mrc')
CONF_DIR = Path('/app/conf')
TRUSTSTORE_PASS = 'changeit'
MOBIUS_CLI_DIR = Path.home() / 'asg' / 'mobius' / 'mobius-cli'

POLLING_INTERVAL = int(os.environ.get('POLLING_INTERVAL', '10'))
DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

# ---------------------------------------------------------------------------
# Create worker directories on startup
# ---------------------------------------------------------------------------
for d in [LOGS_DIR, PLAN_DIR, TASKS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Cleanup old task files (>1 day) on startup
# ---------------------------------------------------------------------------
_now = time.time()
for _f in TASKS_DIR.iterdir():
    if _f.is_file() and (_now - _f.stat().st_mtime) > 86400:
        _f.unlink()

# ---------------------------------------------------------------------------
# Rotate existing worker.log on startup
# ---------------------------------------------------------------------------
_log_file = LOGS_DIR / 'worker.log'
if _log_file.is_file() and _log_file.stat().st_size > 0:
    _ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    _rotated = LOGS_DIR / f'worker.{_ts}.log'
    shutil.move(str(_log_file), str(_rotated))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger('worker')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(formatter)
logger.addHandler(stdout_handler)

log_file = LOGS_DIR / 'worker.log'
file_handler = logging.FileHandler(str(log_file), encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------

def get_repo_env(repo):
    """Return connection parameters for SOURCE or TARGET from env vars."""
    prefix = f'CE_{repo.upper()}_REPO'
    return {
        'url': os.environ.get(f'{prefix}_URL', ''),
        'name': os.environ.get(f'{prefix}_NAME', 'Mobius'),
        'user': os.environ.get(f'{prefix}_USER', ''),
        'password': os.environ.get(f'{prefix}_PASS', ''),
        'server_user': os.environ.get(f'{prefix}_SERVER_USER', 'ADMIN'),
        'server_pass': os.environ.get(f'{prefix}_SERVER_PASS', ''),
    }

# ---------------------------------------------------------------------------
# Shell script generation
# ---------------------------------------------------------------------------

def _shell_escape(value):
    """Escape a value for safe use inside single quotes in bash."""
    return value.replace("'", "'\\''")


def generate_task_script(operation, command_args, repo, repo_env):
    """Generate a self-contained .sh script for a single task.

    The script:
      1. Copies application-{repo}.yaml -> $HOME/asg/mobius/mobius-cli/application.yaml
      2. Sets the correct truststore for the repo (HTTPS only)
      3. Resolves placeholders in command_args
      4. Calls MobiusRemoteCLI.sh which handles java invocation internally
    """
    repo_label = repo.lower()   # "source" or "target"
    op = operation.lower()

    # Resolve placeholders in command_args
    command_args = (
        command_args
        .replace('{SERVER_PASS}', repo_env.get('server_pass', ''))
        .replace('{SERVER_USER}', repo_env.get('server_user', ''))
        .replace('{REPO_NAME}', repo_env.get('name', ''))
    )

    # Truststore for HTTPS repos (passed via JAVA_TOOL_OPTIONS)
    truststore_path = f'{CONF_DIR}/custom-truststore-{repo_label}.jks'
    url = repo_env.get('url', '')
    use_ssl = url.lower().startswith('https://')

    if use_ssl:
        truststore_export = (
            f'export JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore={truststore_path} '
            f'-Djavax.net.ssl.trustStorePassword={TRUSTSTORE_PASS}"'
        )
        java_opts_line = '# SSL truststore passed via JAVA_TOOL_OPTIONS'
    else:
        truststore_export = 'export JAVA_TOOL_OPTIONS=""'
        java_opts_line = '# No SSL — no truststore needed'

    app_yaml_src = f'{MOBIUS_CLI_DIR}/application-{repo_label}.yaml'
    app_yaml_dst = f'{MOBIUS_CLI_DIR}/application.yaml'

    # All MRC commands go through MobiusRemoteCLI.sh
    # The plan CSV COMMAND column contains the full command with all flags
    # (built by the UI/backend, including timestamp if needed)
    mrc_cmd = f'./MobiusRemoteCLI.sh {command_args}'

    secret_src = '/workspace/conf/secret.sec'
    secret_dst = f'{Path.home()}/asg/security/secret.sec'

    script = f"""#!/bin/bash
# Auto-generated task script -- repo={repo_label} operation={op}
# Generated: {datetime.now().isoformat()}
# Can be executed standalone:  bash <this_script.sh>
set -e

# 1. Ensure secret.sec exists
if [ ! -f '{_shell_escape(secret_dst)}' ] && [ -f '{_shell_escape(secret_src)}' ]; then
    mkdir -p "$(dirname '{_shell_escape(secret_dst)}')"
    cp '{_shell_escape(secret_src)}' '{_shell_escape(secret_dst)}'
    echo "[task] secret.sec copied to {secret_dst}"
fi

# 2. Copy the correct application.yaml for {repo_label}
cp '{_shell_escape(app_yaml_src)}' '{_shell_escape(app_yaml_dst)}'
echo "[task] application.yaml set to {repo_label}"

# 3. Set truststore (HTTPS only)
{java_opts_line}
{truststore_export}

# 3b. Ensure Java is available for MobiusRemoteCLI.sh
export JAVA_HOME=/opt/java/openjdk
export PATH="$JAVA_HOME/bin:$PATH"

# 4. Execute from MRC directory via MobiusRemoteCLI.sh
cd {MRC_PATH}
{mrc_cmd}
"""
    return script


def generate_rm_definitions_script(repo, command_args):
    """Generate a .sh script for rm-definitions (Python-based)."""
    script = f"""#!/bin/bash
# Auto-generated task script — repo={repo.lower()} operation=rm-definitions
# Generated: {datetime.now().isoformat()}
set -e

export REPO='{_shell_escape(repo.upper())}'
python /app/worker/rm_definitions.py {command_args}
"""
    return script

# ---------------------------------------------------------------------------
# Plan parsing → step files
# ---------------------------------------------------------------------------

def parse_plan_file(plan_path):
    """Parse a CSV/TXT plan file and return a list of step dicts."""
    steps = []
    with open(plan_path, 'r', encoding='utf-8') as f:
        first_line = f.readline()
        f.seek(0)
        delimiter = ',' if ',' in first_line else '\t'
        reader = csv.DictReader(f, delimiter=delimiter)
        for i, row in enumerate(reader, start=1):
            steps.append({
                'step': i,
                'repo': row.get('REPO', '').strip(),
                'operation': row.get('OPERATION', '').strip(),
                'command': row.get('COMMAND', '').strip(),
            })
    return steps


def create_step_files(plan_path, steps):
    """Write one step file per row into the tasks directory."""
    base_name = Path(plan_path).stem
    step_files = []
    for step in steps:
        step_filename = f"{base_name}_step_{step['step']:03d}.txt"
        step_path = TASKS_DIR / step_filename
        content = (
            f"REPO={step['repo']}\n"
            f"OPERATION={step['operation']}\n"
            f"COMMAND={step['command']}\n"
        )
        step_path.write_text(content, encoding='utf-8')
        step_files.append(step_path)
        logger.info(f"Created step file: {step_filename}")
    return step_files

# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------

def read_step_file(step_path):
    """Read a step file and return a dict with REPO, OPERATION, COMMAND."""
    data = {}
    with open(step_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '=' in line:
                key, value = line.split('=', 1)
                data[key.strip()] = value.strip()
    return data


def execute_step(step_path):
    """Generate a .sh script for a step, then execute it via bash."""
    step_data = read_step_file(step_path)
    repo = step_data.get('REPO', 'SOURCE')
    operation = step_data.get('OPERATION', '')
    command_args = step_data.get('COMMAND', '')

    logger.info(f"Processing step: {step_path.name} | REPO={repo} OPERATION={operation}")

    step_log = LOGS_DIR / f"{step_path.stem}.log"

    # 1. Generate the .sh script
    if operation.lower() == 'rm-definitions':
        script_content = generate_rm_definitions_script(repo, command_args)
    else:
        repo_env = get_repo_env(repo)
        if not repo_env['url']:
            logger.error(f"No URL configured for repo {repo}. Skipping step.")
            step_path.rename(step_path.with_suffix('.error'))
            return False
        script_content = generate_task_script(operation, command_args, repo, repo_env)

    # 2. Write the .sh script next to the step file
    script_path = step_path.with_suffix('.sh')
    script_path.write_text(script_content, encoding='utf-8')
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
    logger.info(f"Script generated: {script_path.name}")

    # 3. DEBUG mode: generate but do NOT execute
    if DEBUG:
        logger.info(f"[DEBUG] Script generated (not executed): {script_path}")
        with open(step_log, 'w', encoding='utf-8') as f:
            f.write(f"Step: {step_path.name}\n")
            f.write(f"REPO: {repo}\n")
            f.write(f"OPERATION: {operation}\n")
            f.write(f"Script: {script_path.name}\n")
            f.write(f"DEBUG: true — script NOT executed\n")
            f.write("--- SCRIPT ---\n")
            f.write(script_content)
        step_path.rename(step_path.with_suffix('.debug'))
        # Remove step log (already recorded in worker.log)
        if step_log.is_file():
            step_log.unlink()
        return True

    # 4. Execute the .sh script via bash
    cmd = f'bash {script_path}'
    logger.info(f"Executing: {cmd}")
    try:
        process = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(WORKER_DIR),
        )
        stdout_lines, stderr_lines = [], []
        for line in process.stdout:
            stripped = line.strip()
            if stripped:
                logger.info(f"[{step_path.name}] {stripped}")
                stdout_lines.append(stripped)
        for line in process.stderr:
            stripped = line.strip()
            if stripped:
                logger.error(f"[{step_path.name}] {stripped}")
                stderr_lines.append(stripped)
        process.wait()

        with open(step_log, 'w', encoding='utf-8') as f:
            f.write(f"Step: {step_path.name}\n")
            f.write(f"REPO: {repo}\n")
            f.write(f"OPERATION: {operation}\n")
            f.write(f"Script: {script_path.name}\n")
            f.write(f"Return code: {process.returncode}\n")
            f.write("--- SCRIPT ---\n")
            f.write(script_content)
            f.write("--- STDOUT ---\n")
            f.write('\n'.join(stdout_lines) + '\n')
            f.write("--- STDERR ---\n")
            f.write('\n'.join(stderr_lines) + '\n')

        # Remove step log (already recorded in worker.log)
        if step_log.is_file():
            step_log.unlink()

        if process.returncode == 0:
            logger.info(f"Step {step_path.name} completed successfully")
            step_path.rename(step_path.with_suffix('.done'))
            return True

        logger.error(f"Step {step_path.name} failed (rc={process.returncode})")
        step_path.rename(step_path.with_suffix('.error'))
        return False

    except Exception as e:
        logger.error(f"Error executing step {step_path.name}: {e}")
        step_path.rename(step_path.with_suffix('.error'))
        return False

# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

TASK_MAX_AGE_SECONDS = 86400  # 1 day

def write_heartbeat():
    """Write workspace/$WORKER/status.json so the web UI can discover this worker."""
    pending_plans = sum(1 for f in PLAN_DIR.iterdir()
                        if f.is_file() and f.suffix.lower() in ('.txt', '.csv'))
    pending_tasks = sum(1 for f in TASKS_DIR.iterdir()
                        if f.is_file() and f.suffix == '.txt')
    done_tasks = sum(1 for f in TASKS_DIR.iterdir()
                     if f.is_file() and f.suffix in ('.done', '.debug'))
    error_tasks = sum(1 for f in TASKS_DIR.iterdir()
                      if f.is_file() and f.suffix == '.error')
    status = {
        'worker': WORKER,
        'status': 'active',
        'debug': DEBUG,
        'last_heartbeat': datetime.now().isoformat(),
        'pending_plans': pending_plans,
        'pending_tasks': pending_tasks,
        'done_tasks': done_tasks,
        'error_tasks': error_tasks,
    }
    status_path = WORKER_DIR / 'status.json'
    status_path.write_text(json.dumps(status, indent=2), encoding='utf-8')


def cleanup_old_tasks():
    """Delete .done, .debug and .error task files older than 1 day."""
    now = time.time()
    for f in TASKS_DIR.iterdir():
        if not f.is_file():
            continue
        if f.suffix not in ('.done', '.debug', '.error'):
            continue
        age = now - f.stat().st_mtime
        if age > TASK_MAX_AGE_SECONDS:
            logger.info(f"Removing old task file: {f.name} (age={int(age)}s)")
            f.unlink()


def get_next_pending_task():
    """Return the next pending .txt task file sorted by name (sequential order)."""
    tasks = sorted(
        (f for f in TASKS_DIR.iterdir() if f.is_file() and f.suffix == '.txt'),
        key=lambda f: f.name,
    )
    return tasks[0] if tasks else None


def load_oldest_plan():
    """Take the oldest plan file, convert it to task files, and move plan to processed/.
    Returns True if a plan was loaded."""
    plans = sorted(
        (f for f in PLAN_DIR.iterdir() if f.is_file() and f.suffix.lower() in ('.txt', '.csv')),
        key=lambda f: f.stat().st_mtime,
    )
    if not plans:
        return False

    plan_file = plans[0]
    logger.info(f"Loading plan file: {plan_file.name}")
    try:
        steps = parse_plan_file(plan_file)
        if not steps:
            logger.warning(f"No steps found in {plan_file.name}, moving to processed/")
        else:
            logger.info(f"Plan {plan_file.name}: {len(steps)} step(s)")
            create_step_files(plan_file, steps)

        # Move plan to processed/
        processed_dir = PLAN_DIR / 'processed'
        processed_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dest = processed_dir / f"{plan_file.stem}_{timestamp}{plan_file.suffix}"
        shutil.move(str(plan_file), str(dest))
        logger.info(f"Plan file moved to {dest}")
        return bool(steps)
    except Exception as e:
        logger.error(f"Error processing plan file {plan_file.name}: {e}")
        return False


def main():
    logger.info(f"Worker '{WORKER}' started")
    logger.info(f"  Plan dir : {PLAN_DIR}")
    logger.info(f"  Tasks dir: {TASKS_DIR}")
    logger.info(f"  Logs dir : {LOGS_DIR}")
    logger.info(f"  Work dir : {WORKER_DIR}")
    logger.info(f"  Polling  : {POLLING_INTERVAL}s")
    logger.info(f"  DEBUG    : {DEBUG}")
    if DEBUG:
        logger.info("  *** DRY-RUN MODE — commands will be logged but NOT executed ***")

    # Verify acreate-cli.jar is available
    acreate_jar = MRC_PATH / 'acreate-cli.jar'
    if not acreate_jar.is_file():
        logger.error(f"acreate-cli.jar not found at {acreate_jar}")
        sys.exit(1)

    while True:
        try:
            write_heartbeat()
            cleanup_old_tasks()

            # Priority: execute pending tasks one at a time
            task = get_next_pending_task()
            if task:
                execute_step(task)
                continue  # immediately check for next task (no sleep)

            # No pending tasks → load the oldest plan
            if load_oldest_plan():
                continue  # tasks were created, loop back to execute them

            # Nothing to do — idle
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        time.sleep(POLLING_INTERVAL)


if __name__ == '__main__':
    main()
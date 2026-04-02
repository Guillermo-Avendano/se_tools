#!/bin/bash
# ------------------------------------------------------------------
# init_conf.sh — Run once at container startup (called from entrypoint.sh)
#
# Strategy:
#   1. If /workspace/conf/secret.sec exists → user-provided (use as-is)
#      otherwise → copy template from /app/worker/files/secret.sec
#   2. On every startup, copy /workspace/conf/application.yaml to
#      /workspace/conf/application-{label}.yaml and replace only repositoryUrl
#      with CE_{LABEL}_REPO_URL (+ /mobius)
#   3. Copy secret.sec  → $HOME/asg/security/secret.sec
#   4. Copy application-{label}.yaml → $HOME/asg/mobius/mobius-cli/
#   5. Create truststores from certificates (if present)
#
# User override: place your own application-source.yaml,
#   application-target.yaml and/or secret.sec in /workspace/conf/
#   and they will be used without modification.
# ------------------------------------------------------------------
set -e

CONF_DIR="/app/conf"
TRUSTSTORE_PASS="changeit"
MOBIUS_CLI_DIR="$HOME/asg/mobius/mobius-cli"
SECURITY_DIR="$HOME/asg/security"
WORKSPACE_CONF="/workspace/conf"
TEMPLATE_DIR="/app/worker/files"

mkdir -p "$CONF_DIR" "$MOBIUS_CLI_DIR" "$SECURITY_DIR" "$WORKSPACE_CONF"

# ── secret.sec ────────────────────────────────────────────────────
if [ -f "$WORKSPACE_CONF/secret.sec" ]; then
    echo "[init_conf] Using user-provided secret.sec from $WORKSPACE_CONF"
else
    cp "$TEMPLATE_DIR/secret.sec" "$WORKSPACE_CONF/secret.sec"
    echo "[init_conf] Copied template secret.sec to $WORKSPACE_CONF"
fi
cp "$WORKSPACE_CONF/secret.sec" "$SECURITY_DIR/secret.sec"
echo "[init_conf] secret.sec installed at $SECURITY_DIR/secret.sec"

# ── Helper: provision application-<label>.yaml ────────────────────
provision_app_yaml() {
    local label="$1"       # source | target
    local repo_url="$2"    # CE_{LABEL}_REPO_URL
    local ws_yaml="$WORKSPACE_CONF/application-${label}.yaml"
    local base_yaml="$WORKSPACE_CONF/application.yaml"

    if [ -f "$base_yaml" ]; then
        cp "$base_yaml" "$ws_yaml"
        echo "[init_conf] Base application.yaml copied from $WORKSPACE_CONF"
    else
        cp "$TEMPLATE_DIR/application.yaml" "$ws_yaml"
        echo "[init_conf] Base application.yaml missing in workspace; using template"
    fi

    if [ -n "$repo_url" ]; then
        local mrc_url="${repo_url%/}/mobius"
        sed -i "s|^[[:space:]]*repositoryUrl:.*$|        repositoryUrl: \"${mrc_url}\"|" "$ws_yaml"
        echo "[init_conf] application-${label}.yaml repositoryUrl set to ${mrc_url}"
    else
        echo "[init_conf] WARN: CE_${label^^}_REPO_URL not set; keeping repositoryUrl from base YAML"
    fi

    # Install into Mobius CLI directory
    cp "$ws_yaml" "$MOBIUS_CLI_DIR/application-${label}.yaml"
    echo "[init_conf] application-${label}.yaml installed at $MOBIUS_CLI_DIR"
}

# ── Helper: create a truststore with one certificate ──────────────
create_truststore() {
    local label="$1"     # source | target
    local cert_path="$2" # path to cert file or directory
    local ts_path="$CONF_DIR/custom-truststore-${label}.jks"

    # Resolve cert: if directory, pick first file inside
    if [ -d "$cert_path" ]; then
        cert_path=$(find "$cert_path" -maxdepth 1 -type f | head -1)
    fi
    if [ -z "$cert_path" ] || [ ! -f "$cert_path" ]; then
        echo "[init_conf] No certificate found for $label — skipping truststore"
        return
    fi

    # Remove stale truststore if it exists
    rm -f "$ts_path"

    # Import certificate
    keytool -importcert -noprompt -trustcacerts \
        -alias "cert_${label}" \
        -file "$cert_path" \
        -keystore "$ts_path" \
        -storepass "$TRUSTSTORE_PASS" 2>/dev/null

    echo "[init_conf] Truststore created: $ts_path  (cert: $cert_path)"
}

# ── SOURCE ────────────────────────────────────────────────────────
provision_app_yaml \
    "source" \
    "${CE_SOURCE_REPO_URL:-}"
create_truststore  "source" "${CE_SOURCE_CERT:-/workspace/conf/cert_source/ca.crt}"

# ── TARGET ────────────────────────────────────────────────────────
provision_app_yaml \
    "target" \
    "${CE_TARGET_REPO_URL:-}"
create_truststore  "target" "${CE_TARGET_CERT:-/workspace/conf/cert_target/ca.crt}"

echo "[init_conf] Initialization complete"

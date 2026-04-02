# ═══════════════════════════════════════════════════════════════════════════
# SE ContentEdge Tools — Unified multi-stage Docker image
# Build context: project root (to access shared contentedge/)
# Stage 1: Node.js frontend (static files + proxy)
# Stage 2: MRC tools extraction (Java + Mobius CLI)
# Stage 3: Final image — Python backend + frontend + worker
#   When WORKER env is set  → runs worker/worker.py
#   When WORKER env is empty → runs supervisord (backend + frontend)
# ═══════════════════════════════════════════════════════════════════════════

# ── Stage 1: Frontend build ───────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /build
COPY se_ce_tools/frontend/package.json se_ce_tools/frontend/package-lock.json* ./
RUN npm ci --production
COPY se_ce_tools/frontend/ ./

# ── Stage 2: MRC tools extraction ────────────────────────────────────────
FROM eclipse-temurin:21-jdk-jammy AS mrc-builder

ARG MRC_FILE=MobiusRemoteCLI-12.5.2005.zip
ARG MRC_PATH=/app/mrc

RUN apt-get update && \
    apt-get install -y --no-install-recommends unzip dos2unix && \
    rm -rf /var/lib/apt/lists/*

COPY se_ce_tools/worker/${MRC_FILE} /tmp/${MRC_FILE}

RUN mkdir -p ${MRC_PATH} && \
    unzip /tmp/${MRC_FILE} -d ${MRC_PATH} && \
    rm /tmp/${MRC_FILE} && \
    find ${MRC_PATH} -name "*.sh" -exec dos2unix {} \; && \
    find ${MRC_PATH} -name "*.sh" -exec chmod +x {} \;

# ── Stage 3: Final unified image ─────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy Java 21 JRE from eclipse-temurin
COPY --from=mrc-builder /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# System deps (frontend + backend + worker)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl supervisor nodejs npm \
        inotify-tools dos2unix procps nano && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies — backend
COPY se_ce_tools/backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Python dependencies — worker
RUN pip install --no-cache-dir pyyaml schedule

# Copy backend
COPY se_ce_tools/backend/ /app/backend/

# Copy shared contentedge library
COPY contentedge/ /app/contentedge/

# Copy frontend (with node_modules from build stage)
COPY --from=frontend-build /build/ /app/frontend/

# Copy MRC tools (acreate-cli.jar, MobiusRemoteCli, etc.)
COPY --from=mrc-builder /app/mrc /app/mrc

# Copy worker files
COPY se_ce_tools/worker/worker.py se_ce_tools/worker/rm_definitions.py /app/worker/
COPY se_ce_tools/worker/init_conf.sh /app/worker/init_conf.sh
RUN chmod +x /app/worker/init_conf.sh
COPY se_ce_tools/worker/files/ /app/worker/files/

# Workspace directory (mounted at runtime)
RUN mkdir -p /workspace/conf /workspace/tmp /workspace/exports /app/conf

ENV APP_ROOT=/app
ENV WORKSPACE_ROOT=/workspace
# WORKER: when set (e.g. worker-1, worker-2), the container runs worker.py
# when empty, the container runs the web UI (backend + frontend)
ENV WORKER=""

# Supervisord config for web UI mode
RUN cat > /etc/supervisor/conf.d/se-ce-tools.conf <<'EOF'
[supervisord]
nodaemon=true
logfile=/dev/stdout
logfile_maxbytes=0

[program:backend]
command=python -m uvicorn server:app --host 0.0.0.0 --port 8500
directory=/app/backend
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:frontend]
command=node server.js
directory=/app/frontend
environment=PORT="3000",API_URL="http://localhost:8500"
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

# Entrypoint: decides between worker mode and web UI mode
COPY se_ce_tools/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 3000 8500

ENTRYPOINT ["/app/entrypoint.sh"]

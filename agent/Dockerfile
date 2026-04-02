FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2, matplotlib, healthcheck, and shell skill
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq-dev gcc fonts-dejavu-core curl bash procps && \
    rm -rf /var/lib/apt/lists/*

COPY agent/pyproject.toml .
COPY agent/README.md .
COPY agent/app/__init__.py /app/app/__init__.py
RUN pip install --no-cache-dir .

# Copy agent application
COPY agent/app/ /app/app/
COPY agent/scripts/ /app/scripts/

# Copy shared contentedge library
COPY contentedge/ /app/contentedge/

# Agent workspace with subdirectories
RUN mkdir -p /workspace/charts_output \
             /workspace/prompts \
             /workspace/knowledge/corrections \
             /workspace/knowledge/procedures \
             /workspace/knowledge/preferences \
             /workspace/tmp

ENV AGENT_WORKSPACE=/workspace

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

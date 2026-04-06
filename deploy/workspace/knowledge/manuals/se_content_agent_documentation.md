# SE ContentEdge Agent Documentation (Current)

This document describes the current behavior of the running SE ContentEdge agent.
It intentionally excludes deprecated features.

## Scope

The agent is focused on ContentEdge operations and repository guidance.
It uses retrieval from Qdrant plus deterministic command guidance for MobiusRemoteCLI cases.

## Runtime Components

- FastAPI service on port 8000
- Qdrant for vector memory
- Ollama or llama.cpp for LLM and embeddings
- Redis for chat history
- AnythingLLM via OpenAI-compatible endpoints

## Supported API Endpoints

### Agent routes

- GET /health
- POST /ask
- POST /ask/stream (SSE progress + final answer)
- DELETE /chat/{session_id}
- GET /skills
- POST /reindex

### OpenAI-compatible routes

- GET /v1/models
- POST /v1/chat/completions

## Memory and Indexing

Knowledge is loaded into Qdrant with chunking and payload metadata.

Current knowledge sources:

- knowledge/manuals (Markdown)
- knowledge/generated_md (Markdown generated from PDFs)

Behavior on empty Qdrant collection:

1. PDFs under knowledge are reprocessed.
2. Markdown is regenerated into knowledge/generated_md.
3. Generated Markdown is indexed into Qdrant.

## MobiusRemoteCLI Context Behavior

When request context includes:

- tool=MobiusRemoteCLI
- operation=adelete
- command=<template>

the agent should return the full command, not only a clause.

Example expected output style:

adelete -s Mobius -u ADMIN -r {CONTENT_CLASS} -c -n -y ALL -o -t 20210228235959

## Operational Notes

- If embeddings model does not support embeddings, indexing fails.
- Health must report qdrant=ok, ollama=ok, redis=ok for stable operation.
- After code changes, containers must be recreated to apply new images.

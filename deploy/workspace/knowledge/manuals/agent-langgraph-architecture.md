# Agent LangGraph Architecture (Current)

```mermaid
flowchart TB
    START([START])

    CONTEXT[Parse question + context hint]
    RETRIEVE[Retrieve Qdrant context]
    ADVISORY{Deterministic advisory match?}

    DIRECT[Return deterministic answer]
    ROUTE{Route selection}
    CONTENTEDGE[ContentEdge LangGraph]
    GENERAL[General ReAct agent]

    HARNESS[Harness: timeout + retry + fallback]
    RETRY{Transient failure?}
    FALLBACK[Run fallback route]
    GIVEUP[Safe fallback answer]

    RAG{Graph answer generic?}
    DOC_ANSWER[Answer from retrieved docs]
    END([END])

    START --> CONTEXT
    CONTEXT --> RETRIEVE
    RETRIEVE --> ADVISORY
    ADVISORY -->|yes| DIRECT
    ADVISORY -->|no| ROUTE

    ROUTE -->|contentedge| CONTENTEDGE
    ROUTE -->|general| GENERAL

    CONTENTEDGE --> HARNESS
    GENERAL --> HARNESS
    HARNESS --> RETRY
    RETRY -->|retry| HARNESS
    RETRY -->|no retry| FALLBACK
    FALLBACK -->|success| END
    FALLBACK -->|failure| GIVEUP
    GIVEUP --> END

    CONTENTEDGE --> RAG
    RAG -->|yes| DOC_ANSWER
    RAG -->|no| END
    DOC_ANSWER --> END
    DIRECT --> END

    style START fill:#90EE90
    style END fill:#87CEEB
    style GIVEUP fill:#FFB6C6
    style HARNESS fill:#FFE4B5
    style ROUTE fill:#F0E68C
    style CONTENTEDGE fill:#B0E0E6
    style GENERAL fill:#B0E0E6
    style DIRECT fill:#DDA0DD
```

## Runtime Notes

- Context hints from SE Tools are injected into each turn.
- For MobiusRemoteCLI adelete requests with command template context, output should be an executable full command.
- Harness controls resiliency: timeout, retry on transient errors, and route fallback.
- Harness settings come from environment variables:
    - AGENT_HARNESS_TIMEOUT_SECONDS
    - AGENT_HARNESS_FALLBACK_TIMEOUT_SECONDS
    - AGENT_HARNESS_MAX_ATTEMPTS
    - AGENT_HARNESS_RETRY_BACKOFF_SECONDS

## Streaming Stages (`POST /ask/stream`)

The stream can emit status events including:

- received
- reset_history
- loading_history
- agent_processing
- routing_contentedge_langgraph / routing_general_react
- harness_attempt
- harness_retry
- harness_fallback_start
- harness_fallback_success
- harness_give_up
- saving_history
- finalizing
- answer
- done

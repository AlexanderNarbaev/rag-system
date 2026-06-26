# RAG System — Unternehmenswissens-Assistent (DE)

<div class="hero" markdown>
<div class="hero-content" markdown>

**OpenAI-kompatibler RAG-Proxy mit vollständiger ETL-Pipeline.** Erfasst Confluence, Jira, GitLab, Dokumente, Bücher und Chat-Verläufe und indiziert sie in Qdrant + Neo4j. Bereitgestellt über beliebige LLM-Backends — vLLM, llama.cpp, Anthropic, Ollama oder jeden OpenAI-kompatiblen Endpoint.

**Version:** v2.0 | **Tests:** 1333+ | **Reife:** RAG Level 5 (Selbstkorrigierend)

[Erste Schritte](#schnellstart){ .md-button .md-button--primary }
[API-Referenz](../en/api_reference.md){ .md-button }

</div>
</div>

---

## Architektur

```mermaid
graph TB
    subgraph "Datenquellen"
        CONF[Confluence]
        JIRA[Jira]
        GL[GitLab]
        DOCS[Dokumente & Bücher]
        CHATS[Chat-Verlauf]
    end

    subgraph "ETL-Pipeline"
        EXTRACT[Extraktoren]
        CHUNK[Semantischer Chunker]
        EMBED[Embedding BGE-M3]
        INDEX[Indexer]
    end

    subgraph "Speicher"
        QDRANT[(Qdrant<br/>Vektor-DB)]
        NEO4J[(Neo4j<br/>Graph-DB)]
        REDIS[(Redis<br/>Cache)]
    end

    subgraph "RAG-Proxy :8080"
        API[OpenAI-kompatible API]
        ORCH[LangGraph Orchestrator]
        RETR[Hybrid-Suche]
        RERANK[Cross-Encoder Reranking]
        CTX[Kontext-Builder]
        TOKEN[Token-Optimierer]
    end

    subgraph "LLM-Backend"
        LLM[vLLM/llama.cpp/Anthropic/Ollama]
        SLM[Leichtes SLM für Routing]
    end

    subgraph "Human-in-the-Loop"
        DASH[Streamlit Dashboard]
        FB[Feedback-Sammlung]
    end

    CONF --> EXTRACT
    JIRA --> EXTRACT
    GL --> EXTRACT
    DOCS --> EXTRACT
    CHATS --> EXTRACT
    EXTRACT --> CHUNK
    CHUNK --> EMBED
    EMBED --> INDEX
    INDEX --> QDRANT
    INDEX --> NEO4J
    API --> ORCH
    ORCH --> RETR
    ORCH --> RERANK
    ORCH --> CTX
    ORCH --> TOKEN
    RETR --> QDRANT
    RETR --> NEO4J
    RETR --> REDIS
    CTX --> LLM
    LLM --> API
    API --> FB
    FB --> DASH
```

## Funktionen

| Funktion | Beschreibung |
|----------|-------------|
| **Hybrid-Suche** | Dense + Sparse Vektorsuche mit RRF-Fusion (Qdrant) |
| **Cross-Encoder Reranking** | Neubewertung der Top-K-Ergebnisse für höhere Präzision |
| **Graph-Erweiterung** | Neo4j-Wissensgraph zur Anreicherung von Entitätsbeziehungen |
| **Spracherkennung** | Automatische Erkennung von DE/FR/ZH/RU/EN |
| **Token-Optimierung** | BPE-bewusste Token-Zählung und Kompression |
| **Selbstkorrektur** | HyDE-Query-Erweiterung, CRAG-Evaluator, Reflexionsschleifen |
| **Halluzinationserkennung** | NLI-basierte Antwortüberprüfung |
| **RBAC** | Rollenbasierte Zugriffskontrolle |
| **Multi-Modal** | Unterstützung für Bilder, Code und Tabellen |
| **Streaming-ETL** | Redis Streams für inkrementelle Updates |
| **K8s-Bereitstellung** | Helm-Chart, HPA, Prometheus-Metriken |

## Schnellstart

```bash
# Repository klonen
git clone https://github.com/AlexanderNarbaev/rag-system.git
cd rag-system

# Vollständige Installation
make install

# Tests ausführen
make test

# Docker-Images erstellen und starten
make docker-build
make docker-up
```

### Voraussetzungen

- Python 3.10+
- Qdrant (Vektor-Datenbank)
- Neo4j (optional, für Graph-Erweiterung)
- Redis (optional, für Caching)
- LLM-Backend (vLLM, llama.cpp oder OpenAI-kompatibel)

## API-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|-------------|
| `/v1/chat/completions` | POST | Chat-Vervollständigung (Streaming + nicht-Streaming) |
| `/v1/models` | GET | Verfügbare Modelle auflisten |
| `/v1/health` | GET | Gesundheitscheck |
| `/v1/feedback` | POST | Experten-Feedback einreichen |
| `/v1/auth/login` | POST | JWT-Token-Generierung |
| `/metrics` | GET | Prometheus-Metriken |

## Unterstützte Sprachen

Das System erkennt automatisch die Sprache der Anfrage und antwortet entsprechend:

| Sprache | Code | Erkennung |
|---------|------|-----------|
| Englisch | `en` | Standard |
| Russisch | `ru` | Kyrillische Zeichen |
| **Deutsch** | `de` | Umlaute + gebräuchliche Wörter |
| Französisch | `fr` | Akzente + gebräuchliche Wörter |
| Chinesisch | `zh` | CJK-Zeichen |

---

> Für detaillierte technische Dokumentation besuchen Sie die [englischen Dokumente](../en/index.md).
> Diese Seite ist eine lokalisierte Kurzfassung für deutschsprachige Benutzer.

# План улучшений RAG-системы — Q3 2026

> **Статус**: Draft  
> **Создан**: 2026-07-13  
> **Автор**: System Architect  
> **Цикл ревью**: Еженедельно

---

## Executive Summary

На основе глубокого исследования 19 статей Habr + 12 академических работ мы идентифицировали 25 техник. **12 реализованы**, **13 требуют реализации**. Этот план покрывает оставшиеся улучшения по 5 фазам за 12 недель.

### Источники исследования

- **Habr**: RAG best practices, ColBERT интеграция, RAPTOR построение дерева, GraphRAG обнаружение сообществ, RAGAS оценка, FLARE активный retrieval
- **Papers**: RAPTOR (Stanford 2024), ColBERTv2, GraphRAG (Microsoft 2024), RAGAS, FLARE, HyDE

### Текущее состояние (Реализовано ✅)

| Фича                                  | Статус | Расположение                                |
|---------------------------------------|--------|---------------------------------------------|
| Hybrid Search (dense + sparse + RRF)  | ✅      | `proxy/app/core/retrieval.py`              |
| Cross-encoder Reranking               | ✅      | `proxy/app/core/rerank.py`                 |
| HyDE Query Expansion                  | ✅      | `proxy/app/core/hyde.py`                   |
| LangGraph Orchestration               | ✅      | `proxy/app/core/orchestrator/`             |
| Neo4j Graph Expansion                 | ✅      | `proxy/app/core/retrieval.py`              |
| Semantic Chunking                     | ✅      | `etl/chunker/semantic_chunker.py`          |
| Token Optimization                    | ✅      | `proxy/app/core/token_optimizer.py`        |
| Context Compression                   | ✅      | `proxy/app/core/context/compression.py`    |
| Hallucination Detection               | ✅      | `proxy/app/core/hallucination.py`          |
| Confidence Scoring                    | ✅      | `proxy/app/core/confidence.py`             |
| Query Enhancement                     | ✅      | `proxy/app/core/query_enhancer.py`         |
| Live Source Queries                   | ✅      | `proxy/app/core/live_sources.py`           |

### Gap Analysis (13 улучшений)

| #  | Фича                      | Приоритет | Фаза | Источник исследования       |
|----|---------------------------|-----------|------|-----------------------------|
| 1  | ColBERT Late Interaction  | CRITICAL  | 1    | ColBERTv2, Habr             |
| 2  | RAGAS Integration         | CRITICAL  | 1    | RAGAS paper, Habr           |
| 3  | Negative Rejection        | CRITICAL  | 1    | Best practices, Habr        |
| 4  | NLI Model Upgrade         | CRITICAL  | 1    | NLI papers, Habr            |
| 5  | RAPTOR Hierarchical       | HIGH      | 2    | RAPTOR paper                |
| 6  | Multi-Query Rewriting     | HIGH      | 2    | HyDE extension              |
| 7  | Knee-Point Pruning        | HIGH      | 2    | Score analysis              |
| 8  | GraphRAG Community        | MEDIUM    | 3    | GraphRAG paper              |
| 9  | Global Search Mode        | MEDIUM    | 3    | GraphRAG paper              |
| 10 | Multi-Hop Reasoning       | MEDIUM    | 3    | Graph traversal             |
| 11 | FLARE Active Retrieval    | MEDIUM    | 5    | FLARE paper                 |
| 12 | Two-Stage Reranking       | MEDIUM    | 5    | ColBERT + Cross-encoder     |
| 13 | Adaptive Chunking         | MEDIUM    | 5    | Semantic chunking           |

---

## Phase 1 — Foundation (Week 1-2) [CRITICAL]

> **Цель**: Установить измерение качества, улучшить точность retrieval, исправить галлюцинации  
> **Риск**: HIGH — foundation для всех последующих фаз  
> **Зависимости**: bge-m3 модель, NLI модель предзагружена

### 1.1 ColBERT Late Interaction

**Цель**: Добавить ColBERT token-level reranking используя нативную поддержку ColBERT в bge-m3

**Зачем**: ColBERT обеспечивает детальный token-level скоринг релевантности. bge-m3 уже генерирует ColBERT векторы — нужно только сохранить и запросить их.

**Исследование**: ColBERTv2 paper показывает 15-20% улучшение precision по сравнению с dense-only retrieval.

**Файлы для модификации:**

```
etl/indexer/qdrant_hybrid.py     — Сохранение ColBERT векторов при индексации
proxy/app/core/retrieval.py      — Запрос с ColBERT late interaction
proxy/app/core/rerank.py         — Интеграция ColBERT в pipeline реранжирования
```

**Новые файлы:**

```
tests/proxy/test_colbert.py      — Unit + интеграционные тесты
docs/en/adr/ADR-015-colbert.md   — Архитектурное решение
```

**Шаги реализации:**

1. Настроить коллекцию Qdrant с ColBERT vector field
2. Модифицировать ETL для извлечения и хранения ColBERT векторов из bge-m3
3. Реализовать ColBERT scoring функцию (MaxSim)
4. Интегрировать в гибридный поиск с настраиваемым весом
5. A/B тестирование против текущего retrieval

**Критерии приёмки:**

- [ ] ColBERT векторы сохранены для всех проиндексированных документов
- [ ] ColBERT scoring возвращает корректные MaxSim значения
- [ ] Reranking precision улучшается на ≥15% на тестовом наборе
- [ ] Увеличение задержки < 50ms на запрос

**TDD подход:**

```python
# tests/proxy/test_colbert.py

def test_colbert_vectors_stored(qdrant_client, sample_docs):
    """Given indexed docs, ColBERT vectors should be present."""
    # Arrange: индексация sample документов
    # Act: извлечение point с векторами
    # Assert: colbert_vectors field существует и имеет корректные размерности

def test_maxsim_scoring(query_tokens, doc_tokens):
    """MaxSim should compute token-level similarity correctly."""
    # Arrange: известные token векторы
    # Act: вычисление MaxSim
    # Assert: score совпадает с ожидаемым значением (±0.01)

def test_colbert_improves_reranking(test_queries, ground_truth):
    """ColBERT reranking should outperform dense-only."""
    # Arrange: тестовые запросы с известными релевантными документами
    # Act: retrieval с ColBERT и без
    # Assert: ColBERT вариант имеет более высокий MRR
```

**Риск**: Storage overhead +20%
**Митигация**: Использовать ColBERT квантование (int8), IVF index

---

### 1.2 RAGAS Integration

**Цель**: Подключить RAGAS метрики в feedback loop для систематического измерения качества

**Зачем**: RAGAS предоставляет стандартизированные метрики качества RAG (faithfulness, answer relevancy, context precision, context recall). В настоящее время у нас нет систематического измерения качества.

**Исследование**: RAGAS paper (2023) — индустриальный стандарт для оценки RAG.

**Файлы для модификации:**

```
proxy/app/core/ragas_eval.py     — NEW: RAGAS модуль оценки
proxy/app/api/feedback.py        — Добавить RAGAS scoring к feedback
proxy/app/api/chat.py            — Включить RAGAS скоры в ответ
```

**Новые файлы:**

```
tests/proxy/test_ragas.py        — Unit тесты
config/ragas_config.yaml         — RAGAS конфигурация
```

**Шаги реализации:**

1. Создать `ragas_eval.py` с реализацией метрик
2. Подключить к feedback эндпоинту для post-hoc оценки
3. Добавить RAGAS скоры к response extensions
4. Создать evaluation dataset из экспертного feedback
5. Настроить детекцию регрессии в CI/CD

**Критерии приёмки:**

- [ ] Каждый ответ включает RAGAS скоры в extensions
- [ ] `ragas.faithfulness` > 0.8 на тестовом наборе
- [ ] `ragas.answer_relevancy` > 0.7 на тестовом наборе
- [ ] RAGAS скоры хранятся в feedback database

**RAGAS метрики:**
| Метрика | Описание | Цель |
|---------|----------|------|
| Faithfulness | Ответ основан на контексте | > 0.8 |
| Answer Relevancy | Ответ адресует вопрос | > 0.7 |
| Context Precision | Retrieved контекст релевантен | > 0.7 |
| Context Recall | Весь релевантный контекст извлечён | > 0.6 |

**Риск**: RAGAS оценка добавляет задержку
**Митигация**: Async оценка, sample-based для high-volume

---

### 1.3 Negative Rejection

**Цель**: Возвращать "Я не знаю" когда качество retrieval недостаточно

**Зачем**: Система в настоящее время галлюцинирует когда нет релевантных документов. Лучше отказать, чем фабриковать.

**Исследование**: Best practices из RAG production деплоев — negative rejection критичен для доверия.

**Файлы для модификации:**

```
proxy/app/core/confidence.py     — Добавить порог качества retrieval
proxy/app/main.py                — Обработка rejection в chat endpoint
proxy/app/api/chat.py            — Возврат структурированного rejection ответа
```

**Новые файлы:**

```
tests/proxy/test_negative_rejection.py — Behavior тесты
docs/en/adr/ADR-016-negative-rejection.md
```

**Шаги реализации:**

1. Определить критерии "strong source" (score > порога, count >= 2)
2. Добавить проверку качества retrieval перед LLM вызовом
3. Вернуть структурированное "Я не знаю" с confidence 0.0
4. Логировать rejections для анализа
5. A/B тестирование значений порога

**Критерии приёмки:**

- [ ] 100% отказов для запросов с < 2 strong sources
- [ ] Rejection ответ включает `rag_confidence: 0.0`
- [ ] Rejection ответ включает причину (insufficient_sources)
- [ ] Нет галлюцинированных ответов для неизвестных тем

**BDD сценарий:**

```gherkin
Feature: Negative Rejection

  Scenario: Query with no relevant sources
    Given the knowledge base has no documents about "quantum computing"
    When user asks "What is quantum computing?"
    Then system returns "I don't have enough information to answer that question"
    And response includes rag_confidence: 0.0
    And response includes rag_rejection_reason: "insufficient_sources"

  Scenario: Query with weak sources
    Given the knowledge base has 1 document about "quantum computing" with score 0.3
    When user asks "What is quantum computing?"
    Then system returns "I don't have enough information to answer that question"
    And response includes rag_confidence: 0.1
```

**Риск**: Over-rejection блокирует валидные ответы
**Митигация**: Настраиваемый порог, A/B тестирование, экспертный review loop

---

### 1.4 NLI Model Upgrade

**Цель**: Заменить word-overlap proxy реальной NLI моделью для детекции галлюцинаций

**Зачем**: Текущая детекция галлюцинаций использует word overlap — примитивно и ненадёжно. Реальные NLI модели обеспечивают семантический entailment скоринг.

**Исследование**: NLI-based grounding — state-of-the-art для детекции галлюцинаций.

**Файлы для модификации:**

```
proxy/app/core/confidence.py     — Использовать NLI для grounding check
proxy/app/core/hallucination.py  — NLI-based hallucination scoring
proxy/app/core/grounding.py      — Обновление NLI реализации
```

**Модель**: `cross-encoder/nli-distilroberta-base` (предзагружена для air-gapped)

**Новые файлы:**

```
tests/proxy/test_nli.py          — NLI-специфичные тесты
```

**Шаги реализации:**

1. Загрузить NLI модель при старте (lazy loading с warmup)
2. Заменить word-overlap на NLI entailment scoring
3. Реализовать three-way классификацию: entailment/neutral/contradiction
4. Установить пороги: entailment > 0.7 = grounded, contradiction > 0.7 = hallucination
5. Benchmark против текущего подхода

**Критерии приёмки:**

- [ ] NLI модель загружена и функциональна
- [ ] Hallucination detection F1 > 0.8
- [ ] False positive rate < 10%
- [ ] Задержка < 100ms на проверку

**Риск**: Потребление памяти NLI моделью (~500MB)
**Митигация**: Дистиллированная модель, lazy loading, circuit breaker

---

## Phase 2 — Advanced Retrieval (Week 3-4) [HIGH]

> **Цель**: Улучшить качество retrieval с продвинутыми техниками  
> **Риск**: MEDIUM — зависит от завершения Phase 1  
> **Зависимости**: ColBERT интеграция, RAGAS baseline

### 2.1 RAPTOR Hierarchical Retrieval

**Цель**: Построить древовидные саммари для многоуровневого retrieval

**Зачем**: RAPTOR обеспечивает retrieval на разных уровнях абстракции — от конкретных деталей до высокоуровневых саммари. Критично для сложных запросов.

**Исследование**: RAPTOR paper (Stanford 2024) — 20% улучшение на multi-hop QA.

**Новые файлы:**

```
etl/indexer/tree_builder.py      — Построение дерева из чанков
etl/indexer/summarizer.py        — Построчное суммирование
tests/etl/test_tree_builder.py   — Тесты построения дерева
```

**Файлы для модификации:**

```
etl/scheduler/run_etl.py         — Добавить шаг построения дерева
proxy/app/core/retrieval.py      — Multi-level retrieval
```

**Шаги реализации:**

1. Кластеризовать чанки по сходству эмбеддингов (Gaussian Mixture)
2. Суммировать кластеры → level 1 узлы
3. Кластеризовать саммари → level 2 узлы
4. Повторять до глубины дерева 3-4
5. Индексировать все узлы дерева в Qdrant с level metadata
6. Извлекать из нескольких уровней, объединять с RRF

**Критерии приёмки:**

- [ ] Глубина дерева 3-4 уровня для документов > 10 чанков
- [ ] Качество саммари > 0.7 (human eval)
- [ ] Multi-level retrieval улучшает Recall@10 на > 10%
- [ ] Время построения дерева < 5min на 1000 чанков

**Алгоритм:**

```
1. chunks = extract_chunks(document)
2. embeddings = embed(chunks)
3. clusters = gaussian_mixture(embeddings, n_components=sqrt(len(chunks)))
4. for level in range(max_depth):
5.     summaries = llm_summarize(clusters)
6.     if len(summaries) < min_cluster_size: break
7.     clusters = gaussian_mixture(embed(summaries))
8. tree = build_tree(clusters, summaries)
9. index_tree(tree)
```

**Риск**: Время построения, качество саммари
**Митигация**: Async ETL, human-in-the-loop для качества

---

### 2.2 Query Rewriting с множественными формулировками

**Цель**: Генерировать 2-3 варианта запроса, объединять результаты с RRF

**Зачем**: Один запрос может пропустить релевантные документы. Множественные формулировки увеличивают recall.

**Исследование**: HyDE extension — множество гипотетических документов улучшают покрытие.

**Файлы для модификации:**

```
proxy/app/core/query_enhancer.py — Multi-query генерация
proxy/app/core/retrieval.py      — RRF слияние multi-query результатов
```

**Новые файлы:**

```
tests/proxy/test_query_enhancer.py — Multi-query тесты
```

**Шаги реализации:**

1. Генерировать 2-3 переформулировки запроса через SLM
2. Извлекать для каждого варианта
3. Объединять результаты с RRF (Reciprocal Rank Fusion)
4. Дедуплицировать и реранжировать

**Критерии приёмки:**

- [ ] 2-3 варианта запроса генерируются per request
- [ ] Recall@10 улучшение > 10%
- [ ] Увеличение задержки < 200ms
- [ ] Варианты семантически разнообразны

**Стратегии переформулировки запроса:**
| Стратегия | Пример |
|-----------|--------|
| Paraphrase | "Как настроить X?" → "Руководство по настройке X" |
| Specificity | "auth" → "Настройка JWT аутентификации" |
| Abstraction | "JWT token refresh" → "Управление токенами аутентификации" |

---

### 2.3 Knee-Point Pruning

**Цель**: Dynamic top-k используя анализ кривой скоров

**Зачем**: Фиксированный top-k либо включает нерелевантные документы, либо пропускает релевантные. Knee-point находит естественную границу отсечения.

**Исследование**: Score distribution analysis — максимальное расстояние от хорды.

**Файлы для модификации:**

```
proxy/app/core/retrieval.py      — Knee-point детекция
```

**Новые файлы:**

```
tests/proxy/test_knee_point.py   — Knee-point тесты
```

**Алгоритм:**

```
1. scores = [doc.score for doc in retrieved_docs]
2. normalized = normalize(scores)  # [0, 1]
3. chord = line from (0, normalized[0]) to (n-1, normalized[-1])
4. distances = [perpendicular_distance(point, chord) for point in enumerate(normalized)]
5. knee_index = argmax(distances)
6. return docs[:knee_index + 1]
```

**Критерии приёмки:**

- [ ] 60%+ нерелевантных документов отсекаются автоматически
- [ ] Нет релевантных документов в отсечённом наборе (precision = 1.0)
- [ ] Работает для разных распределений скоров
- [ ] Fallback на фиксированный top-k если кривая линейна

**Риск**: Over-pruning для равномерных скоров
**Митигация**: Минимальное количество документов (3), fallback порог

---

## Phase 3 — Knowledge Graph (Week 5-6) [MEDIUM]

> **Цель**: Использовать графовую структуру для сложных запросов  
> **Риск**: MEDIUM — зависимость от Neo4j  
> **Зависимости**: Neo4j GDS library, community detection

### 3.1 GraphRAG Community Detection

**Цель**: Leiden алгоритм для обнаружения сообществ в Neo4j

**Зачем**: Сообщества представляют кластеры тем. Саммари позволяют отвечать на вопросы по всему корпусу.

**Исследование**: GraphRAG paper (Microsoft 2024) — обнаружение сообществ + суммирование.

**Новые файлы:**

```
etl/graph_builder/community.py   — Обнаружение сообществ
etl/graph_builder/summarizer.py  — Суммирование сообществ
tests/etl/test_community.py      — Тесты сообществ
```

**Файлы для модификации:**

```
etl/graph_builder/neo4j_loader.py — Сохранение сообществ
etl/graph_builder/schema.yaml     — Схема сообществ
```

**Шаги реализации:**

1. Установить Neo4j GDS library
2. Запустить Leiden алгоритм на графе сущностей
3. Сохранить членство в сообществах как свойство узла
4. Генерировать саммари сообществ через LLM
5. Индексировать саммари в Qdrant для retrieval

**Критерии приёмки:**

- [ ] Сообщества обнаружены с modularity > 0.3
- [ ] Саммари сообществ сгенерированы для всех сообществ
- [ ] Саммари проиндексированы и доступны для retrieval
- [ ] Обнаружение сообществ работает < 10min для 10K узлов

---

### 3.2 Global Search Mode

**Цель**: Отвечать на вопросы по всему корпусу используя community summaries

**Зачем**: Некоторые вопросы требуют понимания по всей базе знаний, а не только конкретных документов.

**Исследование**: GraphRAG global search — map-reduce по community summaries.

**Файлы для модификации:**

```
proxy/app/core/retrieval.py      — Global search режим
proxy/app/api/chat.py            — Экспонировать global search параметр
```

**Новые файлы:**

```
tests/proxy/test_global_search.py — Global search тесты
```

**Шаги реализации:**

1. Определить является ли запрос "global" (по всему корпусу) или "local" (конкретный)
2. Для global: извлечь все community summaries
3. Map: сгенерировать частичные ответы из каждого саммари
4. Reduce: объединить частичные ответы в финальный ответ
5. Включить community источники в ответ

**Критерии приёмки:**

- [ ] Global запросы возвращают ответы на уровне сообществ
- [ ] Источники включают community summaries
- [ ] Задержка global search < 5s
- [ ] Качество ответа > 0.7 (human eval)

---

### 3.3 Multi-Hop Reasoning

**Цель**: Обход графа для сложных запросов требующих множественных сущностей

**Зачем**: Некоторые вопросы требуют следования по связям сущностей через несколько хопов.

**Исследование**: Knowledge graph traversal для multi-hop QA.

**Файлы для модификации:**

```
proxy/app/core/retrieval.py      — graph_expand() улучшение
```

**Новые файлы:**

```
tests/proxy/test_multi_hop.py    — Multi-hop тесты
```

**Шаги реализации:**

1. Извлечь сущности из запроса
2. Найти сущности в Neo4j
3. Обойти граф до 3 хопов
4. Собрать связанные документы
5. Объединить с результатами векторного retrieval

**Критерии приёмки:**

- [ ] 3+ hop запросы отвечаются корректно
- [ ] Обход графа добавляет релевантный контекст
- [ ] Задержка < 500ms для 3-hop обхода
- [ ] Нет циклических обходов

---

## Phase 4 — Production Hardening (Week 7-8) [HIGH]

> **Цель**: Достичь production-grade качества, безопасности и наблюдаемости  
> **Риск**: LOW — инкрементальные улучшения  
> **Зависимости**: Все фазы фич

### 4.1 TDD/BDD Test Coverage

**Цель**: 90%+ покрытие тестами с реальными behavioral тестами

**Зачем**: Текущие тесты в основном unit тесты. Нужны интеграционные и behavioral тесты.

**Стратегия**: Given-When-Then для всех user stories.

**Файлы для модификации:**

```
All test files                    — Добавить behavioral тесты
tests/conftest.py                — Shared фикстуры
```

**Новые файлы:**

```
tests/bdd/                       — BDD feature файлы
pytest.ini                       — Pytest конфигурация
```

**Критерии приёмки:**

- [ ] Покрытие > 90% (измерено через `pytest --cov`)
- [ ] 0 фейковых тестов (все тесты верифицируют реальное поведение)
- [ ] Все user stories имеют BDD сценарии
- [ ] CI падает при снижении покрытия

**Категории тестов:**
| Категория | Количество | Цель покрытия |
|-----------|------------|---------------|
| Unit | 200+ | 95% |
| Integration | 50+ | 80% |
| BDD | 30+ | Все user stories |
| E2E | 10+ | Критические пути |

---

### 4.2 CI/CD Pipeline

**Цель**: Полный GitHub Actions pipeline с quality gates

**Зачем**: Автоматизированные проверки качества на каждый PR.

**Новые файлы:**

```
.github/workflows/ci.yml         — Основной CI pipeline
.github/workflows/security.yml   — Security scanning
.github/workflows/release.yml    — Автоматизация релизов
```

**Этапы Pipeline:**

```yaml
stages:
  - lint:        ruff check, ruff format --check
  - typecheck:   mypy --strict
  - test:        pytest --cov --cov-fail-under=80
  - security:    bandit, trivy, codeql
  - build:       docker build
  - deploy:      staging (on main)
```

**Критерии приёмки:**

- [ ] Все gates проходят на каждый PR
- [ ] PR блокируется при падении любого gate
- [ ] Отчёт покрытия в PR comments
- [ ] Результаты security scan в PR

---

### 4.3 Security Hardening

**Цель**: Исправить все находки безопасности, включить Dependabot

**Зачем**: Baseline безопасности для production.

**Новые файлы:**

```
.github/dependabot.yml           — Обновления зависимостей
.github/workflows/codeql.yml     — Сканирование кода
```

**Файлы для модификации:**

```
proxy/app/auth/                  — Security fixes
requirements_proxy.txt           — Pin versions
```

**Критерии приёмки:**

- [ ] 0 critical/high уязвимостей (Trivy)
- [ ] 0 high/critical проблем кода (Bandit)
- [ ] Dependabot включён для всех экосистем
- [ ] Secrets scanning включён

---

### 4.4 Observability

**Цель**: Структурное логирование, метрики, трейсинг

**Зачем**: Production debugging и мониторинг.

**Файлы для модификации:**

```
proxy/app/shared/logging.py      — Структурное JSON логирование
proxy/app/shared/metrics.py      — Prometheus метрики
proxy/app/shared/tracing.py      — OpenTelemetry трейсинг
```

**Новые файлы:**

```
config/monitoring/prometheus.yml — Prometheus конфигурация
config/monitoring/grafana/       — Grafana дашборды
```

**Метрики для отслеживания:**
| Метрика | Тип | Описание |
|---------|-----|----------|
| `rag_retrieval_latency_ms` | Histogram | Задержка retrieval |
| `rag_rerank_latency_ms` | Histogram | Задержка реранжирования |
| `rag_llm_latency_ms` | Histogram | Задержка генерации LLM |
| `rag_ragas_faithfulness` | Gauge | RAGAS faithfulness score |
| `rag_hallucination_rate` | Counter | Детекции галлюцинаций |
| `rag_negative_rejection_rate` | Counter | Negative rejections |
| `rag_cache_hit_rate` | Gauge | Эффективность кэша |

**Критерии приёмки:**

- [ ] Все запросы трейсятся с correlation ID
- [ ] Метрики экспортируются в Prometheus
- [ ] Grafana дашборды operational
- [ ] Алерты настроены для SLA нарушений

---

## Phase 5 — Advanced Features (Week 9-12) [MEDIUM]

> **Цель**: Реализовать cutting-edge RAG техники  
> **Риск**: LOW — optional enhancements  
> **Зависимости**: Phase 1-4 complete

### 5.1 FLARE Active Retrieval

**Цель**: Мониторить уверенность генерации, повторно извлекать при низкой

**Зачем**: Для длинных ответов начальный retrieval может быть недостаточным. FLARE триггерит повторный retrieval mid-generation.

**Исследование**: FLARE paper — active retrieval во время генерации.

**Файлы для модификации:**

```
proxy/app/core/orchestrator/nodes.py — FLARE node
proxy/app/core/orchestrator/graph.py — Добавить FLARE loop
```

**Новые файлы:**

```
tests/proxy/test_flare.py           — FLARE тесты
```

**Шаги реализации:**

1. Мониторить token probabilities во время генерации
2. Если confidence < порога, приостановить генерацию
3. Сгенерировать гипотетический запрос из частичного ответа
4. Извлечь дополнительный контекст
5. Возобновить генерацию с новым контекстом

**Критерии приёмки:**

- [ ] Длинные ответы поддерживают качество на протяжении всего текста
- [ ] Повторный retrieval триггерится при падении уверенности
- [ ] Увеличение задержки < 30% для длинных ответов
- [ ] Нет бесконечных циклов повторного retrieval (макс 2)

---

### 5.2 Two-Stage Reranking

**Цель**: Быстрый embed (30-50ms) → cross-encoder (150-400ms)

**Зачем**: Текущий реранжинг применяет cross-encoder ко всем кандидатам. Two-stage быстрее.

**Файлы для модификации:**

```
proxy/app/core/rerank.py            — Two-stage реализация
```

**Новые файлы:**

```
tests/proxy/test_rerank.py          — Reranking тесты
```

**Шаги реализации:**

1. Stage 1: Быстрый embedding rerank (top-50 → top-15)
2. Stage 2: Cross-encoder rerank (top-15 → top-5)
3. Настраиваемые пороги stage
4. Fallback на single-stage при необходимости

**Критерии приёмки:**

- [ ] 50% снижение задержки при том же качестве
- [ ] Stage 1 задержка < 50ms
- [ ] Stage 2 задержка < 400ms
- [ ] Качество в пределах 2% от single-stage

---

### 5.3 Adaptive Chunking

**Цель**: Динамический размер чанка на основе структуры документа

**Зачем**: Фиксированный размер чанка разрывает семантические единицы. Adaptive уважает структуру документа.

**Файлы для модификации:**

```
etl/chunker/semantic_chunker.py    — Adaptive логика
```

**Новые файлы:**

```
tests/etl/test_adaptive_chunking.py — Adaptive тесты
```

**Шаги реализации:**

1. Анализировать структуру документа (заголовки, параграфы, списки)
2. Установить базовый размер чанка по типу документа
3. Скорректировать границы для уважения семантических единиц
4. Объединить маленькие чанки, разделить большие
5. Сохранить метаданные (секция, страница и т.д.)

**Критерии приёмки:**

- [ ] Качество чанков > 0.8 по всем типам документов
- [ ] Нет разорванных предложений на границах чанков
- [ ] Метаданные секций сохранены
- [ ] Работает для Confluence, Jira, GitLab, docs

---

## Архитектурные решения

### ADR-015: ColBERT Integration

- **Статус**: Proposed
- **Контекст**: bge-m3 поддерживает ColBERT нативно, storage overhead приемлем
- **Решение**: Сохранять ColBERT векторы рядом с dense векторами в Qdrant
- **Последствия**: +20% storage, +15% precision retrieval, +30ms задержка запроса
- **Альтернативы**: Late interaction во время запроса (отклонено: слишком медленно)

### ADR-016: RAGAS as Quality Gate

- **Статус**: Proposed
- **Контекст**: Нужно систематическое измерение качества RAG
- **Решение**: RAGAS метрики в CI/CD pipeline, блокировка деплоя при регрессии
- **Последствия**: Детекция регрессии качества до деплоя, стоимость оценки
- **Альтернативы**: Ручная оценка (отклонено: не масштабируется)

### ADR-017: Negative Rejection Policy

- **Статус**: Proposed
- **Контекст**: Система галлюцинирует когда нет релевантных документов
- **Решение**: Отказываться генерировать когда < 2 strong sources (score > 0.5)
- **Последствия**: Некоторые запросы получат "Я не знаю" вместо ответа
- **Альтернативы**: Всегда генерировать с дисклеймером (отклонено: подрывает доверие)

---

## Стратегия реализации

### TDD подход (Test-Driven Development)

```
1. Написать падающий тест (RED)
2. Реализовать минимальный код для прохождения (GREEN)
3. Рефакторинг с уверенностью (REFACTOR)
4. Коммит с тестовым доказательством
```

### BDD User Stories (Behavior-Driven Development)

```gherkin
Feature: Negative Rejection
  Scenario: Query with no relevant sources
    Given the knowledge base has no documents about "quantum computing"
    When user asks "What is quantum computing?"
    Then system returns "I don't have enough information"
    And response includes rag_confidence: 0.0

Feature: ColBERT Reranking
  Scenario: Improved precision with ColBERT
    Given documents about "JWT authentication"
    When user asks "How to implement JWT?"
    Then ColBERT-reranked results have higher precision
    And top-3 results are all relevant
```

### DDD Boundaries (Domain-Driven Design)

```
┌─────────────────────────────────────────────────────────────┐
│                    RAG System                               │
├──────────────────┬──────────────────┬───────────────────────┤
│ Retrieval Domain │ Generation Domain│    ETL Domain         │
│                  │                  │                       │
│ retrieval.py     │ orchestrator/    │ extractors/           │
│ hyde.py          │ confidence.py    │ chunker/              │
│ query_enhancer.py│ hallucination.py │ indexer/              │
│ rerank.py        │ grounding.py     │ graph_builder/        │
│ colbert.py       │                  │                       │
├──────────────────┴──────────────────┴───────────────────────┤
│                   Evaluation Domain                         │
│                                                             │
│ evaluation.py    │ ragas_eval.py    │ retrieval_evaluator.py│
└─────────────────────────────────────────────────────────────┘
```

---

## Quality Gates

### Каждый PR должен пройти:

1. `ruff check` — 0 ошибок
2. `ruff format --check` — formatted
3. `mypy --strict` — 0 ошибок (target)
4. `pytest` — все тесты проходят
5. `pytest --cov --cov-fail-under=80` — покрытие ≥ 80%
6. `bandit -r proxy/` — 0 high/critical
7. `trivy fs .` — 0 critical CVEs
8. GitHub CI — всё зелёное

### Каждый релиз должен иметь:

1. CHANGELOG.md обновлён со всеми изменениями
2. Все ADR пересмотрены и приняты
3. Бенчмарки производительности (retrieval, rerank, generation)
4. Отчёт security scan (Bandit, Trivy, CodeQL)
5. Документация обновлена (API, guides, ADRs)
6. RAGAS оценка на тестовом наборе

---

## Мониторинг и наблюдаемость

### Ключевые метрики (SLI):

| SLI                | Определение                   | Цель (SLO) |
|--------------------|-------------------------------|------------|
| Retrieval Latency  | p95 время retrieval            | < 500ms    |
| Rerank Latency     | p95 время реранжирования       | < 400ms    |
| End-to-End Latency | p95 общее время ответа         | < 3s       |
| RAGAS Faithfulness | Ответ основан на контексте     | > 0.8      |
| Hallucination Rate | % ответов с галлюцинацией      | < 5%       |
| Negative Rejection | Корректный отказ               | 100%       |
| Availability       | Uptime                        | > 99.5%    |

### Алерты:

| Алерт              | Условие          | Серьёзность |
|--------------------|------------------|-------------|
| High Latency       | p95 > 2s         | Warning     |
| Critical Latency   | p95 > 5s         | Critical    |
| Low Faithfulness   | RAGAS < 0.7      | Warning     |
| High Hallucination | > 10%            | Critical    |
| Service Down       | Health check fails| Critical    |
| Disk Full          | > 90% usage      | Warning     |

### Grafana дашборды:

1. **RAG Overview**: Request rate, latency, error rate
2. **Retrieval Quality**: RAGAS scores, rerank metrics
3. **ETL Pipeline**: Indexing rate, chunk quality, tree depth
4. **Infrastructure**: CPU, memory, disk, network

---

## Митигация рисков

| Риск                           | Вероятность | Влияние | Митигация                          | Владелец    |
|--------------------------------|-------------|---------|------------------------------------|------------|
| ColBERT storage overhead       | High        | Medium  | Квантование векторов (int8), IVF index | ETL Lead   |
| RAPTOR build time              | Medium      | Low     | Async ETL, трекинг прогресса       | ETL Lead   |
| NLI model memory               | Medium      | Medium  | Дистиллированная модель, lazy loading | Proxy Lead |
| GraphRAG complexity            | High        | High    | Начать только с local search       | Architect  |
| RAGAS evaluation cost          | Medium      | Low     | Sample-based, async                | QA Lead    |
| Negative rejection over-refuse | Medium      | Medium  | A/B тест, экспертный review        | Product    |
| Neo4j GDS dependency           | Low         | High    | Fallback на простые graph queries  | Architect  |

---

## Метрики успеха

| Метрика                   | Текущее | Цель     | Дедлайн  | Владелец    |
|---------------------------|---------|----------|----------|------------|
| Test coverage             | ~77%    | 90%      | Week 4   | QA Lead    |
| RAGAS faithfulness        | N/A     | > 0.8    | Week 2   | Proxy Lead |
| Hallucination rate        | Unknown | < 5%     | Week 4   | Proxy Lead |
| Retrieval latency p95     | ~500ms  | < 300ms  | Week 6   | Proxy Lead |
| Negative rejection        | 0%      | 100%     | Week 1   | Proxy Lead |
| ColBERT precision gain    | 0%      | +15%     | Week 2   | ETL Lead   |
| Multi-query recall gain   | 0%      | +10%     | Week 4   | Proxy Lead |
| Security vulnerabilities  | ?       | 0 critical| Week 8  | DevOps     |

---

## Зависимости

### Внешние:

| Зависимость    | Назначение               | Статус         | Действие               |
|----------------|--------------------------|----------------|------------------------|
| bge-m3 model   | ColBERT vectors          | Available      | Verify ColBERT support |
| Neo4j GDS      | Community detection      | Needs install  | Add to docker-compose  |
| NLI model      | Hallucination detection  | Needs download | Pre-download offline   |
| RAGAS library  | Quality metrics          | Needs install  | Add to requirements    |

### Внутренние:

| Зависимость                | Влияние          | Действие           |
|---------------------------|------------------|-------------------|
| Qdrant collection rebuild | ColBERT vectors  | Migration script  |
| Neo4j schema update       | Communities      | Schema migration  |
| Config update             | New features     | .env updates      |
| Test infrastructure       | BDD support      | pytest-bdd setup  |

---

## План отката

Каждая фаза independently deployable с возможностью отката:

1. **Feature Flags**: Новое поведение за `ENABLE_COLBERT`, `ENABLE_RAPTOR` и т.д.
2. **A/B Testing**: Сравнение нового vs старого с разделением трафика
3. **Circuit Breakers**: Отключение новых компонентов при сбое
4. **WAL для ETL**: Возобновление с чекпоинта при сбое построения дерева
5. **Database Migrations**: Обратимые изменения схемы

---

## План коммуникации

### Еженедельно:

- Обновление прогресса в `project-checklist.md`
- Результаты тестов в CI/CD dashboard
- Сводка результатов security scan
- Обновление risk register

### Per change:

- Git commit с clear message (conventional commits)
- CHANGELOG.md запись
- ADR для архитектурных решений
- Memory update для persistence контекста

### Milestones:

| Неделя | Milestone              | Deliverable                                |
|--------|------------------------|--------------------------------------------|
| 2      | Foundation Complete    | ColBERT, RAGAS, Negative Rejection, NLI    |
| 4      | Advanced Retrieval     | RAPTOR, Multi-Query, Knee-Point            |
| 6      | Knowledge Graph        | GraphRAG, Global Search, Multi-Hop         |
| 8      | Production Ready       | Tests, CI/CD, Security, Observability      |
| 12     | Advanced Features      | FLARE, Two-Stage Rerank, Adaptive Chunking |

---

## Приложение

### A. Источники исследования

**Habr статьи** (19):

1. RAG best practices для production
2. ColBERT интеграция с Qdrant
3. RAPTOR построение дерева
4. GraphRAG обнаружение сообществ
5. RAGAS фреймворк оценки
6. FLARE активный retrieval
7. HyDE расширение запроса
8. Стратегии семантического чанкинга
9. Cross-encoder реранжирование
10. Гибридный поиск с RRF
11. Knowledge graph для RAG
12. Техники оптимизации токенов
13. Стратегии сжатия контекста
14. Методы детекции галлюцинаций
15. Паттерны negative rejection
16. Multi-hop рассуждения
17. Техники переформулировки запросов
18. Анализ распределения скоров
19. RAG наблюдаемость

**Академические работы** (12):

1. RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval (Stanford 2024)
2. ColBERTv2: Effective and Efficient Retrieval via Lightweight Late Interaction
3. GraphRAG: Unlocking LLM Discovery on Narrative Private Data (Microsoft 2024)
4. RAGAS: Automated Evaluation of Retrieval Augmented Generation
5. FLARE: Forward-Looking Active REtrieval Augmented Generation
6. HyDE: Precise Zero-Shot Dense Retrieval without Relevance Labels
7. Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks
8. Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods
9. NLI-based Hallucination Detection
10. Semantic Chunking for RAG
11. Token-Level Late Interaction
12. Adaptive Retrieval for RAG

### B. Глоссарий

| Термин    | Определение                                                   |
|-----------|---------------------------------------------------------------|
| ColBERT   | Contextualized Late Interaction over BERT                     |
| RAPTOR    | Recursive Abstractive Processing for Tree-Organized Retrieval |
| GraphRAG  | Graph-based Retrieval Augmented Generation                    |
| RAGAS     | Retrieval Augmented Generation Assessment                     |
| FLARE     | Forward-Looking Active REtrieval                              |
| HyDE      | Hypothetical Document Embeddings                              |
| RRF       | Reciprocal Rank Fusion                                        |
| NLI       | Natural Language Inference                                    |
| MaxSim    | Maximum Similarity (ColBERT scoring)                          |
| Leiden    | Community detection algorithm                                 |

---

*Этот план — living документ. Обновляйте еженедельно с прогрессом, рисками и решениями.*

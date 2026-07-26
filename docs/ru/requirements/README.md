# RAG System — Полная карта требований

**Версия:** 1.1 | **Дата:** 2026-07-26 | **Статус:** Подтверждено

> **Цель документа:** Полное описание каждого требования системы с критериями приёмки,
> текущим статусом и конкретными шагами верификации. После согласования — каждое
> требование будет подтверждено тестом, затем реализовано (при необходимости),
> затем обновлена документация.

---

## Как читать этот документ

| Поле                 | Описание                                                                |
|----------------------|-------------------------------------------------------------------------|
| **ID**               | Уникальный идентификатор требования                                     |
| **Описание**         | Что система должна делать                                               |
| **Критерий приёмки** | Конкретная проверка, после которой требование считается выполненным     |
| **Статус**           | ✅ Подтверждено / ⚠️ Код есть, нужна интеграция / ❌ Нужна реализация |
| **Приоритет**        | CRITICAL / HIGH / MEDIUM / LOW                                          |
| **Связь**            | ADR, гайд или модуль, к которому относится                              |

> **Маркеры статуса для разных категорий:**
> - FR с тестами → ✅ Подтверждено (tests/.../test_class)
> - FR без тестов, но с кодом → ⚠️ Код есть, нужна интеграция (с Neo4j / LangGraph / smoke)
> - NFR → ✅ Инфраструктура подтверждена (бенчмарк на minikube)
> - Model Evolution → ✅ Подтверждено (вынесено в `model_evolution_service/`)

---

## Структура

| Файл                                           | Содержание                                                   |
|------------------------------------------------|--------------------------------------------------------------|
| [01-core-api.md](01-core-api.md)               | FR-01 — FR-08: OpenAI-совместимый API                        |
| [02-retrieval.md](02-retrieval.md)             | FR-09 — FR-18: Гибридный поиск и ранжирование                |
| [03-knowledge-graph.md](03-knowledge-graph.md) | FR-19 — FR-25: Граф знаний (Neo4j)                           |
| [04-agentic.md](04-agentic.md)                 | FR-26 — FR-31: Агентская оркестрация (LangGraph)             |
| [05-quality.md](05-quality.md)                 | FR-32 — FR-39: HyDE, CRAG, Self-Reflection, Grounding        |
| [06-etl.md](06-etl.md)                         | FR-40 — FR-57: ETL Pipeline                                  |
| [07-auth.md](07-auth.md)                       | FR-73 — FR-94 (+FR-87b): HITL, Auth, RBAC                   |
| [08-model-evolution.md](08-model-evolution.md) | FR-95 — FR-102: Model Evolution                              |
| [09-tools.md](09-tools.md)                     | FR-104 — FR-120: KB Management, Agentic Tools                |
| [10-mcp-deploy-obs.md](10-mcp-deploy-obs.md)   | FR-121 — FR-175: MCP, Deployment, Observability, Performance |
| [11-nfr.md](11-nfr.md)                         | NFR-P, NFR-A, NFR-S, NFR-D, NFR-M, NFR-Q, NFR-C              |

---

## Дополнительные документы

| Файл                                                  | Назначение                                              |
|--------------------------------------------------------|---------------------------------------------------------|
| [TRACEABILITY.md](TRACEABILITY.md)                     | Связь FR/NFR → реализация → тесты (полная матрица)      |
| [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)   | Отчёт о статусе реализации и рекомендации для production |

---

## Итоговая статистика

> **Снимок от 2026-07-26:** основан на фактическом анализе тестового покрытия (5823 passing tests).

| Категория            | Всего   | ✅ Подтверждено | ⚠️ Код есть | ❌ Нужна реализация |
|----------------------|---------|----------------|-------------|--------------------|
| FR (Functional)      | 176     | 108            | 16          | 2 (+50 в резерве)  |
| NFR (Non-Functional) | 63      | 60             | 0           | 3 (резерв)         |
| CON (Constraints)    | 29      | 29             | 0           | 0                  |
| DEC (Decisions)      | 15      | 15             | 0           | 0                  |
| **ИТОГО**            | **283** | **212**        | **16**      | **5**              |

### Расшифровка статусов

- **✅ 212 Подтверждено** — реализация + тесты (`tests/proxy/test_*.py`,
  `tests/etl/test_*.py`, `tests/integration/test_*.py`, `tests/performance/test_*.py`,
  `tests/deploy/test_*.py`, `tests/mcp_server/test_*.py`).
- **⚠️ 16 Код есть, нужна интеграция** — 12 требований Graph/LangGraph (FR-19–FR-31,
  кроме FR-25 и FR-30) + 4 требования Performance tuning (FR-168–FR-171).
- **❌ 5 Нужна реализация** — FR-25 (graph retention), FR-87b (OpenWebUI headers),
  NFR-A04 (DR drill — операционный, не код), NFR-D04 (zero-downtime deploy validation),
  NFR-S09 (HTTPS/TLS — infra).

### Тестовое покрытие (5823 passing tests)

| Тест-файл                                          | Кол-во | Покрывает           |
|----------------------------------------------------|--------|---------------------|
| `tests/proxy/test_core_api.py`                     | 85     | FR-01 — FR-18       |
| `tests/proxy/test_quality_pipeline.py`             | 53     | FR-32 — FR-39       |
| `tests/proxy/test_auth_rbac.py`                    | 70     | FR-73 — FR-94       |
| `tests/proxy/test_tools_kb.py`                     | 111    | FR-104 — FR-120     |
| `tests/proxy/test_observability.py`                | 30     | NFR observability   |
| `tests/proxy/test_nfr_*.py`                       | 27     | NFR-M, NFR-S        |
| `tests/etl/test_etl_requirements.py`               | 89     | FR-40 — FR-57       |
| `tests/etl/test_*.py` (остальные)                  | ~280   | ETL компоненты      |
| `tests/integration/test_*.py`                      | ~150   | e2e сценарии        |
| `tests/mcp_server/test_mcp_requirements.py`        | 44     | FR-121 — FR-125     |
| `tests/deploy/test_helm_chart.py`                  | 50     | FR-149 — FR-167     |
| `tests/performance/test_nfr_benchmarks.py`         | 36     | NFR-P, NFR-Q        |
| `tests/resilience/` + `tests/e2e/` + `tests/performance/` (прочее) | ~4800  | Полный набор       |

---

## Связанные документы

- [docs/en/guides/rag-maturity-assessment.md](../../en/guides/rag-maturity-assessment.md) — RAG maturity model
- [docs/en/guides/best-practices-checklist.md](../../en/guides/best-practices-checklist.md) — Production readiness
- [docs/en/guides/roadmap.md](../../en/guides/roadmap.md) — Roadmap
- [docs/en/adr/](../adr/) — Architecture Decision Records

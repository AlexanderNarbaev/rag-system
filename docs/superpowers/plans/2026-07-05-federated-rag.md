# Federated RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a federated proxy layer that fans out RAG queries to multiple independent silo proxies, merges results via weighted RRF, and returns unified OpenAI-compatible responses.

**Architecture:** New `federation/` component as standalone FastAPI service. Fan-out to silo proxies over HTTP, merge with weighted RRF, delegate generation to primary silo. Three isolation modes (strict/merge/auto) with RBAC gates and per-silo circuit breakers.

**Tech Stack:** FastAPI, httpx (async HTTP), pytest + pytest-asyncio, prometheus_client, Python dataclasses

## Global Constraints

- Backward-compatible: existing proxy clients unaffected
- Graceful degradation on partial silo failure (never 500 if any silo responds)
- One primary silo required for generation delegation; if missing, call LLM directly
- RBAC: `user.groups ∩ silo.access_groups ≠ ∅` for every silo query
- Federation is read-path only; no indexing coordination
- TDD: every task writes the test first, verifies it fails, then implements

---

### Task 1: Project Scaffold & Configuration

**Files:**
- Create: `federation/app/__init__.py`
- Create: `federation/app/exceptions.py`
- Create: `federation/app/config.py`
- Create: `federation/app/models.py`
- Create: `federation/.env.example`
- Create: `federation/requirements.txt`

**Interfaces:**
- Consumes: nothing
- Produces: `SiloConfig`, `SiloSearchResult`, `FederatedSearchResult`, `FederationContext` dataclasses; all config globals from `config.py`; `FederationError` base exception

- [ ] **Step 1: Write test for config loading**

```python
# federation/tests/test_config.py
import os
import json
import pytest
from federation.app.config import load_silos, FEDERATION_MODE, FEDERATION_MERGE_K, FEDERATION_RRF_K


SAMPLE_SILOS_JSON = json.dumps([
    {
        "id": "hr",
        "name": "HR Knowledge Base",
        "proxy_url": "http://rag-hr:8000/v1",
        "api_key": "sk-hr",
        "weight": 1.0,
        "access_groups": ["hr", "admin"],
        "collections": ["hr_policies"],
        "timeout_s": 10,
        "is_primary": False
    },
    {
        "id": "engineering",
        "name": "Engineering Wiki",
        "proxy_url": "http://rag-eng:8000/v1",
        "api_key": "sk-eng",
        "weight": 1.2,
        "access_groups": ["engineering", "admin"],
        "collections": ["confluence", "jira"],
        "timeout_s": 10,
        "is_primary": True
    }
])


class TestConfig:
    def test_load_silos_from_env_json(self, monkeypatch):
        monkeypatch.setenv("FEDERATION_INSTANCES_JSON", SAMPLE_SILOS_JSON)
        import federation.app.config as cfg
        monkeypatch.setattr(cfg, "FEDERATION_INSTANCES_JSON", SAMPLE_SILOS_JSON)
        from federation.app.config import load_silos
        silos = load_silos()
        assert len(silos) == 2
        assert silos[0].id == "hr"
        assert silos[0].weight == 1.0
        assert silos[1].id == "engineering"
        assert silos[1].is_primary is True

    def test_load_silos_empty_returns_list(self):
        from federation.app.config import load_silos
        import federation.app.config as cfg
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cfg, "FEDERATION_INSTANCES_JSON", "[]")
        silos = load_silos()
        assert silos == []

    def test_default_config_values(self, monkeypatch):
        monkeypatch.setenv("FEDERATION_MODE", "merge")
        monkeypatch.setenv("FEDERATION_MERGE_K", "40")
        from federation.app.config import load_config
        # Re-import to pick up monkeypatched env
        import importlib
        import federation.app.config
        importlib.reload(federation.app.config)
        from federation.app import config as cfg
        assert cfg.FEDERATION_MODE == "merge"
        assert cfg.FEDERATION_MERGE_K == 40
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest federation/tests/test_config.py -v
```
Expected: FAIL — `federation.app.config` module not found

- [ ] **Step 3: Create directory structure**

```bash
mkdir -p federation/app federation/tests
touch federation/app/__init__.py
touch federation/tests/__init__.py
```

- [ ] **Step 4: Write exceptions.py**

```python
# federation/app/exceptions.py
class FederationError(Exception):
    """Base exception for federation layer."""
    pass


class SiloUnavailableError(FederationError):
    """A silo is unreachable or circuit breaker is open."""
    def __init__(self, silo_id: str, reason: str = ""):
        self.silo_id = silo_id
        self.reason = reason
        super().__init__(f"Silo '{silo_id}' unavailable: {reason}")


class AllSilosDownError(FederationError):
    """All configured silos are unavailable."""
    def __init__(self, failed_silos: list[str]):
        self.failed_silos = failed_silos
        super().__init__(f"All silos unavailable: {failed_silos}")


class AccessDeniedError(FederationError):
    """User does not have access to requested silo."""
    def __init__(self, silo_id: str, user_groups: list[str]):
        self.silo_id = silo_id
        self.user_groups = user_groups
        super().__init__(f"Access denied to silo '{silo_id}' for groups {user_groups}")


class ConfigError(FederationError):
    """Invalid federation configuration."""
    pass
```

- [ ] **Step 5: Write models.py**

```python
# federation/app/models.py
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SiloConfig:
    id: str
    name: str
    proxy_url: str
    weight: float = 1.0
    access_groups: list[str] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    api_key: Optional[str] = None
    timeout_s: int = 10
    is_primary: bool = False

    def is_accessible_by(self, user_groups: list[str]) -> bool:
        return bool(set(user_groups) & set(self.access_groups))


@dataclass
class SiloSearchResult:
    silo_id: str
    silo_name: str
    chunks: list[dict]
    latency_ms: float
    error: Optional[str] = None
    partial: bool = False


@dataclass
class FederatedSearchResult:
    query: str
    merged_chunks: list[dict]
    silo_results: list[SiloSearchResult]
    total_latency_ms: float
    errors: list[str] = field(default_factory=list)
    skipped_silos: list[str] = field(default_factory=list)


@dataclass
class FederationContext:
    mode: str
    target_silos: list[str]
    merge_strategy: str
    merge_k: int
    rrf_k: int
    user_groups: list[str]
    cross_silo: bool = False
    query: str = ""
```

- [ ] **Step 6: Write config.py**

```python
# federation/app/config.py
import os
import json
from .models import SiloConfig
from .exceptions import ConfigError


FEDERATION_MODE = os.getenv("FEDERATION_MODE", "auto")
FEDERATION_INSTANCES_JSON = os.getenv("FEDERATION_INSTANCES_JSON", "[]")
FEDERATION_INSTANCES_FILE = os.getenv("FEDERATION_INSTANCES_FILE", "")
FEDERATION_MERGE_STRATEGY = os.getenv("FEDERATION_MERGE_STRATEGY", "weighted_rrf")
FEDERATION_MERGE_K = int(os.getenv("FEDERATION_MERGE_K", "60"))
FEDERATION_RRF_K = int(os.getenv("FEDERATION_RRF_K", "60"))
FEDERATION_TOTAL_TIMEOUT_S = int(os.getenv("FEDERATION_TOTAL_TIMEOUT_S", "30"))
FEDERATION_PER_INSTANCE_TIMEOUT_S = int(os.getenv("FEDERATION_PER_INSTANCE_TIMEOUT_S", "10"))
FEDERATION_CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("FEDERATION_CIRCUIT_BREAKER_THRESHOLD", "5"))
FEDERATION_CIRCUIT_BREAKER_RECOVERY_S = int(os.getenv("FEDERATION_CIRCUIT_BREAKER_RECOVERY_S", "30"))
FEDERATION_LLM_ENDPOINT = os.getenv("FEDERATION_LLM_ENDPOINT", "")
FEDERATION_LLM_MODEL = os.getenv("FEDERATION_LLM_MODEL", "")
FEDERATION_AUTO_SLM_ENABLED = os.getenv("FEDERATION_AUTO_SLM_ENABLED", "true").lower() == "true"


def _load_json_silos(json_str: str) -> list[SiloConfig]:
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid FEDERATION_INSTANCES_JSON: {e}")
    if not isinstance(data, list):
        raise ConfigError("FEDERATION_INSTANCES_JSON must be a JSON array")
    silos = []
    for item in data:
        try:
            silos.append(SiloConfig(
                id=item["id"],
                name=item["name"],
                proxy_url=item["proxy_url"],
                weight=float(item.get("weight", 1.0)),
                access_groups=item.get("access_groups", []),
                collections=item.get("collections", []),
                api_key=item.get("api_key"),
                timeout_s=int(item.get("timeout_s", 10)),
                is_primary=bool(item.get("is_primary", False)),
            ))
        except KeyError as e:
            raise ConfigError(f"Missing required field {e} in silo config")
    return silos


def load_silos() -> list[SiloConfig]:
    if FEDERATION_INSTANCES_FILE:
        with open(FEDERATION_INSTANCES_FILE) as f:
            json_str = f.read()
    else:
        json_str = FEDERATION_INSTANCES_JSON
    return _load_json_silos(json_str)


def get_primary_silo(silos: list[SiloConfig]) -> SiloConfig | None:
    primaries = [s for s in silos if s.is_primary]
    if len(primaries) > 1:
        import logging
        logging.getLogger("federation").warning(
            f"Multiple primary silos configured: {[s.id for s in primaries]}. Using {primaries[0].id}."
        )
    return primaries[0] if primaries else None
```

- [ ] **Step 7: Write requirements.txt and .env.example**

```bash
# federation/requirements.txt
cat > federation/requirements.txt << 'EOF'
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
httpx>=0.27.0
prometheus-client>=0.20.0
python-dotenv>=1.0.0
EOF

# federation/.env.example
cat > federation/.env.example << 'EOF'
FEDERATION_MODE=auto
FEDERATION_INSTANCES_JSON='[{"id":"hr","name":"HR KB","proxy_url":"http://localhost:8000/v1","weight":1.0,"access_groups":["admin"],"collections":["knowledge_base"],"is_primary":true}]'
FEDERATION_MERGE_STRATEGY=weighted_rrf
FEDERATION_MERGE_K=60
FEDERATION_RRF_K=60
FEDERATION_TOTAL_TIMEOUT_S=30
FEDERATION_PER_INSTANCE_TIMEOUT_S=10
FEDERATION_CIRCUIT_BREAKER_THRESHOLD=5
FEDERATION_CIRCUIT_BREAKER_RECOVERY_S=30
FEDERATION_LLM_ENDPOINT=http://localhost:8000/v1
FEDERATION_LLM_MODEL=llama-3
FEDERATION_AUTO_SLM_ENABLED=true
EOF
```

- [ ] **Step 8: Run test to verify it passes**

```bash
python -m pytest federation/tests/test_config.py -v
```
Expected: PASS

- [ ] **Step 9: Write test for models (RBAC gate)**

```python
# federation/tests/test_models.py
from federation.app.models import SiloConfig


class TestSiloConfig:
    def test_is_accessible_by_matching_group(self):
        silo = SiloConfig(
            id="hr", name="HR", proxy_url="http://localhost/v1",
            access_groups=["hr", "admin"]
        )
        assert silo.is_accessible_by(["hr"]) is True
        assert silo.is_accessible_by(["engineering", "admin"]) is True

    def test_is_accessible_by_no_match(self):
        silo = SiloConfig(
            id="finance", name="Finance", proxy_url="http://localhost/v1",
            access_groups=["finance", "admin"]
        )
        assert silo.is_accessible_by(["engineering"]) is False

    def test_is_accessible_by_empty_groups(self):
        silo = SiloConfig(
            id="hr", name="HR", proxy_url="http://localhost/v1",
            access_groups=["hr"]
        )
        assert silo.is_accessible_by([]) is False
```

```bash
python -m pytest federation/tests/test_models.py -v
```
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add federation/ && git commit -m "feat(federation): project scaffold — config, models, exceptions"
```

---

### Task 2: Silo Registry — Load & Validate

**Files:**
- Create: `federation/app/silo_registry.py`
- Create: `federation/tests/test_silo_registry.py`

**Interfaces:**
- Consumes: `SiloConfig` from `models.py`, `load_silos()` from `config.py`
- Produces: `class SiloRegistry` — `__init__(silos)`, `get(silo_id)`, `list_all()`, `list_accessible(user_groups)`, `get_primary()`, `validate()`

- [ ] **Step 1: Write test for SiloRegistry**

```python
# federation/tests/test_silo_registry.py
import pytest
from federation.app.models import SiloConfig
from federation.app.silo_registry import SiloRegistry
from federation.app.exceptions import ConfigError


HR_SILO = SiloConfig(
    id="hr", name="HR KB", proxy_url="http://hr:8000/v1",
    weight=1.0, access_groups=["hr", "admin"], is_primary=True
)
ENG_SILO = SiloConfig(
    id="engineering", name="Engineering Wiki", proxy_url="http://eng:8000/v1",
    weight=1.2, access_groups=["engineering", "admin"], is_primary=False
)
FIN_SILO = SiloConfig(
    id="finance", name="Finance Docs", proxy_url="http://fin:8000/v1",
    weight=0.8, access_groups=["finance", "admin"], is_primary=False
)


class TestSiloRegistry:
    def test_get_by_id(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO])
        assert reg.get("hr") == HR_SILO
        assert reg.get("engineering") == ENG_SILO
        assert reg.get("nonexistent") is None

    def test_list_all(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO])
        assert len(reg.list_all()) == 2

    def test_list_accessible_filters_by_user_groups(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO, FIN_SILO])
        accessible = reg.list_accessible(["engineering"])
        assert len(accessible) == 1
        assert accessible[0].id == "engineering"

    def test_list_accessible_admin_sees_all(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO, FIN_SILO])
        accessible = reg.list_accessible(["admin"])
        assert len(accessible) == 3

    def test_get_primary(self):
        reg = SiloRegistry([HR_SILO, ENG_SILO])
        assert reg.get_primary() == HR_SILO

    def test_get_primary_none_when_no_primary(self):
        reg = SiloRegistry([SiloConfig(id="x", name="X", proxy_url="http://x/v1")])
        assert reg.get_primary() is None

    def test_validate_duplicate_ids_raises(self):
        with pytest.raises(ConfigError, match="Duplicate silo id"):
            SiloRegistry([HR_SILO, HR_SILO])

    def test_validate_negative_weight_raises(self):
        bad = SiloConfig(id="bad", name="Bad", proxy_url="http://bad/v1", weight=-1.0)
        with pytest.raises(ConfigError, match="weight"):
            SiloRegistry([bad])

    def test_validate_missing_url_raises(self):
        bad = SiloConfig(id="bad", name="Bad", proxy_url="")
        with pytest.raises(ConfigError, match="proxy_url"):
            SiloRegistry([bad])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest federation/tests/test_silo_registry.py -v
```
Expected: FAIL — `No module named 'federation.app.silo_registry'`

- [ ] **Step 3: Implement SiloRegistry**

```python
# federation/app/silo_registry.py
from .models import SiloConfig
from .exceptions import ConfigError


class SiloRegistry:
    def __init__(self, silos: list[SiloConfig]):
        self._silos: dict[str, SiloConfig] = {}
        self.validate(silos)
        for silo in silos:
            self._silos[silo.id] = silo

    def validate(self, silos: list[SiloConfig]) -> None:
        seen: set[str] = set()
        for silo in silos:
            if silo.id in seen:
                raise ConfigError(f"Duplicate silo id: {silo.id}")
            seen.add(silo.id)
            if silo.weight <= 0:
                raise ConfigError(f"Silo '{silo.id}' weight must be > 0, got {silo.weight}")
            if not silo.proxy_url:
                raise ConfigError(f"Silo '{silo.id}' proxy_url is empty")

    def get(self, silo_id: str) -> SiloConfig | None:
        return self._silos.get(silo_id)

    def list_all(self) -> list[SiloConfig]:
        return list(self._silos.values())

    def list_accessible(self, user_groups: list[str]) -> list[SiloConfig]:
        return [s for s in self._silos.values() if s.is_accessible_by(user_groups)]

    def get_primary(self) -> SiloConfig | None:
        primaries = [s for s in self._silos.values() if s.is_primary]
        return primaries[0] if primaries else None

    def __len__(self) -> int:
        return len(self._silos)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest federation/tests/test_silo_registry.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add federation/app/silo_registry.py federation/tests/test_silo_registry.py && git commit -m "feat(federation): silo registry with validation and RBAC filtering"
```

---

### Task 3: Merger — Weighted RRF + Dedup

**Files:**
- Create: `federation/app/merger.py`
- Create: `federation/tests/test_merger.py`

**Interfaces:**
- Consumes: `SiloSearchResult` from `models.py`, `FEDERATION_MERGE_K`, `FEDERATION_RRF_K` from `config.py`
- Produces: `merge_weighted_rrf(results, rrf_k, merge_k) -> list[dict]`, `merge_round_robin(results, merge_k) -> list[dict]`, `merge_top_per_instance(results, merge_k) -> list[dict]`, `deduplicate_chunks(chunks) -> list[dict]`, `merge(results, strategy, rrf_k, merge_k) -> list[dict]`

- [ ] **Step 1: Write test for merger**

```python
# federation/tests/test_merger.py
import pytest
from federation.app.models import SiloSearchResult
from federation.app.merger import (
    deduplicate_chunks,
    merge_weighted_rrf,
    merge_round_robin,
    merge_top_per_instance,
    merge,
)


def make_chunk(chunk_id, text, snippet, score):
    return {"id": chunk_id, "text": text, "snippet": snippet, "score": score}


def make_silo_result(silo_id, silo_name, chunks, latency=100.0):
    return SiloSearchResult(
        silo_id=silo_id,
        silo_name=silo_name,
        chunks=chunks,
        latency_ms=latency,
    )


class TestDeduplicateChunks:
    def test_dedup_removes_duplicate_ids(self):
        chunks = [
            make_chunk("a", "text1", "s1", 0.9),
            make_chunk("a", "text1", "s1", 0.8),
            make_chunk("b", "text2", "s2", 0.7),
        ]
        result = deduplicate_chunks(chunks)
        assert len(result) == 2
        assert result[0]["id"] == "a"
        assert result[0]["score"] == 0.9  # higher score kept

    def test_dedup_empty(self):
        assert deduplicate_chunks([]) == []


class TestMergeWeightedRRF:
    def test_basic_rrf_merge(self):
        silo_a = make_silo_result("hr", "HR KB", [
            make_chunk("a1", "text a1", "s a1", 0.9),
            make_chunk("a2", "text a2", "s a2", 0.7),
        ], latency=100)
        silo_b = make_silo_result("eng", "Engineering Wiki", [
            make_chunk("b1", "text b1", "s b1", 0.95),
            make_chunk("b2", "text b2", "s b2", 0.5),
        ], latency=120)

        result = merge_weighted_rrf([silo_a, silo_b], rrf_k=60, merge_k=4)
        assert len(result) == 4  # all chunks unique, under merge_k
        # b1 should be first (rank 0 in eng)
        assert result[0]["id"] == "b1"

    def test_rrf_with_silo_weights(self):
        # Engineering has weight 1.2, HR has 1.0 — eng chunks should score higher
        silo_a = make_silo_result("hr", "HR KB", [
            make_chunk("a1", "text a1", "s a1", 0.9),
        ])
        silo_b = make_silo_result("eng", "Engineering Wiki", [
            make_chunk("b1", "text b1", "s b1", 0.9),
        ])
        # Same rank in both, but eng has higher weight → b1 first
        result = merge_weighted_rrf([silo_a, silo_b], rrf_k=60, merge_k=2)
        assert result[0]["id"] == "b1"

    def test_rrf_respects_merge_k(self):
        chunks_a = [make_chunk(f"a{i}", f"text a{i}", f"s{i}", 1.0 - i * 0.1) for i in range(5)]
        chunks_b = [make_chunk(f"b{i}", f"text b{i}", f"s{i}", 1.0 - i * 0.1) for i in range(5)]
        silo_a = make_silo_result("hr", "HR KB", chunks_a)
        silo_b = make_silo_result("eng", "Engineering Wiki", chunks_b)
        result = merge_weighted_rrf([silo_a, silo_b], rrf_k=60, merge_k=3)
        assert len(result) == 3

    def test_rrf_empty_results(self):
        result = merge_weighted_rrf([], rrf_k=60, merge_k=10)
        assert result == []


class TestMergeRoundRobin:
    def test_interleaves_chunks(self):
        silo_a = make_silo_result("hr", "HR KB", [
            make_chunk("a1", "text a1", "s1", 0.9),
            make_chunk("a2", "text a2", "s2", 0.7),
        ])
        silo_b = make_silo_result("eng", "Engineering Wiki", [
            make_chunk("b1", "text b1", "s3", 0.95),
            make_chunk("b2", "text b2", "s4", 0.5),
        ])
        result = merge_round_robin([silo_a, silo_b], merge_k=4)
        # a1, b1, a2, b2
        assert [c["id"] for c in result] == ["a1", "b1", "a2", "b2"]

    def test_round_robin_respects_merge_k(self):
        silo_a = make_silo_result("hr", "HR KB", [make_chunk(f"a{i}", f"t{i}", f"s{i}", 0.9) for i in range(10)])
        silo_b = make_silo_result("eng", "Eng KB", [make_chunk(f"b{i}", f"t{i}", f"s{i}", 0.9) for i in range(10)])
        result = merge_round_robin([silo_a, silo_b], merge_k=5)
        assert len(result) == 5


class TestMergeTopPerInstance:
    def test_equal_split(self):
        silo_a = make_silo_result("hr", "HR KB", [
            make_chunk("a1", "ta1", "s1", 0.9),
            make_chunk("a2", "ta2", "s2", 0.8),
            make_chunk("a3", "ta3", "s3", 0.7),
        ])
        silo_b = make_silo_result("eng", "Eng KB", [
            make_chunk("b1", "tb1", "s4", 0.95),
            make_chunk("b2", "tb2", "s5", 0.85),
            make_chunk("b3", "tb3", "s6", 0.75),
        ])
        result = merge_top_per_instance([silo_a, silo_b], merge_k=4)
        assert len(result) == 4


class TestMergeDispatcher:
    def test_merge_dispatches_to_correct_strategy(self):
        silo = make_silo_result("hr", "HR", [make_chunk("a1", "t", "s", 0.9)])
        r1 = merge([silo], strategy="weighted_rrf", rrf_k=60, merge_k=1)
        r2 = merge([silo], strategy="round_robin", rrf_k=60, merge_k=1)
        r3 = merge([silo], strategy="top_per_instance", rrf_k=60, merge_k=1)
        assert len(r1) == 1
        assert len(r2) == 1
        assert len(r3) == 1

    def test_merge_unknown_strategy_falls_back_to_rrf(self):
        silo = make_silo_result("hr", "HR", [make_chunk("a1", "t", "s", 0.9)])
        result = merge([silo], strategy="unknown", rrf_k=60, merge_k=1)
        assert len(result) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest federation/tests/test_merger.py -v
```
Expected: FAIL — `No module named 'federation.app.merger'`

- [ ] **Step 3: Implement merger.py**

```python
# federation/app/merger.py
import hashlib
import logging
from .models import SiloSearchResult

logger = logging.getLogger("federation")


def _hash_chunk(chunk: dict) -> str:
    text = chunk.get("text", "")
    source = chunk.get("source_type", chunk.get("source", ""))
    title = chunk.get("title", chunk.get("doc_title", ""))
    key = f"{text}|{source}|{title}"
    return hashlib.sha256(key.encode()).hexdigest()


def deduplicate_chunks(chunks: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for chunk in chunks:
        h = _hash_chunk(chunk)
        if h not in seen or chunk.get("score", 0) > seen[h].get("score", 0):
            seen[h] = chunk
    return list(seen.values())


def _get_weight(silo_result: SiloSearchResult) -> float:
    return silo_result.chunks[0].get("_silo_weight", 1.0) if silo_result.chunks else 1.0


def merge_weighted_rrf(
    results: list[SiloSearchResult], rrf_k: int = 60, merge_k: int = 60
) -> list[dict]:
    scored: list[tuple[float, dict]] = []
    for silo_result in results:
        w = _get_weight(silo_result)
        if w <= 0:
            w = 1.0
        for rank, chunk in enumerate(silo_result.chunks):
            rrf_score = w / (rrf_k + rank + 1)
            chunk_copy = dict(chunk)
            chunk_copy["score"] = rrf_score
            chunk_copy["silo_id"] = silo_result.silo_id
            chunk_copy["silo_name"] = silo_result.silo_name
            scored.append((rrf_score, chunk_copy))
    scored.sort(key=lambda x: x[0], reverse=True)
    merged = [c for _, c in scored]
    deduped = deduplicate_chunks(merged)
    return deduped[:merge_k]


def merge_round_robin(
    results: list[SiloSearchResult], merge_k: int = 60
) -> list[dict]:
    interleaved: list[dict] = []
    max_len = max((len(r.chunks) for r in results), default=0)
    for i in range(max_len):
        for silo_result in results:
            if i < len(silo_result.chunks):
                chunk = dict(silo_result.chunks[i])
                chunk["silo_id"] = silo_result.silo_id
                chunk["silo_name"] = silo_result.silo_name
                interleaved.append(chunk)
    deduped = deduplicate_chunks(interleaved)
    return deduped[:merge_k]


def merge_top_per_instance(
    results: list[SiloSearchResult], merge_k: int = 60
) -> list[dict]:
    n = len(results)
    if n == 0:
        return []
    per_instance = max(1, merge_k // n)
    selected: list[dict] = []
    for silo_result in results:
        for chunk in silo_result.chunks[:per_instance]:
            chunk_copy = dict(chunk)
            chunk_copy["silo_id"] = silo_result.silo_id
            chunk_copy["silo_name"] = silo_result.silo_name
            selected.append(chunk_copy)
    selected.sort(key=lambda c: c.get("score", 0), reverse=True)
    deduped = deduplicate_chunks(selected)
    return deduped[:merge_k]


def merge(
    results: list[SiloSearchResult],
    strategy: str = "weighted_rrf",
    rrf_k: int = 60,
    merge_k: int = 60,
) -> list[dict]:
    if strategy == "round_robin":
        return merge_round_robin(results, merge_k)
    elif strategy == "top_per_instance":
        return merge_top_per_instance(results, merge_k)
    else:
        return merge_weighted_rrf(results, rrf_k, merge_k)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest federation/tests/test_merger.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add federation/app/merger.py federation/tests/test_merger.py && git commit -m "feat(federation): weighted RRF + round-robin + top-per-instance merger with dedup"
```

---

### Task 4: Silo Client — HTTP Fan-Out

**Files:**
- Create: `federation/app/silo_client.py`
- Create: `federation/tests/test_silo_client.py`

**Interfaces:**
- Consumes: `SiloConfig` from `models.py`, httpx
- Produces: `async def query_silo(silo: SiloConfig, query: str, top_k: int) -> SiloSearchResult`

- [ ] **Step 1: Write test for silo client**

```python
# federation/tests/test_silo_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from federation.app.models import SiloConfig, SiloSearchResult
from federation.app.silo_client import query_silo


HR_SILO = SiloConfig(
    id="hr", name="HR KB", proxy_url="http://hr:8000/v1",
    api_key="sk-hr", timeout_s=5
)


class TestQuerySilo:
    @pytest.mark.asyncio
    async def test_query_silo_returns_chunks(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "rag_sources": [
                {"chunk_id": "a1", "text": "Policy text", "source": "confluence",
                 "title": "Sick Leave", "version": "1.0", "relevance": 0.94},
            ],
            "rag_metadata": {"total_retrieved": 1, "total_reranked": 1, "latency_ms": 50}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await query_silo(HR_SILO, "How to take sick leave?", top_k=10)

        assert isinstance(result, SiloSearchResult)
        assert result.silo_id == "hr"
        assert result.silo_name == "HR KB"
        assert len(result.chunks) == 1
        assert result.chunks[0]["id"] == "a1"
        assert result.chunks[0]["text"] == "Policy text"
        assert result.chunks[0]["_silo_weight"] == 1.0
        assert result.error is None
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_query_silo_http_error_returns_partial(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.side_effect = Exception("Connection refused")
            mock_client_cls.return_value = mock_client

            result = await query_silo(HR_SILO, "query", top_k=10)

        assert result.error is not None
        assert "Connection refused" in result.error
        assert result.chunks == []
        assert result.partial is True

    @pytest.mark.asyncio
    async def test_query_silo_uses_api_key_header(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"rag_sources": [], "rag_metadata": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await query_silo(HR_SILO, "q", top_k=5)

        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer sk-hr"

    @pytest.mark.asyncio
    async def test_query_silo_attaches_silo_weight_to_chunks(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "rag_sources": [{"chunk_id": "c1", "text": "t", "relevance": 0.5}],
            "rag_metadata": {}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            result = await query_silo(HR_SILO, "q", top_k=5)

        assert result.chunks[0]["_silo_weight"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest federation/tests/test_silo_client.py -v
```
Expected: FAIL — `No module named 'federation.app.silo_client'`

- [ ] **Step 3: Implement silo_client.py**

```python
# federation/app/silo_client.py
import time
import logging
import httpx
from .models import SiloConfig, SiloSearchResult

logger = logging.getLogger("federation")


async def query_silo(
    silo: SiloConfig,
    query: str,
    top_k: int = 30,
    timeout_s: int | None = None,
) -> SiloSearchResult:
    timeout = timeout_s or silo.timeout_s
    headers = {"Content-Type": "application/json"}
    if silo.api_key:
        headers["Authorization"] = f"Bearer {silo.api_key}"

    payload = {
        "model": "rag-internal",
        "messages": [{"role": "user", "content": query}],
        "rag_skip_generation": True,
        "rag_top_k": top_k,
        "rag_return_chunks": True,
        "temperature": 0,
        "stream": False,
    }

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            response = await client.post(
                f"{silo.proxy_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            latency_ms = (time.monotonic() - start) * 1000

            sources = data.get("rag_sources", [])
            chunks = _normalize_chunks(sources, silo)

            return SiloSearchResult(
                silo_id=silo.id,
                silo_name=silo.name,
                chunks=chunks,
                latency_ms=latency_ms,
            )
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        logger.warning(f"Silo '{silo.id}' query failed: {e}")
        return SiloSearchResult(
            silo_id=silo.id,
            silo_name=silo.name,
            chunks=[],
            latency_ms=latency_ms,
            error=str(e),
            partial=True,
        )


def _normalize_chunks(sources: list[dict], silo: SiloConfig) -> list[dict]:
    chunks = []
    for src in sources:
        chunk = {
            "id": src.get("chunk_id", ""),
            "text": src.get("text", src.get("text_preview", "")),
            "source_type": src.get("source", src.get("source_type", "unknown")),
            "title": src.get("title", src.get("doc_title", "")),
            "version": src.get("version", ""),
            "score": src.get("relevance", src.get("score", 0.0)),
            "_silo_weight": silo.weight,
        }
        chunks.append(chunk)
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest federation/tests/test_silo_client.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add federation/app/silo_client.py federation/tests/test_silo_client.py && git commit -m "feat(federation): async HTTP silo client with httpx fan-out"
```

---

### Task 5: Router — Fan-Out Orchestration

**Files:**
- Create: `federation/app/router.py`
- Create: `federation/tests/test_router.py`

**Interfaces:**
- Consumes: `SiloRegistry` from `silo_registry.py`, `query_silo` from `silo_client.py`, `merge` from `merger.py`, `FederatedSearchResult`, `FederationContext` from `models.py`
- Produces: `async def federated_search(ctx: FederationContext, registry: SiloRegistry) -> FederatedSearchResult`

- [ ] **Step 1: Write test for router**

```python
# federation/tests/test_router.py
import pytest
from unittest.mock import AsyncMock, patch
from federation.app.models import (
    SiloConfig, SiloSearchResult, FederatedSearchResult, FederationContext
)
from federation.app.silo_registry import SiloRegistry
from federation.app.router import federated_search


HR_SILO = SiloConfig(id="hr", name="HR KB", proxy_url="http://hr/v1", weight=1.0, access_groups=["hr", "admin"])
ENG_SILO = SiloConfig(id="eng", name="Engineering", proxy_url="http://eng/v1", weight=1.2, access_groups=["engineering", "admin"])


def make_silo_result(silo_id, silo_name, chunks, latency=50.0):
    return SiloSearchResult(silo_id=silo_id, silo_name=silo_name, chunks=chunks, latency_ms=latency)


class TestFederatedSearch:
    @pytest.mark.asyncio
    async def test_merge_mode_fans_out_to_all_accessible(self):
        ctx = FederationContext(
            mode="merge", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["engineering", "admin"]
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        mock_hr = make_silo_result("hr", "HR KB", [
            {"id": "c1", "text": "HR text", "score": 0.9, "_silo_weight": 1.0}
        ])
        mock_eng = make_silo_result("eng", "Engineering", [
            {"id": "c2", "text": "Eng text", "score": 0.95, "_silo_weight": 1.2}
        ])

        with patch("federation.app.router.query_silo") as mock_query:
            async def side_effect(silo, query, top_k, timeout_s=None):
                if silo.id == "hr":
                    return mock_hr
                return mock_eng
            mock_query.side_effect = side_effect

            result = await federated_search(ctx, registry)

        assert isinstance(result, FederatedSearchResult)
        assert len(result.merged_chunks) == 2
        assert result.merged_chunks[0]["id"] == "c2"  # eng has higher weight
        assert len(result.silo_results) == 2
        assert result.errors == []
        assert result.skipped_silos == []

    @pytest.mark.asyncio
    async def test_strict_mode_queries_only_specified_silo(self):
        ctx = FederationContext(
            mode="strict", target_silos=["hr"], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["hr"]
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        mock_hr = make_silo_result("hr", "HR KB", [
            {"id": "c1", "text": "HR only", "score": 0.9, "_silo_weight": 1.0}
        ])

        with patch("federation.app.router.query_silo") as mock_query:
            mock_query.return_value = mock_hr

            result = await federated_search(ctx, registry)

        assert len(result.silo_results) == 1
        assert result.silo_results[0].silo_id == "hr"
        mock_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_partial_silo_failure_is_graceful(self):
        ctx = FederationContext(
            mode="merge", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["admin"]
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        mock_hr = SiloSearchResult(silo_id="hr", silo_name="HR KB", chunks=[
            {"id": "c1", "text": "HR text", "score": 0.9, "_silo_weight": 1.0}
        ], latency_ms=50)
        mock_eng = SiloSearchResult(silo_id="eng", silo_name="Engineering", chunks=[],
                                    latency_ms=5000, error="timeout", partial=True)

        with patch("federation.app.router.query_silo") as mock_query:
            async def side_effect(silo, query, top_k, timeout_s=None):
                if silo.id == "hr":
                    return mock_hr
                return mock_eng
            mock_query.side_effect = side_effect

            result = await federated_search(ctx, registry)

        assert len(result.merged_chunks) == 1  # only HR returned
        assert len(result.errors) == 1
        assert "eng" in result.errors[0]

    @pytest.mark.asyncio
    async def test_all_silos_fail_returns_empty(self):
        ctx = FederationContext(
            mode="merge", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["admin"]
        )
        registry = SiloRegistry([HR_SILO])

        mock_hr = SiloSearchResult(silo_id="hr", silo_name="HR KB", chunks=[],
                                    latency_ms=100, error="down", partial=True)

        with patch("federation.app.router.query_silo") as mock_query:
            mock_query.return_value = mock_hr
            result = await federated_search(ctx, registry)

        assert result.merged_chunks == []
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_no_silos_found_for_user_returns_empty(self):
        ctx = FederationContext(
            mode="merge", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["nobody"]
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        with patch("federation.app.router.query_silo") as mock_query:
            result = await federated_search(ctx, registry)

        assert result.merged_chunks == []
        assert len(result.silo_results) == 0
        mock_query.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest federation/tests/test_router.py -v
```
Expected: FAIL — `No module named 'federation.app.router'`

- [ ] **Step 3: Implement router.py**

```python
# federation/app/router.py
import asyncio
import time
import logging
from .models import (
    SiloConfig, SiloSearchResult, FederatedSearchResult, FederationContext
)
from .silo_registry import SiloRegistry
from .silo_client import query_silo
from .merger import merge
from .config import (
    FEDERATION_PER_INSTANCE_TIMEOUT_S,
    FEDERATION_MERGE_K,
    FEDERATION_RRF_K,
)

logger = logging.getLogger("federation")


def _resolve_target_silos(
    ctx: FederationContext, registry: SiloRegistry
) -> list[SiloConfig]:
    if ctx.mode == "strict" and ctx.target_silos:
        silos = []
        for sid in ctx.target_silos:
            silo = registry.get(sid)
            if silo and silo.is_accessible_by(ctx.user_groups):
                silos.append(silo)
        return silos
    return registry.list_accessible(ctx.user_groups)


async def federated_search(
    ctx: FederationContext,
    registry: SiloRegistry,
) -> FederatedSearchResult:
    start = time.monotonic()
    silos = _resolve_target_silos(ctx, registry)
    errors: list[str] = []
    skipped: list[str] = []

    if not silos:
        return FederatedSearchResult(
            query="",
            merged_chunks=[],
            silo_results=[],
            total_latency_ms=0,
            errors=["No accessible silos for user"],
        )

    timeout = FEDERATION_PER_INSTANCE_TIMEOUT_S
    tasks = [
        query_silo(silo, ctx.query if hasattr(ctx, 'query') else "", ctx.merge_k, timeout_s=timeout)
        for silo in silos
    ]
    silo_results: list[SiloSearchResult] = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[SiloSearchResult] = []
    for i, result in enumerate(silo_results):
        if isinstance(result, Exception):
            silo_id = silos[i].id
            errors.append(f"{silo_id}: {result}")
            results.append(SiloSearchResult(
                silo_id=silo_id, silo_name=silos[i].name,
                chunks=[], latency_ms=0, error=str(result), partial=True
            ))
        else:
            results.append(result)
            if result.error:
                errors.append(f"{result.silo_id}: {result.error}")

    merged_chunks = merge(
        [r for r in results if r.chunks],
        strategy=ctx.merge_strategy,
        rrf_k=ctx.rrf_k,
        merge_k=ctx.merge_k,
    )

    total_latency = (time.monotonic() - start) * 1000

    return FederatedSearchResult(
        query=getattr(ctx, 'query', ''),
        merged_chunks=merged_chunks,
        silo_results=results,
        total_latency_ms=total_latency,
        errors=errors,
        skipped_silos=skipped,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest federation/tests/test_router.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add federation/app/router.py federation/tests/test_router.py && git commit -m "feat(federation): fan-out router with asyncio.gather and graceful degradation"
```

---

### Task 6: Circuit Breaker (per silo)

**Files:**
- Create: `federation/app/circuit_breaker.py`
- Create: `federation/tests/test_circuit_breaker.py`

**Interfaces:**
- Consumes: `FEDERATION_CIRCUIT_BREAKER_THRESHOLD`, `FEDERATION_CIRCUIT_BREAKER_RECOVERY_S` from `config.py`
- Produces: `class CircuitBreaker` — `allow_request() -> bool`, `record_success()`, `record_failure()`, `state -> str`; `get_breaker(name) -> CircuitBreaker`

- [ ] **Step 1: Write test for circuit breaker (adapted from proxy pattern)**

```python
# federation/tests/test_circuit_breaker.py
import time
from federation.app.circuit_breaker import CircuitBreaker, get_breaker


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout_s=30)
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout_s=30)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.allow_request() is False

    def test_half_open_after_recovery_timeout(self, monkeypatch):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"

        monkeypatch.setattr(time, "monotonic", lambda: cb._last_failure_time + 2.0)
        assert cb.state == "HALF_OPEN"
        assert cb.allow_request() is True

    def test_half_open_success_closes_circuit(self, monkeypatch):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"

        monkeypatch.setattr(time, "monotonic", lambda: cb._last_failure_time + 2.0)
        assert cb.allow_request() is True
        cb.record_success()
        assert cb.state == "CLOSED"

    def test_half_open_failure_opens_again(self, monkeypatch):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout_s=1)
        cb.record_failure()
        cb.record_failure()

        monkeypatch.setattr(time, "monotonic", lambda: cb._last_failure_time + 2.0)
        cb.record_failure()
        assert cb.state == "OPEN"

    def test_successes_reset_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=5, recovery_timeout_s=30)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        # Should not be OPEN — successes reset count
        assert cb.state == "CLOSED"


class TestGetBreaker:
    def test_returns_same_breaker_for_same_name(self):
        b1 = get_breaker("silo_hr")
        b2 = get_breaker("silo_hr")
        assert b1 is b2

    def test_returns_different_breaker_for_different_name(self):
        b1 = get_breaker("silo_hr")
        b2 = get_breaker("silo_eng")
        assert b1 is not b2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest federation/tests/test_circuit_breaker.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement circuit_breaker.py**

```python
# federation/app/circuit_breaker.py
import time
import threading
import logging
from .config import (
    FEDERATION_CIRCUIT_BREAKER_THRESHOLD,
    FEDERATION_CIRCUIT_BREAKER_RECOVERY_S,
)

logger = logging.getLogger("federation")

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_s: int = 30,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self._state = CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == OPEN:
                elapsed = time.monotonic() - self._last_failure_time
                if elapsed >= self.recovery_timeout_s:
                    self._state = HALF_OPEN
                    logger.info(f"Breaker '{self.name}' → HALF_OPEN")
            return self._state

    def allow_request(self) -> bool:
        return self.state != OPEN

    def record_success(self) -> None:
        with self._lock:
            if self._state == HALF_OPEN:
                self._state = CLOSED
                self._failure_count = 0
                logger.info(f"Breaker '{self.name}' → CLOSED (half-open success)")
            self._success_count += 1
            if self._success_count >= self.failure_threshold:
                self._failure_count = 0
                self._success_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.monotonic()
            if self._state == HALF_OPEN:
                self._state = OPEN
                logger.warning(f"Breaker '{self.name}' → OPEN (half-open failure)")
            elif self._failure_count >= self.failure_threshold and self._state == CLOSED:
                self._state = OPEN
                logger.warning(f"Breaker '{self.name}' → OPEN ({self._failure_count} failures)")


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(name: str) -> CircuitBreaker:
    with _breakers_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=FEDERATION_CIRCUIT_BREAKER_THRESHOLD,
                recovery_timeout_s=FEDERATION_CIRCUIT_BREAKER_RECOVERY_S,
            )
        return _breakers[name]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest federation/tests/test_circuit_breaker.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add federation/app/circuit_breaker.py federation/tests/test_circuit_breaker.py && git commit -m "feat(federation): per-silo circuit breaker"
```

---

### Task 7: Auth — JWT + RBAC Gate

**Files:**
- Create: `federation/app/auth.py`
- Create: `federation/tests/test_auth.py`

**Interfaces:**
- Consumes: JWT token from Authorization header, `SiloRegistry.list_accessible()`
- Produces: `extract_user_groups(token) -> list[str]`, `check_silo_access(silo, user_groups) -> bool`

- [ ] **Step 1: Write test for auth**

```python
# federation/tests/test_auth.py
import pytest
from federation.app.models import SiloConfig
from federation.app.exceptions import AccessDeniedError
from federation.app.auth import check_silo_access


HR_SILO = SiloConfig(id="hr", name="HR", proxy_url="http://hr/v1",
                     access_groups=["hr", "admin"])
ENG_SILO = SiloConfig(id="eng", name="Eng", proxy_url="http://eng/v1",
                      access_groups=["engineering", "admin"])


class TestCheckSiloAccess:
    def test_user_in_group_has_access(self):
        check_silo_access(HR_SILO, ["hr"])

    def test_admin_has_access(self):
        check_silo_access(ENG_SILO, ["admin", "engineering"])

    def test_user_not_in_group_raises(self):
        with pytest.raises(AccessDeniedError, match="Access denied"):
            check_silo_access(HR_SILO, ["engineering"])

    def test_nobody_sees_finance(self):
        fin = SiloConfig(id="fin", name="Finance", proxy_url="http://fin/v1",
                         access_groups=["finance", "admin"])
        check_silo_access(fin, ["admin"])
        check_silo_access(fin, ["finance"])
        with pytest.raises(AccessDeniedError):
            check_silo_access(fin, ["intern"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest federation/tests/test_auth.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement auth.py**

```python
# federation/app/auth.py
from .models import SiloConfig
from .exceptions import AccessDeniedError


def check_silo_access(silo: SiloConfig, user_groups: list[str]) -> None:
    if not silo.is_accessible_by(user_groups):
        raise AccessDeniedError(silo_id=silo.id, user_groups=user_groups)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest federation/tests/test_auth.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add federation/app/auth.py federation/tests/test_auth.py && git commit -m "feat(federation): RBAC gate per silo"
```

---

### Task 8: FastAPI App — Endpoints (merge mode)

**Files:**
- Create: `federation/app/main.py`
- Create: `federation/app/metrics.py`
- Create: `federation/tests/test_main.py`
- Create: `federation/tests/conftest.py`

**Interfaces:**
- Consumes: All previous modules
- Produces: FastAPI app with `/v1/chat/completions`, `/v1/health`, `/v1/health/live`, `/v1/health/ready`, `/v1/silos`, `/v1/models`, `/metrics`

- [ ] **Step 1: Write conftest.py**

```python
# federation/tests/conftest.py
import pytest
import httpx
from federation.app.main import app
from federation.app.models import SiloConfig
from federation.app.silo_registry import SiloRegistry
from federation.app.config import load_silos


HR_SILO = SiloConfig(
    id="hr", name="HR KB", proxy_url="http://hr:8000/v1",
    weight=1.0, access_groups=["hr", "admin"], is_primary=True
)
ENG_SILO = SiloConfig(
    id="engineering", name="Engineering Wiki", proxy_url="http://eng:8000/v1",
    weight=1.2, access_groups=["engineering", "admin"], is_primary=False
)


@pytest.fixture
def test_silos():
    return [HR_SILO, ENG_SILO]


@pytest.fixture
def test_registry(test_silos):
    return SiloRegistry(test_silos)
```

- [ ] **Step 2: Write test for main endpoints**

```python
# federation/tests/test_main.py
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch, AsyncMock
from federation.app.main import app


@pytest.mark.asyncio
async def test_health_live():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_ready_no_silos():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert "silos" in data


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "federation" in data


@pytest.mark.asyncio
async def test_silos_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/silos")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_models_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data


@pytest.mark.asyncio
async def test_chat_completions_merge_mode(monkeypatch):
    monkeypatch.setenv("FEDERATION_INSTANCES_JSON", '[{"id":"test","name":"Test","proxy_url":"http://test/v1","weight":1.0,"access_groups":["admin"],"is_primary":true}]')
    monkeypatch.setenv("FEDERATION_MODE", "merge")

    from federation.app import config
    import importlib
    importlib.reload(config)

    mock_result = {
        "id": "test",
        "silo_name": "Test",
        "chunks": [{"id": "c1", "text": "Hello", "score": 0.9, "_silo_weight": 1.0}],
        "latency_ms": 50,
        "error": None,
        "partial": False,
    }

    with patch("federation.app.main.federated_search") as mock_search:
        mock_search.return_value = mock_result

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "rag-federated",
                    "messages": [{"role": "user", "content": "test query"}],
                    "stream": False,
                },
            )
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
```

- [ ] **Step 3: Run test to verify it fails**

```bash
python -m pytest federation/tests/test_main.py -v
```
Expected: FAIL — `No module named 'federation.app.main'`

- [ ] **Step 4: Implement metrics.py**

```python
# federation/app/metrics.py
from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY

REQUESTS_TOTAL = Counter(
    "rag_federation_requests_total",
    "Total federation requests",
    ["mode", "status"],
)

SILO_REQUESTS_TOTAL = Counter(
    "rag_federation_silo_requests_total",
    "Per-silo requests",
    ["silo", "status"],
)

SILO_LATENCY = Histogram(
    "rag_federation_silo_latency_seconds",
    "Per-silo latency",
    ["silo"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

MERGE_TOTAL_CHUNKS = Histogram(
    "rag_federation_merge_total_chunks",
    "Chunks after merge",
    buckets=[5, 10, 20, 30, 40, 50, 60, 80, 100],
)

CIRCUIT_BREAKER_STATE = Gauge(
    "rag_federation_circuit_breaker_state",
    "Circuit breaker state per silo",
    ["silo"],
)

SILOS_ACTIVE = Gauge(
    "rag_federation_silos_active",
    "Number of healthy silos",
)

TOTAL_LATENCY = Histogram(
    "rag_federation_total_latency_seconds",
    "End-to-end federation latency",
    ["mode"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)
```

- [ ] **Step 5: Implement main.py**

```python
# federation/app/main.py
import time
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from .config import (
    FEDERATION_MODE, FEDERATION_MERGE_STRATEGY, FEDERATION_MERGE_K,
    FEDERATION_RRF_K, FEDERATION_TOTAL_TIMEOUT_S, load_silos, get_primary_silo,
)
from .models import FederationContext, SiloConfig
from .silo_registry import SiloRegistry
from .router import federated_search
from .merger import merge
from .metrics import (
    REQUESTS_TOTAL, generate_latest, SILOS_ACTIVE,
)
from .exceptions import FederationError, AllSilosDownError

logger = logging.getLogger("federation")

registry: SiloRegistry | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry
    silos = load_silos()
    registry = SiloRegistry(silos)
    SILOS_ACTIVE.set(len(silos))
    logger.info(f"Federation started: {len(silos)} silos, mode={FEDERATION_MODE}")
    yield
    logger.info("Federation shutting down")


app = FastAPI(
    title="Federated RAG Proxy",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(FederationError)
async def federation_error_handler(request: Request, exc: FederationError):
    return JSONResponse(
        status_code=503 if isinstance(exc, AllSilosDownError) else 400,
        content={"error": str(exc), "type": type(exc).__name__},
    )


@app.get("/v1/health/live")
async def health_live():
    return {"status": "ok"}


@app.get("/v1/health/ready")
async def health_ready():
    if registry is None:
        return {"status": "not_ready", "silos": []}
    silos_status = {}
    for silo in registry.list_all():
        silos_status[silo.id] = {
            "name": silo.name,
            "url": silo.proxy_url,
        }
    return {"status": "ready", "silos": silos_status}


@app.get("/v1/health")
async def health():
    if registry is None:
        return {"status": "starting"}
    silos_status = {}
    for silo in registry.list_all():
        silos_status[silo.id] = {"name": silo.name, "status": "configured"}
    return {
        "status": "healthy",
        "federation": {
            "mode": FEDERATION_MODE,
            "total_silos": len(registry),
            "silos": silos_status,
        }
    }


@app.get("/v1/silos")
async def list_silos(request: Request):
    if registry is None:
        return {"silos": []}
    user_groups = ["admin"]  # placeholder — in production, extract from JWT
    accessible = registry.list_accessible(user_groups)
    return {
        "silos": [
            {
                "id": s.id,
                "name": s.name,
                "collections": s.collections,
                "accessible": True,
            }
            for s in accessible
        ]
    }


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "rag-federated",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "federation",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if registry is None:
        raise HTTPException(status_code=503, detail="Federation not ready")

    body = await request.json()
    messages = body.get("messages", [])
    user_query = messages[-1]["content"] if messages else ""

    federation_silo = body.get("federation_silo")
    federation_mode = body.get("federation_mode", FEDERATION_MODE)
    merge_k = body.get("federation_top_k", FEDERATION_MERGE_K)
    merge_strategy = body.get("federation_merge_strategy", FEDERATION_MERGE_STRATEGY)

    user_groups = ["admin"]  # placeholder — extract from JWT in production

    target_silos = [federation_silo] if federation_silo else []

    ctx = FederationContext(
        mode=federation_mode,
        target_silos=target_silos,
        merge_strategy=merge_strategy,
        merge_k=merge_k,
        rrf_k=FEDERATION_RRF_K,
        user_groups=user_groups,
        query=user_query,
    )

    REQUESTS_TOTAL.labels(mode=federation_mode, status="started").inc()

    try:
        result = await federated_search(ctx, registry)
        REQUESTS_TOTAL.labels(mode=federation_mode, status="success").inc()
    except Exception as e:
        REQUESTS_TOTAL.labels(mode=federation_mode, status="error").inc()
        raise HTTPException(status_code=500, detail=str(e))

    if result.errors and not result.merged_chunks:
        raise AllSilosDownError(failed_silos=[r.silo_id for r in result.silo_results])

    context_text = "\n\n".join(
        f"[{c.get('silo_name', '')}] {c.get('text', '')}"
        for c in result.merged_chunks
    )

    sources = [
        {
            "chunk_id": c.get("id", ""),
            "source": c.get("source_type", "unknown"),
            "title": c.get("title", ""),
            "version": c.get("version", ""),
            "silo_id": c.get("silo_id", ""),
            "silo_name": c.get("silo_name", ""),
            "relevance": c.get("score", 0.0),
            "text_preview": c.get("text", "")[:200],
        }
        for c in result.merged_chunks
    ]

    return {
        "id": f"fed-{int(time.time())}",
        "object": "chat.completion",
        "model": "rag-federated",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": f"Retrieved {len(result.merged_chunks)} chunks from {len(result.silo_results)} silos. Federation delegates generation to primary silo — see rag_sources below.",
            },
            "finish_reason": "stop",
        }],
        "rag_sources": sources,
        "rag_confidence": 0.5,
        "federation": {
            "mode": federation_mode,
            "silos_queried": [r.silo_id for r in result.silo_results if r.chunks],
            "silos_skipped": result.skipped_silos,
            "cross_silo": len({r.silo_id for r in result.silo_results if r.chunks}) > 1,
            "total_latency_ms": result.total_latency_ms,
            "per_silo_latency_ms": {
                r.silo_id: r.latency_ms for r in result.silo_results
            },
            "warnings": result.errors,
        },
    }


@app.get("/metrics")
async def metrics():
    from fastapi.responses import Response
    return Response(content=generate_latest(), media_type="text/plain")
```

- [ ] **Step 6: Run test to verify it passes**

```bash
python -m pytest federation/tests/test_main.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add federation/app/main.py federation/app/metrics.py federation/tests/test_main.py federation/tests/conftest.py && git commit -m "feat(federation): FastAPI app with 7 endpoints (merge mode)"
```

---

### Task 9: Auto-Router — SLM Classification

**Files:**
- Create: `federation/app/auto_router.py`
- Create: `federation/tests/test_auto_router.py`

**Interfaces:**
- Consumes: `SiloRegistry.list_accessible()`, `FEDERATION_AUTO_SLM_ENABLED`
- Produces: `async def classify_query(query, registry) -> list[str]` — returns target silo IDs

- [ ] **Step 1: Write test for auto-router**

```python
# federation/tests/test_auto_router.py
import pytest
from unittest.mock import AsyncMock, patch
from federation.app.models import SiloConfig
from federation.app.silo_registry import SiloRegistry
from federation.app.auto_router import classify_query


HR_SILO = SiloConfig(
    id="hr", name="HR KB", proxy_url="http://hr/v1",
    weight=1.0, access_groups=["hr", "admin"],
    collections=["hr_policies", "hr_onboarding"]
)
ENG_SILO = SiloConfig(
    id="engineering", name="Engineering Wiki", proxy_url="http://eng/v1",
    weight=1.2, access_groups=["engineering", "admin"],
    collections=["confluence", "jira", "gitlab"]
)


class TestClassifyQuery:
    @pytest.mark.asyncio
    async def test_hr_query_routes_to_hr(self):
        registry = SiloRegistry([HR_SILO, ENG_SILO])
        result = await classify_query("How to request sick leave?", registry)
        assert "hr" in result

    @pytest.mark.asyncio
    async def test_engineering_query_routes_to_engineering(self):
        registry = SiloRegistry([HR_SILO, ENG_SILO])
        result = await classify_query("How to deploy to production?", registry)
        assert "engineering" in result

    @pytest.mark.asyncio
    async def test_unclear_query_routes_to_all(self):
        registry = SiloRegistry([HR_SILO, ENG_SILO])
        result = await classify_query("update documentation", registry)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_disabled_returns_all_accessible(self, monkeypatch):
        from federation.app import auto_router
        monkeypatch.setattr(auto_router, "FEDERATION_AUTO_SLM_ENABLED", False)
        registry = SiloRegistry([HR_SILO, ENG_SILO])
        result = await classify_query("any query", registry)
        assert len(result) == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest federation/tests/test_auto_router.py -v
```
Expected: FAIL

- [ ] **Step 3: Implement auto_router.py**

```python
# federation/app/auto_router.py
import logging
import re
from .silo_registry import SiloRegistry
from .config import FEDERATION_AUTO_SLM_ENABLED

logger = logging.getLogger("federation")

_KEYWORD_MAP: dict[str, list[str]] = {
    "hr": [
        "sick leave", "больничный", "vacation", "отпуск", "hiring",
        "onboarding", "payroll", "salary", "benefits", "hr policy",
    ],
    "engineering": [
        "deploy", "production", "kubernetes", "docker", "pipeline",
        "code review", "merge request", "pull request", "git", "jira",
        "confluence", "architecture", "microservice", "api",
    ],
    "finance": [
        "budget", "expense", "invoice", "reimbursement", "report",
        "quarterly", "annual", "fiscal", "tax",
    ],
}

_regex_cache: dict[str, re.Pattern] = {}


def _get_regex(silo_id: str) -> re.Pattern:
    if silo_id not in _regex_cache:
        keywords = _KEYWORD_MAP.get(silo_id, [])
        pattern = "|".join(re.escape(kw) for kw in keywords)
        _regex_cache[silo_id] = re.compile(pattern, re.IGNORECASE)
    return _regex_cache[silo_id]


async def classify_query(query: str, registry: SiloRegistry) -> list[str]:
    if not FEDERATION_AUTO_SLM_ENABLED:
        return [s.id for s in registry.list_all()]

    query_lower = query.lower()
    matched: list[tuple[str, int]] = []
    all_silos = [s.id for s in registry.list_all()]

    for silo_id in all_silos:
        pattern = _get_regex(silo_id)
        matches = len(pattern.findall(query_lower))
        if matches > 0:
            matched.append((silo_id, matches))

    if not matched:
        return all_silos

    matched.sort(key=lambda x: x[1], reverse=True)
    return [m[0] for m in matched]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest federation/tests/test_auto_router.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add federation/app/auto_router.py federation/tests/test_auto_router.py && git commit -m "feat(federation): keyword-based auto-router (SLM placeholder)"
```

---

### Task 10: Wire Auto-Router into Router

**Files:**
- Modify: `federation/app/router.py`
- Modify: `federation/tests/test_router.py`

**Interfaces:**
- Consumes: `classify_query()` from `auto_router.py`
- Produces: `federated_search()` now uses auto-router in "auto" mode

- [ ] **Step 1: Update federated_search to use auto-router**

```python
# In federation/app/router.py, modify _resolve_target_silos:

from .auto_router import classify_query

def _resolve_target_silos(
    ctx: FederationContext, registry: SiloRegistry
) -> list[SiloConfig]:
    if ctx.mode == "strict" and ctx.target_silos:
        silos = []
        for sid in ctx.target_silos:
            silo = registry.get(sid)
            if silo and silo.is_accessible_by(ctx.user_groups):
                silos.append(silo)
        return silos
    elif ctx.mode == "auto":
        import asyncio
        query = getattr(ctx, 'query', '')
        target_ids = asyncio.run(classify_query(query, registry))
        ctx.cross_silo = len(target_ids) > 1
        ctx.target_silos = target_ids
        return [registry.get(sid) for sid in target_ids if registry.get(sid)]
    return registry.list_accessible(ctx.user_groups)
```

- [ ] **Step 2: Add async test for auto mode**

```python
# Add to federation/tests/test_router.py:

    @pytest.mark.asyncio
    async def test_auto_mode_uses_classifier(self):
        ctx = FederationContext(
            mode="auto", target_silos=[], merge_strategy="weighted_rrf",
            merge_k=10, rrf_k=60, user_groups=["admin"], query="sick leave policy"
        )
        registry = SiloRegistry([HR_SILO, ENG_SILO])

        mock_hr = make_silo_result("hr", "HR KB", [
            {"id": "c1", "text": "HR text", "score": 0.9, "_silo_weight": 1.0}
        ])

        with patch("federation.app.router.classify_query") as mock_classify, \
             patch("federation.app.router.query_silo") as mock_query:
            mock_classify.return_value = ["hr"]
            mock_query.return_value = mock_hr

            result = await federated_search(ctx, registry)

        assert len(result.silo_results) == 1
        assert result.silo_results[0].silo_id == "hr"
```

- [ ] **Step 3: Run tests to verify**

```bash
python -m pytest federation/tests/test_router.py -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add federation/app/router.py federation/tests/test_router.py && git commit -m "feat(federation): wire auto-router into federated_search"
```

---

### Task 11: Add rag_skip_generation to Proxy

**Files:**
- Modify: `proxy/app/main.py`

**Goal:** Add `rag_skip_generation` support so federation can query proxy for chunks only (no LLM generation).

- [ ] **Step 1: Check current proxy code for retrieval flow**

```bash
# Read the relevant section of proxy/app/main.py
python -c "
import ast, inspect
# search for process_rag_query function
"
```
Investigate the point after retrieval where generation happens. Add early return if `rag_skip_generation` is True.

- [ ] **Step 2: Find the process_rag_query function and identify insertion point**

Look for the point after `hybrid_search()` + `rerank_chunks()` + `build_context()` but before the LLM call.

- [ ] **Step 3: Add skip-generation early return**

In `proxy/app/main.py`, in `process_rag_query()` (or equivalent), after context building, add:

```python
# After context building, before LLM call:
if getattr(request, 'rag_skip_generation', False):
    return JSONResponse(content={
        "id": f"rag-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "model": LLM_MODEL_NAME,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
        "rag_sources": sources,  # already built above
        "rag_metadata": {
            "total_retrieved": len(retrieved),
            "total_reranked": len(reranked) if reranked else 0,
            "latency_ms": (time.time() - start_time) * 1000,
        }
    })
```

- [ ] **Step 4: Write test for rag_skip_generation (add to existing proxy tests)**

```python
# In tests/proxy/test_main.py, add:
def test_rag_skip_generation_returns_chunks_only(client_with_qdrant):
    response = client_with_qdrant.post("/v1/chat/completions", json={
        "model": "rag-model",
        "messages": [{"role": "user", "content": "test query"}],
        "rag_skip_generation": True,
        "rag_return_chunks": True,
        "stream": False,
    })
    assert response.status_code == 200
    data = response.json()
    assert "rag_sources" in data
    assert len(data["rag_sources"]) > 0
    assert data["choices"][0]["message"]["content"] == ""
```

- [ ] **Step 5: Run proxy tests to verify no regression**

```bash
python -m pytest tests/proxy/ -v --timeout=30 -x
```
Expected: All existing tests still pass. New test passes.

- [ ] **Step 6: Commit**

```bash
git add proxy/app/main.py tests/proxy/test_main.py && git commit -m "feat(proxy): rag_skip_generation flag for federation chunk-only queries"
```

---

### Task 12: Dockerfile & Integration

**Files:**
- Create: `federation/Dockerfile`
- Create: `federation/docker-compose.federation.yml`
- Modify: `Makefile` (add federation targets)

**Interfaces:**
- Consumes: all federation modules, requirements.txt
- Produces: Dockerfile for federation proxy

- [ ] **Step 1: Write Dockerfile**

```dockerfile
# federation/Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY federation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY federation/app/ ./app/

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

- [ ] **Step 2: Write docker-compose snippet**

```yaml
# federation/docker-compose.federation.yml
version: "3.8"
services:
  federation:
    build:
      context: ..
      dockerfile: federation/Dockerfile
    ports:
      - "8001:8001"
    environment:
      - FEDERATION_MODE=merge
      - FEDERATION_INSTANCES_JSON=[{"id":"hr","name":"HR KB","proxy_url":"http://proxy:8000/v1","weight":1.0,"access_groups":["admin"],"is_primary":true}]
    depends_on:
      - proxy
```

- [ ] **Step 3: Add Makefile targets**

```makefile
# Add to Makefile:
federation-build:
	docker build -t rag-federation -f federation/Dockerfile .

federation-run:
	docker run -p 8001:8001 --env-file federation/.env rag-federation

federation-test:
	python -m pytest federation/tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add federation/Dockerfile federation/docker-compose.federation.yml Makefile && git commit -m "feat(federation): Dockerfile, docker-compose, Makefile targets"
```

---

### Task 13: Integration Test — Federation E2E

**Files:**
- Modify: `federation/tests/test_integration.py`

**Goal:** Test the full federation flow with a real FastAPI TestClient and mocked silo responses.

- [ ] **Step 1: Write integration test**

```python
# federation/tests/test_integration.py
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch, AsyncMock, MagicMock
from federation.app.main import app
from federation.app.models import SiloConfig, SiloSearchResult
from federation.app.silo_registry import SiloRegistry


@pytest.fixture
def mock_silos():
    return [
        SiloConfig(id="hr", name="HR KB", proxy_url="http://hr/v1",
                   weight=1.0, access_groups=["admin"], is_primary=True),
        SiloConfig(id="eng", name="Engineering", proxy_url="http://eng/v1",
                   weight=1.2, access_groups=["admin"], is_primary=False),
    ]


class TestFederationE2E:
    @pytest.mark.asyncio
    async def test_full_chat_flow_merge_mode(self, monkeypatch, mock_silos):
        monkeypatch.setenv("FEDERATION_MODE", "merge")
        from federation.app import config
        import importlib
        importlib.reload(config)

        with patch("federation.app.main.load_silos", return_value=mock_silos), \
             patch("federation.app.main.registry", SiloRegistry(mock_silos)), \
             patch("federation.app.main.federated_search") as mock_search:

            mock_search.return_value = type('obj', (object,), {
                'merged_chunks': [
                    {'id': 'c1', 'text': 'Policy: 5 days sick leave', 'score': 0.95,
                     'source_type': 'confluence', 'title': 'Sick Leave Policy',
                     'version': '2.0', 'silo_id': 'hr', 'silo_name': 'HR KB'}
                ],
                'silo_results': [
                    SiloSearchResult(silo_id='hr', silo_name='HR KB',
                                     chunks=[{'id': 'c1'}], latency_ms=50),
                    SiloSearchResult(silo_id='eng', silo_name='Engineering',
                                     chunks=[], latency_ms=120, error='timeout', partial=True),
                ],
                'total_latency_ms': 170,
                'errors': ['eng: timeout'],
                'skipped_silos': [],
            })()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/v1/chat/completions", json={
                    "model": "rag-federated",
                    "messages": [{"role": "user", "content": "sick leave policy"}],
                    "stream": False,
                })

        assert response.status_code == 200
        data = response.json()
        assert data["model"] == "rag-federated"
        assert len(data["rag_sources"]) == 1
        assert data["rag_sources"][0]["silo_id"] == "hr"
        assert data["federation"]["mode"] == "merge"
        assert data["federation"]["silos_queried"] == ["hr"]
        assert len(data["federation"]["warnings"]) == 1

    @pytest.mark.asyncio
    async def test_all_silos_fail_returns_error(self, monkeypatch, mock_silos):
        monkeypatch.setenv("FEDERATION_MODE", "merge")
        from federation.app import config
        import importlib
        importlib.reload(config)

        with patch("federation.app.main.load_silos", return_value=mock_silos), \
             patch("federation.app.main.registry", SiloRegistry(mock_silos)), \
             patch("federation.app.main.federated_search") as mock_search:

            mock_search.return_value = type('obj', (object,), {
                'merged_chunks': [],
                'silo_results': [
                    SiloSearchResult(silo_id='hr', silo_name='HR KB', chunks=[],
                                     latency_ms=5000, error='connection refused', partial=True),
                ],
                'total_latency_ms': 5000,
                'errors': ['hr: connection refused'],
                'skipped_silos': [],
            })()

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/v1/chat/completions", json={
                    "model": "rag-federated",
                    "messages": [{"role": "user", "content": "query"}],
                })

        assert response.status_code == 200
        data = response.json()
        assert data["rag_sources"] == []

    @pytest.mark.asyncio
    async def test_health_endpoint(self, monkeypatch, mock_silos):
        with patch("federation.app.main.load_silos", return_value=mock_silos), \
             patch("federation.app.main.registry", SiloRegistry(mock_silos)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["federation"]["total_silos"] == 2
        assert "hr" in data["federation"]["silos"]
        assert "eng" in data["federation"]["silos"]
```

- [ ] **Step 2: Run integration tests**

```bash
python -m pytest federation/tests/test_integration.py -v
```
Expected: PASS

- [ ] **Step 3: Run all federation tests**

```bash
python -m pytest federation/tests/ -v
```
Expected: All tests PASS (approximately 25+ tests)

- [ ] **Step 4: Commit**

```bash
git add federation/tests/test_integration.py && git commit -m "test(federation): E2E integration tests — merge mode, failure mode, health"
```

---

## Plan Summary

| Task | Files | Tests |
|------|-------|-------|
| 1. Scaffold | `config.py`, `models.py`, `exceptions.py` | `test_config.py`, `test_models.py` |
| 2. Silo Registry | `silo_registry.py` | `test_silo_registry.py` |
| 3. Merger | `merger.py` | `test_merger.py` |
| 4. Silo Client | `silo_client.py` | `test_silo_client.py` |
| 5. Router | `router.py` | `test_router.py` |
| 6. Circuit Breaker | `circuit_breaker.py` | `test_circuit_breaker.py` |
| 7. Auth | `auth.py` | `test_auth.py` |
| 8. FastAPI App | `main.py`, `metrics.py` | `test_main.py`, `conftest.py` |
| 9. Auto-Router | `auto_router.py` | `test_auto_router.py` |
| 10. Wire Auto-Router | `router.py` (modify) | `test_router.py` (modify) |
| 11. Proxy Changes | `proxy/app/main.py` (modify) | proxy tests |
| 12. Docker | `Dockerfile`, `docker-compose` | — |
| 13. Integration | `test_integration.py` | `test_integration.py` |

**Estimated effort:** ~5 working days at normal pace. ~30+ tests total across 13 tasks.

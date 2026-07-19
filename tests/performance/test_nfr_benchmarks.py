# tests/performance/test_nfr_benchmarks.py
"""NFR benchmark and configuration tests.

Covers:
- FR-168: Qdrant scalar quantization (INT8)
- FR-169: Qdrant gRPC client
- FR-170: vLLM prefix caching
- FR-171: HNSW tuning
- FR-173: Model warm-up
- FR-174: AST-based code chunking
- FR-175: Table extraction from Confluence
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ============================================================================
# FR-168: Qdrant scalar quantization (INT8)
# ============================================================================


class TestQdrantQuantization:
    """FR-168: Collection must be created with INT8 scalar quantization."""

    def test_quantization_config_in_kb_manager(self):
        """kb_manager must reference ScalarQuantization with INT8 type."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "kb_manager.py").read_text()
        assert "ScalarQuantization" in content
        assert "INT8" in content or "ScalarType.INT8" in content

    def test_quantization_configurable(self):
        """Quantization must be toggleable via config."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "kb_manager.py").read_text()
        assert "QDRANT_QUANTIZATION_ENABLED" in content

    def test_quantization_uses_always_ram(self):
        """INT8 quantization should use always_ram=True for consistent performance."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "kb_manager.py").read_text()
        assert "always_ram" in content


# ============================================================================
# FR-169: Qdrant gRPC client
# ============================================================================


class TestQdrantGRPC:
    """FR-169: Proxy must prefer gRPC for Qdrant connections."""

    def test_grpc_config_exists(self):
        """Config must define QDRANT_GRPC_ENABLED and QDRANT_GRPC_PORT."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "QDRANT_GRPC_ENABLED" in content
        assert "QDRANT_GRPC_PORT" in content

    def test_retrieval_uses_prefer_grpc(self):
        """Retrieval module must use prefer_grpc option."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "retrieval.py").read_text()
        assert "prefer_grpc" in content

    def test_grpc_port_used_when_enabled(self):
        """grpc_port must be passed to client when gRPC is enabled."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "retrieval.py").read_text()
        assert "grpc_port" in content

    def test_enricher_uses_prefer_grpc(self):
        """Enricher module must also use prefer_grpc option."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "enricher.py").read_text()
        assert "prefer_grpc" in content


# ============================================================================
# FR-170: vLLM prefix caching
# ============================================================================


class TestVLLMPrefixCaching:
    """FR-170: vLLM prefix caching must be supported."""

    def test_prefix_caching_config_exists(self):
        """Config must include PREFIX_CACHING_ENABLED option."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "PREFIX_CACHING" in content

    def test_prefix_cache_hit_ratio_metric(self):
        """Must expose rag_vllm_prefix_cache_hit_ratio gauge."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "rag_vllm_prefix_cache_hit_ratio" in content

    def test_distributed_compose_enables_prefix_caching(self):
        """Distributed compose should enable prefix caching."""
        compose = (PROJECT_ROOT / "deploy" / "docker" / "docker-compose.distributed.yml").read_text()
        assert "PREFIX_CACHING" in compose


# ============================================================================
# FR-171: HNSW tuning
# ============================================================================


class TestHNSWTuning:
    """FR-171: HNSW parameters must be configurable."""

    def test_hnsw_m_configurable(self):
        """HNSW m parameter must come from config."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "QDRANT_HNSW_M" in content

    def test_hnsw_ef_construct_configurable(self):
        """HNSW ef_construct parameter must come from config."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        assert "QDRANT_HNSW_EF_CONSTRUCT" in content

    def test_kb_manager_uses_hnsw_config(self):
        """kb_manager must pass HNSW config to collection creation."""
        content = (PROJECT_ROOT / "proxy" / "app" / "core" / "kb_manager.py").read_text()
        assert "HnswConfigDiff" in content
        assert "_get_qdrant_hnsw_m" in content
        assert "_get_qdrant_hnsw_ef_construct" in content

    def test_hnsw_defaults_are_sensible(self):
        """Default HNSW values must be in valid ranges."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "config.py").read_text()
        # Find default values for HNSW parameters
        import re

        m_match = re.search(r"QDRANT_HNSW_M\s*=\s*int\(os\.environ\.get\([^)]+,\s*['\"]*(\d+)", content)
        if m_match:
            m_val = int(m_match.group(1))
            assert 8 <= m_val <= 64, f"HNSW m={m_val} outside expected range [8, 64]"

        ef_match = re.search(
            r"QDRANT_HNSW_EF_CONSTRUCT\s*=\s*int\(os\.environ\.get\([^)]+,\s*['\"]*(\d+)",
            content,
        )
        if ef_match:
            ef_val = int(ef_match.group(1))
            assert 64 <= ef_val <= 512, f"HNSW ef_construct={ef_val} outside expected range [64, 512]"


# ============================================================================
# FR-173: Model warm-up
# ============================================================================


class TestModelWarmup:
    """FR-173: Models must warm up on startup to avoid cold-start latency."""

    def test_warmup_module_exists(self):
        """warmup.py must exist with warmup functions."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "warmup.py").read_text()
        assert "warmup_embedder" in content
        assert "warmup_reranker" in content

    def test_warmup_configurable(self):
        """Warmup must be toggleable via WARMUP_ENABLED or WARMUP_ON_STARTUP."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "warmup.py").read_text()
        assert "WARMUP_ENABLED" in content

    def test_warmup_handles_failures_gracefully(self):
        """Warmup must not crash on failure — graceful degradation."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "warmup.py").read_text()
        # Must have try/except for each warmup step
        assert "except Exception" in content
        assert "return False" in content

    def test_warmup_status_metric(self):
        """Must expose warmup status as Prometheus gauge."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "metrics.py").read_text()
        assert "RAG_WARMUP_STATUS" in content or "rag_warmup_status" in content

    def test_warmup_all_models_function(self):
        """Must have a warmup_all function that orchestrates all warmups."""
        content = (PROJECT_ROOT / "proxy" / "app" / "shared" / "warmup.py").read_text()
        assert "warmup_all" in content


# ============================================================================
# FR-174: AST-based code chunking
# ============================================================================


class TestCodeChunking:
    """FR-174: Python files must be chunked by AST (functions/classes)."""

    def test_code_chunker_imports(self):
        """Code chunker must be importable."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.code_chunker import chunk_code, chunk_python

        assert callable(chunk_python)
        assert callable(chunk_code)

    def test_python_five_functions_produce_five_chunks(self):
        """Python file with 5 functions must produce 5 chunks."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.code_chunker import chunk_python

        source = '''\
def alpha():
    """First function."""
    return 1

def beta():
    """Second function."""
    return 2

def gamma():
    """Third function."""
    return 3

def delta():
    """Fourth function."""
    return 4

def epsilon():
    """Fifth function."""
    return 5
'''
        chunks = chunk_python(source)
        assert len(chunks) == 5, f"Expected 5 chunks, got {len(chunks)}: {[c.name for c in chunks]}"
        names = {c.name for c in chunks}
        assert names == {"alpha", "beta", "gamma", "delta", "epsilon"}

    def test_chunk_contains_complete_function(self):
        """Each chunk must contain the complete function body, not truncated."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.code_chunker import chunk_python

        source = '''\
def compute(x, y):
    """Add two numbers and return result."""
    result = x + y
    return result
'''
        chunks = chunk_python(source)
        assert len(chunks) == 1
        chunk = chunks[0]
        assert "def compute" in chunk.code
        assert "return result" in chunk.code
        assert chunk.docstring == "Add two numbers and return result."

    def test_class_chunking(self):
        """Python classes must be chunked as single units."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.code_chunker import chunk_python

        source = '''\
class MyService:
    """A service class."""

    def __init__(self, name):
        self.name = name

    def process(self):
        return self.name
'''
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert chunks[0].name == "MyService"
        assert "def __init__" in chunks[0].code
        assert "def process" in chunks[0].code

    def test_chunk_has_language_metadata(self):
        """Chunks must include language='python' metadata."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.code_chunker import chunk_python

        source = "def foo():\n    pass\n"
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert chunks[0].language == "python"

    def test_chunk_has_line_numbers(self):
        """Chunks must include line_start and line_end."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.code_chunker import chunk_python

        source = "x = 1\n\ndef foo():\n    return 42\n"
        chunks = chunk_python(source)
        assert len(chunks) == 1
        assert chunks[0].line_start > 0
        assert chunks[0].line_end >= chunks[0].line_start

    def test_empty_source_returns_no_chunks(self):
        """Empty source must return empty list."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.code_chunker import chunk_python

        assert chunk_python("") == []
        assert chunk_python("   \n  ") == []

    def test_syntax_error_falls_back_to_regex(self):
        """Invalid Python must fall back to regex chunker without crashing."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.code_chunker import chunk_python

        # Invalid syntax — missing colon
        source = "def broken(x)\n    return x\n"
        chunks = chunk_python(source)
        # Should not raise, may return 0 or more chunks from regex fallback
        assert isinstance(chunks, list)

    def test_dispatch_to_correct_language(self):
        """chunk_code must dispatch to the right language chunker."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.code_chunker import chunk_code

        python_src = "def hello():\n    pass\n"
        chunks = chunk_code(python_src, "python")
        assert len(chunks) == 1
        assert chunks[0].language == "python"


# ============================================================================
# FR-175: Table extraction from Confluence
# ============================================================================


class TestTableExtraction:
    """FR-175: Confluence tables must be extracted as structured data."""

    def test_table_extractor_imports(self):
        """Table extractor must be importable."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.table_extractor import extract_tables_from_html, table_to_json, table_to_markdown

        assert callable(extract_tables_from_html)
        assert callable(table_to_json)
        assert callable(table_to_markdown)

    def test_extract_simple_table(self):
        """Must extract a simple HTML table with headers and rows."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.table_extractor import extract_tables_from_html

        html = """
        <table>
            <thead><tr><th>Name</th><th>Value</th></tr></thead>
            <tbody>
                <tr><td>Alpha</td><td>100</td></tr>
                <tr><td>Beta</td><td>200</td></tr>
            </tbody>
        </table>
        """
        tables = extract_tables_from_html(html)
        assert len(tables) == 1
        t = tables[0]
        assert t.headers == ["Name", "Value"]
        assert len(t.rows) == 2
        assert t.rows[0] == ["Alpha", "100"]

    def test_table_to_json(self):
        """table_to_json must return structured dict with records."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.table_extractor import TableData, table_to_json

        table = TableData(
            headers=["A", "B"],
            rows=[["1", "2"], ["3", "4"]],
        )
        result = table_to_json(table)
        assert result["headers"] == ["A", "B"]
        assert result["row_count"] == 2
        assert len(result["records"]) == 2
        assert result["records"][0] == {"A": "1", "B": "2"}

    def test_table_to_markdown(self):
        """table_to_json must produce valid markdown table string."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.table_extractor import TableData, table_to_markdown

        table = TableData(
            headers=["Col1", "Col2"],
            rows=[["a", "b"]],
        )
        md = table_to_markdown(table)
        assert "Col1" in md
        assert "Col2" in md
        assert "---" in md  # separator row
        assert "a" in md
        assert "b" in md

    def test_extract_multiple_tables(self):
        """Must extract multiple tables from the same HTML."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.table_extractor import extract_tables_from_html

        html = """
        <table><tr><th>H1</th></tr><tr><td>V1</td></tr></table>
        <table><tr><th>H2</th></tr><tr><td>V2</td></tr></table>
        """
        tables = extract_tables_from_html(html)
        assert len(tables) == 2

    def test_extract_table_with_caption(self):
        """Must extract table caption when present."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.table_extractor import extract_tables_from_html

        html = """
        <table>
            <caption>System Status</caption>
            <tr><th>Service</th><th>Status</th></tr>
            <tr><td>Qdrant</td><td>UP</td></tr>
        </table>
        """
        tables = extract_tables_from_html(html)
        assert len(tables) == 1
        assert tables[0].caption == "System Status"

    def test_empty_html_returns_empty(self):
        """Empty HTML must return empty list."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.table_extractor import extract_tables_from_html

        assert extract_tables_from_html("") == []
        assert extract_tables_from_html("<p>No tables here</p>") == []

    def test_table_without_thead(self):
        """Must handle tables without explicit thead."""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT / "etl"))
        from etl.chunker.table_extractor import extract_tables_from_html

        html = """
        <table>
            <tr><th>Name</th><th>Age</th></tr>
            <tr><td>Alice</td><td>30</td></tr>
        </table>
        """
        tables = extract_tables_from_html(html)
        assert len(tables) == 1
        assert tables[0].headers == ["Name", "Age"]

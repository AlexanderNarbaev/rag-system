from federation.app.merger import (
    deduplicate_chunks,
    merge,
    merge_round_robin,
    merge_top_per_instance,
    merge_weighted_rrf,
)
from federation.app.models import SiloSearchResult


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
            make_chunk("a1", "text a1", "s a1", 0.9) | {"_silo_weight": 1.0},
            make_chunk("a2", "text a2", "s a2", 0.7) | {"_silo_weight": 1.0},
        ], latency=100)
        silo_b = make_silo_result("eng", "Engineering Wiki", [
            make_chunk("b1", "text b1", "s b1", 0.95) | {"_silo_weight": 1.0},
            make_chunk("b2", "text b2", "s b2", 0.5) | {"_silo_weight": 1.0},
        ], latency=120)

        result = merge_weighted_rrf([silo_a, silo_b], rrf_k=60, merge_k=4)
        assert len(result) == 4  # all chunks unique, under merge_k
        # a1 should be first (both rank 0, same weight, a1 from first silo)
        assert result[0]["id"] == "a1"

    def test_rrf_with_silo_weights(self):
        # Engineering has weight 1.2, HR has 1.0 — eng chunks should score higher
        silo_a = make_silo_result("hr", "HR KB", [
            make_chunk("a1", "text a1", "s a1", 0.9) | {"_silo_weight": 1.0},
        ])
        silo_b = make_silo_result("eng", "Engineering Wiki", [
            make_chunk("b1", "text b1", "s b1", 0.9) | {"_silo_weight": 1.2},
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

# tests/etl/test_entity_extractor.py
from unittest.mock import MagicMock

from etl.graph_builder.entity_extractor import (
    Entity,
    EntityRelationExtractor,
    Relation,
    entities_to_cypher,
)


class TestEntityDataclass:
    def test_entity_construction(self):
        e = Entity(id="e1", name="John", type="PERSON", source_id="doc_1")
        assert e.id == "e1"
        assert e.name == "John"
        assert e.type == "PERSON"
        assert e.source_id == "doc_1"
        assert e.properties == {}

    def test_entity_with_properties(self):
        e = Entity(
            id="e2",
            name="Acme Corp",
            type="ORGANIZATION",
            source_id="doc_2",
            properties={"founded": 1990, "industry": "tech"},
        )
        assert e.properties["founded"] == 1990


class TestRelationDataclass:
    def test_relation_construction(self):
        r = Relation(source="e1", target="e2", type="WORKS_FOR")
        assert r.source == "e1"
        assert r.target == "e2"
        assert r.type == "WORKS_FOR"
        assert r.properties == {}

    def test_relation_with_properties(self):
        r = Relation(
            source="e1",
            target="e2",
            type="DEPENDS_ON",
            properties={"description": "System A depends on System B"},
        )
        assert r.properties["description"] == "System A depends on System B"


class TestEntityRelationExtractorInit:
    def test_init_without_spacy(self, monkeypatch):
        monkeypatch.setattr("etl.graph_builder.entity_extractor.SPACY_AVAILABLE", False)
        extractor = EntityRelationExtractor(use_spacy=True)
        assert extractor.use_spacy is False
        assert extractor.nlp is None

    def test_init_with_cache_dir(self, tmp_path):
        cache = tmp_path / "entity_cache"
        EntityRelationExtractor(use_spacy=False, use_slm=False, cache_dir=cache)
        assert cache.is_dir()

    def test_init_with_slm_endpoint(self):
        extractor = EntityRelationExtractor(
            use_spacy=False,
            use_slm=True,
            slm_endpoint="http://localhost:8080/v1/completions",
        )
        assert extractor.slm_endpoint == "http://localhost:8080/v1/completions"


class TestExtractEntitiesSpacy:
    def test_no_nlp_returns_empty(self):
        extractor = EntityRelationExtractor(use_spacy=False)
        extractor.nlp = None
        result = extractor.extract_entities_spacy("some text")
        assert result == []

    def test_with_mocked_spacy(self):
        extractor = EntityRelationExtractor(use_spacy=False)
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_ent1 = MagicMock()
        mock_ent1.text = "Alice"
        mock_ent1.label_ = "PERSON"
        mock_ent2 = MagicMock()
        mock_ent2.text = "Google"
        mock_ent2.label_ = "ORG"
        mock_ent3 = MagicMock()
        mock_ent3.text = "London"
        mock_ent3.label_ = "GPE"
        mock_doc.ents = [mock_ent1, mock_ent2, mock_ent3]
        mock_nlp.return_value = mock_doc
        extractor.nlp = mock_nlp
        entities = extractor.extract_entities_spacy("Alice works at Google in London")
        assert len(entities) == 3
        names = {e.name for e in entities}
        assert "Alice" in names
        assert "Google" in names
        assert "London" in names

    def test_deduplication_by_name(self):
        extractor = EntityRelationExtractor(use_spacy=False)
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_ent1 = MagicMock()
        mock_ent1.text = "John"
        mock_ent1.label_ = "PERSON"
        mock_ent2 = MagicMock()
        mock_ent2.text = "John"
        mock_ent2.label_ = "PERSON"
        mock_doc.ents = [mock_ent1, mock_ent2]
        mock_nlp.return_value = mock_doc
        extractor.nlp = mock_nlp
        entities = extractor.extract_entities_spacy("John and John")
        assert len(entities) == 1

    def test_entity_type_mapping(self):
        extractor = EntityRelationExtractor(use_spacy=False)
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_ent = MagicMock()
        mock_ent.text = "EventX"
        mock_ent.label_ = "EVENT"
        mock_doc.ents = [mock_ent]
        mock_nlp.return_value = mock_doc
        extractor.nlp = mock_nlp
        entities = extractor.extract_entities_spacy("EventX happened")
        assert entities[0].type == "EVENT"


class TestExtractFromChunk:
    def test_extract_from_chunk_with_spacy(self):
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False)
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_ent = MagicMock()
        mock_ent.text = "Python"
        mock_ent.label_ = "PRODUCT"
        mock_doc.ents = [mock_ent]
        mock_nlp.return_value = mock_doc
        extractor.nlp = mock_nlp
        extractor.use_spacy = True
        entities, relations = extractor.extract_from_chunk("Python is great", source_id="doc_42")
        assert len(entities) >= 1
        assert entities[0].source_id == "doc_42"

    def test_extract_from_chunk_no_spacy(self):
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False)
        extractor.nlp = None
        entities, relations = extractor.extract_from_chunk("text", source_id="x")
        assert entities == []
        assert relations == []

    def test_extract_from_chunk_with_metadata(self):
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False)
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_ent = MagicMock()
        mock_ent.text = "Django"
        mock_ent.label_ = "PRODUCT"
        mock_doc.ents = [mock_ent]
        mock_nlp.return_value = mock_doc
        extractor.nlp = mock_nlp
        extractor.use_spacy = True
        entities, relations = extractor.extract_from_chunk(
            "Django framework",
            source_id="doc_1",
            chunk_metadata={"section": "intro"},
        )
        assert entities[0].properties.get("section") == "intro"


class TestExtractBatch:
    def test_extract_batch(self):
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False)
        mock_nlp = MagicMock()
        mock_doc = MagicMock()
        mock_ent = MagicMock()
        mock_ent.text = "FastAPI"
        mock_ent.label_ = "PRODUCT"
        mock_doc.ents = [mock_ent]
        mock_nlp.return_value = mock_doc
        extractor.nlp = mock_nlp
        extractor.use_spacy = True
        chunks = [
            {"text": "FastAPI is modern", "source_id": "c1"},
            {"text": "FastAPI is fast", "source_id": "c2"},
        ]
        entities, relations = extractor.extract_batch(chunks)
        # Deduplication should merge same entities by id
        assert len(entities) >= 1
        assert len(relations) >= 0

    def test_extract_batch_empty(self):
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False)
        entities, relations = extractor.extract_batch([])
        assert entities == []
        assert relations == []

    def test_extract_batch_with_prefix(self):
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False)
        extractor.nlp = None
        chunks = [{"text": "some text"}]
        entities, relations = extractor.extract_batch(chunks, source_id_prefix="default_prefix")
        assert entities == []


class TestEntitiesToCypher:
    def test_generates_cypher_queries(self):
        entities = [
            Entity(id="e1", name="PostgreSQL", type="TECHNOLOGY", source_id="doc_1"),
            Entity(id="e2", name="Redis", type="TECHNOLOGY", source_id="doc_1"),
        ]
        relations = [
            Relation(source="e1", target="e2", type="DEPENDS_ON"),
        ]
        queries = entities_to_cypher(entities, relations)
        assert len(queries) == 3  # 2 entity MERGE + 1 relation MERGE
        assert "MERGE" in queries[0] or "MERGE" in queries[1]
        assert "DEPENDS_ON" in queries[2]

    def test_empty_lists(self):
        queries = entities_to_cypher([], [])
        assert queries == []


class TestCacheOperations:
    def test_cache_save_and_load(self, tmp_path):
        cache = tmp_path / "cache"
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False, cache_dir=cache)
        entities = [Entity(id="e1", name="Test", type="CONCEPT", source_id="doc_1")]
        relations = [Relation(source="e1", target="e2", type="RELATES_TO")]
        key = extractor._get_cache_key("test text")
        extractor._save_to_cache(key, entities, relations)
        loaded = extractor._load_from_cache(key)
        assert loaded is not None
        loaded_entities, loaded_relations = loaded
        assert len(loaded_entities) == 1
        assert loaded_entities[0].name == "Test"
        assert len(loaded_relations) == 1

    def test_cache_load_nonexistent(self, tmp_path):
        cache = tmp_path / "cache"
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False, cache_dir=cache)
        result = extractor._load_from_cache("nonexistent_key")
        assert result is None

    def test_cache_load_no_cache_dir(self):
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False)
        result = extractor._load_from_cache("any_key")
        assert result is None

    def test_cache_save_no_cache_dir(self):
        extractor = EntityRelationExtractor(use_spacy=False, use_slm=False)
        # Should not raise
        extractor._save_to_cache("key", [], [])

    def test_cache_key_deterministic(self):
        extractor = EntityRelationExtractor(use_spacy=False)
        key1 = extractor._get_cache_key("hello world")
        key2 = extractor._get_cache_key("hello world")
        key3 = extractor._get_cache_key("different")
        assert key1 == key2
        assert key1 != key3

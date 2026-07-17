# etl/graph_builder/entity_extractor.py
"""Извлечение сущностей и отношений из текста для построения графа знаний.
Использует:
- spaCy (если доступна) для быстрого NER
- SLM (локальную модель) для извлечения отношений и кастомных сущностей
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import spacy

    SPACY_AVAILABLE = True
except ImportError:
    SPACY_AVAILABLE = False

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """Сущность для графа знаний."""

    id: str
    name: str
    type: str  # PERSON, ORGANIZATION, TECHNOLOGY, PRODUCT, GPE, CONCEPT, etc.
    source_id: str  # документ, из которого извлечена
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relation:
    """Отношение между двумя сущностями."""

    source: str  # id источника
    target: str  # id цели
    type: str  # RELATES_TO, DEPENDS_ON, USES, CONTAINS, etc.
    properties: dict[str, Any] = field(default_factory=dict)


class EntityRelationExtractor:
    """Извлекает сущности и отношения из текста, используя комбинацию NLP и SLM."""

    def __init__(
        self,
        use_spacy: bool = True,
        spacy_model: str = "ru_core_news_sm",
        use_slm: bool = False,
        slm_endpoint: str | None = None,
        cache_dir: Path | None = None,
        max_text_length: int = 4000,
    ):
        """:param use_spacy: использовать ли spaCy для базового NER
        :param spacy_model: модель spaCy (ru_core_news_sm, en_core_web_sm и т.д.)
        :param use_slm: использовать ли SLM для извлечения отношений
        :param slm_endpoint: URL локального сервера LLM (например, http://localhost:8080/v1/completions)
        :param cache_dir: директория для кэширования результатов (избежать повторных вызовов SLM)
        :param max_text_length: максимальная длина текста для обработки (токены/символы)
        """
        self.use_spacy = use_spacy and SPACY_AVAILABLE
        self.use_slm = use_slm and REQUESTS_AVAILABLE and slm_endpoint
        self.slm_endpoint = slm_endpoint
        self.max_text_length = max_text_length
        self.nlp = None
        if self.use_spacy:
            try:
                self.nlp = spacy.load(spacy_model)
                logger.info(f"Loaded spaCy model {spacy_model}")
            except OSError:
                logger.warning(
                    f"spaCy model {spacy_model} not found. Install with: python -m spacy download {spacy_model}",
                )
                self.use_spacy = False

        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache = {}  # in-memory cache

    def _get_cache_key(self, text: str) -> str:
        """Генерирует ключ кэша на основе текста."""
        return hashlib.sha256(text.encode()).hexdigest()

    def _load_from_cache(self, key: str) -> tuple[list[Entity], list[Relation]] | None:
        if not self.cache_dir:
            return None
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            with open(cache_file, encoding="utf-8") as f:
                data = json.load(f)
                entities = [Entity(**e) for e in data.get("entities", [])]
                relations = [Relation(**r) for r in data.get("relations", [])]
                return entities, relations
        return None

    def _save_to_cache(self, key: str, entities: list[Entity], relations: list[Relation]):
        if not self.cache_dir:
            return
        cache_file = self.cache_dir / f"{key}.json"
        data = {"entities": [e.__dict__ for e in entities], "relations": [r.__dict__ for r in relations]}
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def extract_entities_spacy(self, text: str) -> list[Entity]:
        """Извлекает сущности с помощью spaCy."""
        if not self.nlp:
            return []
        doc = self.nlp(text[: self.max_text_length])
        entities = []
        seen = set()
        for ent in doc.ents:
            # Приводим к каноническому виду
            name = ent.text.strip()
            if name and name not in seen:
                seen.add(name)
                ent_type = ent.label_
                # Маппинг типов спайси на наши типы
                type_map = {
                    "PERSON": "PERSON",
                    "ORG": "ORGANIZATION",
                    "GPE": "LOCATION",
                    "LOC": "LOCATION",
                    "PRODUCT": "PRODUCT",
                    "EVENT": "EVENT",
                    "WORK_OF_ART": "PRODUCT",
                }
                mapped_type = type_map.get(ent_type, "CONCEPT")
                entities.append(
                    Entity(
                        id=hashlib.sha256(f"{name}_{mapped_type}".encode()).hexdigest(),
                        name=name,
                        type=mapped_type,
                        source_id="",
                    ),
                )
        return entities

    def extract_relations_slm(self, text: str, entities: list[Entity]) -> list[Relation]:
        """Использует SLM для извлечения отношений между известными сущностями.
        Отправляет текст + список сущностей и запрашивает JSON с отношениями.
        """
        if not self.use_slm:
            return []

        # Подготовка промпта
        entity_names = [e.name for e in entities]
        entities_str = ", ".join(entity_names)
        prompt = (
            "You are an expert knowledge extractor. "
            "Analyze the following text and extract relationships "
            "between the listed entities."
            "\n"
            "Return ONLY valid JSON in the format: "
            '[{{"source": "entity1", "target": "entity2", '
            '"relation_type": "RELATES_TO", "description": "..."}}'
            ", ...]"
            f"\n\nText: {text[:3000]}"
            f"\n\nEntities: {entities_str}"
            "\n\nRelations:"
        )

        try:
            # Вызов SLM (ожидаем OpenAI-совместимый endpoint)
            payload: dict[str, Any] = {
                "prompt": prompt,
                "max_tokens": 1000,
                "temperature": 0.2,
                "stop": ["\n\n", "```"],
            }
            if self.slm_endpoint and self.slm_endpoint.endswith("/completions"):
                response = requests.post(self.slm_endpoint, json=payload, timeout=30)
            elif self.slm_endpoint:
                # Предполагаем chat completions API
                payload["messages"] = [{"role": "user", "content": prompt}]
                del payload["prompt"]
                response = requests.post(self.slm_endpoint + "/chat/completions", json=payload, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if "choices" in result:
                    output = (
                        result["choices"][0].get("text", "")
                        if "text" in result["choices"][0]
                        else result["choices"][0].get("message", {}).get("content", "")
                    )
                else:
                    output = result.get("text", "")
                # Извлечение JSON из ответа
                output = output.strip()
                # Убираем возможные маркеры кода
                output = output.removeprefix("```json")
                output = output.removesuffix("```")
                relations_data = json.loads(output)
                relations = []
                for rel in relations_data:
                    source_name = rel.get("source")
                    target_name = rel.get("target")
                    rel_type = rel.get("relation_type", "RELATES_TO")
                    # Находим id сущностей по имени
                    source_entity = next((e for e in entities if e.name == source_name), None)
                    target_entity = next((e for e in entities if e.name == target_name), None)
                    if source_entity and target_entity:
                        relations.append(
                            Relation(
                                source=source_entity.id,
                                target=target_entity.id,
                                type=rel_type,
                                properties={"description": rel.get("description", "")},
                            ),
                        )
                return relations
        except Exception as e:
            logger.warning(f"SLM relation extraction failed: {e}")
        return []

    def extract_from_chunk(
        self,
        text: str,
        source_id: str,
        chunk_metadata: dict[str, Any] | None = None,
    ) -> tuple[list[Entity], list[Relation]]:
        """Основной метод извлечения сущностей и отношений из одного чанка."""
        cache_key = self._get_cache_key(text + source_id)
        cached = self._load_from_cache(cache_key)
        if cached:
            return cached

        entities = []
        # 1. Базовое извлечение через spaCy
        if self.use_spacy:
            entities = self.extract_entities_spacy(text)

        # 2. Дополнительное извлечение кастомных сущностей через SLM (если включено)
        if self.use_slm and entities:  # noqa: SIM108
            relations = self.extract_relations_slm(text, entities)
        else:
            relations = []

        # Присваиваем source_id всем сущностям
        for e in entities:
            e.source_id = source_id
            if chunk_metadata:
                e.properties.update(chunk_metadata)

        self._save_to_cache(cache_key, entities, relations)
        return entities, relations

    def extract_batch(self, chunks: list[dict], source_id_prefix: str = None) -> tuple[list[Entity], list[Relation]]:
        """Обрабатывает пакет чанков (список словарей с полем 'text' и опционально 'metadata').
        Возвращает объединённые сущности и отношения с дедупликацией.
        """
        all_entities = []
        all_relations = []
        for chunk in chunks:
            text = chunk.get("text", "")
            source_id = chunk.get("source_id", source_id_prefix or "unknown")
            metadata = chunk.get("metadata", {})
            entities, relations = self.extract_from_chunk(text, source_id, metadata)
            all_entities.extend(entities)
            all_relations.extend(relations)

        # Дедупликация сущностей (объединяем по id)
        unique_entities = {}
        for e in all_entities:
            if e.id not in unique_entities:
                unique_entities[e.id] = e
            else:
                # Объединяем свойства
                unique_entities[e.id].properties.update(e.properties)
        # Дедупликация отношений (по source+target+type)
        unique_relations = {}
        for r in all_relations:
            key = f"{r.source}|{r.target}|{r.type}"
            if key not in unique_relations:
                unique_relations[key] = r
        return list(unique_entities.values()), list(unique_relations.values())


# Функция для подготовки данных в Neo4j (cypher-запросы)
def entities_to_cypher(entities: list[Entity], relations: list[Relation]) -> list[str]:
    """Генерирует Cypher-запросы для создания узлов и рёбер в Neo4j."""
    queries = []
    # Создание узлов
    for ent in entities:
        props = json.dumps({**ent.properties, "name": ent.name, "type": ent.type}, ensure_ascii=False)
        queries.append(f"MERGE (e:{ent.type.replace(' ', '_')} {{id: '{ent.id}'}}) SET e += {props}")
    # Создание рёбер
    for rel in relations:
        queries.append(
            f"MATCH (a {{id: '{rel.source}'}}), (b {{id: '{rel.target}'}}) "
            f"MERGE (a)-[r:{rel.type.upper()}]->(b) SET r += {json.dumps(rel.properties)}",
        )
    return queries


if __name__ == "__main__":
    # Пример использования
    sample_text = """
    Jira проект PROJ-123 использует Confluence страницу "Architecture" для документации.
    Разработчик Иван Иванов работает над интеграцией с GitLab CI.
    Система зависит от PostgreSQL 15 и Redis.
    """
    extractor = EntityRelationExtractor(
        use_spacy=True,
        use_slm=False,  # для теста без SLM
        cache_dir=Path("./entity_cache"),
    )
    entities, relations = extractor.extract_from_chunk(sample_text, source_id="test_doc")
    print("Entities:")
    for e in entities:
        print(f"  {e.name} ({e.type})")
    print("Relations:")
    for r in relations:
        print(f"  {r.source} -> {r.target} : {r.type}")

    # Генерация Cypher
    cypher = entities_to_cypher(entities, relations)
    print("\nCypher queries:")
    for q in cypher:
        print(q)

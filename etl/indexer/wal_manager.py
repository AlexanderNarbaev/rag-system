# etl/indexer/wal_manager.py
"""Универсальный менеджер Write-Ahead Log (WAL) для ETL-пайплайнов.
Используется для:
- Инкрементальных выгрузок (Confluence, Jira, GitLab)
- Индексации чанков в Qdrant
- Отслеживания последних успешных меток времени и идентификаторов

Формат WAL: JSON-файл с секциями для разных pipeline.
Поддерживает конкурентный доступ через filelock (опционально).

Remote backends:
- WAL_BACKEND="file" (default): local JSON file
- WAL_BACKEND="redis": store checkpoints in Redis
- WAL_BACKEND="proxy": POST checkpoints to proxy API
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from filelock import FileLock

    FILELOCK_AVAILABLE = True
except ImportError:
    FILELOCK_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class BaseWALBackend(ABC):
    """Abstract backend for WAL storage."""

    @abstractmethod
    def read(self) -> dict[str, Any]:
        """Read the complete WAL state."""

    @abstractmethod
    def write(self, data: dict[str, Any]) -> None:
        """Write the complete WAL state."""


class FileWALBackend(BaseWALBackend):
    """Local JSON file backend (default)."""

    def __init__(self, wal_path: Path, use_lock: bool = True, lock_timeout: int = 30):
        self.wal_path = Path(wal_path)
        self.use_lock = use_lock and FILELOCK_AVAILABLE
        self.lock_timeout = lock_timeout
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.wal_path.exists():
            self._write_raw({})

    def _get_lock(self) -> Any:
        if self.use_lock and FILELOCK_AVAILABLE:
            lock_path = self.wal_path.with_suffix(".lock")
            return FileLock(lock_path, timeout=self.lock_timeout)
        return None

    def _read_raw(self) -> dict[str, Any]:
        try:
            with open(self.wal_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning(f"WAL file {self.wal_path} corrupted or missing, reinitializing")
            return {}

    def _write_raw(self, data: dict[str, Any]) -> None:
        try:
            with open(self.wal_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error(f"Failed to write WAL file {self.wal_path}: {e}")
            raise

    def read(self) -> dict[str, Any]:
        return self._read_raw()

    def write(self, data: dict[str, Any]) -> None:
        lock = self._get_lock()
        if lock:
            with lock:
                self._write_raw(data)
        else:
            self._write_raw(data)


class RedisWALBackend(BaseWALBackend):
    """Redis-backed WAL storage. Stores each checkpoint under `etl:wal:{checkpoint_name}`."""

    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379, key_prefix: str = "etl:wal"):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.key_prefix = key_prefix
        self._redis: Any = None

    def _get_redis(self) -> Any:
        if self._redis is None:
            import redis as redis_lib

            self._redis = redis_lib.Redis(
                host=self.redis_host,
                port=self.redis_port,
                socket_connect_timeout=5,
                decode_responses=True,
            )
        return self._redis

    def read(self) -> dict[str, Any]:
        try:
            r = self._get_redis()
            keys = r.keys(f"{self.key_prefix}:*")
            result: dict[str, Any] = {}
            for key in keys:
                key_str: str = key if isinstance(key, str) else key.decode("utf-8")
                checkpoint_name = key_str[len(self.key_prefix) + 1 :]
                try:
                    result[checkpoint_name] = json.loads(r.get(key_str) or "{}")
                except (json.JSONDecodeError, TypeError):
                    result[checkpoint_name] = {}
            return result
        except Exception as e:
            logger.warning(f"Redis WAL read failed: {e}")
            return {}

    def write(self, data: dict[str, Any]) -> None:
        try:
            r = self._get_redis()
            pipe = r.pipeline()
            for checkpoint_name, checkpoint_data in data.items():
                key = f"{self.key_prefix}:{checkpoint_name}"
                pipe.set(key, json.dumps(checkpoint_data))
            pipe.execute()
        except Exception as e:
            logger.error(f"Redis WAL write failed: {e}")
            raise


class ProxyWALBackend(BaseWALBackend):
    """Proxy API-backed WAL storage. POSTs/GETs checkpoints via HTTP."""

    def __init__(self, proxy_url: str, api_key: str | None = None):
        self.proxy_url = proxy_url.rstrip("/")
        self.api_key = api_key

    def _get_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def read(self) -> dict[str, Any]:
        import urllib.request

        try:
            req = urllib.request.Request(
                f"{self.proxy_url}/v1/admin/etl/wal",
                headers={k: v for k, v in self._get_headers().items() if k != "Content-Type"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                return result.get("checkpoints", {})
        except Exception as e:
            logger.warning(f"Proxy WAL read failed: {e}")
            return {}

    def write(self, data: dict[str, Any]) -> None:
        import urllib.request

        for checkpoint_name, checkpoint_data in data.items():
            try:
                body = json.dumps(checkpoint_data).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.proxy_url}/v1/admin/etl/wal/{checkpoint_name}",
                    data=body,
                    headers=self._get_headers(),
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status not in (200, 201):
                        logger.warning(f"Proxy WAL write returned {resp.status} for {checkpoint_name}")
            except Exception as e:
                logger.error(f"Proxy WAL write failed for {checkpoint_name}: {e}")
                raise


class WALManager:
    """Менеджер WAL для ETL-процессов.
    Каждый pipeline (например, 'confluence_extractor', 'jira_extractor', 'indexing') имеет свою секцию.

    Supports pluggable backends: FileWALBackend (default), RedisWALBackend, ProxyWALBackend.
    """

    def __init__(
        self,
        wal_path: Path | None = None,
        use_lock: bool = True,
        lock_timeout: int = 30,
        backend: BaseWALBackend | None = None,
    ):
        """:param wal_path: путь к JSON-файлу WAL (used with file backend)
        :param use_lock: использовать ли файловую блокировку (требуется pip install filelock)
        :param lock_timeout: таймаут ожидания блокировки (секунды)
        :param backend: WAL backend instance. If None, creates FileWALBackend from wal_path.
        """
        if backend is not None:
            self._backend = backend
            self.wal_path = wal_path or Path("./wal/etl_wal.json")
        elif wal_path is not None:
            self._backend = FileWALBackend(Path(wal_path), use_lock=use_lock, lock_timeout=lock_timeout)
            self.wal_path = Path(wal_path)
        else:
            raise ValueError("Either wal_path or backend must be provided")
        self.use_lock = use_lock
        self.lock_timeout = lock_timeout

    def _read_wal(self) -> dict[str, Any]:
        """Читает текущий WAL (без блокировки, только чтение)."""
        try:
            return self._backend.read()
        except Exception:
            logger.warning("WAL read failed, returning empty state")
            return {}

    def _write_wal(self, data: dict[str, Any]) -> None:
        """Записывает WAL (без блокировки). Raises OSError on disk full."""
        self._backend.write(data)

    def _update_wal(self, update_func: Any) -> None:
        """Безопасное обновление WAL с блокировкой.
        update_func принимает текущие данные и возвращает обновлённые.
        """
        if self.use_lock and isinstance(self._backend, FileWALBackend):
            lock = self._backend._get_lock()
            if lock:
                with lock:
                    data = self._read_wal()
                    new_data = update_func(data)
                    self._write_wal(new_data)
                return
        data = self._read_wal()
        new_data = update_func(data)
        self._write_wal(new_data)

    def get_checkpoint(self, pipeline: str, key: str | None = None) -> Any:
        """Получает чекпоинт для указанного pipeline.
        Если key указан, возвращает конкретное значение (или None).
        Иначе возвращает весь словарь чекпоинта для этого pipeline.
        """
        data = self._read_wal()
        pipeline_data = data.get(pipeline, {})
        if key:
            return pipeline_data.get(key)
        return pipeline_data

    def set_checkpoint(self, pipeline: str, updates: dict[str, Any]):
        """Обновляет чекпоинт для pipeline. Добавляет/перезаписывает переданные ключи.
        Автоматически добавляет метку времени обновления '_updated_at'.
        """
        updates_with_time = updates.copy()
        updates_with_time["_updated_at"] = datetime.now(UTC).isoformat()

        def update(data: dict[str, Any]) -> dict[str, Any]:
            if pipeline not in data:
                data[pipeline] = {}
            data[pipeline].update(updates_with_time)
            return data

        self._update_wal(update)
        logger.debug(f"Updated checkpoint for pipeline '{pipeline}': {list(updates.keys())}")

    def update_last_run(self, pipeline: str, last_run: str | datetime | None = None) -> None:
        """Удобный метод для обновления временной метки последнего успешного запуска."""
        if last_run is None:
            last_run = datetime.now(UTC).isoformat()
        elif isinstance(last_run, datetime):
            last_run = last_run.isoformat()
        self.set_checkpoint(pipeline, {"last_run": last_run})

    def get_last_run(self, pipeline: str) -> str | None:
        """Возвращает last_run для pipeline или None."""
        result: Any = self.get_checkpoint(pipeline, "last_run")
        return str(result) if result is not None else None

    def update_offset(self, pipeline: str, offset: int) -> None:
        """Для пагинируемых выгрузок (например, startAt в Jira)."""
        self.set_checkpoint(pipeline, {"offset": offset})

    def get_offset(self, pipeline: str) -> int:
        """Возвращает сохранённый offset (0 по умолчанию)."""
        result: Any = self.get_checkpoint(pipeline, "offset")
        return int(result) if result else 0

    def update_last_id(self, pipeline: str, last_id: str) -> None:
        """Сохраняет последний обработанный ID (например, страницы Confluence или коммита)."""
        self.set_checkpoint(pipeline, {"last_id": last_id})

    def get_last_id(self, pipeline: str) -> str | None:
        result: Any = self.get_checkpoint(pipeline, "last_id")
        return str(result) if result is not None else None

    def update_hash_state(self, pipeline: str, doc_id: str, chunk_hash: str) -> None:
        """Для версионирования чанков: сохраняет хеш документа.
        Может использоваться вместе с ChunkVersionStore, но дублирует функциональность.
        """
        # Получаем текущий словарь хешей
        hash_map = self.get_checkpoint(pipeline, "hash_map") or {}
        hash_map[doc_id] = chunk_hash
        self.set_checkpoint(pipeline, {"hash_map": hash_map})

    def get_hash_state(self, pipeline: str, doc_id: str) -> str | None:
        hash_map: Any = self.get_checkpoint(pipeline, "hash_map") or {}
        return str(hash_map.get(doc_id)) if hash_map.get(doc_id) is not None else None

    def reset_pipeline(self, pipeline: str, keep_last_run: bool = False) -> None:
        """Сбрасывает чекпоинт для указанного pipeline.
        Если keep_last_run=True, сохраняет только last_run.
        """

        def update(data: dict[str, Any]) -> dict[str, Any]:
            if keep_last_run:
                last_run = data.get(pipeline, {}).get("last_run")
                data[pipeline] = {"last_run": last_run} if last_run else {}
            else:
                data.pop(pipeline, None)
            return data

        self._update_wal(update)
        logger.info(f"Reset checkpoint for pipeline '{pipeline}' (keep_last_run={keep_last_run})")

    def reset_all(self) -> None:
        """Полный сброс WAL."""
        self._update_wal(lambda data: {})
        logger.info("Reset all WAL checkpoints")

    def get_all_pipelines(self) -> list[str]:
        """Возвращает список всех pipeline, присутствующих в WAL."""
        data = self._read_wal()
        return list(data.keys())

    def vacuum(self, max_age_days: int = 30) -> None:
        """Очищает устаревшие записи (например, старые hash_map, чтобы WAL не разрастался).
        Удаляет hash_map для pipeline, если их возраст больше max_age_days.
        """

        def update(data: dict[str, Any]) -> dict[str, Any]:
            now = datetime.now(UTC)
            for pipeline, cp in data.items():
                updated_at = cp.get("_updated_at")
                if updated_at:
                    try:
                        updated = datetime.fromisoformat(updated_at)
                        if (now - updated).days > max_age_days:
                            # Удаляем большие поля, оставляя метаданные
                            if "hash_map" in cp:
                                del cp["hash_map"]
                                logger.debug(f"Vacuumed hash_map from {pipeline}")
                            if "processed_ids" in cp:
                                del cp["processed_ids"]
                    except Exception:
                        pass
            return data

        self._update_wal(update)


def create_wal_manager(config: dict[str, Any]) -> WALManager:
    """Factory function: creates WALManager with the appropriate backend based on config.

    Config keys used:
      wal.wal_backend: "file" (default), "redis", "proxy"
      wal.wal_file: path to WAL file (file backend)
      wal.use_lock: enable file locking (file backend)
      wal.lock_timeout: lock timeout (file backend)
      wal.redis_host: Redis host (redis backend)
      wal.redis_port: Redis port (redis backend)
      wal.proxy_url: proxy URL (proxy backend)

    Falls back to "file" if backend is unrecognized.
    """
    wal_cfg = config.get("wal", {})
    backend_name = wal_cfg.get("wal_backend") or os.environ.get("WAL_BACKEND", "file")
    use_lock = wal_cfg.get("use_lock", True) if isinstance(wal_cfg.get("use_lock"), bool) else True
    lock_timeout = int(wal_cfg.get("lock_timeout", 30))

    if backend_name == "redis":
        redis_host = wal_cfg.get("redis_host") or os.environ.get("REDIS_HOST", "localhost")
        redis_port = int(wal_cfg.get("redis_port") or os.environ.get("REDIS_PORT", 6379))
        backend: BaseWALBackend = RedisWALBackend(redis_host=redis_host, redis_port=redis_port)
        logger.info("WAL backend: redis (%s:%d)", redis_host, redis_port)
        return WALManager(wal_path=Path("./wal/etl_wal.json"), backend=backend, use_lock=False)
    elif backend_name == "proxy":
        proxy_url = wal_cfg.get("proxy_url") or os.environ.get("PROXY_URL", "http://localhost:8080")
        api_key = wal_cfg.get("proxy_api_key") or os.environ.get("PROXY_API_KEY", "")
        backend = ProxyWALBackend(proxy_url=proxy_url, api_key=api_key)
        logger.info("WAL backend: proxy (%s)", proxy_url)
        return WALManager(wal_path=Path("./wal/etl_wal.json"), backend=backend, use_lock=False)
    else:
        wal_file = wal_cfg.get("wal_file", "./wal/etl_wal.json")
        wal_path = Path(wal_file)
        logger.info("WAL backend: file (%s)", wal_path)
        return WALManager(wal_path=wal_path, use_lock=use_lock, lock_timeout=lock_timeout)


# Предустановленные константы для имён pipeline
PIPELINE_CONFLUENCE = "confluence_extractor"
PIPELINE_JIRA = "jira_extractor"
PIPELINE_GITLAB = "gitlab_extractor"
PIPELINE_INDEXING = "indexing"
PIPELINE_GRAPH = "graph_builder"

# Пример использования и тестирование
if __name__ == "__main__":
    # Создаём WAL менеджер
    wal = WALManager(Path("./test_wal/etl_wal.json"), use_lock=False)

    # Обновляем чекпоинт для Confluence
    wal.set_checkpoint(
        PIPELINE_CONFLUENCE,
        {"last_run": "2025-06-01T00:00:00", "space_keys": ["DEV", "OPS"], "total_pages": 1250},
    )

    # Обновляем last_run для Jira
    wal.update_last_run(PIPELINE_JIRA, "2025-06-02T12:00:00")

    # Сохраняем offset для GitLab (пагинация)
    wal.update_offset(PIPELINE_GITLAB, 150)

    # Получаем данные
    print(f"Confluence last_run: {wal.get_last_run(PIPELINE_CONFLUENCE)}")
    print(f"Jira last_run: {wal.get_last_run(PIPELINE_JIRA)}")
    print(f"GitLab offset: {wal.get_offset(PIPELINE_GITLAB)}")

    # Сохраняем хеш документа для индексации
    wal.update_hash_state(PIPELINE_INDEXING, "confluence_123", "abc123hash")
    print(f"Indexing hash for doc: {wal.get_hash_state(PIPELINE_INDEXING, 'confluence_123')}")

    # Сброс одного pipeline
    wal.reset_pipeline(PIPELINE_CONFLUENCE, keep_last_run=True)
    print(f"After reset, Confluence last_run: {wal.get_last_run(PIPELINE_CONFLUENCE)}")

    # Очистка старых данных
    wal.vacuum(max_age_days=1)

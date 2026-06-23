# etl/extractors/confluence.py
"""
Выгрузка данных из Confluence (Self-Hosted) с поддержкой:
- Страницы (тело: storage, view, export)
- Версии (полная история изменений)
- Вложения (метаданные + бинарные файлы)
- Комментарии (поток)
- Макросы (рендеренные и исходные параметры)
- Ссылки (внутренние на другие страницы, внешние URL)
- Инкрементальный режим (только изменённые страницы)
- WAL (чекпоинты для возобновления)
"""

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ConfluenceExtractor:
    def __init__(self, config: dict[str, Any]):
        """
        config: {
            "url": "https://confluence.internal/",
            "username": "bot",
            "token": "personal_access_token",
            "space_keys": ["DEV", "OPS"],  # None для всех пространств
            "output_dir": "./raw_data/confluence",
            "wal_file": "./wal/confluence_wal.json",
            "incremental": True,
            "download_attachments": True,
            "max_versions": 0,  # 0 = все версии
            "api_version": "2"   # '2' для нового REST API, '1' для старого
        }
        """
        self.url = config["url"].rstrip("/")
        self.auth = HTTPBasicAuth(config["username"], config["token"])
        self.space_keys = config.get("space_keys")
        self.output_dir = Path(config.get("output_dir", "./raw_data/confluence"))
        self.wal_path = Path(config.get("wal_file", "./wal/confluence_wal.json"))
        self.incremental = config.get("incremental", True)
        self.download_attachments = config.get("download_attachments", True)
        self.max_versions = config.get("max_versions", 0)
        self.api_version = config.get("api_version", "2")  # '2' или '1'

        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.headers.update({"Accept": "application/json"})

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)

        self.wal_data = self._load_wal()

    def _load_wal(self) -> dict:
        """Загружает WAL (последние успешные метки времени и хеши страниц)."""
        if self.wal_path.exists():
            with open(self.wal_path) as f:
                return json.load(f)
        return {"last_run": None, "pages_hash": {}}

    def _save_wal(self):
        with open(self.wal_path, "w") as f:
            json.dump(self.wal_data, f, indent=2)

    def _request(self, endpoint: str, params: dict = None) -> dict:
        """Выполняет GET запрос к Confluence API."""
        url = urljoin(self.url, endpoint)
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _get_all_pages(self, space_key: str = None, start: int = 0, limit: int = 50) -> list[dict]:
        """
        Рекурсивно получает все страницы с пагинацией.
        Возвращает список страниц (с минимальными полями).
        """
        pages = []
        while True:
            params = {
                "limit": limit,
                "start": start,
                "expand": "version,space,body.storage,body.view,ancestors",
            }
            if space_key:
                params["spaceKey"] = space_key
            data = self._request("/rest/api/content", params)
            pages.extend(data["results"])
            if "_links" in data and "next" in data["_links"]:
                # Используем URL следующей страницы
                next_url = data["_links"]["next"]
                if next_url.startswith("http"):
                    resp = self.session.get(next_url, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                else:
                    # относительный путь
                    data = self._request(next_url)
                start = 0  # сброс, т.к. следующий URL уже включает start
                # Чтобы избежать бесконечного цикла, проверяем
                if not data.get("results"):
                    break
            else:
                break
        return pages

    def _get_page_versions(self, page_id: str) -> list[dict]:
        """Возвращает историю версий страницы."""
        endpoint = f"/rest/api/content/{page_id}/version"
        data = self._request(endpoint)
        versions = data.get("results", [])
        if self.max_versions > 0 and len(versions) > self.max_versions:
            versions = versions[-self.max_versions :]
        return versions

    def _get_comments(self, page_id: str) -> list[dict]:
        """Возвращает комментарии к странице."""
        endpoint = f"/rest/api/content/{page_id}/child/comment"
        data = self._request(endpoint, params={"expand": "body.storage,version"})
        return data.get("results", [])

    def _get_attachments_metadata(self, page_id: str) -> list[dict]:
        """Возвращает метаданные вложений (без содержимого)."""
        endpoint = f"/rest/api/content/{page_id}/child/attachment"
        data = self._request(endpoint, params={"expand": "version"})
        return data.get("results", [])

    def _download_attachment(self, page_id: str, attachment_id: str, filename: str, output_dir: Path) -> str | None:
        """Скачивает файл вложения и возвращает путь к сохранённому файлу."""
        download_url = f"/rest/api/content/{page_id}/child/attachment/{attachment_id}/download"
        try:
            resp = self.session.get(urljoin(self.url, download_url), stream=True, timeout=60)
            resp.raise_for_status()
            safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_").strip()
            if not safe_name:
                safe_name = f"attachment_{attachment_id}.bin"
            file_path = output_dir / safe_name
            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return str(file_path)
        except Exception as e:
            logger.error(f"Failed to download attachment {attachment_id}: {e}")
            return None

    def _extract_links_from_html(self, html: str) -> dict[str, list[str]]:
        """Извлекает внутренние (Confluence) и внешние ссылки из HTML."""
        soup = BeautifulSoup(html, "html.parser")
        internal = []
        external = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/") or self.url in href:
                internal.append(href)
            else:
                external.append(href)
        return {"internal_links": list(set(internal)), "external_links": list(set(external))}

    def _calculate_page_hash(self, page: dict) -> str:
        """Вычисляет хеш содержимого страницы для проверки изменений."""
        # Берём body.storage.value + версию + дату изменения
        body = page.get("body", {}).get("storage", {}).get("value", "")
        version = page.get("version", {}).get("number", 0)
        modified = page.get("version", {}).get("when", "")
        content = f"{body}|{version}|{modified}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _should_process_page(self, page_id: str, new_hash: str) -> bool:
        """Определяет, нужно ли обрабатывать страницу заново (инкрементальный режим)."""
        if not self.incremental:
            return True
        old_hash = self.wal_data["pages_hash"].get(page_id)
        return old_hash != new_hash

    def _save_page_data(self, page_data: dict, page_id: str):
        """Сохраняет структурированные данные страницы в JSON."""
        page_dir = self.output_dir / page_id
        page_dir.mkdir(parents=True, exist_ok=True)
        # Основной файл с метаданными и контентом
        with open(page_dir / "page.json", "w", encoding="utf-8") as f:
            json.dump(page_data, f, ensure_ascii=False, indent=2)
        # Отдельно сохраняем raw body.storage (если нужно для семантического чанкинга)
        if "body_storage_raw" in page_data:
            with open(page_dir / "content_storage.html", "w", encoding="utf-8") as f:
                f.write(page_data["body_storage_raw"])
        logger.info(f"Saved page {page_id} to {page_dir}")

    def extract_page(self, page: dict) -> dict:
        """
        Извлекает полные данные одной страницы:
        - Метаданные (id, title, space, версии, даты)
        - Тело в форматах storage, view, export (если доступно)
        - Комментарии
        - Вложения (метаданные и файлы)
        - Ссылки
        """
        page_id = str(page["id"])
        title = page["title"]
        space = page.get("space", {}).get("key", "UNKNOWN")
        version_number = page.get("version", {}).get("number", 1)
        created = page.get("version", {}).get("when", "")
        updated = page.get("version", {}).get("when", "")

        # Получение тела в storage и view
        body_storage = page.get("body", {}).get("storage", {}).get("value", "")
        body_view = page.get("body", {}).get("view", {}).get("value", "")

        # Дополнительно: экспорт в PDF/Word через API (опционально, требует времени)
        # Можно вызвать /rest/api/content/{id}/export?type=pdf – но это асинхронно, не будем усложнять.

        # Извлечение ссылок из HTML тела
        links = self._extract_links_from_html(body_view if body_view else body_storage)

        # Версии (история)
        versions = self._get_page_versions(page_id)
        version_list = []
        for v in versions:
            version_list.append(
                {
                    "number": v.get("number"),
                    "when": v.get("when"),
                    "message": v.get("message", ""),
                    "author": v.get("by", {}).get("displayName", ""),
                }
            )

        # Комментарии
        comments = self._get_comments(page_id)
        comment_data = []
        for com in comments:
            com_body = com.get("body", {}).get("storage", {}).get("value", "")
            comment_data.append(
                {
                    "id": com["id"],
                    "author": com.get("version", {}).get("by", {}).get("displayName", ""),
                    "created": com.get("version", {}).get("when", ""),
                    "body_storage": com_body,
                }
            )

        # Вложения
        attachments_meta = self._get_attachments_metadata(page_id)
        attachment_data = []
        att_dir = self.output_dir / page_id / "attachments"
        if self.download_attachments:
            att_dir.mkdir(exist_ok=True)
        for att in attachments_meta:
            att_id = att["id"]
            att_filename = att.get("title", "unnamed")
            att_info = {
                "id": att_id,
                "filename": att_filename,
                "media_type": att.get("mediaType", "application/octet-stream"),
                "size": att.get("fileSize", 0),
                "version": att.get("version", {}).get("number", 1),
                "comment": att.get("version", {}).get("message", ""),
            }
            if self.download_attachments:
                local_path = self._download_attachment(page_id, att_id, att_filename, att_dir)
                att_info["local_path"] = local_path
            attachment_data.append(att_info)

        # Макросы: можно извлечь из storage формата (XML-like)
        # Пример: <ac:structured-macro ac:name="code">...</ac:structured-macro>
        macros = []
        if body_storage:
            soup_macros = BeautifulSoup(body_storage, "html.parser")
            for macro in soup_macros.find_all("ac:structured-macro"):
                macro_name = macro.get("ac:name", "")
                macro_params = {}
                for param in macro.find_all("ac:parameter"):
                    key = param.get("ac:name")
                    value = param.get_text(strip=True)
                    if key:
                        macro_params[key] = value
                macros.append({"name": macro_name, "parameters": macro_params, "raw_html": str(macro)})

        # Итоговый объект
        page_data = {
            "id": page_id,
            "title": title,
            "space": space,
            "version": version_number,
            "created_at": created,
            "updated_at": updated,
            "body_storage_raw": body_storage,
            "body_view_html": body_view,
            "links": links,
            "versions": version_list,
            "comments": comment_data,
            "attachments": attachment_data,
            "macros": macros,
            "extracted_at": datetime.now(UTC).isoformat(),
        }
        return page_data

    def run(self):
        """Основной цикл выгрузки всех страниц (по указанным пространствам или всем)."""
        spaces_to_process = self.space_keys if self.space_keys else [None]  # None = все пространства
        for space in spaces_to_process:
            logger.info(f"Processing space: {space if space else 'ALL'}")
            pages = self._get_all_pages(space_key=space)
            logger.info(f"Found {len(pages)} pages in space {space}")
            for page in pages:
                page_id = str(page["id"])
                new_hash = self._calculate_page_hash(page)
                if not self._should_process_page(page_id, new_hash):
                    logger.debug(f"Skipping page {page_id} (no changes)")
                    continue
                try:
                    full_data = self.extract_page(page)
                    self._save_page_data(full_data, page_id)
                    # Обновляем WAL
                    self.wal_data["pages_hash"][page_id] = new_hash
                    self.wal_data["last_run"] = datetime.now(UTC).isoformat()
                    self._save_wal()
                except Exception as e:
                    logger.error(f"Failed to process page {page_id}: {e}", exc_info=True)
                    # Продолжаем, не прерываем весь процесс
        logger.info("Extraction finished.")


if __name__ == "__main__":
    # Пример конфигурации (загружать из etl_config.yaml или переменных окружения)
    config_example = {
        "url": os.getenv("CONFLUENCE_URL", "https://confluence.example.com"),
        "username": os.getenv("CONFLUENCE_USER", "bot"),
        "token": os.getenv("CONFLUENCE_TOKEN", "your_token"),
        "space_keys": ["DEV", "OPS"],  # или None для всех
        "output_dir": "./raw_data/confluence",
        "wal_file": "./wal/confluence_wal.json",
        "incremental": True,
        "download_attachments": True,
        "max_versions": 0,
        "api_version": "2",
    }
    extractor = ConfluenceExtractor(config_example)
    extractor.run()

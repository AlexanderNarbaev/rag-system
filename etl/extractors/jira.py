# etl/extractors/jira.py
"""
Выгрузка данных из Jira (Self-Hosted) с поддержкой:
- Задачи (issues) с полным набором полей
- Комментарии
- Changelog (история изменений полей)
- Вложения (скачивание бинарных файлов)
- Спринты (из agile-API)
- Связи: issuelinks, subtasks
- Инкрементальный режим (updated > last_run)
- WAL для возобновления
"""

import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import urllib3
from requests.auth import HTTPBasicAuth

# Подавление SSL warnings для самоподписанных сертификатов
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class JiraExtractor:
    def __init__(self, config: dict[str, Any]):
        """
        config: {
            "url": "https://jira.internal.company.com",
            "username": "bot",                   # опционально для Basic Auth
            "token": "api_token_or_password",    # Bearer токен или пароль
            "verify_ssl": true,                  # false для самоподписанных сертификатов
            "ca_bundle": "",                     # путь к корпоративному CA bundle
            "jql": "project in (ABC, DEF) ORDER BY updated DESC",
            "output_dir": "./raw_data/jira",
            "wal_file": "./wal/jira_wal.json",
            "incremental": True,
            "download_attachments": True,
            "max_issues_per_run": 0,
            "since_date": None,
            "fields": "*all",
            "expand": "changelog,renderedBody"
        }
        """
        self.url = config["url"].rstrip("/")
        self.base_jql = config.get("jql", "ORDER BY updated DESC")
        self.output_dir = Path(config.get("output_dir", "./raw_data/jira"))
        self.wal_path = Path(config.get("wal_file", "./wal/jira_wal.json"))
        self.incremental = config.get("incremental", True)
        self.download_attachments = config.get("download_attachments", True)
        self.max_issues_per_run = config.get("max_issues_per_run", 0)
        self.since_date = config.get("since_date")
        self.fields = config.get("fields", "*all")
        self.expand = config.get("expand", "changelog,renderedBody")

        # Timeout configuration
        self.connect_timeout = config.get("connect_timeout", 10)
        self.read_timeout = config.get("timeout", 30)
        self.timeout = (self.connect_timeout, self.read_timeout)

        self.session = requests.Session()

        # SSL configuration
        verify_ssl = config.get("verify_ssl", True)
        ca_bundle = config.get("ca_bundle", "")
        if ca_bundle and os.path.exists(ca_bundle):
            self.session.verify = ca_bundle
        else:
            self.session.verify = verify_ssl

        # Auth: Bearer token (если нет username) или Basic Auth
        token = config.get("token", "")
        username = config.get("username", "")
        if username:
            self.session.auth = HTTPBasicAuth(username, token)
        else:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers.update({"Accept": "application/json"})

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        self.wal_data = self._load_wal()

    def _load_wal(self) -> dict:
        if self.wal_path.exists():
            with open(self.wal_path) as f:
                return json.load(f)
        return {"last_run": None, "last_issue_id": None, "processed_issues": []}

    def _save_wal(self):
        with open(self.wal_path, "w") as f:
            json.dump(self.wal_data, f, indent=2)

    def _request(self, endpoint: str, params: dict = None) -> dict:
        url = urljoin(self.url, endpoint)
        logger.debug(f"Requesting: {url}")
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            logger.debug(f"Response: {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL Error: {e}")
            raise
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection Error: {e}")
            raise
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout: {e}")
            raise

    def _paginated_issues(self, jql: str, start_at: int = 0, max_results: int = 100) -> Iterator[dict]:
        """Генератор для пагинированного получения задач."""
        while True:
            params = {
                "jql": jql,
                "fields": self.fields,
                "expand": self.expand,
                "startAt": start_at,
                "maxResults": max_results,
            }
            data = self._request("/rest/api/3/search", params)
            issues = data.get("issues", [])
            yield from issues
            if start_at + max_results >= data["total"]:
                break
            start_at += max_results

    def _get_issue_transitions(self, issue_key: str) -> list[dict]:
        """Возвращает доступные переходы (не все хранятся в changelog, но полезно)."""
        endpoint = f"/rest/api/3/issue/{issue_key}/transitions"
        data = self._request(endpoint)
        return data.get("transitions", [])

    def _get_sprints_for_issue(self, issue_key: str) -> list[dict]:
        """
        Получает спринты, связанные с задачей (через agile API).
        Требует установленного дополнения Jira Agile (Greenhopper).
        """
        endpoint = f"/rest/agile/1.0/issue/{issue_key}"
        try:
            data = self._request(endpoint)
            return data.get("fields", {}).get("sprint", [])
        except Exception as e:
            logger.debug(f"Sprint info not available for {issue_key}: {e}")
            return []

    def _download_attachment(self, attachment: dict, issue_key: str) -> str | None:
        """Скачивает вложение и возвращает локальный путь."""
        attachment_id = attachment["id"]
        filename = attachment["filename"]
        download_url = attachment["content"]
        # Используем сессию с аутентификацией
        try:
            resp = self.session.get(download_url, stream=True, timeout=60)
            resp.raise_for_status()
            issue_dir = self.output_dir / issue_key / "attachments"
            issue_dir.mkdir(parents=True, exist_ok=True)
            safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_")
            if not safe_name:
                safe_name = f"attachment_{attachment_id}.bin"
            file_path = issue_dir / safe_name
            with open(file_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return str(file_path)
        except Exception as e:
            logger.error(f"Failed to download attachment {attachment_id} for {issue_key}: {e}")
            return None

    def _extract_links_from_text(self, text: str) -> dict[str, list[str]]:
        """Извлекает ссылки из текста (описание, комментарий): URL и Jira issue ключи."""
        import re

        url_pattern = r'https?://[^\s<>"\']+'
        issue_key_pattern = r"[A-Z][A-Z0-9]+-\d+"
        urls = re.findall(url_pattern, text) if text else []
        issue_keys = re.findall(issue_key_pattern, text) if text else []
        return {"external_urls": list(set(urls)), "mentioned_issues": list(set(issue_keys))}

    def _process_issue(self, issue: dict) -> dict:
        """Преобразует сырой JSON задачи в структурированный формат с нужными данными."""
        key = issue["key"]
        fields = issue.get("fields", {})

        # Базовые поля
        summary = fields.get("summary", "")
        description = fields.get("description", "")
        status = fields.get("status", {}).get("name", "")
        priority = fields.get("priority", {}).get("name", "")
        issuetype = fields.get("issuetype", {}).get("name", "")
        created = fields.get("created", "")
        updated = fields.get("updated", "")
        resolution = fields.get("resolution", {}).get("name", "") if fields.get("resolution") else None
        assignee = fields.get("assignee", {}).get("displayName", "") if fields.get("assignee") else None
        reporter = fields.get("reporter", {}).get("displayName", "") if fields.get("reporter") else None
        labels = fields.get("labels", [])

        # Спринты (если есть)
        sprints = self._get_sprints_for_issue(key)

        # Комментарии (уже входят в expand=renderedBody)
        comments_data = fields.get("comment", {}).get("comments", [])
        comments = []
        for com in comments_data:
            comment_body = com.get("body", "")
            comments.append(
                {
                    "id": com["id"],
                    "author": com.get("author", {}).get("displayName", ""),
                    "created": com.get("created", ""),
                    "updated": com.get("updated", ""),
                    "body": comment_body,
                    "links": self._extract_links_from_text(comment_body),
                }
            )

        # Changelog (история изменений)
        changelog = issue.get("changelog", {})
        histories = changelog.get("histories", [])
        changelog_entries = []
        for hist in histories:
            for item in hist.get("items", []):
                changelog_entries.append(
                    {
                        "author": hist.get("author", {}).get("displayName", ""),
                        "created": hist.get("created", ""),
                        "field": item.get("field", ""),
                        "from": item.get("fromString", ""),
                        "to": item.get("toString", ""),
                    }
                )

        # Вложения
        attachments = []
        if self.download_attachments:
            for att in fields.get("attachment", []):
                local_path = self._download_attachment(att, key)
                attachments.append(
                    {
                        "id": att["id"],
                        "filename": att["filename"],
                        "size": att.get("size", 0),
                        "mime_type": att.get("mimeType", ""),
                        "created": att.get("created", ""),
                        "author": att.get("author", {}).get("displayName", ""),
                        "local_path": local_path,
                    }
                )
        else:
            attachments = [
                {
                    "id": att["id"],
                    "filename": att["filename"],
                    "size": att.get("size", 0),
                    "mime_type": att.get("mimeType", ""),
                    "created": att.get("created", ""),
                }
                for att in fields.get("attachment", [])
            ]

        # Связи (issuelinks, subtasks)
        links = []
        for link in fields.get("issuelinks", []):
            link_info = {}
            if "outwardIssue" in link:
                link_info["direction"] = "outward"
                link_info["type"] = link.get("type", {}).get("outward", "")
                link_info["target_key"] = link["outwardIssue"]["key"]
            elif "inwardIssue" in link:
                link_info["direction"] = "inward"
                link_info["type"] = link.get("type", {}).get("inward", "")
                link_info["target_key"] = link["inwardIssue"]["key"]
            if link_info:
                links.append(link_info)

        # Подзадачи (subtasks)
        subtasks = [{"key": st["key"], "summary": st["fields"].get("summary", "")} for st in fields.get("subtasks", [])]

        # Извлечение ссылок из описания
        description_links = self._extract_links_from_text(description)

        # Итоговый объект задачи
        result = {
            "key": key,
            "summary": summary,
            "description": description,
            "status": status,
            "priority": priority,
            "issuetype": issuetype,
            "created": created,
            "updated": updated,
            "resolution": resolution,
            "assignee": assignee,
            "reporter": reporter,
            "labels": labels,
            "sprints": sprints,
            "comments": comments,
            "changelog": changelog_entries,
            "attachments": attachments,
            "links": links,
            "subtasks": subtasks,
            "description_links": description_links,
            "extracted_at": datetime.now(UTC).isoformat(),
        }
        return result

    def _build_jql(self) -> str:
        """Формирует JQL с учётом инкрементального режима."""
        jql = self.base_jql
        if self.incremental and (self.wal_data["last_run"] or self.since_date):
            last = self.since_date or self.wal_data["last_run"]
            # Добавляем условие updated >= last (но нужно аккуратно с ORDER BY)
            # Если в базовом JQL уже есть updated, заменяем или добавляем
            updated_condition = f"updated >= '{last}'"
            if "updated" in jql:
                # Простейшее: предполагаем, что updated встречается в виде updated > ... или updated >= ...
                import re

                if re.search(r"updated\s*[<>=]", jql):
                    logger.warning("Base JQL already has updated condition. Incremental may overlap.")
                    return f"({jql}) AND {updated_condition}"
            else:
                if jql.strip():  # noqa: SIM108
                    jql = f"({jql}) AND {updated_condition}"
                else:
                    jql = updated_condition
        return jql

    def run(self):
        """Основной процесс выгрузки задач."""
        jql = self._build_jql()
        logger.info(f"Executing JQL: {jql}")
        total_processed = 0
        for issue in self._paginated_issues(jql):
            key = issue["key"]
            if key in self.wal_data["processed_issues"] and self.incremental:
                logger.debug(f"Skipping already processed issue {key}")
                continue

            try:
                processed = self._process_issue(issue)
                # Сохраняем в JSON
                issue_dir = self.output_dir / key
                issue_dir.mkdir(parents=True, exist_ok=True)
                with open(issue_dir / "issue.json", "w", encoding="utf-8") as f:
                    json.dump(processed, f, ensure_ascii=False, indent=2)

                # Обновляем WAL
                if key not in self.wal_data["processed_issues"]:
                    self.wal_data["processed_issues"].append(key)
                self.wal_data["last_run"] = datetime.now(UTC).isoformat()
                self._save_wal()

                total_processed += 1
                if self.max_issues_per_run > 0 and total_processed >= self.max_issues_per_run:
                    logger.info(f"Reached max issues per run ({self.max_issues_per_run})")
                    break

                logger.info(f"Processed issue {key}")
            except Exception as e:
                logger.error(f"Failed to process issue {key}: {e}", exc_info=True)
                # продолжаем со следующей задачей

        logger.info(f"Jira extraction finished. Processed {total_processed} issues.")


if __name__ == "__main__":
    # Пример конфигурации (загружать из etl_config.yaml или переменных окружения)
    config_example = {
        "url": os.getenv("JIRA_URL", "https://jira.example.com"),
        "username": os.getenv("JIRA_USER", "bot"),
        "token": os.getenv("JIRA_TOKEN", "your_token"),
        "jql": "project in (DEV, OPS) AND status not in (Closed, Resolved) ORDER BY updated DESC",
        "output_dir": "./raw_data/jira",
        "wal_file": "./wal/jira_wal.json",
        "incremental": True,
        "download_attachments": True,
        "max_issues_per_run": 0,
        "since_date": "2025-01-01T00:00:00.000+0000",
        "fields": "*all",
        "expand": "changelog,renderedBody",
    }
    extractor = JiraExtractor(config_example)
    extractor.run()

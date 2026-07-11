# etl/extractors/gitlab.py
"""
Выгрузка данных из GitLab (Self-Hosted) с поддержкой:
- Проекты (все или по списку)
- Коммиты (полные метаданные + diff файлов)
- Ветки
- Содержимое файлов (код, конфиги)
- Merge Requests (обсуждения, комментарии, изменения)
- Дискуссии (нити комментариев в MR)
- Инкрементальный режим (хеши коммитов, timestamp последнего MR)
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

# Подавление SSL warnings для самоподписанных сертификатов
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class GitLabExtractor:
    def __init__(self, config: dict[str, Any]):
        """
        config: {
            "url": "https://gitlab.internal.company.com",
            "token": "personal_access_token",
            "verify_ssl": true,                  # false для самоподписанных сертификатов
            "ca_bundle": "",                     # путь к корпоративному CA bundle
            "project_ids": None,
            "output_dir": "./raw_data/gitlab",
            "wal_file": "./wal/gitlab_wal.json",
            "incremental": True,
            "fetch_commits": True,
            "fetch_files": True,
            "fetch_merge_requests": True,
            "max_commits_per_project": 0,
            "since_date": None,
            "file_paths_filter": ["*.py", "*.md", "Dockerfile", "*.yaml"]
        }
        """
        self.url = config["url"].rstrip("/")
        self.token = config["token"]
        self.project_ids = config.get("project_ids")
        self.output_dir = Path(config.get("output_dir", "./raw_data/gitlab"))
        self.wal_path = Path(config.get("wal_file", "./wal/gitlab_wal.json"))
        self.incremental = config.get("incremental", True)
        self.fetch_commits = config.get("fetch_commits", True)
        self.fetch_files = config.get("fetch_files", True)
        self.fetch_merge_requests = config.get("fetch_merge_requests", True)
        self.max_commits_per_project = config.get("max_commits_per_project", 0)
        self.since_date = config.get("since_date")
        self.file_paths_filter = config.get("file_paths_filter", [])

        self.session = requests.Session()

        # SSL configuration
        verify_ssl = config.get("verify_ssl", True)
        ca_bundle = config.get("ca_bundle", "")
        if ca_bundle and os.path.exists(ca_bundle):
            self.session.verify = ca_bundle
        else:
            self.session.verify = verify_ssl

        # GitLab token auth
        self.session.headers["PRIVATE-TOKEN"] = self.token
        self.session.headers.update({"PRIVATE-TOKEN": self.token, "Accept": "application/json"})

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.wal_path.parent.mkdir(parents=True, exist_ok=True)
        self.wal_data = self._load_wal()

    def _load_wal(self) -> dict:
        if self.wal_path.exists():
            with open(self.wal_path) as f:
                return json.load(f)
        return {"last_run": None, "projects": {}}

    def _save_wal(self):
        with open(self.wal_path, "w") as f:
            json.dump(self.wal_data, f, indent=2)

    def _request(self, endpoint: str, params: dict = None, method: str = "GET") -> dict:
        url = urljoin(self.url, endpoint)
        resp = self.session.request(method, url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _paginated_get(self, endpoint: str, params: dict = None, per_page: int = 100) -> Iterator[dict]:
        """Пагинированный сбор всех элементов (постранично)."""
        page = 1
        while True:
            paginated_params = {"page": page, "per_page": per_page}
            if params:
                paginated_params.update(params)
            data = self._request(endpoint, params=paginated_params)
            if not data:
                break
            yield from data
            page += 1

    def get_projects(self) -> list[dict]:
        """Список проектов (репозиториев)."""
        if self.project_ids:
            projects = []
            for pid in self.project_ids:
                proj = self._request(f"/api/v4/projects/{pid}")
                projects.append(proj)
            return projects
        else:
            return list(self._paginated_get("/api/v4/projects", {"simple": True}))

    def get_commits(self, project_id: int, since: str = None) -> list[dict]:
        """Коммиты с пагинацией. Опционально фильтр since (ISO8601)."""
        params = {"with_stats": True}
        if since:
            params["since"] = since
        commits = []
        for commit in self._paginated_get(f"/api/v4/projects/{project_id}/repository/commits", params):
            commits.append(commit)
            if self.max_commits_per_project > 0 and len(commits) >= self.max_commits_per_project:
                break
        # Добавить diff для каждого коммита (ограничимся топ-50 файлов)
        for commit in commits:
            sha = commit["id"]
            diff_endpoint = f"/api/v4/projects/{project_id}/repository/commits/{sha}/diff"
            try:
                diff_data = self._request(diff_endpoint)
                commit["diff"] = diff_data  # список файлов с изменениями
            except Exception as e:
                logger.warning(f"Failed to fetch diff for commit {sha}: {e}")
                commit["diff"] = []
        return commits

    def get_branches(self, project_id: int) -> list[dict]:
        """Список веток репозитория."""
        return list(self._paginated_get(f"/api/v4/projects/{project_id}/repository/branches"))

    def get_file_content(self, project_id: int, file_path: str, ref: str = "main") -> str | None:
        """Получает содержимое файла (текст). Возвращает None если не удалось."""
        encoded_path = file_path.replace("/", "%2F")
        endpoint = f"/api/v4/projects/{project_id}/repository/files/{encoded_path}/raw"
        try:
            resp = self.session.get(urljoin(self.url, endpoint), params={"ref": ref}, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning(f"Failed to fetch file {file_path} in project {project_id}: {e}")
            return None

    def get_merge_requests(self, project_id: int, state: str = "all") -> list[dict]:
        """MR с пагинацией. Добавляет обсуждения и комментарии."""
        params = {"state": state}
        if self.since_date:
            params["updated_after"] = self.since_date
        mrs = []
        for mr in self._paginated_get(f"/api/v4/projects/{project_id}/merge_requests", params):
            # Добавляем обсуждения (discussions) и отдельные комментарии (notes)
            mr_iid = mr["iid"]
            discussions = self.get_mr_discussions(project_id, mr_iid)
            mr["discussions"] = discussions
            # Также получаем изменения (changes) – файлы, затронутые MR
            changes = self._request(f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/changes")
            mr["changes"] = changes.get("changes", [])
            mrs.append(mr)
        return mrs

    def get_mr_discussions(self, project_id: int, mr_iid: int) -> list[dict]:
        """Возвращает все дискуссии (нити комментариев) в MR."""
        discussions = list(self._paginated_get(f"/api/v4/projects/{project_id}/merge_requests/{mr_iid}/discussions"))
        # Преобразуем в удобный формат: каждая дискуссия содержит массив заметок (notes)
        result = []
        for disc in discussions:
            notes = []
            for note in disc.get("notes", []):
                notes.append(
                    {
                        "id": note["id"],
                        "author": note["author"]["username"],
                        "created_at": note["created_at"],
                        "body": note["body"],
                        "type": note.get("type", "regular"),  # DiffNote, etc.
                    }
                )
            result.append({"id": disc["id"], "notes": notes})
        return result

    def _should_process_commit(self, project_id: int, commit_sha: str, commit_updated: str) -> bool:
        """Инкрементальная проверка: обрабатывать коммит, если он новый или изменился."""
        if not self.incremental:
            return True
        project_wal = self.wal_data["projects"].get(str(project_id), {})
        last_commit = project_wal.get("last_commit_sha")
        if not last_commit:
            return True
        # Если SHA изменился (новый коммит) – всё равно нужно обработать
        # Простой подход: проверяем, есть ли SHA в WAL
        if commit_sha == last_commit:  # noqa: SIM103
            return False
        # Иначе если коммит новее – обрабатываем
        return True

    def _update_wal_commit(self, project_id: int, last_commit_sha: str, last_commit_date: str):
        if str(project_id) not in self.wal_data["projects"]:
            self.wal_data["projects"][str(project_id)] = {}
        self.wal_data["projects"][str(project_id)]["last_commit_sha"] = last_commit_sha
        self.wal_data["projects"][str(project_id)]["last_commit_date"] = last_commit_date
        self.wal_data["last_run"] = datetime.now(UTC).isoformat()
        self._save_wal()

    def _save_project_data(
        self,
        project: dict,
        commits: list[dict],
        branches: list[dict],
        merge_requests: list[dict],
        files_data: list[dict],
    ):
        """Сохраняет все данные проекта в JSON структуру."""
        project_id = str(project["id"])
        proj_dir = self.output_dir / project_id
        proj_dir.mkdir(parents=True, exist_ok=True)

        # Метаданные проекта
        with open(proj_dir / "project.json", "w", encoding="utf-8") as f:
            json.dump(project, f, ensure_ascii=False, indent=2)

        # Коммиты
        if commits:
            with open(proj_dir / "commits.json", "w", encoding="utf-8") as f:
                json.dump(commits, f, ensure_ascii=False, indent=2)

        # Ветки
        if branches:
            with open(proj_dir / "branches.json", "w", encoding="utf-8") as f:
                json.dump(branches, f, ensure_ascii=False, indent=2)

        # Merge Requests
        if merge_requests:
            with open(proj_dir / "merge_requests.json", "w", encoding="utf-8") as f:
                json.dump(merge_requests, f, ensure_ascii=False, indent=2)

        # Файлы (код)
        if files_data:
            files_dir = proj_dir / "files"
            files_dir.mkdir(exist_ok=True)
            for file_info in files_data:
                file_path = file_info["path"]
                safe_name = file_path.replace("/", "_").replace("\\", "_")
                with open(files_dir / f"{safe_name}.txt", "w", encoding="utf-8") as f:
                    f.write(file_info["content"])
            # также сохраняем список файлов как JSON
            with open(proj_dir / "files_manifest.json", "w", encoding="utf-8") as f:
                json.dump(files_data, f, ensure_ascii=False, indent=2)

    def run(self):
        """Основной процесс выгрузки по всем проектам."""
        projects = self.get_projects()
        logger.info(f"Found {len(projects)} projects")
        for project in projects:
            project_id = project["id"]
            logger.info(f"Processing project {project['path_with_namespace']} (id={project_id})")

            commits = []
            if self.fetch_commits:
                commits = self.get_commits(project_id, since=self.since_date)
                logger.info(f"  Retrieved {len(commits)} commits")
                if commits:
                    last_commit = commits[0]  # самый новый (первый в списке)
                    self._update_wal_commit(project_id, last_commit["id"], last_commit["created_at"])

            branches = []
            if self.fetch_commits:  # ветки не требуют отдельного флага, но идём вместе
                branches = self.get_branches(project_id)
                logger.info(f"  Retrieved {len(branches)} branches")

            merge_requests = []
            if self.fetch_merge_requests:
                merge_requests = self.get_merge_requests(project_id)
                logger.info(f"  Retrieved {len(merge_requests)} merge requests")

            files_data = []
            if self.fetch_files:
                # Для каждого коммита (или последнего) получаем изменённые файлы, но лучше взять из последнего коммита на main  # noqa: E501
                # Или сканируем репозиторий через API дерева (неэффективно). Для простоты:
                # Берём корневую структуру и выбираем файлы по фильтру.
                try:
                    # Получаем дерево корня репозитория
                    tree = self._request(f"/api/v4/projects/{project_id}/repository/tree", params={"recursive": "true"})
                    for item in tree:
                        if item["type"] == "blob":
                            # Проверяем, соответствует ли путь фильтру (упрощённо по расширению)
                            path = item["path"]
                            if self._matches_filter(path):
                                content = self.get_file_content(project_id, path, ref="main")
                                if content:
                                    files_data.append({"path": path, "content": content, "sha": item["id"]})
                    logger.info(f"  Retrieved {len(files_data)} files from repository")
                except Exception as e:
                    logger.error(f"  Failed to fetch repository tree for project {project_id}: {e}")

            self._save_project_data(project, commits, branches, merge_requests, files_data)
            logger.info(f"Finished project {project_id}")

        logger.info("GitLab extraction finished.")

    def _matches_filter(self, path: str) -> bool:
        """Проверяет, подходит ли путь файла под фильтр (простое окончание или точное совпадение)."""
        if not self.file_paths_filter:
            return True
        for pattern in self.file_paths_filter:
            if pattern.startswith("*.") and path.endswith(pattern[1:]):
                return True
            if pattern in path:
                return True
        return False


if __name__ == "__main__":
    # Пример конфигурации (загружать из etl_config.yaml или переменных окружения)
    config_example = {
        "url": os.getenv("GITLAB_URL", "https://gitlab.example.com"),
        "token": os.getenv("GITLAB_TOKEN", "your_token"),
        "project_ids": None,  # или [1,2]
        "output_dir": "./raw_data/gitlab",
        "wal_file": "./wal/gitlab_wal.json",
        "incremental": True,
        "fetch_commits": True,
        "fetch_files": True,
        "fetch_merge_requests": True,
        "max_commits_per_project": 500,
        "since_date": "2025-01-01T00:00:00Z",
        "file_paths_filter": ["*.py", "*.md", "Dockerfile", "*.yaml", "*.yml"],
    }
    extractor = GitLabExtractor(config_example)
    extractor.run()

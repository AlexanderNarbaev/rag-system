# proxy/app/live_sources.py
"""
Live API clients for Confluence, Jira, and GitLab.
Provides real-time queries to corporate data sources with caching and graceful degradation.

Each client:
- Authenticates via API token or basic auth (configurable)
- Caches results in-memory with TTL (60s default)
- Gracefully degrades on API failure (logs warning, returns empty)
- Never crashes the proxy if the external API is unreachable
"""

import base64
import logging
from dataclasses import dataclass, field
from time import time
from typing import Any

import aiohttp
from aiohttp import ClientTimeout

from app.config import (
    CONFLUENCE_API_TOKEN,
    CONFLUENCE_API_URL,
    CONFLUENCE_API_USER,
    GITLAB_API_TOKEN,
    GITLAB_API_URL,
    JIRA_API_TOKEN,
    JIRA_API_URL,
    JIRA_API_USER,
    LIVE_SOURCES_ENABLED,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

CACHE_TTL = 60
LIVE_REQUEST_TIMEOUT = 15


# ── Data Models ──


@dataclass
class ConfluencePage:
    """Confluence page result."""
    id: str
    title: str
    space_key: str
    page_type: str = "page"
    body: str = ""
    url: str = ""


@dataclass
class JiraIssue:
    """Jira issue result."""
    id: str
    key: str
    summary: str
    description: str = ""
    status: str = ""
    priority: str = ""
    assignee: str = ""
    issue_type: str = ""


@dataclass
class GitLabProject:
    """GitLab project result."""
    id: str
    name: str
    path_with_namespace: str = ""
    description: str = ""


@dataclass
class GitLabFile:
    """GitLab file content result."""
    file_name: str
    file_path: str
    content: str
    ref: str = "main"
    size: int = 0


# ── Base Cache Mixin ──


class _CacheMixin:
    """In-memory TTL cache for live source responses."""

    def __init__(self):
        self._cache: dict[str, tuple[Any, float]] = {}

    def _get_from_cache(self, key: str) -> Any | None:
        """Retrieve from cache if not expired."""
        if key in self._cache:
            value, expire_at = self._cache[key]
            if time() < expire_at:
                return value
            del self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any, ttl: int = CACHE_TTL) -> None:
        """Store value in cache with TTL."""
        self._cache[key] = (value, time() + ttl)


# ── F2: ConfluenceLiveClient ──


class ConfluenceLiveClient(_CacheMixin):
    """REST API client for Confluence with caching and graceful degradation."""

    def __init__(self):
        super().__init__()
        self.base_url = CONFLUENCE_API_URL.rstrip("/") if CONFLUENCE_API_URL else ""
        self.headers: dict[str, str] = {}
        if CONFLUENCE_API_USER and CONFLUENCE_API_TOKEN:
            self.headers["Authorization"] = aiohttp.encode_basic_auth(
                CONFLUENCE_API_USER, CONFLUENCE_API_TOKEN
            )

    @property
    def _enabled(self) -> bool:
        return bool(LIVE_SOURCES_ENABLED and self.base_url)

    async def search_confluence(self, query: str, max_results: int = 5) -> list[ConfluencePage]:
        """Search Confluence pages by CQL query."""
        if not self._enabled:
            logger.debug("Confluence live source disabled or not configured")
            return []

        cache_key = f"conf_search:{query}:{max_results}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            cql = f'text ~ "{query}"'
            url = f"{self.base_url}/content/search"
            params = {"cql": cql, "limit": max_results, "expand": "space,body.view"}

            timeout = ClientTimeout(total=LIVE_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(f"Confluence search returned {resp.status}: {await resp.text()}")
                        return []
                    data = await resp.json()

            results = []
            for item in data.get("results", []):
                body = item.get("body", {}).get("view", {}).get("value", "")
                results.append(
                    ConfluencePage(
                        id=item.get("id", ""),
                        title=item.get("title", ""),
                        space_key=item.get("space", {}).get("key", ""),
                        page_type=item.get("type", "page"),
                        body=body,
                        url=f"{self.base_url}/content/{item.get('id', '')}",
                    )
                )
            self._set_cache(cache_key, results)
            return results
        except (TimeoutError, aiohttp.ClientError, OSError) as e:
            logger.warning(f"Confluence search failed (graceful degradation): {e}")
            return []

    async def get_confluence_page(self, page_id: str) -> ConfluencePage | None:
        """Get a single Confluence page by ID."""
        if not self._enabled:
            return None

        cache_key = f"conf_page:{page_id}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            url = f"{self.base_url}/content/{page_id}"
            params = {"expand": "space,body.view"}

            timeout = ClientTimeout(total=LIVE_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(f"Confluence page {page_id} not found: {resp.status}")
                        return None
                    data = await resp.json()

            body = data.get("body", {}).get("view", {}).get("value", "")
            page = ConfluencePage(
                id=data.get("id", ""),
                title=data.get("title", ""),
                space_key=data.get("space", {}).get("key", ""),
                page_type=data.get("type", "page"),
                body=body,
                url=f"{self.base_url}/content/{page_id}",
            )
            self._set_cache(cache_key, page)
            return page
        except (TimeoutError, aiohttp.ClientError, OSError) as e:
            logger.warning(f"Confluence get page failed (graceful): {e}")
            return None


# ── F3: JiraLiveClient ──


class JiraLiveClient(_CacheMixin):
    """REST API client for Jira with caching and graceful degradation."""

    def __init__(self):
        super().__init__()
        self.base_url = JIRA_API_URL.rstrip("/") if JIRA_API_URL else ""
        self.headers: dict[str, str] = {}
        if JIRA_API_USER and JIRA_API_TOKEN:
            auth_str = aiohttp.encode_basic_auth(JIRA_API_USER, JIRA_API_TOKEN)
            self.headers["Authorization"] = auth_str

    @property
    def _enabled(self) -> bool:
        return bool(LIVE_SOURCES_ENABLED and self.base_url)

    async def search_jira(self, query: str, max_results: int = 5) -> list[JiraIssue]:
        """Search Jira issues by JQL query."""
        if not self._enabled:
            logger.debug("Jira live source disabled or not configured")
            return []

        cache_key = f"jira_search:{query}:{max_results}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            jql = f'text ~ "{query}"'
            url = f"{self.base_url}/search"
            params = {"jql": jql, "maxResults": max_results, "fields": "summary,description,status,priority,assignee,issuetype"}

            timeout = ClientTimeout(total=LIVE_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(f"Jira search returned {resp.status}: {await resp.text()}")
                        return []
                    data = await resp.json()

            results = []
            for item in data.get("issues", []):
                fields = item.get("fields", {})
                results.append(
                    JiraIssue(
                        id=item.get("id", ""),
                        key=item.get("key", ""),
                        summary=fields.get("summary", ""),
                        description=fields.get("description", "") or "",
                        status=fields.get("status", {}).get("name", ""),
                        priority=fields.get("priority", {}).get("name", ""),
                        assignee=fields.get("assignee", {}).get("displayName", ""),
                        issue_type=fields.get("issuetype", {}).get("name", ""),
                    )
                )
            self._set_cache(cache_key, results)
            return results
        except (TimeoutError, aiohttp.ClientError, OSError) as e:
            logger.warning(f"Jira search failed (graceful degradation): {e}")
            return []

    async def get_jira_issue(self, issue_key: str) -> JiraIssue | None:
        """Get a single Jira issue by key."""
        if not self._enabled:
            return None

        cache_key = f"jira_issue:{issue_key}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            url = f"{self.base_url}/issue/{issue_key}"
            params = {"fields": "summary,description,status,priority,assignee,issuetype"}

            timeout = ClientTimeout(total=LIVE_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(f"Jira issue {issue_key} not found: {resp.status}")
                        return None
                    data = await resp.json()

            fields = data.get("fields", {})
            issue = JiraIssue(
                id=data.get("id", ""),
                key=data.get("key", ""),
                summary=fields.get("summary", ""),
                description=fields.get("description", "") or "",
                status=fields.get("status", {}).get("name", ""),
                priority=fields.get("priority", {}).get("name", ""),
                assignee=fields.get("assignee", {}).get("displayName", ""),
                issue_type=fields.get("issuetype", {}).get("name", ""),
            )
            self._set_cache(cache_key, issue)
            return issue
        except (TimeoutError, aiohttp.ClientError, OSError) as e:
            logger.warning(f"Jira get issue failed (graceful): {e}")
            return None


# ── F4: GitLabLiveClient ──


class GitLabLiveClient(_CacheMixin):
    """REST API client for GitLab with caching and graceful degradation."""

    def __init__(self):
        super().__init__()
        self.base_url = GITLAB_API_URL.rstrip("/") if GITLAB_API_URL else ""
        self.headers: dict[str, str] = {}
        if GITLAB_API_TOKEN:
            self.headers["PRIVATE-TOKEN"] = GITLAB_API_TOKEN

    @property
    def _enabled(self) -> bool:
        return bool(LIVE_SOURCES_ENABLED and self.base_url)

    async def search_gitlab(self, query: str, max_results: int = 5) -> list[GitLabProject]:
        """Search GitLab projects by name."""
        if not self._enabled:
            logger.debug("GitLab live source disabled or not configured")
            return []

        cache_key = f"gl_search:{query}:{max_results}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            url = f"{self.base_url}/projects"
            params = {"search": query, "per_page": max_results, "order_by": "name"}

            timeout = ClientTimeout(total=LIVE_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(f"GitLab search returned {resp.status}: {await resp.text()}")
                        return []
                    data = await resp.json()

            results = [
                GitLabProject(
                    id=str(item.get("id", "")),
                    name=item.get("name", ""),
                    path_with_namespace=item.get("path_with_namespace", ""),
                    description=item.get("description", "") or "",
                )
                for item in data
            ]
            self._set_cache(cache_key, results)
            return results
        except (TimeoutError, aiohttp.ClientError, OSError) as e:
            logger.warning(f"GitLab search failed (graceful degradation): {e}")
            return []

    async def get_gitlab_file(self, project_id: str, file_path: str, ref: str = "main") -> GitLabFile | None:
        """Get a file from a GitLab repository."""
        if not self._enabled:
            return None

        cache_key = f"gl_file:{project_id}:{file_path}:{ref}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        try:
            encoded_path = file_path.replace("/", "%2F")
            url = f"{self.base_url}/projects/{project_id}/repository/files/{encoded_path}"
            params = {"ref": ref}

            timeout = ClientTimeout(total=LIVE_REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(headers=self.headers, timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        logger.warning(f"GitLab file {file_path} not found in project {project_id}: {resp.status}")
                        return None
                    data = await resp.json()

            content = data.get("content", "")
            encoding = data.get("encoding", "text")
            if encoding == "base64":
                try:
                    content = base64.b64decode(content).decode("utf-8", errors="replace")
                except Exception as e:
                    logger.warning(f"Failed to decode GitLab file content: {e}")

            file_obj = GitLabFile(
                file_name=data.get("file_name", ""),
                file_path=file_path,
                content=content,
                ref=data.get("ref", ref),
                size=data.get("size", 0),
            )
            self._set_cache(cache_key, file_obj)
            return file_obj
        except (TimeoutError, aiohttp.ClientError, OSError) as e:
            logger.warning(f"GitLab get file failed (graceful): {e}")
            return None

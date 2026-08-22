# etl/extractors/confluence.py
"""Data extraction from Confluence (Self-Hosted) with support for:
- Pages (body: storage, view, export)
- Versions (full change history)
- Attachments (metadata + binary files)
- Comments (stream)
- Macros (rendered and raw parameters)
- Links (internal to other pages, external URLs)
- Incremental mode (only changed pages)
- WAL (checkpoints for resuming)
"""

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth

from etl.extractors.acl_extractor import extract_confluence_acl
from etl.extractors.base_extractor import SyncExtractor

# Suppress SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ConfluenceExtractor(SyncExtractor):
    def __init__(self, config: dict[str, Any]):
        """config: {
            "url": "https://confluence.internal/",
            "username": "bot",                  # optional for Basic Auth
            "token": "personal_access_token",   # Bearer token or password
            "verify_ssl": true,                 # false for self-signed certificates
            "ca_bundle": "",                    # path to the corporate CA bundle
            "space_keys": ["DEV", "OPS"],       # None for all spaces
            "output_dir": "./raw_data/confluence",
            "wal_file": "./wal/confluence_wal.json",
            "incremental": True,
            "download_attachments": True,
            "max_versions": 0,                  # 0 = all versions
            "api_version": "2",                 # '2' for the new REST API, '1' for the old one
            "since_date": null                  # ISO 8601 — extract only pages changed after this date
        }
        """
        self._init_sync_extractor(config)
        # Input validation
        url = config.get("url", "")
        if not url or not url.strip():
            raise ValueError("ConfluenceExtractor: 'url' is required and must not be empty")
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"ConfluenceExtractor: 'url' must start with http:// or https://, got: {url}")
        token = config.get("api_key") or config.get("token", "")
        if not token or not token.strip():
            raise ValueError("ConfluenceExtractor: 'token' or 'api_key' is required and must not be empty")

        self.url = url.rstrip("/")
        self.config = config  # Store full config for retry logic
        self.space_keys = config.get("space_keys")
        self.output_dir = Path(config.get("output_dir", "./raw_data/confluence"))
        self.incremental = config.get("incremental", True)
        self.download_attachments = config.get("download_attachments", True)
        self.max_versions = config.get("max_versions", 0)
        self.api_version = config.get("api_version", "2")
        self.since_date = config.get("since_date")

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

        # Auth: Bearer token (if no username) or Basic Auth
        token = config.get("token", "")
        username = config.get("username", "")
        if username:
            self.session.auth = HTTPBasicAuth(username, token)
        else:
            self.session.headers["Authorization"] = f"Bearer {token}"

        self.session.headers.update({"Accept": "application/json"})

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def test_connection(self) -> bool:
        """Tests the connection to the Confluence API."""
        logger.info(f"Testing connection to {self.url}...")
        logger.info(f"SSL verify: {self.session.verify}")
        logger.info(f"Auth: {'Bearer token' if 'Authorization' in self.session.headers else 'Basic auth'}")
        try:
            resp = self.session.get(
                urljoin(self.url, "/rest/api/content"),
                params={"limit": 1},
                timeout=(10, 30),
            )
            logger.info(f"Connection test: {resp.status_code}")
            if resp.status_code == 200:
                logger.info("✅ Connection successful")
                return True
            logger.error(f"❌ Error: {resp.status_code} - {resp.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            return False

    def _load_wal(self, config: dict[str, Any]) -> dict[str, Any]:
        """Loads the WAL (last successful timestamps and page hashes)."""
        default = {"last_run": None, "pages_hash": {}}
        if self.wal_path.exists():
            try:
                with open(self.wal_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"WAL file {self.wal_path} corrupted or unreadable: {e}. Reinitializing.")
                return default
        return default

    def _request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Performs a GET request to the Confluence API with retry logic and exponential backoff."""
        url = urljoin(self.url, endpoint)
        max_retries = self.config.get("max_retries", 5)
        base_delay = self.config.get("retry_delay", 2)

        for attempt in range(max_retries + 1):
            self._check_shutdown()
            try:
                logger.debug(f"Requesting: {url} (attempt {attempt + 1})")
                resp = self.session.get(url, params=params, timeout=self.timeout)
                logger.debug(f"Response: {resp.status_code}")
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.SSLError as e:
                logger.error(f"SSL Error: {e}")
                logger.error("Try setting verify_ssl: false in the config")
                raise
            except requests.exceptions.ConnectionError as e:
                logger.error(f"Connection Error: {e}")
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(f"Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    self._interruptible_sleep(delay)
                else:
                    logger.error(f"Failed to connect to {self.url} after {max_retries} attempts")
                    raise
            except requests.exceptions.Timeout as e:
                logger.warning(f"Timeout: {e}")
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(f"Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    self._interruptible_sleep(delay)
                else:
                    logger.error(f"Server not responding after {max_retries} attempts. Increase timeout in config")
                    raise

    def _get_all_pages(
        self, space_key: str | None = None, since: str | None = None, start: int = 0, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Fetches all pages with pagination (metadata only, no body).
        The body is loaded separately when processing each page.

        If since (ISO 8601 timestamp) is set, a CQL search via
        /rest/api/search is used to filter only changed pages.
        """
        if since:
            return self._get_pages_since(since, space_key, start, limit)

        pages = []
        while True:
            params = {
                "limit": limit,
                "start": start,
                "expand": "version,space",  # Without body — faster and does not hang
            }
            if space_key:
                params["spaceKey"] = space_key
            data = self._request("/rest/api/content", params)
            results = data.get("results", [])
            pages.extend(results)
            logger.info(f"  Fetched {len(results)} pages (total: {len(pages)})")

            # Check whether there is a next page
            if len(results) < limit:
                break
            start += limit

        return pages

    def _get_pages_since(
        self, since: str, space_key: str | None = None, start: int = 0, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Fetches pages changed since the given date using a CQL search."""
        cql_parts = [f'lastModified > "{since}"', 'type = "page"']
        if space_key:
            cql_parts.append(f'space = "{space_key}"')
        cql = " AND ".join(cql_parts)
        logger.info(f"  Searching with CQL: {cql}")

        pages = []
        while True:
            params = {
                "cql": cql,
                "start": start,
                "limit": limit,
                "expand": "content.version,content.space",
            }
            data = self._request("/rest/api/search", params)
            results = data.get("results", [])
            for result in results:
                content = result.get("content", {})
                if content.get("type") == "page":
                    pages.append(content)
            logger.info(f"  Fetched {len(results)} pages since {since} (total: {len(pages)})")

            if start + limit >= data.get("totalSize", 0):
                break
            start += limit

        return pages

    def _get_page_versions(self, page_id: str) -> list[dict[str, Any]]:
        """Returns the page version history."""
        endpoint = f"/rest/experimental/content/{page_id}/version"
        data = self._request(endpoint)
        versions = data.get("results", [])
        if self.max_versions > 0 and len(versions) > self.max_versions:
            versions = versions[-self.max_versions :]
        return versions

    def _get_comments(self, page_id: str) -> list[dict[str, Any]]:
        """Returns the page comments."""
        endpoint = f"/rest/api/content/{page_id}/child/comment"
        data = self._request(endpoint, params={"expand": "body.storage,version"})
        return data.get("results", [])

    def _get_attachments_metadata(self, page_id: str) -> list[dict[str, Any]]:
        """Returns attachment metadata (without content)."""
        endpoint = f"/rest/api/content/{page_id}/child/attachment"
        data = self._request(endpoint, params={"expand": "version"})
        return data.get("results", [])

    def _download_attachment(
        self,
        page_id: str,
        attachment_id: str,
        filename: str,
        output_dir: Path,
        att_download_link: str,
    ) -> str | None:
        """Downloads an attachment file and returns the path to the saved file."""
        url = urljoin(self.url, att_download_link)
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                resp = self.session.get(url, stream=True, timeout=60)
                resp.raise_for_status()
                safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_").strip()
                if not safe_name:
                    safe_name = f"attachment_{attachment_id}.bin"
                file_path = output_dir / safe_name
                with open(file_path, "wb") as f:
                    f.writelines(resp.iter_content(chunk_size=8192))
                return str(file_path)
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Attachment download connection error (attempt {attempt + 1}/{max_retries + 1}): {e}")
                if attempt < max_retries:
                    delay = 2**attempt  # 1s, 2s, 4s
                    logger.info(f"Retrying attachment download in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to download attachment {attachment_id} after {max_retries + 1} attempts: {e}")
                    return None
            except requests.exceptions.Timeout as e:
                logger.warning(f"Attachment download timeout (attempt {attempt + 1}/{max_retries + 1}): {e}")
                if attempt < max_retries:
                    delay = 2**attempt  # 1s, 2s, 4s
                    logger.info(f"Retrying attachment download in {delay}s...")
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to download attachment {attachment_id} after {max_retries + 1} attempts: {e}")
                    return None
            except Exception as e:
                logger.error(f"Failed to download attachment {attachment_id}: {e}")
                return None

    def _extract_links_from_html(self, html: str) -> dict[str, list[str]]:
        """Extracts internal (Confluence) and external links from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        internal = []
        external = []
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            if href.startswith("/") or self.url in href:
                internal.append(href)
            else:
                external.append(href)
        return {"internal_links": list(set(internal)), "external_links": list(set(external))}

    def _calculate_page_hash(self, page: dict) -> str:
        """Computes a hash of the page content for change detection."""
        # Take body.storage.value + version + modification date
        body = page.get("body", {}).get("storage", {}).get("value", "")
        version = page.get("version", {}).get("number", 0)
        modified = page.get("version", {}).get("when", "")
        content = f"{body}|{version}|{modified}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _should_process_page(self, page_id: str, new_hash: str) -> bool:
        # """Determines whether the page needs to be reprocessed (incremental mode)."""
        # 1. If incremental mode is disabled, always process
        if not self.incremental:
            return True

        # 2. Safely read pages_hash. If wal_data is missing or has no such key,
        # .get() returns None and we return True (needs processing)
        pages_hash = self.wal_data.get("pages_hash") if hasattr(self, "wal_data") else None
        if pages_hash is None:
            return True

        # 3. Get the old hash. If missing, old_hash is None
        old_hash = pages_hash.get(page_id)

        # 4. If hashes differ (or there is no old hash), return True
        return old_hash != new_hash

    def _save_page_data(self, page_data: dict, page_id: str):
        """Saves the structured page data to JSON."""
        page_dir = self.output_dir / page_id
        page_dir.mkdir(parents=True, exist_ok=True)
        # Main file with metadata and content
        with open(page_dir / "page.json", "w", encoding="utf-8") as f:
            json.dump(page_data, f, ensure_ascii=False, indent=2)
        # Save raw body.storage separately (if needed for semantic chunking)
        if "body_storage_raw" in page_data:
            with open(page_dir / "content_storage.html", "w", encoding="utf-8") as f:
                f.write(page_data["body_storage_raw"])
        logger.info(f"Saved page {page_id} to {page_dir}")

    def extract_page(self, page: dict) -> dict[str, Any]:
        """Extracts full data for a single page:
        - Metadata (id, title, space, versions, dates)
        - Body in storage, view, export formats (if available)
        - Comments
        - Attachments (metadata and files)
        - Links
        """
        page_id = str(page["id"])
        title = page["title"]
        space = page.get("space", {}).get("key", "UNKNOWN")

        # 1. Request full page data
        page_detail = self._request(
            f"/rest/api/content/{page_id}",
            params={"expand": "body.storage,body.view,metadata.labels,metadata.properties,version"},
        )
        body_storage = page_detail.get("body", {}).get("storage", {}).get("value", "")
        body_view = page_detail.get("body", {}).get("view", {}).get("value", "")
        page.update(page_detail)

        # 2. Noise cleanup and conversion to Markdown
        body_markdown = ""
        headings = []
        if body_view:
            soup = BeautifulSoup(body_view, "html.parser")
            # Keep only the main content, ignoring sidebars
            main_content = soup.find("div", class_="wiki-content") or soup.find("div", id="main-content") or soup

            # Extract headings for a future title_boost in search
            headings = [h.get_text(strip=True) for h in main_content.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])]

            # Convert to Markdown preserving the structure
            try:
                from markdownify import markdownify as md

                body_markdown = md(str(main_content), heading_style="ATX", bullets="-")
            except ImportError:
                logger.warning("markdownify not installed, falling back to plain text")
                body_markdown = main_content.get_text(separator="\n", strip=True)

        # 3. Macro processing in storage (replace XML with text markers)
        import re

        body_storage_clean = re.sub(
            r'<ac:structured-macro ac:name="([^"]+)".*?>(.*?)</ac:structured-macro>',
            r"[Macro \1]",
            body_storage,
            flags=re.DOTALL,
        )

        # Extract links, versions, comments, and attachments from the HTML body
        links = self._extract_links_from_html(body_view or body_storage)

        # Versions (history)
        versions = self._get_page_versions(page_id)
        version_list = []
        for v in versions:
            version_list.append(
                {
                    "number": v.get("number"),
                    "when": v.get("when"),
                    "message": v.get("message", ""),
                    "author": v.get("by", {}).get("displayName", ""),
                },
            )

        # Comments
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
                },
            )

        # Attachments
        attachments_meta = self._get_attachments_metadata(page_id)
        attachment_data = []
        att_dir = self.output_dir / page_id / "attachments"
        if self.download_attachments:
            att_dir.mkdir(parents=True, exist_ok=True)
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
            att_download_link = att.get("_links", {}).get("download", {})
            if self.download_attachments:
                local_path = self._download_attachment(page_id, att_id, att_filename, att_dir, att_download_link)
                att_info["local_path"] = local_path
            attachment_data.append(att_info)

        # Macros: can be extracted from the storage format (XML-like)
        # Example: <ac:structured-macro ac:name="code">...</ac:structured-macro>
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

        # Final object
        # RBAC metadata: author from current version, contributors from all versions
        author = page.get("version", {}).get("by", {}).get("displayName", "")
        contributors = list(
            {v.get("by", {}).get("displayName", "") for v in versions if v.get("by", {}).get("displayName")},
        )
        space_key = page.get("space", {}).get("key", "")

        # Labels and restrictions (may not be available in all Confluence versions)
        labels = page.get("metadata", {}).get("labels", [])
        restrictions = page.get("metadata", {}).get("restrictions", {})

        # ACL extraction from page restrictions and space metadata
        acl = extract_confluence_acl(page)

        # Content hash for incremental updates at the embedding stage
        content_hash = hashlib.sha256(body_markdown.encode("utf-8")).hexdigest()

        page_data = {
            "id": page_id,
            "title": title,
            "space": space,
            "space_key": space_key,
            "version": page.get("version", {}).get("number", 1),
            "author": author,
            "contributors": contributors,
            "labels": labels,
            "restrictions": restrictions,
            "created_at": page.get("version", {}).get("when", ""),
            "updated_at": page.get("version", {}).get("when", ""),
            "body_storage_raw": body_storage_clean,
            "body_view_html": body_view,
            "body_markdown": body_markdown,
            "headings": headings,
            "content_hash": content_hash,
            "links": links,
            "versions": version_list,
            "comments": comment_data,
            "attachments": attachment_data,
            "macros": macros,
            "extracted_at": datetime.now(UTC).isoformat(),
            "acl": {
                "access_level": acl.access_level,
                "allowed_groups": acl.allowed_groups,
                "allowed_users": acl.allowed_users,
                "source_permissions": acl.source_permissions,
            },
        }
        return page_data

    def run(self) -> None:
        """Main extraction loop over all pages (for the given spaces or all)."""
        spaces_to_process = self.space_keys or [None]  # None = all spaces
        for space in spaces_to_process:
            self._check_shutdown()
            logger.info(f"Processing space: {space or 'ALL'}")
            pages = self._get_all_pages(space_key=space, since=self.since_date)
            logger.info(f"Found {len(pages)} pages in space {space}")
            for page in pages:
                self._check_shutdown()
                page_id = str(page["id"])
                new_hash = self._calculate_page_hash(page)
                if not self._should_process_page(page_id, new_hash):
                    logger.debug(f"Skipping page {page_id} (no changes)")
                    continue
                try:
                    full_data = self.extract_page(page)
                    self._save_page_data(full_data, page_id)
                    # Update the WAL
                    self.wal_data.setdefault("pages_hash", {})[page_id] = new_hash
                    self.wal_data["last_run"] = datetime.now(UTC).isoformat()
                    self._save_wal()
                except InterruptedError:
                    logger.warning("Confluence extraction interrupted by shutdown")
                    return
                except Exception as e:
                    logger.error(
                        f"Failed to process page {page_id}: {e}",
                        exc_info=True,
                    )  # Continue without aborting the whole process
        logger.info("Extraction finished.")


if __name__ == "__main__":
    # Configuration example (load from etl_config.yaml or environment variables)
    config_example = {
        "url": os.getenv("CONFLUENCE_URL", "https://confluence.example.com"),
        "username": os.getenv("CONFLUENCE_USER", "bot"),
        "token": os.getenv("CONFLUENCE_TOKEN", "your_token"),
        "space_keys": ["DEV", "OPS"],  # or None for all
        "output_dir": "./raw_data/confluence",
        "wal_file": "./wal/confluence_wal.json",
        "incremental": True,
        "download_attachments": True,
        "max_versions": 0,
        "api_version": "2",
    }
    extractor = ConfluenceExtractor(config_example)
    extractor.run()

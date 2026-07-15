#!/usr/bin/env python3
"""
ETL Pipeline — Parallel extraction with streaming indexing.

Extracts from Confluence, Jira, GitLab in parallel with concurrency limits.
Streams chunks directly to Qdrant instead of saving locally first.
Resumes from WAL checkpoints on restart.

Supports graceful shutdown via SIGINT/SIGTERM — saves WAL checkpoint
before exiting so the pipeline can resume from where it left off.
"""

import asyncio
import logging
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

# Add project root to path
sys.path.insert (0, str (Path (__file__).parent.parent.parent))

from etl.chunker.semantic_chunker import SemanticChunker
from etl.extractors.confluence import ConfluenceExtractor
from etl.extractors.gitlab import GitLabExtractor
from etl.extractors.jira import JiraExtractor
from etl.indexer.qdrant_hybrid import QdrantHybridIndexer
from etl.indexer.wal_manager import WALManager

logging.basicConfig (level = logging.INFO, format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s", )
logger = logging.getLogger ("etl-pipeline")


class StreamingETLPipeline:
  """
  Parallel ETL pipeline with streaming indexing.

  - Extracts from multiple sources concurrently
  - Chunks and indexes directly to Qdrant (no local storage)
  - Resumes from WAL checkpoints
  """

  def __init__ (self, config: dict [str, Any]):
    self.config = config
    self.global_cfg = config.get ("global", {})
    self.timeout = self.global_cfg.get ("timeout", 120)
    self.connect_timeout = self.global_cfg.get ("connect_timeout", 30)
    self.max_retries = self.global_cfg.get ("max_retries", 5)
    self.retry_delay = self.global_cfg.get ("retry_delay", 5)

    # Concurrency limits
    self.max_concurrent_sources = self.global_cfg.get ("max_concurrent_sources", 3)
    self.max_concurrent_pages = self.global_cfg.get ("max_concurrent_pages", 5)

    # WAL
    wal_cfg = config.get ("wal", {})
    self.wal = WALManager (Path (wal_cfg.get ("wal_file", "./wal/etl_wal.json")),
        use_lock = wal_cfg.get ("use_lock", True), )

    # Chunker
    chunk_cfg = config.get ("chunking", {})
    self.chunker = SemanticChunker (max_tokens = chunk_cfg.get ("max_tokens", 1500),
        overlap_tokens = chunk_cfg.get ("overlap_tokens", 200),
        min_chunk_tokens = chunk_cfg.get ("min_chunk_tokens", 100), )

    # Indexer (Qdrant)
    index_cfg = config.get ("indexing", {})
    qdrant_url = index_cfg.get ("qdrant_url", "http://localhost:6333")
    parsed = urlparse (qdrant_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6333
    self.indexer = QdrantHybridIndexer (host = host, port = port,
        collection_name = index_cfg.get ("collection_name", "knowledge_base"), )

    # Stats
    self.stats = {
        "confluence": {"pages": 0, "chunks": 0, "errors": 0}, "jira": {"issues": 0, "chunks": 0, "errors": 0},
        "gitlab": {"projects": 0, "chunks": 0, "errors": 0},
    }

    # Graceful shutdown
    self._shutdown = False
    self._setup_signal_handlers ()

  def _setup_signal_handlers (self):
    """Setup signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop ()
    for sig in (signal.SIGINT, signal.SIGTERM):
      loop.add_signal_handler (sig, self._handle_shutdown, sig)

  def _handle_shutdown (self, sig):
    """Handle shutdown signal — save WAL and exit gracefully."""
    if self._shutdown:
      logger.warning ("Forced shutdown requested — exiting immediately")
      sys.exit (1)
    self._shutdown = True
    logger.warning (f"Received {sig.name} — saving WAL checkpoint and shutting down gracefully...")
    self._save_shutdown_checkpoint ()

  def _save_shutdown_checkpoint (self):
    """Save current progress to WAL before shutdown."""
    try:
      self.wal.set_checkpoint ("pipeline", {
          "last_run": datetime.now (UTC).isoformat (), "shutdown": True, "stats": self.stats,
          "total_chunks": sum (s ["chunks"] for s in self.stats.values ()),
          "total_errors": sum (s ["errors"] for s in self.stats.values ()),
      }, )
      logger.info ("WAL checkpoint saved — pipeline can resume from this point")
    except Exception as e:
      logger.error (f"Failed to save WAL checkpoint: {e}")

  def _create_extractors (self) -> dict [str, Any]:
    """Create extractors for configured sources."""
    extractors = {}

    for source in ["confluence", "jira", "gitlab"]:
      if source in self.config:
        cfg = dict (self.config [source])
        cfg.setdefault ("timeout", self.timeout)
        cfg.setdefault ("connect_timeout", self.connect_timeout)
        cfg.setdefault ("max_retries", self.max_retries)
        cfg.setdefault ("retry_delay", self.retry_delay)

        if source == "confluence" and cfg.get ("url"):
          cfg ["wal_file"] = str (self.wal.wal_path)
          extractors ["confluence"] = ConfluenceExtractor (cfg)
        elif source == "jira" and cfg.get ("url"):
          cfg ["wal_file"] = str (self.wal.wal_path)
          extractors ["jira"] = JiraExtractor (cfg)
        elif source == "gitlab" and cfg.get ("url"):
          cfg ["wal_file"] = str (self.wal.wal_path)
          extractors ["gitlab"] = GitLabExtractor (cfg)

    return extractors

  def _chunk_and_index (self, text: str, metadata: dict [str, Any], source: str) -> int:
    """Chunk text and stream directly to Qdrant. Returns number of chunks indexed."""
    if not text or not text.strip ():
      return 0

    try:
      # Use chunk_markdown for text content
      chunks = self.chunker.chunk_markdown (text, source_metadata = metadata)
      if not chunks:
        return 0

      # Convert Chunk objects to dicts for indexer
      chunk_dicts = []
      for chunk in chunks:
        chunk_dicts.append ({
            "text": chunk.text, "source_id": metadata.get ("source_id", ""), "source_type": metadata.get ("source", ""),
            "title": metadata.get ("title", ""), "hash": chunk.hash if hasattr (chunk, "hash") else "",
            "position": chunk.position if hasattr (chunk, "position") else 0, "metadata": metadata,
        })

      # Index directly to Qdrant
      self.indexer.index_chunks (chunk_dicts)
      return len (chunk_dicts)
    except Exception as e:
      logger.error (f"Error chunking/indexing from {source}: {e}")
      self.stats [source] ["errors"] += 1
      return 0

  def _process_confluence_page (self, extractor: ConfluenceExtractor, page: dict) -> int:
    """Process a single Confluence page: extract content, chunk, index."""
    page_id = str (page ["id"])
    title = page.get ("title", "Untitled")

    try:
      # Extract full page content
      full_data = extractor.extract_page (page)
      text = full_data.get ("body", "")
      if not text:
        return 0

      metadata = {
          "source": "confluence", "source_id": page_id, "title": title, "space": page.get ("space", {}).get ("key", ""),
          "url": f"{extractor.url}/wiki/spaces/{page.get ('space', {}).get ('key', '')}/pages/{page_id}",
          "version": page.get ("version", {}).get ("number", 1), "extracted_at": datetime.now (UTC).isoformat (),
      }

      chunks_count = self._chunk_and_index (text, metadata, "confluence")
      self.stats ["confluence"] ["pages"] += 1
      self.stats ["confluence"] ["chunks"] += chunks_count

      # Update WAL
      self.wal.set_checkpoint ("confluence", {
          "last_page_id": page_id, "last_title": title, "pages_processed": self.stats ["confluence"] ["pages"],
          "chunks_indexed": self.stats ["confluence"] ["chunks"],
      }, )

      return chunks_count

    except Exception as e:
      logger.error (f"Error processing Confluence page {page_id}: {e}")
      self.stats ["confluence"] ["errors"] += 1
      return 0

  def _process_jira_issue (self, extractor: JiraExtractor, issue: dict) -> int:
    """Process a single Jira issue: extract content, chunk, index."""
    issue_key = issue.get ("key", "UNKNOWN")
    summary = issue.get ("fields", {}).get ("summary", "")

    try:
      # Build text from issue
      description = issue.get ("fields", {}).get ("description", "") or ""
      comments = []
      for comment in issue.get ("fields", {}).get ("comment", {}).get ("comments", []):
        comments.append (comment.get ("body", ""))

      text = f"# {summary}\n\n{description}"
      if comments:
        text += "\n\n## Comments\n\n" + "\n\n".join (comments)

      metadata = {
          "source": "jira", "source_id": issue_key, "title": summary,
          "project": issue.get ("fields", {}).get ("project", {}).get ("key", ""),
          "issue_type": issue.get ("fields", {}).get ("issuetype", {}).get ("name", ""),
          "status": issue.get ("fields", {}).get ("status", {}).get ("name", ""),
          "url": f"{extractor.url}/browse/{issue_key}", "extracted_at": datetime.now (UTC).isoformat (),
      }

      chunks_count = self._chunk_and_index (text, metadata, "jira")
      self.stats ["jira"] ["issues"] += 1
      self.stats ["jira"] ["chunks"] += chunks_count

      # Update WAL
      self.wal.set_checkpoint ("jira", {
          "last_issue_key": issue_key, "issues_processed": self.stats ["jira"] ["issues"],
          "chunks_indexed": self.stats ["jira"] ["chunks"],
      }, )

      return chunks_count

    except Exception as e:
      logger.error (f"Error processing Jira issue {issue_key}: {e}")
      self.stats ["jira"] ["errors"] += 1
      return 0

  def _process_gitlab_project (self, extractor: GitLabExtractor, project: dict) -> int:
    """Process a single GitLab project: extract content, chunk, index."""
    project_id = project.get ("id")
    project_name = project.get ("name", "Unknown")

    try:
      chunks_count = 0

      # Process commits
      if extractor.fetch_commits:
        commits = extractor._request (f"/api/v4/projects/{project_id}/repository/commits", {"per_page": 100})
        for commit in commits [: extractor.max_commits_per_project]:
          text = f"Commit: {commit.get ('title', '')}\n\n{commit.get ('message', '')}"
          metadata = {
              "source": "gitlab_commit", "source_id": f"{project_id}_{commit.get ('id', '')}",
              "title": commit.get ("title", ""), "project": project_name, "url": commit.get ("web_url", ""),
              "extracted_at": datetime.now (UTC).isoformat (),
          }
          chunks_count += self._chunk_and_index (text, metadata, "gitlab")

      # Process merge requests
      if extractor.fetch_merge_requests:
        mrs = extractor._request (f"/api/v4/projects/{project_id}/merge_requests", {"state": "all", "per_page": 100}, )
        for mr in mrs:
          text = f"MR: {mr.get ('title', '')}\n\n{mr.get ('description', '')}"
          metadata = {
              "source": "gitlab_mr", "source_id": f"{project_id}_mr_{mr.get ('iid', '')}",
              "title": mr.get ("title", ""), "project": project_name, "url": mr.get ("web_url", ""),
              "state": mr.get ("state", ""), "extracted_at": datetime.now (UTC).isoformat (),
          }
          chunks_count += self._chunk_and_index (text, metadata, "gitlab")

      self.stats ["gitlab"] ["projects"] += 1
      self.stats ["gitlab"] ["chunks"] += chunks_count

      # Update WAL
      self.wal.set_checkpoint ("gitlab", {
          "last_project_id": project_id, "projects_processed": self.stats ["gitlab"] ["projects"],
          "chunks_indexed": self.stats ["gitlab"] ["chunks"],
      }, )

      return chunks_count

    except Exception as e:
      logger.error (f"Error processing GitLab project {project_id}: {e}")
      self.stats ["gitlab"] ["errors"] += 1
      return 0

  async def _run_confluence (self, extractor: ConfluenceExtractor):
    """Run Confluence extraction with parallel page processing."""
    logger.info ("=== Starting Confluence extraction ===")

    loop = asyncio.get_event_loop ()
    space_keys = extractor.space_keys or [None]

    for space in space_keys:
      if self._shutdown:
        logger.info ("Shutdown requested — stopping Confluence extraction")
        break

      logger.info (f"Processing space: {space if space else 'ALL'}")

      # Get page list (metadata only)
      pages = await loop.run_in_executor (None, extractor._get_all_pages, space)
      logger.info (f"Found {len (pages)} pages in space {space}")

      # Process pages with concurrency limit
      sem = asyncio.Semaphore (self.max_concurrent_pages)

      async def process_page (page, _sem = sem):
        async with _sem:
          await loop.run_in_executor (None, self._process_confluence_page, extractor, page)

      tasks = [process_page (page) for page in pages]
      await asyncio.gather (*tasks, return_exceptions = True)

    logger.info (f"Confluence done: {self.stats ['confluence'] ['pages']} pages, "
                 f"{self.stats ['confluence'] ['chunks']} chunks, "
                 f"{self.stats ['confluence'] ['errors']} errors")

  async def _run_jira (self, extractor: JiraExtractor):
    """Run Jira extraction with parallel issue processing."""
    logger.info ("=== Starting Jira extraction ===")

    loop = asyncio.get_event_loop ()

    # Get issues list using paginated fetch
    def fetch_all_issues ():
      issues = []
      for issue in extractor._paginated_issues (extractor.base_jql):
        issues.append (issue)
      return issues

    issues = await loop.run_in_executor (None, fetch_all_issues)
    logger.info (f"Found {len (issues)} issues")

    # Process issues with concurrency limit
    sem = asyncio.Semaphore (self.max_concurrent_pages)

    async def process_issue (issue):
      async with sem:
        await loop.run_in_executor (None, self._process_jira_issue, extractor, issue)

    tasks = [process_issue (issue) for issue in issues]
    await asyncio.gather (*tasks, return_exceptions = True)

    logger.info (f"Jira done: {self.stats ['jira'] ['issues']} issues, "
                 f"{self.stats ['jira'] ['chunks']} chunks, "
                 f"{self.stats ['jira'] ['errors']} errors")

  async def _run_gitlab (self, extractor: GitLabExtractor):
    """Run GitLab extraction with parallel project processing."""
    logger.info ("=== Starting GitLab extraction ===")

    loop = asyncio.get_event_loop ()

    # Get projects list
    projects = await loop.run_in_executor (None, extractor.get_projects)
    logger.info (f"Found {len (projects)} projects")

    # Process projects with concurrency limit
    sem = asyncio.Semaphore (self.max_concurrent_pages)

    async def process_project (project):
      async with sem:
        await loop.run_in_executor (None, self._process_gitlab_project, extractor, project)

    tasks = [process_project (proj) for proj in projects]
    await asyncio.gather (*tasks, return_exceptions = True)

    logger.info (f"GitLab done: {self.stats ['gitlab'] ['projects']} projects, "
                 f"{self.stats ['gitlab'] ['chunks']} chunks, "
                 f"{self.stats ['gitlab'] ['errors']} errors")

  async def run (self, sources: list [str] | None = None):
    """
    Run the ETL pipeline.

    Args:
        sources: List of sources to run. None = all configured sources.
    """
    start_time = time.time ()

    # Create extractors
    extractors = self._create_extractors ()

    if not extractors:
      logger.error ("No sources configured!")
      return

    # Filter sources if specified
    if sources:
      extractors = {k: v for k, v in extractors.items () if k in sources}

    logger.info (f"Starting ETL pipeline with sources: {list (extractors.keys ())}")
    logger.info (f"Concurrency: {self.max_concurrent_sources} sources, {self.max_concurrent_pages} pages/source")

    # Run all sources concurrently
    tasks = []
    if "confluence" in extractors:
      tasks.append (self._run_confluence (extractors ["confluence"]))
    if "jira" in extractors:
      tasks.append (self._run_jira (extractors ["jira"]))
    if "gitlab" in extractors:
      tasks.append (self._run_gitlab (extractors ["gitlab"]))

    await asyncio.gather (*tasks, return_exceptions = True)

    # Final stats
    elapsed = time.time () - start_time
    total_chunks = sum (s ["chunks"] for s in self.stats.values ())
    total_errors = sum (s ["errors"] for s in self.stats.values ())

    logger.info ("=" * 60)
    logger.info (f"ETL Pipeline completed in {elapsed:.1f}s")
    logger.info (f"  Total chunks indexed: {total_chunks}")
    logger.info (f"  Total errors: {total_errors}")
    logger.info (f"  Confluence: {self.stats ['confluence']}")
    logger.info (f"  Jira: {self.stats ['jira']}")
    logger.info (f"  GitLab: {self.stats ['gitlab']}")
    logger.info ("=" * 60)

    # Update WAL
    self.wal.set_checkpoint ("pipeline", {
        "last_run": datetime.now (UTC).isoformat (), "elapsed_seconds": elapsed, "total_chunks": total_chunks,
        "total_errors": total_errors, "stats": self.stats,
    }, )


def load_config (config_path: Path) -> dict [str, Any]:
  """Load YAML configuration."""
  with open (config_path, encoding = "utf-8") as f:
    return yaml.safe_load (f)


def main ():
  import argparse

  parser = argparse.ArgumentParser (description = "RAG ETL Pipeline — Parallel Streaming")
  parser.add_argument ("--config", type = Path, default = Path ("etl/config/etl_config.yaml"))
  parser.add_argument ("--sources", nargs = "+", choices = ["confluence", "jira", "gitlab"],
      help = "Sources to extract (default: all configured)", )
  parser.add_argument ("--timeout", type = int, help = "Override request timeout")
  parser.add_argument ("--concurrency", type = int, help = "Max concurrent pages per source")
  parser.add_argument ("--test-connection", action = "store_true", help = "Test connections and exit")
  parser.add_argument ("--reset-wal", action = "store_true", help = "Reset WAL checkpoints")
  args = parser.parse_args ()

  config = load_config (args.config)

  # Override from CLI
  if args.timeout:
    for source in ["confluence", "jira", "gitlab"]:
      if source in config:
        config [source] ["timeout"] = args.timeout
    config.setdefault ("global", {}) ["timeout"] = args.timeout

  if args.concurrency:
    config.setdefault ("global", {}) ["max_concurrent_pages"] = args.concurrency

  # Test connection mode
  if args.test_connection:
    logger.info ("=== Testing connections ===")
    pipeline = StreamingETLPipeline (config)
    extractors = pipeline._create_extractors ()

    for name, extractor in extractors.items ():
      try:
        if hasattr (extractor, "test_connection"):
          ok = extractor.test_connection ()
          logger.info (f"  {name}: {'✅ OK' if ok else '❌ FAILED'}")
        else:
          logger.info (f"  {name}: ⚠️ No test_connection method")
      except Exception as e:
        logger.error (f"  {name}: ❌ {e}")
    return

  # Reset WAL
  if args.reset_wal:
    pipeline = StreamingETLPipeline (config)
    pipeline.wal.reset_all ()
    logger.info ("WAL reset complete")
    return

  # Run pipeline
  pipeline = StreamingETLPipeline (config)
  asyncio.run (pipeline.run (sources = args.sources))


if __name__ == "__main__":
  main ()

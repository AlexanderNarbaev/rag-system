# etl/extractors/__init__.py
"""ETL extractors for various data sources."""

from etl.extractors.acl_extractor import DocumentACL, extract_confluence_acl, extract_gitlab_acl, extract_jira_acl
from etl.extractors.base_extractor import BaseExtractor, ExtractedDocument, ExtractorConfig, SyncExtractor

__all__ = [
    "BaseExtractor",
    "DocumentACL",
    "ExtractedDocument",
    "ExtractorConfig",
    "SyncExtractor",
    "extract_confluence_acl",
    "extract_gitlab_acl",
    "extract_jira_acl",
]

# etl/extractors/base.py
"""Alias for base_extractor — provides the documented import path."""

from etl.extractors.base_extractor import BaseExtractor, ExtractedDocument, ExtractorConfig

__all__ = ["BaseExtractor", "ExtractedDocument", "ExtractorConfig"]

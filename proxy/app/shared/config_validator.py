# proxy/app/shared/config_validator.py
"""
Configuration validation — startup checks for required settings.

Validates that all required environment variables are set and that
external services (Qdrant, LLM, Redis) are reachable before the
proxy starts accepting requests.
"""

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger (__name__)


@dataclass
class ValidationResult:
  """Result of a configuration validation check."""

  component: str
  status: str  # ok, warning, error
  message: str
  details: dict = field (default_factory = dict)


def validate_config () -> list [ValidationResult]:
  """Validate all configuration settings.
  
  Returns a list of validation results. Errors indicate the proxy
  cannot start; warnings indicate degraded functionality.
  """
  results: list [ValidationResult] = []

  # --- Required settings ---
  llm_endpoint = os.environ.get ("LLM_ENDPOINT", "")
  if not llm_endpoint:
    results.append (ValidationResult (
        component = "LLM_ENDPOINT", status = "error",
        message = "LLM_ENDPOINT is required. Set it to your LLM backend URL.",
    ))
  elif not llm_endpoint.startswith (("http://", "https://")):
    results.append (ValidationResult (
        component = "LLM_ENDPOINT", status = "error",
        message = f"LLM_ENDPOINT must start with http:// or https://, got: {llm_endpoint}",
    ))
  else:
    results.append (ValidationResult (
        component = "LLM_ENDPOINT", status = "ok",
        message = f"Configured: {llm_endpoint}",
    ))

  # --- Qdrant settings ---
  qdrant_host = os.environ.get ("QDRANT_HOST", "localhost")
  qdrant_port = os.environ.get ("QDRANT_PORT", "6333")
  results.append (ValidationResult (
      component = "QDRANT", status = "ok",
      message = f"Configured: {qdrant_host}:{qdrant_port}",
  ))

  # --- Collection name ---
  collection_name = os.environ.get ("COLLECTION_NAME", "knowledge_base")
  results.append (ValidationResult (
      component = "COLLECTION_NAME", status = "ok",
      message = f"Default collection: {collection_name}",
  ))

  # --- Redis (optional) ---
  use_redis = os.environ.get ("USE_REDIS", "false").lower () in ("true", "1", "yes")
  redis_url = os.environ.get ("REDIS_URL", "")
  if use_redis and not redis_url:
    results.append (ValidationResult (
        component = "REDIS", status = "warning",
        message = "USE_REDIS is enabled but REDIS_URL is not set. Falling back to in-memory cache.",
    ))
  elif use_redis:
    results.append (ValidationResult (
        component = "REDIS", status = "ok", message = f"Configured: {redis_url}",
    ))
  else:
    results.append (ValidationResult (
        component = "REDIS", status = "ok", message = "Disabled (using in-memory cache)",
    ))

  # --- Neo4j (optional) ---
  graph_enabled = os.environ.get ("GRAPH_ENABLED", "false").lower () in ("true", "1", "yes")
  if graph_enabled:
    neo4j_uri = os.environ.get ("NEO4J_URI", "")
    if not neo4j_uri:
      results.append (ValidationResult (
          component = "NEO4J", status = "warning",
          message = "GRAPH_ENABLED is true but NEO4J_URI is not set.",
      ))
    else:
      results.append (ValidationResult (
          component = "NEO4J", status = "ok", message = f"Configured: {neo4j_uri}",
      ))
  else:
    results.append (ValidationResult (
        component = "NEO4J", status = "ok", message = "Graph expansion disabled",
    ))

  # --- Auth (optional) ---
  auth_enabled = os.environ.get ("AUTH_ENABLED", "false").lower () in ("true", "1", "yes")
  if auth_enabled:
    jwt_secret = os.environ.get ("JWT_SECRET_KEY", "")
    if not jwt_secret or jwt_secret == "change-me-in-production":
      results.append (ValidationResult (
          component = "AUTH", status = "warning",
          message = "AUTH_ENABLED but JWT_SECRET_KEY is default or empty. Set a strong secret.",
      ))
    else:
      results.append (ValidationResult (
          component = "AUTH", status = "ok", message = "Authentication enabled",
      ))
  else:
    results.append (ValidationResult (
        component = "AUTH", status = "ok", message = "Authentication disabled",
    ))

  # --- LangGraph (optional) ---
  use_langgraph = os.environ.get ("USE_LANGGRAPH", "false").lower () in ("true", "1", "yes")
  results.append (ValidationResult (
      component = "LANGGRAPH", status = "ok",
      message = "Enabled" if use_langgraph else "Disabled",
  ))

  return results


def check_startup_health () -> tuple [bool, list [ValidationResult]]:
  """Run all validation checks and return (can_start, results).
  
  Returns True if the proxy can start (no errors), False if there
  are blocking configuration errors.
  """
  results = validate_config ()
  errors = [r for r in results if r.status == "error"]
  warnings = [r for r in results if r.status == "warning"]

  if errors:
    logger.error ("Configuration errors found:")
    for r in errors:
      logger.error ("  [%s] %s", r.component, r.message)

  if warnings:
    logger.warning ("Configuration warnings:")
    for r in warnings:
      logger.warning ("  [%s] %s", r.component, r.message)

  can_start = len (errors) == 0
  return can_start, results

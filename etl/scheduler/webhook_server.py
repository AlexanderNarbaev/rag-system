# etl/scheduler/webhook_server.py
"""
FastAPI webhook server for real-time Confluence and GitLab event ingestion.
Accepts webhook events, validates HMAC signatures, and produces to Redis Streams.
Returns 202 Accepted immediately; processing happens asynchronously.
"""

import hashlib
import hmac
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

sys.path.insert (0, str (Path (__file__).parent.parent.parent))

from etl.scheduler.stream_producer import StreamProducer

logging.basicConfig (level = logging.INFO, format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s", )
logger = logging.getLogger ("WebhookServer")

DEFAULT_STREAM_KEY = "etl:events"


def _load_config (config_path: Path) -> dict:
  with open (config_path, encoding = "utf-8") as f:
    return yaml.safe_load (f)


def get_redis_client (host: str, port: int) -> Optional ["redis.Redis"]:  # noqa: F821
  try:
    import redis
  except ImportError:
    logger.warning ("redis package not installed, streaming disabled")
    return None
  try:
    client = redis.Redis (host = host, port = port, socket_connect_timeout = 2)
    client.ping ()
    logger.info ("Redis connected at %s:%d", host, port)
    return client
  except Exception as e:
    logger.warning ("Redis unavailable at %s:%d: %s", host, port, e)
    return None


def create_app (
    redis_client = None, webhook_secret: str = "", stream_key: str = DEFAULT_STREAM_KEY,
    webhook_enabled: bool = True, ) -> FastAPI:
  app = FastAPI (title = "RAG Webhook Server", version = "0.6.0")
  app.state.webhook_secret = webhook_secret
  app.state.stream_key = stream_key
  app.state.webhook_enabled = webhook_enabled
  app.state.producer = StreamProducer (redis_client) if redis_client else None

  @app.get ("/health")
  async def health ():
    return {"status": "ok", "service": "webhook-server"}

  async def _process_event (source: str, event_type: str, payload: dict):
    producer = app.state.producer
    if not producer or not producer.redis:
      raise HTTPException (status_code = 503, detail = "Streaming backend unavailable")
    page = payload.get ("page", payload.get ("object_attributes", {}))
    doc_id = str (page.get ("id", payload.get ("object_kind", "unknown")))
    event = {
        "source": source, "event_type": event_type, "doc_id": doc_id, "timestamp": datetime.now (UTC).isoformat (),
        "payload": json.dumps (payload),
    }
    event_data = {k: v for k, v in event.items () if v is not None}
    result = producer.produce_event (app.state.stream_key, event_data)
    if result is None:
      logger.warning ("Failed to produce event to stream")
      raise HTTPException (status_code = 503, detail = "Streaming backend unavailable")

  async def _verify_signature (request: Request) -> bytes:
    body = await request.body ()
    sig_header = request.headers.get ("X-Hub-Signature-256", "")
    if not sig_header.startswith ("sha256="):
      raise HTTPException (status_code = 401, detail = "Missing or invalid signature header")
    expected_sig = sig_header.removeprefix ("sha256=")
    computed_sig = hmac.new (app.state.webhook_secret.encode (), body, hashlib.sha256, ).hexdigest ()
    if not hmac.compare_digest (computed_sig, expected_sig):
      raise HTTPException (status_code = 401, detail = "Invalid signature")
    return body

  @app.post ("/webhook/confluence")
  async def webhook_confluence (request: Request):
    if not app.state.webhook_enabled:
      raise HTTPException (status_code = 503, detail = "Webhook server disabled")
    body = await _verify_signature (request)
    try:
      payload = json.loads (body)
    except json.JSONDecodeError:
      raise HTTPException (status_code = 422, detail = "Invalid JSON body") from None
    event_type = payload.get ("event", payload.get ("event_type", "unknown"))
    await _process_event ("confluence", event_type, payload)
    return JSONResponse (status_code = 202,
        content = {"status": "accepted", "source": "confluence", "event": event_type}, )

  @app.post ("/webhook/gitlab")
  async def webhook_gitlab (request: Request):
    if not app.state.webhook_enabled:
      raise HTTPException (status_code = 503, detail = "Webhook server disabled")
    body = await _verify_signature (request)
    try:
      payload = json.loads (body)
    except json.JSONDecodeError:
      raise HTTPException (status_code = 422, detail = "Invalid JSON body") from None
    event_type = payload.get ("object_kind", payload.get ("event_name", "unknown"))
    await _process_event ("gitlab", event_type, payload)
    return JSONResponse (status_code = 202, content = {"status": "accepted", "source": "gitlab", "event": event_type}, )

  return app


def main ():
  import argparse

  parser = argparse.ArgumentParser (description = "RAG Webhook Server")
  parser.add_argument ("--config", type = Path, default = Path ("etl/config/etl_config.yaml"))
  parser.add_argument ("--host", type = str, default = None)
  parser.add_argument ("--port", type = int, default = None)
  args = parser.parse_args ()

  config = _load_config (args.config) if args.config.exists () else {}
  streaming_cfg = config.get ("streaming", {})

  webhook_enabled = streaming_cfg.get ("webhook_enabled", True)
  webhook_secret = os.environ.get ("WEBHOOK_SECRET", streaming_cfg.get ("webhook_secret", ""))
  webhook_host = args.host or os.environ.get ("WEBHOOK_HOST", streaming_cfg.get ("webhook_host", "0.0.0.0"))
  webhook_port = args.port or int (os.environ.get ("WEBHOOK_PORT", streaming_cfg.get ("webhook_port", 9000)))

  redis_host = os.environ.get ("REDIS_HOST", streaming_cfg.get ("redis_host", "localhost"))
  redis_port = int (os.environ.get ("REDIS_PORT", streaming_cfg.get ("redis_port", 6379)))

  stream_key = os.environ.get ("REDIS_STREAM_KEY", streaming_cfg.get ("redis_stream_key", DEFAULT_STREAM_KEY))

  rclient = get_redis_client (redis_host, redis_port)
  app = create_app (redis_client = rclient, webhook_secret = webhook_secret, stream_key = stream_key,
      webhook_enabled = webhook_enabled, )

  import uvicorn

  logger.info ("Starting webhook server on %s:%d", webhook_host, webhook_port)
  logger.info ("Redis: %s:%d  Stream: %s  Webhook: %s", redis_host, redis_port, stream_key,
      "enabled" if webhook_enabled else "disabled", )  # noqa: E501
  uvicorn.run (app, host = webhook_host, port = webhook_port)


if __name__ == "__main__":
  main ()

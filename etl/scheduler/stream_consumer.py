# etl/scheduler/stream_consumer.py
"""
Redis Streams consumer for real-time ETL event processing.
Consumes events from Redis Streams using consumer groups (XREADGROUP),
processes extract → chunk → embed → index, acknowledges on success,
and claims pending messages on startup for crash recovery.
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert (0, str (Path (__file__).parent.parent.parent))

logging.basicConfig (level = logging.INFO, format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s", )
logger = logging.getLogger ("StreamConsumer")

DEFAULT_STREAM_KEY = "etl:events"
DEFAULT_CONSUMER_GROUP = "etl-workers"
DEFAULT_CONSUMER_NAME = "etl-consumer-1"


class StreamConsumer:
  """Consumes real-time events from Redis Streams and processes them through ETL."""
  
  def __init__ (
      self, redis_client = None, stream_key: str = DEFAULT_STREAM_KEY, consumer_group: str = DEFAULT_CONSUMER_GROUP,
      consumer_name: str = DEFAULT_CONSUMER_NAME, batch_size: int = 10, ):
    self.redis = redis_client
    self.stream_key = stream_key
    self.consumer_group = consumer_group
    self.consumer_name = consumer_name
    self.batch_size = batch_size
    self.running = True
  
  def _ensure_consumer_group (self) -> bool:
    """Create consumer group if it doesn't exist."""
    if not self.redis:
      return False
    try:
      self.redis.xgroup_create (self.stream_key, self.consumer_group, id = "0", mkstream = True)
      logger.info ("Created consumer group %s on stream %s", self.consumer_group, self.stream_key)
      return True
    except Exception as e:
      if "BUSYGROUP" in str (e):
        logger.debug ("Consumer group %s already exists", self.consumer_group)
        return True
      logger.warning ("Failed to create consumer group: %s", e)
      return False
  
  def claim_pending (self, min_idle_ms: int = 60000) -> int:
    """Claim pending messages from other consumers (crash recovery)."""
    if not self.redis:
      return 0
    try:
      pending_info = self.redis.xpending (self.stream_key, self.consumer_group)
      pending_count = pending_info.get ("pending", 0) if isinstance (pending_info, dict) else 0
      if pending_count == 0:
        return 0
      
      claimed_messages, new_id = self.redis.xautoclaim (self.stream_key, self.consumer_group, self.consumer_name,
          min_idle_time = min_idle_ms, count = 100, )
      claimed_count = len (claimed_messages) if claimed_messages else 0
      if claimed_count:
        logger.info ("Claimed %d pending messages for %s", claimed_count, self.consumer_name)
      return claimed_count
    except Exception as e:
      logger.error ("Failed to claim pending messages: %s", e)
      return 0
  
  def process_event (self, event: dict) -> bool:
    """Process a single event: validate, extract content, chunk, index."""
    source = event.get ("source", "")
    event_type = event.get ("event_type", "")
    doc_id = event.get ("doc_id", "")
    payload_str = event.get ("payload", "{}")
    
    if not source:
      logger.warning ("Unknown source in event, skipping")
      return False
    
    try:
      payload = json.loads (payload_str) if isinstance (payload_str, str) else payload_str
    except (json.JSONDecodeError, TypeError):
      logger.warning ("Invalid payload JSON for event doc_id=%s", doc_id)
      return False
    
    logger.info ("Processing event: source=%s type=%s doc_id=%s", source, event_type, doc_id, )
    
    if source == "confluence":
      return self._process_confluence_event (event_type, doc_id, payload)
    elif source == "gitlab":
      return self._process_gitlab_event (event_type, doc_id, payload)
    else:
      logger.warning ("Unsupported source: %s", source)
      return False
  
  def _process_confluence_event (self, event_type: str, doc_id: str, payload: dict) -> bool:
    """Process a Confluence event through chunk → embed → index.

    Planned, not implemented — StreamConsumer lacks the required pipeline
    dependencies (MDKeyChunker, LiveVectorLake).  When a chunker and indexer
    are wired into this class, this method should:
      1. Extract content from the payload (already available in ``page``).
      2. Chunk via ``MDKeyChunker.process_document(content, "html", metadata)``.
      3. Index via ``LiveVectorLake.sync_document(doc_id, chunks)``.

    Returning ``False`` so the message stays un-ACKed and can be retried
    once real processing is connected.
    """
    page = payload.get ("page", {})
    title = page.get ("title", "")
    _body = page.get ("body", {}).get ("storage", {}).get ("value", "") or page.get ("body_storage_raw", "") or ""
    logger.warning ("Confluence %s: page=%s title='%s' — STUB: real chunk+index not implemented, "
                    "StreamConsumer needs chunker and indexer wired in. Returning failure.", event_type, doc_id,
        title, )
    return False
  
  def _process_gitlab_event (self, event_type: str, doc_id: str, payload: dict) -> bool:
    """Process a GitLab event through chunk → embed → index.

    Planned, not implemented — StreamConsumer lacks the required pipeline
    dependencies (MDKeyChunker, LiveVectorLake).  When a chunker and indexer
    are wired into this class, this method should:
      1. Build content from commits / MR / wiki payload fields.
      2. Chunk via ``MDKeyChunker.process_document(content, content_type, metadata)``.
      3. Index via ``LiveVectorLake.sync_document(doc_id, chunks)``.

    Returning ``False`` so the message stays un-ACKed and can be retried
    once real processing is connected.
    """
    if event_type == "push":
      commits = payload.get ("commits", [])
      logger.warning ("GitLab push: project=%s commits=%d — STUB: real chunk+index not implemented.", doc_id,
          len (commits), )
    elif event_type == "merge_request":
      mr = payload.get ("object_attributes", {})
      title = mr.get ("title", "")
      logger.warning ("GitLab MR: id=%s title='%s' state=%s — STUB: real chunk+index not implemented.", doc_id, title,
          mr.get ("state", ""), )
    elif event_type == "wiki_page":
      wiki = payload.get ("object_attributes", {})
      logger.warning ("GitLab wiki: title='%s' action=%s — STUB: real chunk+index not implemented.",
          wiki.get ("title", ""), wiki.get ("action", ""), )
    else:
      logger.warning ("GitLab event: type=%s project=%s — STUB: real chunk+index not implemented.", event_type,
          doc_id, )
    return False
  
  def consume_batch (self, block_ms: int | None = 5000) -> int:
    """Consume a batch of messages from the stream."""
    if not self.redis:
      return 0
    
    self._ensure_consumer_group ()
    
    try:
      streams = {self.stream_key: ">"}
      results = self.redis.xreadgroup (self.consumer_group, self.consumer_name, streams, count = self.batch_size,
          block = block_ms, )
    except Exception as e:
      logger.error ("Failed to read from stream: %s", e)
      return 0
    
    if not results:
      return 0
    
    processed = 0
    for stream_name, messages in results:
      stream_name = stream_name.decode () if isinstance (stream_name, bytes) else stream_name
      for msg_id, event in messages:
        msg_id = msg_id.decode () if isinstance (msg_id, bytes) else msg_id
        success = self.process_event (event)
        if success:
          try:
            self.redis.xack (self.stream_key, self.consumer_group, msg_id)
            logger.debug ("Acknowledged message %s", msg_id)
            processed += 1
          except Exception as e:
            logger.error ("Failed to acknowledge message %s: %s", msg_id, e)
        else:
          logger.warning ("Failed to process message %s, not acknowledging", msg_id)
    
    return processed
  
  def stop (self):
    """Signal the consumer to stop processing."""
    self.running = False
    logger.info ("Consumer %s stopping", self.consumer_name)
  
  def run_forever (self, block_ms: int = 5000):
    """Run consumer loop: claim pending, then poll for new messages."""
    logger.info ("Stream consumer %s starting on stream %s group %s", self.consumer_name, self.stream_key,
        self.consumer_group, )
    
    self.claim_pending ()
    
    while self.running:
      try:
        processed = self.consume_batch (block_ms = block_ms)
        if processed > 0:
          logger.info ("Batch processed: %d events", processed)
      except KeyboardInterrupt:
        logger.info ("Consumer interrupted, shutting down")
        break
      except Exception as e:
        logger.error ("Unexpected error in consumer loop: %s", e)
    
    logger.info ("Consumer %s stopped", self.consumer_name)


def main ():
  import argparse
  import os
  
  import yaml
  
  parser = argparse.ArgumentParser (description = "RAG Stream Consumer")
  parser.add_argument ("--config", type = Path, default = Path ("etl/config/etl_config.yaml"))
  args = parser.parse_args ()
  
  config = {}
  if args.config.exists ():
    with open (args.config, encoding = "utf-8") as f:
      config = yaml.safe_load (f)
  
  streaming_cfg = config.get ("streaming", {})
  
  redis_host = os.environ.get ("REDIS_HOST", streaming_cfg.get ("redis_host", "localhost"))
  redis_port = int (os.environ.get ("REDIS_PORT", streaming_cfg.get ("redis_port", 6379)))
  stream_key = os.environ.get ("REDIS_STREAM_KEY", streaming_cfg.get ("redis_stream_key", DEFAULT_STREAM_KEY))
  consumer_group = os.environ.get ("REDIS_CONSUMER_GROUP",
      streaming_cfg.get ("redis_consumer_group", DEFAULT_CONSUMER_GROUP))  # noqa: E501
  
  try:
    import redis
    
    rclient = redis.Redis (host = redis_host, port = redis_port, socket_connect_timeout = 2)
    rclient.ping ()
    logger.info ("Connected to Redis at %s:%d", redis_host, redis_port)
  except Exception as e:
    logger.warning ("Redis unavailable: %s. Falling back to batch mode.", e)
    rclient = None
  
  consumer = StreamConsumer (redis_client = rclient, stream_key = stream_key, consumer_group = consumer_group, )
  consumer.run_forever ()


if __name__ == "__main__":
  main ()

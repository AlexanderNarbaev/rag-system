# etl/scheduler/stream_producer.py
"""
Redis Streams producer for real-time ETL events.
Publishes webhook events to Redis Streams for asynchronous processing.
"""

import json
import logging
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("StreamProducer")


class StreamProducer:
    """Produces events to Redis Streams."""

    def __init__(self, redis_client: Any = None) -> None:
        self.redis = redis_client

    def produce_event(self, stream: str, event: dict[str, Any]) -> str | None:
        """
        Produce a single event to a Redis Stream.
        Returns the message ID on success, None on failure.

        Event schema: {source, event_type, doc_id, timestamp, payload}
        """
        if not self.redis:
            logger.warning("Redis client not available, dropping event")
            return None
        try:
            fields = {}
            for key, value in event.items():
                if value is not None:
                    fields[key] = value if isinstance(value, (str, bytes, int, float)) else json.dumps(value)
            message_id = self.redis.xadd(stream, fields, maxlen=10000)
            logger.debug("Produced event %s to stream %s", message_id, stream)
            return message_id
        except Exception as e:
            logger.error("Failed to produce event to stream %s: %s", stream, e)
            return None

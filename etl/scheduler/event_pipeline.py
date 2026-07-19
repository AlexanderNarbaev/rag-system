#!/usr/bin/env python3
# etl/scheduler/event_pipeline.py
"""Event-Driven Streaming Pipeline — orchestrates webhook → Redis Streams → consumer.

Unifies the webhook server, stream producer, and stream consumer into a single
coordinator that can be started/stopped as a long-running service. Replaces the
batch scheduler for real-time processing of Confluence, Jira, and GitLab events.

Stub implementation — full integration with chunker/indexer pending.

Usage:
    pipeline = EventPipeline(config)
    await pipeline.start()
    # ... pipeline runs until stopped ...
    await pipeline.stop()

Design:
    ┌────────────┐    ┌──────────────┐    ┌────────────────┐    ┌──────────┐
    │  Webhooks   │───▶│ Redis Streams│───▶│ StreamConsumer  │───▶│  Qdrant  │
    │ (FastAPI)   │    │ (XADD)       │    │ (XREADGROUP)   │    │ (upsert) │
    └────────────┘    └──────────────┘    └────────────────┘    └──────────┘

See Also:
    - etl/scheduler/webhook_server.py — FastAPI webhook endpoints
    - etl/scheduler/stream_producer.py — Redis Streams XADD
    - etl/scheduler/stream_consumer.py — Redis Streams XREADGROUP
    - docs/en/guides/roadmap.md — Phase 6: Real-Time Indexing & Streaming

"""

import asyncio
import logging
import signal
import sys
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("EventPipeline")


class PipelineState(StrEnum):
    """Lifecycle states for the event pipeline."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


# Default configuration values
DEFAULT_STREAM_KEY = "etl:events"
DEFAULT_CONSUMER_GROUP = "etl-workers"
DEFAULT_WEBHOOK_HOST = "0.0.0.0"
DEFAULT_WEBHOOK_PORT = 9000
DEFAULT_POLL_INTERVAL_MS = 5000
DEFAULT_BATCH_SIZE = 10


class EventPipeline:
    """Orchestrates event-driven ETL: webhooks produce to Redis Streams,
    a consumer group processes events through extract → chunk → index.

    This is a **stub** — the consumer handlers currently return False
    (no real processing). Full implementation requires wiring in:
    - MDKeyChunker for document chunking
    - LiveVectorLake for Qdrant upserts
    - EntityRelationExtractor for graph updates

    Attributes:
        config: Full YAML configuration dict.
        state: Current pipeline lifecycle state.
        stats: Event processing counters (produced, consumed, errors).

    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.state: PipelineState = PipelineState.IDLE
        self._shutdown_event = asyncio.Event()

        # Extract streaming sub-config
        self._streaming_cfg = config.get("streaming", {})
        self._redis_cfg = {
            "host": self._streaming_cfg.get("redis_host", "localhost"),
            "port": int(self._streaming_cfg.get("redis_port", 6379)),
        }
        self._stream_key = self._streaming_cfg.get("redis_stream_key", DEFAULT_STREAM_KEY)
        self._consumer_group = self._streaming_cfg.get("redis_consumer_group", DEFAULT_CONSUMER_GROUP)
        self._webhook_cfg = {
            "host": self._streaming_cfg.get("webhook_host", DEFAULT_WEBHOOK_HOST),
            "port": int(self._streaming_cfg.get("webhook_port", DEFAULT_WEBHOOK_PORT)),
            "secret": self._streaming_cfg.get("webhook_secret", ""),
            "enabled": self._streaming_cfg.get("webhook_enabled", True),
        }
        self._batch_size = int(self._streaming_cfg.get("batch_size", DEFAULT_BATCH_SIZE))
        self._poll_interval_ms = int(self._streaming_cfg.get("poll_interval_ms", DEFAULT_POLL_INTERVAL_MS))

        # Internal components (initialized on start)
        self._redis_client: Any = None
        self._producer: Any = None
        self._consumer: Any = None
        self._webhook_app: Any = None
        self._webhook_server: Any = None
        self._consumer_task: asyncio.Task | None = None

        # Stats
        self.stats: dict[str, Any] = {
            "events_produced": 0,
            "events_consumed": 0,
            "events_failed": 0,
            "started_at": None,
            "stopped_at": None,
        }

        logger.info("EventPipeline created (state=%s)", self.state.value)

    @property
    def is_running(self) -> bool:
        """Check if the pipeline is in RUNNING state."""
        return self.state == PipelineState.RUNNING

    def _connect_redis(self) -> Any:
        """Connect to Redis, returning client or None on failure (graceful degradation)."""
        try:
            import redis

            client = redis.Redis(
                host=self._redis_cfg["host"],
                port=self._redis_cfg["port"],
                socket_connect_timeout=2,
            )
            client.ping()
            logger.info(
                "Redis connected at %s:%d",
                self._redis_cfg["host"],
                self._redis_cfg["port"],
            )
            return client
        except ImportError:
            logger.warning("redis package not installed — streaming disabled")
            return None
        except Exception as e:
            logger.warning("Redis unavailable: %s — falling back to idle mode", e)
            return None

    def _create_consumer(self) -> Any:
        """Create a StreamConsumer instance."""
        from etl.scheduler.stream_consumer import StreamConsumer

        return StreamConsumer(
            redis_client=self._redis_client,
            stream_key=self._stream_key,
            consumer_group=self._consumer_group,
            batch_size=self._batch_size,
        )

    def _create_producer(self) -> Any:
        """Create a StreamProducer instance."""
        from etl.scheduler.stream_producer import StreamProducer

        return StreamProducer(redis_client=self._redis_client)

    def _create_webhook_app(self) -> Any:
        """Create the FastAPI webhook application."""
        from etl.scheduler.webhook_server import create_app

        return create_app(
            redis_client=self._redis_client,
            webhook_secret=self._webhook_cfg["secret"],
            stream_key=self._stream_key,
            webhook_enabled=self._webhook_cfg["enabled"],
        )

    async def _run_webhook_server(self) -> None:
        """Start the webhook server as a background task (stub)."""
        try:
            import uvicorn

            config = uvicorn.Config(
                self._webhook_app,
                host=self._webhook_cfg["host"],
                port=self._webhook_cfg["port"],
                log_level="info",
                access_log=False,
            )
            server = uvicorn.Server(config)
            self._webhook_server = server
            await server.serve()
        except ImportError:
            logger.warning("uvicorn not installed — webhook server disabled")
        except asyncio.CancelledError:
            logger.info("Webhook server task cancelled")
        except Exception as e:
            logger.error("Webhook server error: %s", e)

    async def _run_consumer_loop(self) -> None:
        """Run the stream consumer in a loop (stub — delegates to StreamConsumer)."""
        if not self._consumer:
            logger.warning("Consumer not initialized — consumer loop skipped")
            return

        # Claim pending messages from previous crashes
        self._consumer.claim_pending()

        logger.info(
            "Consumer loop started: stream=%s group=%s batch=%d",
            self._stream_key,
            self._consumer_group,
            self._batch_size,
        )

        while not self._shutdown_event.is_set():
            try:
                processed = self._consumer.consume_batch(block_ms=self._poll_interval_ms)
                if processed > 0:
                    self.stats["events_consumed"] += processed
                    logger.info("Consumed %d events (total: %d)", processed, self.stats["events_consumed"])
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Consumer loop error: %s", e)
                self.stats["events_failed"] += 1

        logger.info("Consumer loop stopped")

    def process_event(self, event: dict[str, Any]) -> bool:
        """Process a single event through the pipeline.

        This is a **stub** — currently delegates to StreamConsumer.process_event()
        which returns False for all events (real chunk+index not yet wired in).

        Args:
            event: Event dict with keys: source, event_type, doc_id, payload.

        Returns:
            True if processed successfully, False otherwise.

        """
        if not self._consumer:
            logger.warning("Cannot process event: consumer not initialized")
            return False

        result = self._consumer.process_event(event)
        if result:
            self.stats["events_consumed"] += 1
        else:
            self.stats["events_failed"] += 1
        return result

    async def start(self) -> None:
        """Start the event-driven pipeline.

        Connects to Redis, initializes producer/consumer/webhook components,
        and starts the webhook server and consumer loop as concurrent tasks.
        """
        if self.state == PipelineState.RUNNING:
            logger.warning("Pipeline already running — ignoring start() call")
            return

        self.state = PipelineState.STARTING
        logger.info("Starting EventPipeline...")

        # Connect to Redis (graceful degradation)
        self._redis_client = self._connect_redis()
        if not self._redis_client:
            logger.warning("Redis unavailable — pipeline will run in idle mode (no events processed)")
            self.state = PipelineState.RUNNING
            self.stats["started_at"] = datetime.now(UTC).isoformat()
            return

        # Initialize components
        self._producer = self._create_producer()
        self._consumer = self._create_consumer()
        self._webhook_app = self._create_webhook_app()

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Start webhook server and consumer loop concurrently
        self._consumer_task = asyncio.create_task(self._run_consumer_loop())
        # Webhook server is started separately via main() or as a standalone service

        self.state = PipelineState.RUNNING
        self.stats["started_at"] = datetime.now(UTC).isoformat()
        logger.info(
            "EventPipeline started: stream=%s group=%s state=%s",
            self._stream_key,
            self._consumer_group,
            self.state.value,
        )

    async def stop(self) -> None:
        """Stop the event-driven pipeline gracefully.

        Signals the consumer to stop, waits for in-flight events,
        and closes the Redis connection.
        """
        if self.state in (PipelineState.STOPPED, PipelineState.STOPPING):
            logger.warning("Pipeline already stopping/stopped — ignoring stop() call")
            return

        self.state = PipelineState.STOPPING
        logger.info("Stopping EventPipeline...")

        # Signal shutdown
        self._shutdown_event.set()

        # Stop consumer
        if self._consumer:
            self._consumer.stop()

        # Cancel consumer task
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._consumer_task

        # Stop webhook server
        if self._webhook_server:
            self._webhook_server.should_exit = True

        # Close Redis
        if self._redis_client:
            try:
                self._redis_client.close()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.warning("Error closing Redis: %s", e)

        self.state = PipelineState.STOPPED
        self.stats["stopped_at"] = datetime.now(UTC).isoformat()
        logger.info(
            "EventPipeline stopped: produced=%d consumed=%d failed=%d",
            self.stats["events_produced"],
            self.stats["events_consumed"],
            self.stats["events_failed"],
        )

    def get_status(self) -> dict[str, Any]:
        """Return current pipeline status and stats."""
        return {
            "state": self.state.value,
            "is_running": self.is_running,
            "stream_key": self._stream_key,
            "consumer_group": self._consumer_group,
            "redis_connected": self._redis_client is not None,
            "stats": dict(self.stats),
            "config": {
                "webhook_enabled": self._webhook_cfg["enabled"],
                "webhook_port": self._webhook_cfg["port"],
                "batch_size": self._batch_size,
                "poll_interval_ms": self._poll_interval_ms,
            },
        }


def main():
    """Entry point for running the event pipeline standalone."""
    import argparse

    import yaml

    parser = argparse.ArgumentParser(description="RAG Event-Driven Streaming Pipeline")
    parser.add_argument("--config", type=Path, default=Path("etl/config/etl_config.yaml"))
    parser.add_argument("--webhook-only", action="store_true", help="Start only webhook server")
    parser.add_argument("--consumer-only", action="store_true", help="Start only stream consumer")
    args = parser.parse_args()

    config = {}
    if args.config.exists():
        with open(args.config, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    pipeline = EventPipeline(config)

    async def run():
        await pipeline.start()
        try:
            # Run until interrupted
            while pipeline.is_running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await pipeline.stop()

    asyncio.run(run())


if __name__ == "__main__":
    main()

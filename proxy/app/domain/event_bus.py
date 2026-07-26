"""In-process domain event bus for audit and side effects.

The EventBus is a lightweight, in-process pub/sub for DomainEvent instances.
It is intentionally simple — no broker, no persistence — so that domain
code can publish events without coupling to specific handlers.

Synchronous handlers run inline during ``publish()``. Async handlers
are gathered via ``publish_async()`` so callers can await all side
effects. Handler errors are logged but do not break the publisher
(graceful degradation — matches AGENTS.md architectural principle #2).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from proxy.app.domain.events import DomainEvent

logger = logging.getLogger(__name__)

# Type aliases — keep module importable without extra deps
SyncHandler = Callable[[DomainEvent], Any]
AsyncHandler = Callable[[DomainEvent], Awaitable[Any]]


class EventBus:
    """Simple synchronous + async event bus.

    Handlers are registered per event *type* (the concrete subclass of
    DomainEvent). Publishing fires every handler registered for the
    event's runtime type.
    """

    def __init__(self) -> None:
        self._sync_handlers: dict[type, list[SyncHandler]] = defaultdict(list)
        self._async_handlers: dict[type, list[AsyncHandler]] = defaultdict(list)

    # ------------------------------------------------------------------ subscribe

    def subscribe(self, event_type: type, handler: SyncHandler) -> None:
        """Register a synchronous handler for an event type."""
        self._sync_handlers[event_type].append(handler)

    def subscribe_async(self, event_type: type, handler: AsyncHandler) -> None:
        """Register an async (coroutine) handler for an event type."""
        self._async_handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Callable[..., Any]) -> None:
        """Remove a previously registered handler (sync or async)."""
        if handler in self._sync_handlers.get(event_type, []):
            self._sync_handlers[event_type].remove(handler)
        if handler in self._async_handlers.get(event_type, []):
            self._async_handlers[event_type].remove(handler)

    def clear(self, event_type: type | None = None) -> None:
        """Drop handlers for a specific event type, or all handlers if None."""
        if event_type is None:
            self._sync_handlers.clear()
            self._async_handlers.clear()
        else:
            self._sync_handlers.pop(event_type, None)
            self._async_handlers.pop(event_type, None)

    # ------------------------------------------------------------------ publish

    def publish(self, event: DomainEvent) -> None:
        """Publish a domain event to all sync handlers.

        Errors raised by individual handlers are logged but do not
        propagate — remaining handlers still run (graceful degradation).
        """
        event_type = type(event)
        handlers = list(self._sync_handlers.get(event_type, []))
        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 — handler isolation
                logger.exception("Sync event handler %s raised: %s", getattr(handler, "__name__", handler), exc)

    async def publish_async(self, event: DomainEvent) -> None:
        """Publish a domain event to all async handlers concurrently.

        ``asyncio.gather(..., return_exceptions=True)`` is used so a
        single failing handler does not abort the others.
        """
        handlers = list(self._async_handlers.get(type(event), []))
        if not handlers:
            return
        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for handler, result in zip(handlers, results, strict=False):
            if isinstance(result, BaseException):
                logger.exception(
                    "Async event handler %s raised: %s",
                    getattr(handler, "__name__", handler),
                    result,
                )

    def handler_count(self, event_type: type) -> int:
        """Return number of registered handlers for ``event_type`` (test/debug)."""
        return len(self._sync_handlers.get(event_type, [])) + len(self._async_handlers.get(event_type, []))


# Global instance used by domain-aware core modules.
# Modules can either import this directly (``from proxy.app.domain.event_bus import bus``)
# or call ``bus.subscribe(...)`` to register their own handlers.
bus = EventBus()


__all__ = ["EventBus", "bus"]

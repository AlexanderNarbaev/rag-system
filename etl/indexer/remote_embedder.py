# etl/indexer/remote_embedder.py
"""Remote embedding client for ETL pipeline.

Calls a remote embedding service via HTTP (OpenAI-compatible /v1/embeddings API).
Drop-in replacement for SentenceTransformer — same encode() interface.

Supports:
- Dense embeddings via POST /v1/embeddings
- Batch encoding with automatic chunking
- Health checks and error handling
- Graceful degradation (returns None for sparse/ColBERT)
- Retry logic with exponential backoff + jitter
- Async support with semaphore-based backpressure
- HTTP connection pooling
- Synchronous batch embedding (send multiple texts in one API call)

Usage:
    embedder = create_remote_embedder(
        url="http://embedder-host:8080/v1/embeddings",
        model="bge-m3",
        api_key="...",
    )
    vectors = embedder.encode(["text1", "text2"], normalize_embeddings=True)

    # Async usage
    vectors = await embedder.encode_async(["text1", "text2"])
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class BackoffStrategy(StrEnum):
    CONSTANT = "constant"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


@dataclass
class RetryConfig:
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    jitter: bool = True
    retryable_http_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


def _compute_retry_delay(attempt: int, config: RetryConfig) -> float:
    if config.strategy == BackoffStrategy.CONSTANT:
        delay = config.base_delay
    elif config.strategy == BackoffStrategy.LINEAR:
        delay = config.base_delay * (attempt + 1)
    else:
        delay = config.base_delay * (2**attempt)

    delay = min(delay, config.max_delay)
    if config.jitter:
        delay *= random.uniform(0.75, 1.25)
    return delay


class RetryExhaustedError(Exception):
    def __init__(self, attempts: int, last_error: Exception):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"All {attempts} retry attempts exhausted. Last error: {last_error!r}")


class RemoteEmbedder:
    """Remote embedding client via OpenAI-compatible /v1/embeddings API.

    Implements the same encode(texts) -> np.ndarray interface as
    SentenceTransformer so it can be used as a drop-in replacement
    in QdrantHybridIndexer.
    """

    def __init__(
        self,
        endpoint: str,
        model: str = "",
        api_key: str = "",
        timeout: int = 60,
        max_batch_size: int = 64,
        retry_config: RetryConfig | None = None,
        connection_pool_size: int = 16,
    ):
        base = endpoint.rstrip("/")
        for suffix in ("/v1/embeddings", "/embeddings", "/v1"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        self._endpoint = base
        self._embedding_url = f"{self._endpoint}/v1/embeddings"
        self._model = model or "default"
        self._api_key = api_key
        self._timeout = timeout
        self._max_batch_size = max_batch_size
        self._healthy = True
        self._embedding_dim: int | None = None
        self._retry_config = retry_config or RetryConfig()
        self._connection_pool_size = connection_pool_size
        self._session: Any = None
        self._headers: dict[str, str] = {}
        self._build_headers()

        logger.info(
            "RemoteEmbedder initialized: endpoint=%s, model=%s, batch=%d, pool=%d",
            self._embedding_url,
            self._model,
            self._max_batch_size,
            self._connection_pool_size,
        )

    def _build_headers(self) -> None:
        self._headers = {"Content-Type": "application/json"}
        if self._api_key:
            self._headers["Authorization"] = f"Bearer {self._api_key}"

    def _make_headers(self) -> dict[str, str]:
        return dict(self._headers)

    def _get_session(self) -> Any:
        if self._session is None:
            import requests
            from requests.adapters import HTTPAdapter

            self._session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=self._connection_pool_size,
                pool_maxsize=self._connection_pool_size,
                max_retries=0,
            )
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
        return self._session

    def _call_api_sync(self, texts: list[str]) -> list[list[float]]:
        session = self._get_session()
        payload = {
            "input": texts,
            "model": self._model,
            "encoding_format": "float",
        }
        resp = session.post(
            self._embedding_url,
            json=payload,
            headers=self._make_headers(),
            timeout=self._timeout,
        )
        if resp.status_code in self._retry_config.retryable_http_statuses:
            raise OSError(f"Remote embedder returned {resp.status_code}: {resp.text[:200]}")
        resp.raise_for_status()
        body = resp.json()
        data = sorted(body.get("data", []), key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    def _call_api_with_retry(self, texts: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(self._retry_config.max_attempts):
            try:
                return self._call_api_sync(texts)
            except Exception as e:
                last_error = e
                if attempt < self._retry_config.max_attempts - 1:
                    delay = _compute_retry_delay(attempt, self._retry_config)
                    logger.warning(
                        "Embedding API call failed (attempt %d/%d): %s. Retrying in %.2fs...",
                        attempt + 1,
                        self._retry_config.max_attempts,
                        e,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "All %d embedding attempts exhausted. Last error: %s",
                        self._retry_config.max_attempts,
                        e,
                    )
                    raise RetryExhaustedError(self._retry_config.max_attempts, e) from e

        raise RetryExhaustedError(
            self._retry_config.max_attempts,
            last_error or RuntimeError("unknown"),
        )

    def encode_batch(self, texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        """Encode a batch of texts in a single API call.

        Unlike encode(), this sends ALL texts in one request.
        Use when you want maximum throughput and the batch fits in one API call.

        :param texts: List of strings to embed.
        :param normalize_embeddings: L2-normalize if True.
        :return: numpy array of shape (len(texts), embedding_dim).
        """
        if not texts:
            return np.array([], dtype=np.float32)

        batch_vecs = self._call_api_with_retry(texts)
        vecs = np.array(batch_vecs, dtype=np.float32)

        if self._embedding_dim is None and vecs.ndim == 2:
            self._embedding_dim = vecs.shape[1]
            logger.info("Remote embedder dimension: %d", self._embedding_dim)

        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            vecs = vecs / norms

        return vecs

    def encode(
        self,
        texts: str | list[str],
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
        **kwargs: Any,
    ) -> np.ndarray:
        """Encode text(s) via remote embedding service.

        :param texts: Single string or list of strings.
        :param normalize_embeddings: If True, L2-normalize the output vectors.
        :param show_progress_bar: Ignored (remote service).
        :return: numpy array of shape (n_texts, embedding_dim) or (embedding_dim,) for single text.
        """
        single = isinstance(texts, str)
        if single:
            input_list: list[str] = [texts]
        else:
            input_list = list(texts)
        if not input_list:
            return np.array([])

        all_vecs: list[list[float]] = []

        for i in range(0, len(input_list), self._max_batch_size):
            batch: list[str] = input_list[i : i + self._max_batch_size]
            try:
                batch_vecs = self._call_api_with_retry(batch)
                all_vecs.extend(batch_vecs)
            except Exception as exc:
                logger.error("Remote embedding failed for batch %d-%d: %s", i, i + len(batch), exc)
                self._healthy = False
                raise

        vecs = np.array(all_vecs, dtype=np.float32)

        if self._embedding_dim is None and vecs.ndim == 2:
            self._embedding_dim = vecs.shape[1]
            logger.info("Remote embedder dimension: %d", self._embedding_dim)

        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            vecs = vecs / norms

        return vecs[0] if single else vecs

    async def encode_async(
        self,
        texts: str | list[str],
        normalize_embeddings: bool = True,
        semaphore: asyncio.Semaphore | None = None,
    ) -> np.ndarray:
        """Async version of encode() using aiohttp.

        :param texts: Single string or list of strings.
        :param normalize_embeddings: L2-normalize if True.
        :param semaphore: Optional semaphore for concurrency control (backpressure).
        :return: numpy array of shape (n_texts, embedding_dim).
        """
        single = isinstance(texts, str)
        if single:
            input_list: list[str] = [texts]
        else:
            input_list = list(texts)
        if not input_list:
            return np.array([])

        import aiohttp

        all_vecs: list[list[float]] = []

        async def _call_batch(session: aiohttp.ClientSession, batch: list[str]) -> list[list[float]]:
            for attempt in range(self._retry_config.max_attempts):
                try:
                    async with session.post(
                        self._embedding_url,
                        json={
                            "input": batch,
                            "model": self._model,
                            "encoding_format": "float",
                        },
                        headers=self._make_headers(),
                        timeout=aiohttp.ClientTimeout(total=self._timeout),
                    ) as resp:
                        if resp.status in self._retry_config.retryable_http_statuses:
                            text = await resp.text()
                            raise OSError(f"Remote embedder returned {resp.status}: {text[:200]}")
                        resp.raise_for_status()
                        body = await resp.json()
                        data = sorted(body.get("data", []), key=lambda d: d.get("index", 0))
                        return [d["embedding"] for d in data]
                except Exception as e:
                    if attempt < self._retry_config.max_attempts - 1:
                        delay = _compute_retry_delay(attempt, self._retry_config)
                        logger.warning(
                            "Async embedding failed (attempt %d/%d): %s. Retrying in %.2fs...",
                            attempt + 1,
                            self._retry_config.max_attempts,
                            e,
                            delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error("All %d async embedding attempts exhausted", self._retry_config.max_attempts)
                        raise RetryExhaustedError(self._retry_config.max_attempts, e) from e
            return []

        connector = aiohttp.TCPConnector(limit=self._connection_pool_size)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for i in range(0, len(input_list), self._max_batch_size):
                batch = input_list[i : i + self._max_batch_size]

                async def _do_batch(b: list[str] = batch) -> list[list[float]]:
                    if semaphore:
                        async with semaphore:
                            return await _call_batch(session, b)
                    return await _call_batch(session, b)

                tasks.append(_do_batch())

            gathered: list[list[list[float]] | BaseException] = await asyncio.gather(
                *tasks, return_exceptions=True
            )
            for result in gathered:
                if isinstance(result, BaseException):
                    self._healthy = False
                    raise result
                all_vecs.extend(result)

        vecs = np.array(all_vecs, dtype=np.float32)

        if self._embedding_dim is None and vecs.ndim == 2:
            self._embedding_dim = vecs.shape[1]

        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            vecs = vecs / norms

        return vecs[0] if single else vecs

    def encode_sparse(self, text: str) -> dict[str, Any] | None:
        return None

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def embedding_dimension(self) -> int | None:
        return self._embedding_dim


def create_remote_embedder(
    url: str,
    model: str = "",
    api_key: str = "",
    timeout: int = 60,
    max_batch_size: int = 64,
    retry_config: RetryConfig | None = None,
    connection_pool_size: int = 16,
) -> RemoteEmbedder:
    return RemoteEmbedder(
        endpoint=url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_batch_size=max_batch_size,
        retry_config=retry_config,
        connection_pool_size=connection_pool_size,
    )


def build_remote_embedder_from_config(config: dict[str, Any]) -> RemoteEmbedder | None:
    """Build a RemoteEmbedder from the full ETL config dict.

    Reads remote_services.embedder section.
    Returns None if no endpoint configured.
    """
    remote_cfg = config.get("remote_services", {})
    embedder_cfg = remote_cfg.get("embedder", {})

    endpoint = embedder_cfg.get("endpoint", embedder_cfg.get("url", ""))
    if not endpoint:
        logger.info("No remote embedder endpoint configured, will use local embedder")
        return None

    retry_cfg = RetryConfig(
        max_attempts=embedder_cfg.get("max_retries", 5),
        base_delay=embedder_cfg.get("retry_delay", 2.0),
        max_delay=embedder_cfg.get("retry_max_delay", 30.0),
        retryable_http_statuses=(429, 500, 502, 503, 504),
    )

    return RemoteEmbedder(
        endpoint=endpoint,
        model=embedder_cfg.get("model", ""),
        api_key=embedder_cfg.get("api_key", remote_cfg.get("api_key", "")),
        timeout=embedder_cfg.get("timeout", 60),
        max_batch_size=embedder_cfg.get("batch_size", 64),
        retry_config=retry_cfg,
        connection_pool_size=embedder_cfg.get("connection_pool_size", 16),
    )

# etl/indexer/remote_embedder.py
"""Remote embedding client for ETL pipeline.

Calls a remote embedding service via HTTP (OpenAI-compatible /v1/embeddings API).
Drop-in replacement for SentenceTransformer — same encode() interface.

Supports:
- Dense embeddings via POST /v1/embeddings
- Batch encoding with automatic chunking
- Health checks and error handling
- Graceful degradation (returns None for sparse/ColBERT)

Usage:
    embedder = create_remote_embedder(
        url="http://embedder-host:8080/v1/embeddings",
        model="bge-m3",
        api_key="...",
    )
    vectors = embedder.encode(["text1", "text2"], normalize_embeddings=True)
"""

import json
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


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
    ):
        """Initialize remote embedder.

        :param endpoint: Full URL to embeddings endpoint (e.g. http://host:8080/v1/embeddings)
        :param model: Model name to send in requests
        :param api_key: API key for Authorization header
        :param timeout: HTTP request timeout in seconds
        :param max_batch_size: Maximum texts per single API call
        """
        # Normalize endpoint URL
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

        logger.info("RemoteEmbedder initialized: endpoint=%s, model=%s", self._embedding_url, self._model)

    def _make_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Call the remote embedding API for a batch of texts."""
        import urllib.request

        payload = json.dumps(
            {
                "input": texts,
                "model": self._model,
                "encoding_format": "float",
            },
        ).encode("utf-8")

        req = urllib.request.Request(
            self._embedding_url,
            data=payload,
            headers=self._make_headers(),
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310
            body = json.loads(resp.read().decode("utf-8"))

        # OpenAI format: {"data": [{"embedding": [...], "index": 0}, ...]}
        data = sorted(body.get("data", []), key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

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

        # Process in batches
        for i in range(0, len(input_list), self._max_batch_size):
            batch: list[str] = input_list[i : i + self._max_batch_size]
            try:
                batch_vecs = self._call_api(batch)
                all_vecs.extend(batch_vecs)
            except Exception as exc:
                logger.error("Remote embedding failed for batch %d-%d: %s", i, i + len(batch), exc)
                self._healthy = False
                raise

        vecs = np.array(all_vecs, dtype=np.float32)

        # Cache embedding dimension
        if self._embedding_dim is None and vecs.ndim == 2:
            self._embedding_dim = vecs.shape[1]
            logger.info("Remote embedder dimension: %d", self._embedding_dim)

        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            vecs = vecs / norms

        return vecs[0] if single else vecs

    def encode_sparse(self, text: str) -> dict[str, Any] | None:
        """Remote services typically don't support sparse vectors.

        Returns None to signal 'not supported' — caller should use dense-only.
        """
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
) -> RemoteEmbedder:
    """Factory function to create a remote embedder from config values.

    :param url: Embedder endpoint URL
    :param model: Model name
    :param api_key: API key
    :param timeout: Request timeout
    :return: RemoteEmbedder instance
    """
    return RemoteEmbedder(
        endpoint=url,
        model=model,
        api_key=api_key,
        timeout=timeout,
    )

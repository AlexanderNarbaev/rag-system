# proxy/app/remote_services.py
"""
Remote service adapters for embedding and reranking.

Provides factory functions that automatically select between:
- Remote HTTP-based services (OpenAI-compatible /v1/embeddings, Cohere-compatible /v1/rerank)
- Local in-process models (SentenceTransformer, CrossEncoder)

Implements graceful degradation: if remote is configured but unreachable,
falls back to local model when *_FALLBACK_LOCAL is true.
"""

import logging
from typing import Any

import numpy as np

from proxy.app.shared.config import (
    EMBEDDER_API_KEY,
    EMBEDDER_DEVICE,
    EMBEDDER_ENDPOINT,
    EMBEDDER_FALLBACK_LOCAL,
    EMBEDDER_MODEL,
    RERANKER_API_KEY,
    RERANKER_ENDPOINT,
    RERANKER_FALLBACK_LOCAL,
    RERANKER_MAX_LENGTH,
    RERANKER_MODEL,
)

logger = logging.getLogger(__name__)


# ─── Remote Embedding Client ─────────────────────────────────────────────────


class RemoteEmbeddingClient:
    """Calls a remote embedding service via HTTP (OpenAI /v1/embeddings API).

    Implements the same encode(texts) -> np.ndarray interface as
    SentenceTransformer so it can be used as a drop-in replacement.
    """

    def __init__(self, endpoint: str, api_key: str = "", model: str = ""):
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._model = model or "default"
        self._embedding_url = f"{self._endpoint}/embeddings"
        self._healthy = True

    def _check_health(self) -> bool:
        """Quick connectivity check (non-blocking).

        Uses GET to /models endpoint which is more widely supported than HEAD.
        Falls back to checking the embeddings endpoint directly.
        """
        import urllib.request

        if not self._healthy:
            return False
        try:
            # Try /models endpoint first (OpenAI-compatible)
            models_url = f"{self._endpoint}/models"
            req = urllib.request.Request(models_url)
            if self._api_key:
                req.add_header("Authorization", f"Bearer {self._api_key}")
            urllib.request.urlopen(req, timeout=5)  # nosec B310
            return True
        except Exception:
            try:
                # Fallback: try the embeddings endpoint with a minimal request
                import json as _json

                test_payload = _json.dumps({"model": self._model, "input": ["test"], "max_tokens": 1}).encode("utf-8")
                req = urllib.request.Request(
                    self._embedding_url,
                    data=test_payload,
                    headers={"Content-Type": "application/json"},
                )
                if self._api_key:
                    req.add_header("Authorization", f"Bearer {self._api_key}")
                urllib.request.urlopen(req, timeout=5)  # nosec B310
                return True
            except Exception:
                self._healthy = False
                return False

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
        :return: numpy array of shape (n_texts, embedding_dim).
        """
        import json as _json
        import urllib.request

        single = isinstance(texts, str)
        input_list = [texts] if single else list(texts)
        if not input_list:
            return np.array([])

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = _json.dumps(
            {
                "input": input_list,
                "model": self._model,
                "encoding_format": "float",
            }
        ).encode("utf-8")

        try:
            req = urllib.request.Request(
                self._embedding_url,
                data=payload,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310
                body = _json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.error("Remote embedding failed: %s", exc)
            self._healthy = False
            raise

        # OpenAI format: {"data": [{"embedding": [...], "index": 0}, ...]}
        data = sorted(body.get("data", []), key=lambda d: d.get("index", 0))
        vecs = np.array([d["embedding"] for d in data], dtype=np.float32)

        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1.0, norms)
            vecs = vecs / norms

        return vecs[0] if single else vecs

    def encode_sparse(self, text: str) -> dict | None:
        """Remote services typically don't support sparse vectors.

        Returns None to signal 'not supported' — caller should use dense-only.
        """
        return None

    @property
    def is_healthy(self) -> bool:
        return self._healthy


# ─── Remote Reranker Client ──────────────────────────────────────────────────


class RemoteRerankerClient:
    """Calls a remote reranker service via HTTP (Cohere /v1/rerank API).

    Implements a predict(pairs) -> np.ndarray interface compatible with
    CrossEncoder.predict() so it can be used as a drop-in replacement.
    """

    def __init__(self, endpoint: str, api_key: str = "", model: str = ""):
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._model = model or "default"
        self._rerank_url = f"{self._endpoint}/rerank"
        self._max_length = 512  # default, configurable
        self._healthy = True

    def _check_health(self) -> bool:
        """Quick connectivity check (non-blocking).

        Uses a minimal rerank request to verify the service is reachable.
        """
        import json as _json
        import urllib.request

        if not self._healthy:
            return False
        try:
            # Send a minimal rerank request to check connectivity
            test_payload = _json.dumps(
                {
                    "model": self._model,
                    "query": "test",
                    "documents": ["test document"],
                    "top_n": 1,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                self._rerank_url,
                data=test_payload,
                headers={"Content-Type": "application/json"},
            )
            if self._api_key:
                req.add_header("Authorization", f"Bearer {self._api_key}")
            urllib.request.urlopen(req, timeout=5)  # nosec B310
            return True
        except Exception:
            self._healthy = False
            return False

    def predict(self, pairs: list[tuple[str, str]], **kwargs: Any) -> np.ndarray:
        """Score (query, document) pairs via remote reranker.

        :param pairs: List of (query, document) tuples.
        :return: numpy array of relevance scores (higher = more relevant).
        """
        import json as _json
        import urllib.request

        if not pairs:
            return np.array([])

        # Cohere format: {"model": "...", "query": "...", "documents": [...]}
        # But we have multiple queries — use the first query and score all docs.
        # For per-pair scoring, we send query+documents in Cohere format
        # and map results back. For multi-query, batch by unique queries.
        query_to_indices: dict[str, list[int]] = {}
        for idx, (q, _doc) in enumerate(pairs):
            query_to_indices.setdefault(q, []).append(idx)

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        scores = np.zeros(len(pairs), dtype=np.float32)

        for query, indices in query_to_indices.items():
            documents = [pairs[i][1] for i in indices]
            payload = _json.dumps(
                {
                    "model": self._model,
                    "query": query,
                    "documents": documents,
                    "top_n": len(documents),
                }
            ).encode("utf-8")

            try:
                req = urllib.request.Request(
                    self._rerank_url,
                    data=payload,
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310
                    body = _json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                logger.error("Remote reranking failed: %s", exc)
                self._healthy = False
                raise

            # Cohere format: {"results": [{"index": 0, "relevance_score": 0.9}, ...]}
            results = body.get("results", [])
            for result in results:
                result_idx = result.get("index", 0)
                if result_idx < len(indices):
                    original_idx = indices[result_idx]
                    scores[original_idx] = float(result.get("relevance_score", 0.0))

        return scores

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def max_length(self) -> int:
        return self._max_length

    @max_length.setter
    def max_length(self, value: int):
        self._max_length = value


# ─── Factory Functions ───────────────────────────────────────────────────────

_embedder_instance: Any = None
_reranker_instance: Any = None


def create_embedder() -> Any:
    """Create an embedder: remote client or local SentenceTransformer.

    Uses EMBEDDER_ENDPOINT if configured, otherwise falls back to local model.
    On remote failure, falls back to local if EMBEDDER_FALLBACK_LOCAL is true.
    Result is cached globally (singleton per process).
    """
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance

    # Remote path
    if EMBEDDER_ENDPOINT:
        client = RemoteEmbeddingClient(
            endpoint=EMBEDDER_ENDPOINT,
            api_key=EMBEDDER_API_KEY,
            model=EMBEDDER_MODEL,
        )
        if client._check_health():
            logger.info(
                "Using remote embedder at %s (model=%s)",
                EMBEDDER_ENDPOINT,
                EMBEDDER_MODEL or "default",
            )
            _embedder_instance = client
            return _embedder_instance

        if EMBEDDER_FALLBACK_LOCAL:
            logger.warning(
                "Remote embedder at %s is unreachable. Falling back to local.",
                EMBEDDER_ENDPOINT,
            )
        else:
            raise ConnectionError(
                f"Remote embedder at {EMBEDDER_ENDPOINT} is unreachable and EMBEDDER_FALLBACK_LOCAL is false."
            )

    # Local fallback
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F811
    except ImportError as err:
        raise ImportError(
            "sentence-transformers is required for local embedding. "
            "Set EMBEDDER_ENDPOINT to use a remote service, or install "
            "sentence-transformers."
        ) from err

    if not EMBEDDER_MODEL:
        raise ValueError(
            "EMBEDDER_MODEL is required when using local embedding. "
            "Set EMBEDDER_ENDPOINT for remote, or EMBEDDER_MODEL for local."
        )

    logger.info("Loading local embedder: %s on %s", EMBEDDER_MODEL, EMBEDDER_DEVICE)
    _embedder_instance = SentenceTransformer(EMBEDDER_MODEL, device=EMBEDDER_DEVICE)
    return _embedder_instance


def create_reranker() -> Any:
    """Create a reranker: remote client or local CrossEncoder.

    Uses RERANKER_ENDPOINT if configured, otherwise falls back to local model.
    On remote failure, falls back to local if RERANKER_FALLBACK_LOCAL is true.
    Result is cached globally (singleton per process).
    """
    global _reranker_instance
    if _reranker_instance is not None:
        return _reranker_instance

    # Remote path
    if RERANKER_ENDPOINT:
        client = RemoteRerankerClient(
            endpoint=RERANKER_ENDPOINT,
            api_key=RERANKER_API_KEY,
            model=RERANKER_MODEL,
        )
        if client._check_health():
            logger.info(
                "Using remote reranker at %s (model=%s)",
                RERANKER_ENDPOINT,
                RERANKER_MODEL or "default",
            )
            _reranker_instance = client
            return _reranker_instance

        if RERANKER_FALLBACK_LOCAL:
            logger.warning(
                "Remote reranker at %s is unreachable. Falling back to local.",
                RERANKER_ENDPOINT,
            )
        else:
            raise ConnectionError(
                f"Remote reranker at {RERANKER_ENDPOINT} is unreachable and RERANKER_FALLBACK_LOCAL is false."
            )

    # Local fallback
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as err:
        raise ImportError(
            "sentence-transformers is required for local reranking. "
            "Set RERANKER_ENDPOINT to use a remote service, or install "
            "sentence-transformers."
        ) from err

    if not RERANKER_MODEL:
        raise ValueError(
            "RERANKER_MODEL is required when using local reranking. "
            "Set RERANKER_ENDPOINT for remote, or RERANKER_MODEL for local."
        )

    logger.info(
        "Loading local reranker: %s (max_length=%d)",
        RERANKER_MODEL,
        RERANKER_MAX_LENGTH,
    )
    _reranker_instance = CrossEncoder(RERANKER_MODEL, max_length=RERANKER_MAX_LENGTH)
    return _reranker_instance


def get_embedder() -> Any:
    """Get the current embedder instance (singleton)."""
    return _embedder_instance


def get_reranker() -> Any:
    """Get the current reranker instance (singleton)."""
    return _reranker_instance

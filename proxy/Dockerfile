# proxy/Dockerfile
# Docker image for the RAG proxy (OpenAI-compatible server with Qdrant, reranking, LangGraph)

FROM python:3.12-slim

# Install system dependencies (required by some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install dependencies
COPY proxy/requirements_proxy.txt .
RUN pip install --no-cache-dir -r requirements_proxy.txt

# Copy the proxy source code (keep the proxy/app structure for imports)
COPY proxy/ /app/proxy/
# Configuration template (mounted/overridden at runtime via .env)
COPY proxy/.env.example /app/.env.example

# ── Optional: GPU support for model fine-tuning ──
# To use GPU, uncomment the following lines and rebuild the image
# COPY proxy/requirements_proxy_gpu.txt /app/requirements_proxy_gpu.txt
# RUN pip install --no-cache-dir -r /app/requirements_proxy_gpu.txt
# After building, add to docker run: --gpus all

# Create directories for logs and cache (optional, will be overridden by volumes)
RUN mkdir -p /app/logs /app/cache

# Environment variables for Hugging Face model caching (can be overridden at runtime)
ENV HF_HOME=/app/cache/huggingface
ENV TRANSFORMERS_CACHE=/app/cache/huggingface/transformers
ENV SENTENCE_TRANSFORMERS_HOME=/app/cache/huggingface/sentence-transformers

# Disable bytecode and log buffering
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Add project root to Python path so 'proxy.app.*' imports work
ENV PYTHONPATH=/app

# Port the server listens on (default 8080)
EXPOSE 8080

# Graceful shutdown signal
STOPSIGNAL SIGTERM

# Health check for orchestration
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD curl -f http://localhost:8080/v1/health/live || exit 1

# Run command via granian (high-performance Rust ASGI server — ADR-008)
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--threads", "4", "proxy.app.main:app"]

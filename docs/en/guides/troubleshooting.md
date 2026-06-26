# Troubleshooting Guide

## Proxy Won't Start

### Port Conflict
```bash
# Symptom: "Address already in use" in docker logs
ss -tlnp | grep 8080

# Fix: kill the conflicting process or change PORT in .env
echo "PORT=8081" >> proxy/.env
# Also update docker-compose.yml ports mapping
```

### Missing Dependencies
```bash
# Symptom: "ModuleNotFoundError: No module named 'fastapi'"
docker logs rag-proxy

# Fix: rebuild the image
docker-compose build --no-cache rag-proxy
docker-compose up -d rag-proxy
```

### Configuration Errors
```bash
# Symptom: proxy starts then exits immediately
docker logs rag-proxy

# Common causes:
# - .env file not mounted or has syntax errors
# - SQLite/Redis connection string malformed
# Fix:
docker run --rm -v $(pwd)/.env:/app/.env:ro rag-proxy python -c "from app.config import print_config; print_config()"
```

### Cannot Connect to Upstream Services
```bash
# Symptom: "Connection refused" to qdrant/neo4j/redis/llm-backend in proxy logs
# Verify all services are running:
docker-compose ps

# Check network connectivity:
docker exec rag-proxy curl -s http://qdrant:6333/health
docker exec rag-proxy curl -s http://llm-backend:8000/health

# Fix: ensure depends_on order is correct, increase start_period
```

## Qdrant Connection Errors

### Host/Port Issues
```bash
# Symptom: "Failed to connect to Qdrant" in proxy logs
# Check Qdrant is running and accessible:
curl http://localhost:6333/collections
curl http://qdrant:6333/collections  # from within docker network

# Fix: verify QDRANT_HOST and QDRANT_PORT in .env match docker-compose service name
```

### Collection Not Found
```bash
# Symptom: "Collection 'knowledge_base' not found"
# Check existing collections:
curl http://localhost:6333/collections

# Fix: initialize the collection:
python scripts/init_collections.py
```

### Collection Already Exists
```bash
# Symptom: "Collection 'knowledge_base' already exists" during init
# Fix: recreate with new schema:
python scripts/init_collections.py --qdrant-recreate
# Warning: this deletes all vector data
```

### Memory Exhaustion
```bash
# Symptom: Qdrant OOM, "memory allocation failed"
docker logs rag-qdrant

# Fix: limit Qdrant memory, add storage config:
# In docker-compose.yml qdrant service:
environment:
  - QDRANT__STORAGE__OPTIMIZERS__INDEXING_THRESHOLD=10000
  - QDRANT__STORAGE__OPTIMIZERS__MEMORY_THRESHOLD=20000
```

## LLM Timeout

### Increase Request Timeout
```bash
# Symptom: "Read timed out" or 504 from LLM backend
# Check current setting:
grep REQUEST_TIMEOUT proxy/.env

# Fix: increase timeout in .env (seconds):
REQUEST_TIMEOUT=300  # 5 minutes for long generations
MAX_RETRIES=2
RETRY_DELAY=2.0

# Restart proxy:
docker-compose restart rag-proxy
```

### Check LLM Backend Status
```bash
# Symptom: LLM returning empty responses or 500
# Check LLM backend is healthy:
curl http://localhost:8000/health

# Check backend logs for OOM or model loading errors:
docker logs rag-llm-backend --tail 50

# Common LLM backend issues:
# - Model file not found: verify /models volume mount
# - GPU out of memory: reduce --max-model-len or use smaller quant
```

### Fallback to Alternative Backend
```bash
# If one backend is down, point proxy to an alternative:
LLM_ENDPOINT=http://localhost:8081/v1
# Start alternative server (e.g., llama.cpp):
llama-server -m /models/your-model.gguf --port 8081
```

## Poor Search Results

### Check Embedding Model
```bash
# Symptom: irrelevant or random chunks returned
# Verify the embedder is using the correct model:
grep EMBEDDER_MODEL proxy/.env
# Must be: EMBEDDER_MODEL=BAAI/bge-m3

# Verify model is loaded correctly:
python -c "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('BAAI/bge-m3'); print(m.encode('test')[:5])"
# Should output a non-zero vector
```

### Verify Collection Schema
```bash
# Check that dense + sparse vectors are configured:
curl http://localhost:6333/collections/knowledge_base | python -m json.tool
# Look for: "vectors": {"dense": ..., "sparse": ...}

# If sparse vectors missing, recreate collection:
python scripts/init_collections.py --qdrant-recreate
# Then re-run ETL to reindex
```

### Tune HNSW Parameters
```bash
# Update collection config for better recall:
curl -X PATCH http://localhost:6333/collections/knowledge_base \
  -H 'Content-Type: application/json' \
  -d '{"hnsw_config": {"m": 32, "ef_construct": 200}, "optimizers_config": {"indexing_threshold": 10000}}'
```

## High Memory Usage

### Cache Limits
```bash
# Symptom: proxy memory grows over time
# Check Redis memory:
docker exec rag-redis redis-cli INFO memory | grep used_memory_human

# Fix: limit Redis memory in docker-compose.yml:
redis:
  command: redis-server --appendonly yes --maxmemory 1gb --maxmemory-policy allkeys-lru
```

### Model Offloading
```bash
# Symptom: GPU OOM during embedding
# Set embedder to CPU and reduce reranker batch:
EMBEDDER_DEVICE=cpu
RERANKER_BATCH_SIZE=8

# For LLM backend, reduce memory usage:
--max-model-len 32768          # shorter context window
--gpu-memory-utilization 0.80  # leave 20% headroom for other processes
```

### Batch Size Reduction
```bash
# Symptom: OOM during batch indexing
# In etl/config/etl_config.yaml:
indexing:
  batch_size: 50   # reduce from 100

# Also reduce retrieval count:
MAX_CHUNKS_RETRIEVAL=30
MAX_CHUNKS_AFTER_RERANK=10
```

## ETL Failures

### WAL Corruption Recovery
```bash
# Symptom: "WAL file corrupted" or ETL hangs on startup
# Check WAL integrity:
python -c "import json; json.load(open('etl/wal/etl_wal.json'))"

# If corrupted, delete WAL and run full reindex:
rm etl/wal/etl_wal.json
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml --full
```

### API Rate Limits
```bash
# Symptom: "429 Too Many Requests" from Confluence/Jira/GitLab
# Fix: add delays between API calls. In etl_config.yaml, adjust per source.
# Or set environment variable:
ETL_RATE_LIMIT_DELAY=1.0  # seconds between requests

# For GitLab, reduce max_commits:
gitlab:
  max_commits_per_project: 100  # was 1000
```

### Partial Reindex
```bash
# Symptom: some documents missing from search results after partial ETL crash
# Check WAL for completed sources:
python -c "
import json
wal = json.load(open('etl/wal/etl_wal.json'))
print('Completed sources:', wal.get('completed_sources', []))
print('Last successful run:', wal.get('last_successful_run'))
"

# Reindex only failed sources:
python etl/scheduler/run_etl.py --config etl/config/etl_config.yaml \
  --sources confluence,jira  # skip completed sources
```

### Disk Full During Indexing
```bash
# Symptom: "No space left on device" during ETL
# Check disk usage:
df -h etl/chunks/ etl/hot_chunks/ etl/cold_chunks/

# Clean cold storage older than 30 days:
find etl/cold_chunks/ -name "*.parquet" -mtime +30 -delete

# Move cold lake to separate volume:
mkdir -p /mnt/cold_storage/rag_lake
ln -s /mnt/cold_storage/rag_lake etl/cold_lake
```

## Neo4j Errors

### Connection Retry
```bash
# Symptom: "Unable to connect to Neo4j" or "ServiceUnavailable"
# Check Neo4j is running:
docker exec rag-neo4j cypher-shell -u neo4j -p password "RETURN 1"

# If connection refused, increase retry in config:
# proxy/.env:
NEO4J_MAX_RETRY_TIME=60  # seconds

# Or in ETL config (etl/config/etl_config.yaml):
graph:
  neo4j:
    max_connection_lifetime: 3600
    connection_acquisition_timeout: 60
```

### Constraint Violations
```bash
# Symptom: "ConstraintViolation: node with property X already exists"
# This is a deduplication issue — check if duplicates are expected:
MATCH (n:Entity {name: 'duplicate_name'}) RETURN count(n)

# If safe to proceed, use MERGE instead of CREATE in loader.
# Otherwise, drop and recreate constraints:
DROP CONSTRAINT entity_name_unique IF EXISTS;
CREATE CONSTRAINT entity_name_unique FOR (n:Entity) REQUIRE n.name IS UNIQUE;
```

### Out of Memory
```bash
# Symptom: Neo4j crashes with "java.lang.OutOfMemoryError"
# Check current heap:
docker exec rag-neo4j cypher-shell -u neo4j -p password \
  "CALL dbms.listConfig() YIELD name, value WHERE name CONTAINS 'memory' RETURN name, value"

# Increase heap in docker-compose.yml:
NEO4J_dbms_memory_heap_initial__size=2G
NEO4J_dbms_memory_heap_max__size=4G
NEO4J_dbms_memory_pagecache_size=2G

# Restart:
docker-compose restart neo4j
```

### Graph Load Failures
```bash
# Symptom: ETL graph builder step fails with deadlock
# Run graph building with reduced concurrency:
# In etl/config/etl_config.yaml:
graph:
  batch_size: 50         # smaller batches
  max_concurrency: 1     # single-threaded

# Or disable graph temporarily and run indexing only:
graph:
  enabled: false
```

---

## Authentication & RBAC Issues

### JWT Token Rejected (401 Unauthorized)

**Symptom:** All authenticated requests return 401.

```bash
# Verify auth is enabled
curl -s http://localhost:8080/v1/health | jq '.components.auth'

# Check JWT secret is set
echo $JWT_SECRET  # Must be non-empty when AUTH_ENABLED=true

# Verify token is not expired
curl -s http://localhost:8080/v1/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

### Token Expiration

```bash
# Refresh before expiry
curl -X POST http://localhost:8080/v1/auth/refresh \
  -H "Authorization: Bearer $TOKEN"

# Increase expiry time:
TOKEN_EXPIRE_HOURS=48
```

### RBAC Access Denied (403 Forbidden)

**Symptom:** Authenticated but cannot access certain documents.

1. Verify the user's role in JWT claims:
   ```bash
   python3 -c "import jwt; print(jwt.decode('$TOKEN', options={'verify_signature': False}))"
   ```
2. Check document access levels match user role:
   - `admin` — can access all documents
   - `expert` — can access `internal` + `public`
   - `user` — can access `public` only
   - `read_only` — read-only, cannot submit feedback
3. Verify `AUTH_VALID_USERS` JSON has correct user entries.

### Keycloak Integration Issues

```bash
# Verify Keycloak connectivity
curl -s http://keycloak:8080/auth/realms/your-realm/.well-known/openid-configuration

# Check JWT public key matches
python3 -c "
import jwt
with open('path/to/public.pem', 'r') as f:
    key = f.read()
token = 'your-jwt'
jwt.decode(token, key, algorithms=['RS256'])
"

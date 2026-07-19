#!/bin/bash
# RAG System Deployment Script
# Usage: ./scripts/deploy.sh [dev|prod]
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
ENVIRONMENT="${1:-dev}"
COMPOSE_FILE="proxy/docker-compose.yml"
HEALTH_URL="http://localhost:8080/v1/health"
HEALTH_TIMEOUT=30

if [ "$ENVIRONMENT" = "prod" ]; then
    COMPOSE_FILE="deploy/docker/docker-compose.prod.yml"
    echo -e "${YELLOW}⚠️  Production deployment requested${NC}"
fi

# Validate environment
if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "prod" ]]; then
    echo -e "${RED}❌ Invalid environment: $ENVIRONMENT. Use 'dev' or 'prod'.${NC}"
    exit 1
fi

# Check if compose file exists
if [ ! -f "$COMPOSE_FILE" ]; then
    echo -e "${RED}❌ Compose file not found: $COMPOSE_FILE${NC}"
    exit 1
fi

echo -e "${GREEN}🚀 Deploying RAG System ($ENVIRONMENT)...${NC}"
echo "   Using: $COMPOSE_FILE"

# Pull latest images
echo -e "\n${YELLOW}📦 Pulling latest images...${NC}"
docker-compose -f "$COMPOSE_FILE" pull

# Stop existing services gracefully
echo -e "\n${YELLOW}🛑 Stopping existing services...${NC}"
docker-compose -f "$COMPOSE_FILE" down --timeout 30

# Start services
echo -e "\n${GREEN}▶️  Starting services...${NC}"
docker-compose -f "$COMPOSE_FILE" up -d

# Wait for services to initialize
echo -e "\n${YELLOW}⏳ Waiting for services to initialize...${NC}"
sleep 10

# Health check with retry
echo -e "\n${YELLOW}🏥 Checking service health...${NC}"
RETRIES=5
RETRY_DELAY=5
HEALTHY=false

for i in $(seq 1 $RETRIES); do
    if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    echo "   Attempt $i/$RETRIES - waiting ${RETRY_DELAY}s..."
    sleep $RETRY_DELAY
done

if [ "$HEALTHY" = true ]; then
    echo -e "\n${GREEN}✅ Health check passed!${NC}"
    echo -e "\n${GREEN}📊 Service status:${NC}"
    curl -s "$HEALTH_URL" | python3 -m json.tool 2>/dev/null || curl -s "$HEALTH_URL"
else
    echo -e "\n${RED}❌ Health check failed after $RETRIES attempts${NC}"
    echo -e "${YELLOW}📋 Checking service logs...${NC}"
    docker-compose -f "$COMPOSE_FILE" logs --tail=20
    exit 1
fi

# Show running services
echo -e "\n${GREEN}🐳 Running services:${NC}"
docker-compose -f "$COMPOSE_FILE" ps

echo -e "\n${GREEN}✅ Deployment complete!${NC}"
echo "   Environment: $ENVIRONMENT"
echo "   Compose file: $COMPOSE_FILE"

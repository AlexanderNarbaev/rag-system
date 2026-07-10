#!/bin/bash
# Verify backup integrity
# Usage: ./scripts/ops/verify_restore.sh [backup_dir]
set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

BACKUP_DIR="${1:-./backups}"
ERRORS=0

echo -e "${GREEN}🔍 Verifying backups in $BACKUP_DIR...${NC}\n"

# Check if backup directory exists
if [ ! -d "$BACKUP_DIR" ]; then
    echo -e "${RED}❌ Backup directory not found: $BACKUP_DIR${NC}"
    exit 1
fi

# ── Qdrant Backup ──────────────────────────────────────────────────────────────
echo -e "${YELLOW}📦 Checking Qdrant backup...${NC}"
QDRANT_BACKUPS=$(find "$BACKUP_DIR" -name "qdrant-*.tar.gz" -type f 2>/dev/null | head -1)

if [ -n "$QDRANT_BACKUPS" ]; then
    echo -e "   ${GREEN}✅ Qdrant backup found: $(basename "$QDRANT_BACKUPS")${NC}"
    
    # Verify archive integrity
    if tar -tzf "$QDRANT_BACKUPS" > /dev/null 2>&1; then
        echo -e "   ${GREEN}✅ Archive integrity OK${NC}"
        
        # Show backup size and date
        BACKUP_SIZE=$(du -h "$QDRANT_BACKUPS" | cut -f1)
        BACKUP_DATE=$(stat -c %y "$QDRANT_BACKUPS" 2>/dev/null || stat -f %Sm "$QDRANT_BACKUPS" 2>/dev/null)
        echo -e "   📊 Size: $BACKUP_SIZE"
        echo -e "   📅 Date: $BACKUP_DATE"
    else
        echo -e "   ${RED}❌ Archive integrity check failed${NC}"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "   ${RED}❌ No Qdrant backup found${NC}"
    ERRORS=$((ERRORS + 1))
fi

# ── Neo4j Backup ───────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}📦 Checking Neo4j backup...${NC}"
NEO4J_BACKUPS=$(find "$BACKUP_DIR" -name "neo4j-*.dump" -type f 2>/dev/null | head -1)

if [ -n "$NEO4J_BACKUPS" ]; then
    echo -e "   ${GREEN}✅ Neo4j backup found: $(basename "$NEO4J_BACKUPS")${NC}"
    
    # Check file size (should be non-zero)
    BACKUP_SIZE=$(du -h "$NEO4J_BACKUPS" | cut -f1)
    BACKUP_DATE=$(stat -c %y "$NEO4J_BACKUPS" 2>/dev/null || stat -f %Sm "$NEO4J_BACKUPS" 2>/dev/null)
    echo -e "   📊 Size: $BACKUP_SIZE"
    echo -e "   📅 Date: $BACKUP_DATE"
    
    if [ ! -s "$NEO4J_BACKUPS" ]; then
        echo -e "   ${RED}❌ Backup file is empty${NC}"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "   ${RED}❌ No Neo4j backup found${NC}"
    ERRORS=$((ERRORS + 1))
fi

# ── Redis Backup ───────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}📦 Checking Redis backup...${NC}"
REDIS_BACKUPS=$(find "$BACKUP_DIR" -name "redis-*.rdb" -type f 2>/dev/null | head -1)

if [ -n "$REDIS_BACKUPS" ]; then
    echo -e "   ${GREEN}✅ Redis backup found: $(basename "$REDIS_BACKUPS")${NC}"
    
    # Check file size (should be non-zero)
    BACKUP_SIZE=$(du -h "$REDIS_BACKUPS" | cut -f1)
    BACKUP_DATE=$(stat -c %y "$REDIS_BACKUPS" 2>/dev/null || stat -f %Sm "$REDIS_BACKUPS" 2>/dev/null)
    echo -e "   📊 Size: $BACKUP_SIZE"
    echo -e "   📅 Date: $BACKUP_DATE"
    
    if [ ! -s "$REDIS_BACKUPS" ]; then
        echo -e "   ${RED}❌ Backup file is empty${NC}"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo -e "   ${RED}❌ No Redis backup found${NC}"
    ERRORS=$((ERRORS + 1))
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ All backup integrity checks passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ Found $ERRORS backup integrity issue(s)${NC}"
    exit 1
fi

#!/bin/bash
# Clean chat export file from ALL git history
# Run: bash scripts/clean_git_history.sh
set -e

echo "=== Step 1/5: Removing from index ==="
git rm --cached -f docs/deepseek-chat-2c423805.json 2>/dev/null || true
git commit -m "chore: remove chat export from tracking" 2>/dev/null || true

echo "=== Step 2/5: Purging from history ==="
git filter-branch -f \
  --index-filter 'git rm --cached --ignore-unmatch docs/deepseek-chat-2c423805.json' \
  --prune-empty --tag-name-filter cat -- --all

echo "=== Step 3/5: Cleaning refs ==="
git for-each-ref --format="%(refname)" refs/original/ | xargs -r -n 1 git update-ref -d

echo "=== Step 4/5: Garbage collection ==="
git reflog expire --expire=now --all
git gc --aggressive --prune=now

echo "=== Step 5/5: Force push to both remotes ==="
git push github main --force
git push gitverse main --force

echo "=== DONE ==="
echo "Verify at: https://github.com/AlexanderNarbaev/rag-system/security/secret-scanning"

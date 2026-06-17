#!/bin/bash
set -e

CURRENT_BRANCH=$(git branch --show-current)
read -p "Please enter a description of this synchronization: " SYNC_MSG

echo "▶ Creating gitlab-feature branch..."
git checkout -b gitlab-feature

echo "▶ Removing .md files from index..."
git rm -r --cached '*.md' 2>/dev/null || true
git rm -r --cached .claude/ 2>/dev/null || true
git checkout HEAD -- docs/README.md 2>/dev/null || true

echo "▶ Committing..."
#git commit -m "chore: sync to GitLab (strip .md)" || echo "Nothing to commit"
git commit -m "chore: sync to GitLab $(date +%Y-%m-%d) — ${SYNC_MSG}"

echo "▶ Pushing to GitLab..."
git push gitlab gitlab-feature:feature --force

echo "▶ Cleaning up..."
git checkout -f "$CURRENT_BRANCH"
git branch -D gitlab-feature

echo "✅ GitLab sync complete."
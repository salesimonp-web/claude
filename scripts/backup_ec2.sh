#!/bin/bash
# backup_ec2.sh — Backup quotidien EC2 → Mac via Tailscale
set -euo pipefail
DEST="/Users/spierre/backups/ec2"
DATE=$(date +%Y-%m-%d)
LOG="/tmp/backup_ec2.log"

echo "[$(date)] Starting EC2 backup..." >> "$LOG"

# Backup configs et state files (pas les logs ni le venv)
rsync -avz --delete \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='*.log' \
  --exclude='node_modules/' \
  ubuntu@100.114.249.88:/home/ubuntu/hyperliquid-bot/ "$DEST/hyperliquid-bot/" 2>> "$LOG"

rsync -avz --delete \
  ubuntu@100.114.249.88:/home/ubuntu/.openclaw/openclaw.json "$DEST/openclaw.json" 2>> "$LOG"

rsync -avz \
  ubuntu@100.114.249.88:/home/ubuntu/.claude-env "$DEST/claude-env" 2>> "$LOG"

echo "[$(date)] Backup completed to $DEST" >> "$LOG"

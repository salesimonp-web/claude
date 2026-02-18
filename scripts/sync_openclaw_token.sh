#!/bin/bash
# sync_openclaw_token.sh — Synchronise le token OAuth Claude vers EC2 OpenClaw
# Tourne en cron sur le Mac toutes les 4h pour éviter les 401

set -euo pipefail

LOG="/tmp/sync_openclaw_token.log"
EC2="ec2"  # alias SSH

echo "[$(date)] Starting token sync..." >> "$LOG"

# 1. Extraire le token frais du keychain Mac
ACCESS_TOKEN=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null | python3 -c "
import sys, json
data = json.loads(sys.stdin.read().strip())
print(data.get('claudeAiOauth', {}).get('accessToken', ''))
")

if [ -z "$ACCESS_TOKEN" ]; then
    echo "[$(date)] ERROR: No access token found in keychain" >> "$LOG"
    exit 1
fi

TOKEN_END="${ACCESS_TOKEN: -8}"
echo "[$(date)] Token extracted (ends: ...$TOKEN_END)" >> "$LOG"

# 2. Pousser vers EC2 et mettre à jour openclaw.json
ssh "$EC2" "python3 -c \"
import json
with open('/home/ubuntu/.openclaw/openclaw.json', 'r') as f:
    config = json.load(f)
config['env']['ANTHROPIC_API_KEY'] = '$ACCESS_TOKEN'
with open('/home/ubuntu/.openclaw/openclaw.json', 'w') as f:
    json.dump(config, f, indent=2)
print('Config updated')
\""

if [ $? -ne 0 ]; then
    echo "[$(date)] ERROR: Failed to update config on EC2" >> "$LOG"
    exit 1
fi

# 3. Mettre à jour .claude-env aussi
ssh "$EC2" "sed -i 's|^CLAUDE_CODE_OAUTH_TOKEN=.*|CLAUDE_CODE_OAUTH_TOKEN=$ACCESS_TOKEN|' /home/ubuntu/.claude-env 2>/dev/null || true"

# 4. Redémarrer OpenClaw gracieusement
ssh "$EC2" "systemctl --user restart openclaw-gateway"

echo "[$(date)] Token synced and OpenClaw restarted successfully" >> "$LOG"

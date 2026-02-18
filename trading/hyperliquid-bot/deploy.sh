#!/bin/bash
# Deploy Hyperliquid Bot v5 to EC2

EC2_HOST="ubuntu@54.197.197.104"
EC2_KEY="$HOME/Documents/clauwdbotmax.pem"
REMOTE_DIR="~/hyperliquid-bot"

echo "=== Deploying Hyperliquid Bot v5 ==="

# Sync files
rsync -avz --progress \
    -e "ssh -i $EC2_KEY -o StrictHostKeyChecking=no" \
    --exclude='*.log' \
    --exclude='*_state.json' \
    --exclude='trades_history.json' \
    --exclude='*.tar.gz' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='farming_wallets.json' \
    --exclude='airdrop_alerts.txt' \
    --exclude='faucet_todo.txt' \
    ./ "$EC2_HOST:$REMOTE_DIR/"

echo "=== Installing dependencies (venv) ==="
ssh -i "$EC2_KEY" -o StrictHostKeyChecking=no "$EC2_HOST" \
    "cd $REMOTE_DIR && source venv/bin/activate && pip install -r requirements.txt -q"

echo "=== Restarting bot in tmux ==="
ssh -i "$EC2_KEY" -o StrictHostKeyChecking=no "$EC2_HOST" \
    "tmux send-keys -t trading C-c 2>/dev/null; sleep 2; tmux kill-session -t trading 2>/dev/null; sleep 1; tmux new-session -d -s trading 'cd $REMOTE_DIR && source venv/bin/activate && python3 bot.py'"

echo "=== Deploy complete! ==="
echo "Check logs: ssh -i $EC2_KEY $EC2_HOST 'tail -f $REMOTE_DIR/trading_bot.log'"

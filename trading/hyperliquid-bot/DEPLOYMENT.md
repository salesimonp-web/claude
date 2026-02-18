# Trading Bot v5 - Deployment

## DEPLOYED

**Server:** EC2 clauwdbotmax (54.197.197.104)
**Session:** tmux session `trading`
**Bot version:** v5 (multi-signal, trailing stop, strategy adapter)

## Deploy

```bash
# Depuis le Mac, dans /Users/spierre/hyperliquid-bot/
./deploy.sh
```

Le script :
1. rsync les fichiers vers EC2 (exclut logs, state, .git, __pycache__)
2. Installe les dependances (pip install -r requirements.txt)
3. Redémarre le bot dans la session tmux "trading"

## Healthcheck

```bash
# Sur EC2
cd ~/hyperliquid-bot
python healthcheck.py
```

Verifie : process actif, logs frais (< 5 min), balance, positions ouvertes, trades, alertes recentes, etat du strategy adapter.

## Commandes manuelles

```bash
# SSH
ssh -i ~/Documents/clauwdbotmax.pem ubuntu@54.197.197.104

# Attach tmux
tmux attach -t trading

# Logs (tout)
tail -f ~/hyperliquid-bot/trading_bot.log

# Alertes critiques uniquement
tail -f ~/hyperliquid-bot/alerts.log

# Stop
tmux send-keys -t trading C-c

# Start
tmux send-keys -t trading 'cd ~/hyperliquid-bot && python bot.py' Enter
```

## Credentials

Stockes dans `~/.claude-env` sur EC2 (jamais dans le repo). Charges par `env_loader.py`.

Variables utilisees :
- `HL_ACCOUNT_ADDRESS` - Adresse du compte
- `HL_API_WALLET` - Adresse du wallet API
- `HL_API_SECRET` - Cle privee du wallet API
- `PERPLEXITY_API_KEY` - Pour le sentiment analysis
- `OPENROUTER_API_KEY` - Pour Grok/Twitter sentiment

## Monitoring via Telegram

Via OpenClaw skill `coding-agent` :
```
tail -20 ~/hyperliquid-bot/trading_bot.log
tail -10 ~/hyperliquid-bot/alerts.log
```

## Features v5

- Trailing stop dynamique
- Funding rate filtering
- Orderbook analysis (murs d'ordres)
- Multi-timeframe confirmation
- Trade tracker (historique JSON)
- Strategy adapter (ajustement auto des seuils)
- Env loader (credentials securises)

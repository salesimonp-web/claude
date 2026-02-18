# Hyperliquid Trading Bot v5

Bot de trading automatise sur Hyperliquid avec strategie multi-signaux.

## Features v5

- **Multi-indicateurs** : RSI, Bollinger Bands, ADX, volume analysis
- **Multi-timeframe** : Confirmation sur plusieurs periodes
- **Trailing stop** : Protection dynamique des profits
- **Funding rates** : Filtre les trades selon le taux de funding
- **Orderbook analysis** : Detection de murs d'ordres
- **Sentiment AI** : Filtrage via Perplexity API
- **Trade tracker** : Historique complet des trades (trades_history.json)
- **Strategy adapter** : Ajustement automatique des seuils selon la performance
- **Env loader** : Credentials securises via ~/.claude-env (pas dans le repo)

## Architecture

```
bot.py              - Boucle principale, execution des trades
config.py           - Configuration (levier, assets, limites)
indicators.py       - Indicateurs techniques (RSI, BB, ADX, volume)
sentiment.py        - Analyse sentiment via Perplexity
trade_tracker.py    - Suivi et historique des trades
strategy_adapter.py - Adaptation dynamique de la strategie
env_loader.py       - Chargement securise des credentials
deploy.sh           - Deploiement automatise vers EC2
healthcheck.py      - Verification de sante du bot
```

## Setup

```bash
pip install -r requirements.txt
```

## Configuration

Modifier `config.py` pour ajuster :
- Levier (defaut: 3x tier 1, 5x tier 2+)
- Stop Loss / Take Profit (defaut: 1.5% / 3%)
- Assets trades (defaut: BTC, ETH, SOL, HYPE, CRV, DYDX, ZRO)
- Max drawdown (defaut: 25%)
- Trailing stop parameters
- Funding rate thresholds

## Lancement

```bash
python bot.py
```

## Deploiement EC2

```bash
# Deploiement automatise (rsync + restart)
./deploy.sh

# Ou manuellement
ssh -i ~/Documents/clauwdbotmax.pem ubuntu@54.197.197.104
cd ~/hyperliquid-bot
tmux attach -t trading
```

## Monitoring

```bash
# Healthcheck complet (sur EC2)
python healthcheck.py

# Logs en direct
tail -f trading_bot.log
```

## Strategie

- **Signaux** : RSI + BB + ADX + Volume + Orderbook + Funding + Multi-TF + AI
- **Score minimum** : Configurable, adapte automatiquement par strategy_adapter
- **Trailing stop** : Suit le prix et protege les gains
- **Sentiment** : Filtre les trades contre-tendance macro
- **Limite** : Max drawdown 25%, max 2 positions simultanées

## Logs

- `trading_bot.log` : toutes les operations (verbose)
- `alerts.log` : evenements critiques uniquement (trades, trailing stops, drawdown, erreurs)

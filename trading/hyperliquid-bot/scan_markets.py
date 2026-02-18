"""Deep market scan — liquidity zones, funding rates, best setups"""
import requests
import json
import time
import numpy as np
from hyperliquid.info import Info
from hyperliquid.utils import constants

from env_loader import get_key

PERPLEXITY_KEY = get_key("PERPLEXITY_API_KEY")
OPENROUTER_KEY = get_key("OPENROUTER_API_KEY")

info = Info(constants.MAINNET_API_URL, skip_ws=True)

def ask_perplexity(prompt):
    r = requests.post("https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {PERPLEXITY_KEY}", "Content-Type": "application/json"},
        json={"model": "sonar-pro", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 1000},
        timeout=60)
    return r.json()['choices'][0]['message']['content'] if r.status_code == 200 else f"Error {r.status_code}"

def ask_grok(prompt):
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        json={"model": "x-ai/grok-3", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 1000},
        timeout=60)
    return r.json()['choices'][0]['message']['content'] if r.status_code == 200 else f"Error {r.status_code}"

# 1. Scan ALL markets on Hyperliquid for funding rates + volume
print("=" * 60)
print("SCANNING HYPERLIQUID MARKETS — FUNDING RATES + VOLUME")
print("=" * 60)

meta = info.meta()
all_assets = [m['name'] for m in meta['universe']]

# Get funding rates + 24h volume for top coins
market_data = []
for asset in all_assets[:50]:  # Top 50
    try:
        candles = info.candles_snapshot(name=asset, interval="1h",
            startTime=int(time.time()*1000) - 24*3600*1000, endTime=int(time.time()*1000))
        if not candles or len(candles) < 12:
            continue

        closes = [float(c['c']) for c in candles]
        volumes = [float(c['v']) for c in candles]  # volume field

        # Calculate volatility (24h range / price)
        high_24h = max(float(c['h']) for c in candles)
        low_24h = min(float(c['l']) for c in candles)
        price = closes[-1]
        volatility = (high_24h - low_24h) / price * 100

        # RSI
        prices = np.array(closes)
        if len(prices) > 14:
            deltas = np.diff(prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_g = np.mean(gains[-14:])
            avg_l = np.mean(losses[-14:])
            rsi = 100 - (100 / (1 + avg_g/avg_l)) if avg_l > 0 else 100
        else:
            rsi = 50

        total_vol = sum(volumes)

        market_data.append({
            "asset": asset, "price": price, "rsi_1h": rsi,
            "volatility_24h": volatility, "volume_24h": total_vol,
            "high_24h": high_24h, "low_24h": low_24h,
            "change_24h": (price - closes[0]) / closes[0] * 100
        })
    except:
        continue

# Sort by volatility (most volatile = most opportunity)
market_data.sort(key=lambda x: x['volatility_24h'], reverse=True)

print(f"\nTop 20 by 24h Volatility:")
print(f"{'Asset':<8} {'Price':>10} {'RSI':>6} {'Vol%':>7} {'Chg%':>7} {'24hVol':>12}")
print("-" * 55)
for m in market_data[:20]:
    flag = ""
    if m['rsi_1h'] < 30: flag = " << OVERSOLD"
    elif m['rsi_1h'] > 70: flag = " << OVERBOUGHT"
    print(f"{m['asset']:<8} {m['price']:>10.2f} {m['rsi_1h']:>6.1f} {m['volatility_24h']:>6.1f}% {m['change_24h']:>+6.1f}% {m['volume_24h']:>12.0f}{flag}")

# Find extreme RSI
oversold = [m for m in market_data if m['rsi_1h'] < 30]
overbought = [m for m in market_data if m['rsi_1h'] > 70]

oversold_str = ", ".join(f"{m['asset']}({m['rsi_1h']:.0f})" for m in oversold)
overbought_str = ", ".join(f"{m['asset']}({m['rsi_1h']:.0f})" for m in overbought)
print(f"\nOVERSOLD (RSI < 30): [{oversold_str}]")
print(f"OVERBOUGHT (RSI > 70): [{overbought_str}]")

# 2. Institutional liquidity zones
print("\n" + "=" * 60)
print("PERPLEXITY: INSTITUTIONAL LIQUIDITY ZONES")
print("=" * 60)

top_assets = [m['asset'] for m in market_data[:10]]
r1 = ask_perplexity(f"""As of February 10 2026, give me the KEY INSTITUTIONAL LIQUIDITY ZONES for:
BTC, ETH, SOL, HYPE

For each coin provide:
1. Major support zones (where buy walls / institutional bids sit)
2. Major resistance zones (where sell walls / institutional offers sit)
3. Liquidation clusters (where leveraged positions will get liquidated)
4. Key psychological levels
5. Fair value gaps that haven't been filled

Use real orderbook data, Coinglass liquidation maps, and recent price action.
Be VERY specific with exact price levels.""")
print(r1)

# 3. Grok — what are traders actually playing right now
print("\n" + "=" * 60)
print("GROK: BEST TRADES RIGHT NOW ON CRYPTO TWITTER")
print("=" * 60)

r2 = ask_grok(f"""What are the BEST crypto trades being discussed on Twitter/X RIGHT NOW?
I need specific, actionable setups:
1. Which coins have the clearest setups? (with entry, SL, TP levels)
2. Where are the liquidation clusters on BTC and ETH?
3. Which altcoins are showing divergence or unusual strength/weakness?
4. Any coins about to break key levels?
5. What's the smart money doing (whale movements, OI changes)?

The most volatile coins on Hyperliquid right now are: {', '.join([f"{m['asset']}({m['volatility_24h']:.1f}%)" for m in market_data[:10]])}

Give me 3 concrete trade ideas with exact levels.""")
print(r2)

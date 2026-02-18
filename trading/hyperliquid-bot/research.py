"""Research best strategies using Perplexity and Grok"""
import requests
import json

from env_loader import get_key

PERPLEXITY_KEY = get_key("PERPLEXITY_API_KEY")
OPENROUTER_KEY = get_key("OPENROUTER_API_KEY")

def ask_perplexity(prompt):
    r = requests.post("https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {PERPLEXITY_KEY}", "Content-Type": "application/json"},
        json={"model": "sonar-pro", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 1500},
        timeout=60)
    if r.status_code == 200:
        return r.json()['choices'][0]['message']['content']
    return f"Error: {r.status_code} {r.text}"

def ask_grok(prompt):
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        json={"model": "x-ai/grok-2-1212", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 1500},
        timeout=60)
    if r.status_code == 200:
        return r.json()['choices'][0]['message']['content']
    return f"Error: {r.status_code} {r.text}"

# Research 1: Best micro-capital strategies
print("=" * 60)
print("PERPLEXITY: Best micro-capital crypto trading strategies")
print("=" * 60)
r1 = ask_perplexity("""I have $16 on Hyperliquid DEX perpetual futures with up to 40x leverage.
Market is very bearish (Fear Index 18), BTC at $68k, ETH at $2.1k.
What are the best automated trading strategies for micro-capital ($10-50) on crypto perps?
Consider: trend-following, scalping, grid trading, funding rate arbitrage, momentum, breakout.
Give specific parameters (timeframes, indicators, leverage, position sizing).
Focus on strategies with highest expected value for growing $16 to $100+.
Current date: February 10, 2026.""")
print(r1)

print("\n" + "=" * 60)
print("PERPLEXITY: Hyperliquid specific strategies and funding rates")
print("=" * 60)
r2 = ask_perplexity("""What are the best trading strategies specifically for Hyperliquid DEX in February 2026?
Include: current funding rates for BTC/ETH/SOL, which coins have high volatility,
any Hyperliquid-specific advantages (low fees, fast execution, specific order types).
What altcoins on Hyperliquid have the best risk/reward right now in this bearish market?
Any tokens with upcoming catalysts or high funding rate opportunities?""")
print(r2)

print("\n" + "=" * 60)
print("GROK: Twitter sentiment and trending crypto plays")
print("=" * 60)
r3 = ask_grok("""What are crypto Twitter/X traders talking about RIGHT NOW?
1. What are the most discussed trading setups and strategies?
2. Which altcoins are trending and why?
3. What's the consensus on market direction for the next 24-48h?
4. Any high-conviction plays being shared by notable traders?
5. What coins have extreme funding rates or unusual activity?
Be specific with tickers, levels, and trader names.""")
print(r3)

print("\n" + "=" * 60)
print("PERPLEXITY: Optimal bot architecture for $16 to $110")
print("=" * 60)
r4 = ask_perplexity("""Design an optimal automated trading bot strategy to grow $16 to $110 on Hyperliquid perps.
Constraints: 24/7 automated, Python bot, API-driven, bearish market environment.
The bot has access to Perplexity (real-time search) and Grok (Twitter sentiment) APIs.
Design a multi-layered strategy:
1. Macro layer: How to use AI/search for directional bias
2. Technical layer: Which indicators, timeframes, entry/exit rules
3. Risk layer: Position sizing, max drawdown, Kelly criterion
4. Adaptation layer: How to scale up as capital grows ($16->$50->$110)
Give specific, implementable parameters.""")
print(r4)

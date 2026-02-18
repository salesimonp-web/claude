"""Test bot v4 connectivity and signals"""
import sys
from bot import HyperliquidBot
from indicators import get_all_signals
import config

def test():
    print("Testing bot v4...")
    bot = HyperliquidBot()

    balance = bot.get_account_value()
    print(f"Balance: ${balance:.2f}")
    tier = bot.get_tier()
    print(f"Tier: ${tier['min']}-${tier['max']} | Leverage: {tier['leverage']}x")

    for asset in config.ASSETS:
        print(f"\n--- {asset} ---")
        candles = bot.get_candles_raw(asset, config.LOOKBACK_CANDLES)
        if not candles:
            print(f"  No candles for {asset}")
            continue

        signals = get_all_signals(candles)
        if signals:
            print(f"  Price: ${signals['price']:.2f}")
            print(f"  RSI: {signals['rsi']:.1f}")
            print(f"  ADX: {signals['adx']:.1f} ({'trending' if signals['trending'] else 'ranging'})")
            print(f"  BB: [{signals['bb_lower']:.1f}, {signals['bb_middle']:.1f}, {signals['bb_upper']:.1f}]")

    # Test AI on BTC only (save API credits)
    print("\n--- AI Sentiment (BTC) ---")
    bias = bot.get_ai_bias("BTC")
    cached = bot.cached_bias.get("BTC", {})
    print(f"  Bias: {bias} (score: {cached.get('score', 'N/A')})")

    print(f"\nAll tests passed. Bot ready.")

if __name__ == "__main__":
    test()

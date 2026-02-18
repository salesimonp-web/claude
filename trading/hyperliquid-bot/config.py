"""Configuration for Hyperliquid trading bot v7 — unified"""

from env_loader import get_key

# Hyperliquid credentials (via env_loader, never hardcoded)
ACCOUNT_ADDRESS = get_key("HL_ACCOUNT_ADDRESS", required=False)
API_WALLET = get_key("HL_API_WALLET", required=False)
API_SECRET = get_key("HL_API_SECRET", required=False)

# API keys (optional — loaded from env)
PERPLEXITY_API_KEY = get_key("PERPLEXITY_API_KEY", required=False)
OPENROUTER_API_KEY = get_key("OPENROUTER_API_KEY", required=False)
GROK_MODEL = "x-ai/grok-3"

# HIP-3 dex support — trade on both default perps and xyz (commodities)
PERP_DEXS = ['', 'xyz']

# Assets to trade — high vol + liquid + commodities (HIP-3)
ASSETS = ["BTC", "ETH", "SOL", "HYPE", "CRV", "DYDX", "ZRO", "xyz:GOLD", "xyz:SILVER"]

# Minimum order sizes (notional USD) — Hyperliquid minimum is $10
MIN_ORDER_SIZE = {
    "BTC": 10, "ETH": 10, "SOL": 10, "HYPE": 10,
    "CRV": 10, "DYDX": 10, "ZRO": 10,
    "xyz:GOLD": 10, "xyz:SILVER": 10,
}

# Extreme oversold bounce threshold (RSI on 1h)
EXTREME_RSI_THRESHOLD = 25

# Scaling tiers — adapt risk to capital
TIERS = [
    {"min": 0,  "max": 30,  "leverage": 3, "risk_pct": 0.30, "tp_pct": 0.03, "sl_pct": 0.015},
    {"min": 30, "max": 70,  "leverage": 5, "risk_pct": 0.40, "tp_pct": 0.035, "sl_pct": 0.018},
    {"min": 70, "max": 999, "leverage": 5, "risk_pct": 0.50, "tp_pct": 0.04, "sl_pct": 0.02},
]

# Technical indicators
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
ADX_PERIOD = 14
ADX_THRESHOLD = 20  # Minimum ADX to confirm trend

# Timeframes
CANDLE_INTERVAL = "15m"
CANDLE_DURATION_MS = 15 * 60 * 1000
LOOKBACK_CANDLES = 100

# Bot timing
CHECK_INTERVAL_SEC = 45  # Check every 45 seconds
SENTIMENT_CHECK_INTERVAL_MIN = 60  # Refresh AI analysis every 60min

# Risk management
MAX_DRAWDOWN_PCT = 0.25  # Pause if drawdown exceeds 25%
MAX_OPEN_POSITIONS = 3  # Max simultaneous positions (9 assets to scan)
TRAILING_STOP_ACTIVATION = 0.02  # Activate trailing after 2% profit
TRAILING_STOP_DISTANCE = 0.01  # Trail by 1%


def is_xyz_asset(asset: str) -> bool:
    """Check if asset is on xyz HIP-3 dex"""
    return asset.startswith('xyz:')


def get_dex(asset: str) -> str:
    """Get dex name for an asset"""
    if ':' in asset:
        return asset.split(':')[0]
    return ''

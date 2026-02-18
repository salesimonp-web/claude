"""Configuration for Hyperliquid trading bot v6 — liquidity + self-optimization"""

# Hyperliquid credentials
ACCOUNT_ADDRESS = "0x8f95dED300a724FEb5ab8C0D2F117891B72F755C"
API_WALLET = "0x083Ee04216C14CeFeBeA5Ce43742D6d73dD97212"
API_SECRET = "0x4a9a995f2952fc0b6466ab99d4e32fdb478dd3a27da4cd98d97a1de3d839f6e3"

# API keys (loaded from ~/.claude-env on EC2)
PERPLEXITY_API_KEY = None
OPENROUTER_API_KEY = None
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
SENTIMENT_CHECK_INTERVAL_MIN = 60  # Refresh AI analysis every 60min (was 30, save API costs)

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

"""Institutional Liquidity Zone Detection

Identifies key price levels where large liquidations cluster:
- Support/resistance from price action (swing highs/lows)
- Volume-weighted levels (where most trading happened)
- Liquidation clusters (leveraged positions likely to get stopped)
- Round numbers (psychological levels)

These zones act as magnets — price tends to sweep them before reversing.
"""

import numpy as np
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def find_swing_levels(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                      lookback: int = 5) -> Dict[str, List[float]]:
    """Find swing highs and lows (local maxima/minima)"""
    supports = []
    resistances = []

    for i in range(lookback, len(highs) - lookback):
        # Swing high: higher than N candles before and after
        if highs[i] == max(highs[i - lookback:i + lookback + 1]):
            resistances.append(float(highs[i]))
        # Swing low: lower than N candles before and after
        if lows[i] == min(lows[i - lookback:i + lookback + 1]):
            supports.append(float(lows[i]))

    return {"supports": supports, "resistances": resistances}


def find_volume_levels(closes: np.ndarray, volumes: np.ndarray,
                       num_levels: int = 5) -> List[Dict]:
    """Find price levels with highest trading volume (volume profile)"""
    if len(volumes) == 0 or volumes.sum() == 0:
        return []

    # Create price bins
    price_min, price_max = closes.min(), closes.max()
    num_bins = 20
    bins = np.linspace(price_min, price_max, num_bins + 1)

    vol_profile = []
    for i in range(num_bins):
        mask = (closes >= bins[i]) & (closes < bins[i + 1])
        vol = volumes[mask].sum() if mask.any() else 0
        mid_price = (bins[i] + bins[i + 1]) / 2
        vol_profile.append({"price": float(mid_price), "volume": float(vol)})

    # Sort by volume, return top levels
    vol_profile.sort(key=lambda x: x["volume"], reverse=True)
    return vol_profile[:num_levels]


def find_liquidation_clusters(price: float, leverage_range=(3, 20)) -> Dict[str, List[float]]:
    """Estimate where leveraged positions would get liquidated.

    Longs liquidated below entry: entry * (1 - 1/leverage)
    Shorts liquidated above entry: entry * (1 + 1/leverage)

    These clusters act as liquidity magnets.
    """
    long_liquidations = []
    short_liquidations = []

    for lev in range(leverage_range[0], leverage_range[1] + 1, 2):
        # Longs opened at current price liquidated at:
        long_liq = price * (1 - 1 / lev)
        long_liquidations.append(round(float(long_liq), 2))

        # Shorts opened at current price liquidated at:
        short_liq = price * (1 + 1 / lev)
        short_liquidations.append(round(float(short_liq), 2))

    return {
        "long_liquidations": long_liquidations,  # Below price (longs get rekt)
        "short_liquidations": short_liquidations,  # Above price (shorts get rekt)
    }


def find_round_numbers(price: float) -> Dict[str, List[float]]:
    """Find nearby psychological round number levels"""
    levels = []

    if price > 10000:  # BTC-scale
        step = 1000
    elif price > 1000:
        step = 100
    elif price > 100:
        step = 10
    elif price > 10:
        step = 5
    elif price > 1:
        step = 0.5
    else:
        step = 0.05

    # Find nearest round numbers above and below
    base = int(price / step) * step
    nearby = [base - step * 2, base - step, base, base + step, base + step * 2]

    supports = [l for l in nearby if l < price]
    resistances = [l for l in nearby if l > price]

    return {"supports": supports, "resistances": resistances}


def analyze_liquidity_zones(candles: list, current_price: float) -> Optional[Dict]:
    """Full liquidity analysis for an asset.

    Returns:
        - key_supports: price levels with buying interest
        - key_resistances: price levels with selling interest
        - nearest_support: closest support below price
        - nearest_resistance: closest resistance above price
        - liquidity_bias: 'LONG' if closer to support, 'SHORT' if closer to resistance
        - liquidation_clusters: where leveraged positions get stopped
    """
    if len(candles) < 30:
        return None

    closes = np.array([float(c['c']) for c in candles])
    highs = np.array([float(c['h']) for c in candles])
    lows = np.array([float(c['l']) for c in candles])

    # Volume: use candle range * close as proxy if no volume data
    volumes = np.array([
        float(c.get('v', 0)) or (float(c['h']) - float(c['l'])) * float(c['c'])
        for c in candles
    ])

    # 1. Swing levels from price action
    swings = find_swing_levels(highs, lows, closes, lookback=5)

    # 2. Volume-weighted levels
    vol_levels = find_volume_levels(closes, volumes, num_levels=3)

    # 3. Liquidation clusters
    liq_clusters = find_liquidation_clusters(current_price)

    # 4. Round number levels
    round_lvls = find_round_numbers(current_price)

    # Merge all supports and resistances
    all_supports = set()
    all_resistances = set()

    for s in swings["supports"]:
        if s < current_price:
            all_supports.add(round(s, 4))
    for r in swings["resistances"]:
        if r > current_price:
            all_resistances.add(round(r, 4))

    for lvl in vol_levels:
        if lvl["price"] < current_price:
            all_supports.add(round(lvl["price"], 4))
        elif lvl["price"] > current_price:
            all_resistances.add(round(lvl["price"], 4))

    for s in round_lvls["supports"]:
        all_supports.add(round(s, 4))
    for r in round_lvls["resistances"]:
        all_resistances.add(round(r, 4))

    # Sort: supports descending (nearest first), resistances ascending
    supports = sorted(all_supports, reverse=True)[:5]
    resistances = sorted(all_resistances)[:5]

    nearest_support = supports[0] if supports else current_price * 0.97
    nearest_resistance = resistances[0] if resistances else current_price * 1.03

    # Liquidity bias: which zone is price closer to?
    dist_to_support = (current_price - nearest_support) / current_price
    dist_to_resistance = (nearest_resistance - current_price) / current_price

    if dist_to_support < dist_to_resistance * 0.5:
        liq_bias = "LONG"  # Near support, likely to bounce
    elif dist_to_resistance < dist_to_support * 0.5:
        liq_bias = "SHORT"  # Near resistance, likely to reject
    else:
        liq_bias = "NEUTRAL"

    return {
        "key_supports": supports,
        "key_resistances": resistances,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "liquidity_bias": liq_bias,
        "dist_to_support_pct": round(dist_to_support * 100, 2),
        "dist_to_resistance_pct": round(dist_to_resistance * 100, 2),
        "liquidation_clusters": liq_clusters,
    }

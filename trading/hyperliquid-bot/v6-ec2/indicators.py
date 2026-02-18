"""Technical indicators: Bollinger Bands, RSI, ADX with directional movement"""

import numpy as np
from typing import Dict, Optional


def calculate_rsi(prices: np.ndarray, period: int = 14) -> float:
    """Wilder's smoothed RSI"""
    if len(prices) < period + 1:
        return 50.0

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_bollinger_bands(prices: np.ndarray, period: int = 20, std_mult: float = 2.0) -> Optional[Dict]:
    """Bollinger Bands: middle, upper, lower"""
    if len(prices) < period:
        return None

    sma = np.mean(prices[-period:])
    std = np.std(prices[-period:])

    return {
        "middle": sma,
        "upper": sma + std_mult * std,
        "lower": sma - std_mult * std,
        "width": (2 * std_mult * std) / sma if sma > 0 else 0
    }


def calculate_adx(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> Dict:
    """Average Directional Index with +DI/-DI for trend direction"""
    if len(closes) < period + 1:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0}

    # True Range
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    # Directional Movement
    up_move = highs[1:] - highs[:-1]
    down_move = lows[:-1] - lows[1:]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Wilder smoothing
    atr = np.mean(tr[:period])
    plus_di_smooth = np.mean(plus_dm[:period])
    minus_di_smooth = np.mean(minus_dm[:period])

    dx_values = []
    last_plus_di = 0.0
    last_minus_di = 0.0

    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + tr[i]) / period
        plus_di_smooth = (plus_di_smooth * (period - 1) + plus_dm[i]) / period
        minus_di_smooth = (minus_di_smooth * (period - 1) + minus_dm[i]) / period

        if atr == 0:
            continue

        last_plus_di = 100 * plus_di_smooth / atr
        last_minus_di = 100 * minus_di_smooth / atr

        di_sum = last_plus_di + last_minus_di
        if di_sum == 0:
            continue

        dx = 100 * abs(last_plus_di - last_minus_di) / di_sum
        dx_values.append(dx)

    if not dx_values:
        return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0}

    adx = np.mean(dx_values[-period:]) if len(dx_values) >= period else np.mean(dx_values)
    return {
        "adx": float(adx),
        "plus_di": float(last_plus_di),
        "minus_di": float(last_minus_di),
    }


def get_all_signals(candles: list, bb_period=20, bb_std=2.0, rsi_period=14, adx_period=14) -> Optional[Dict]:
    """Compute all indicators from raw candle data"""
    if len(candles) < max(bb_period, rsi_period, adx_period) + 5:
        return None

    closes = np.array([float(c['c']) for c in candles])
    highs = np.array([float(c['h']) for c in candles])
    lows = np.array([float(c['l']) for c in candles])

    price = closes[-1]
    rsi = calculate_rsi(closes, rsi_period)
    bb = calculate_bollinger_bands(closes, bb_period, bb_std)
    adx_data = calculate_adx(highs, lows, closes, adx_period)

    if bb is None:
        return None

    # Momentum: price vs SMA5
    sma5 = float(np.mean(closes[-5:])) if len(closes) >= 5 else price

    return {
        "price": price,
        "rsi": rsi,
        "bb_upper": bb["upper"],
        "bb_middle": bb["middle"],
        "bb_lower": bb["lower"],
        "bb_width": bb["width"],
        "adx": adx_data["adx"],
        "plus_di": adx_data["plus_di"],
        "minus_di": adx_data["minus_di"],
        "sma5": sma5,
        # Derived signals
        "above_upper_bb": price > bb["upper"],
        "below_lower_bb": price < bb["lower"],
        "rsi_overbought": rsi > 65,     # Relaxed from 70
        "rsi_oversold": rsi < 35,       # Relaxed from 30
        "trending": adx_data["adx"] > 20,
        "trend_bullish": adx_data["plus_di"] > adx_data["minus_di"],
        "trend_bearish": adx_data["minus_di"] > adx_data["plus_di"],
        "momentum_bullish": price > sma5,
        "momentum_bearish": price < sma5,
    }

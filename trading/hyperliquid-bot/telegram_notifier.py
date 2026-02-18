"""Telegram notification module for the Hyperliquid trading bot."""
import logging
import urllib.request
import urllib.parse
import json

from env_loader import get_key

logger = logging.getLogger(__name__)

_BOT_TOKEN = None
_CHAT_ID = None
_PERPLEXITY_KEY = None


def _get_config():
    global _BOT_TOKEN, _CHAT_ID
    if _BOT_TOKEN is None:
        _BOT_TOKEN = get_key("TELEGRAM_BOT_TOKEN")
        _CHAT_ID = get_key("TELEGRAM_CHAT_ID")
    return _BOT_TOKEN, _CHAT_ID


def _get_perplexity_key():
    global _PERPLEXITY_KEY
    if _PERPLEXITY_KEY is None:
        _PERPLEXITY_KEY = get_key("PERPLEXITY_API_KEY", required=False) or ""
    return _PERPLEXITY_KEY


def _generate_trade_comment(asset, direction, entry_price, signals, context="open"):
    """Generate a short trade explanation via Perplexity Sonar (cheap & fast)."""
    key = _get_perplexity_key()
    if not key:
        return ""
    try:
        sig_summary = ""
        if isinstance(signals, dict):
            parts = []
            if signals.get("rsi_oversold"):
                parts.append("RSI oversold")
            if signals.get("rsi_overbought"):
                parts.append("RSI overbought")
            if signals.get("below_lower_bb"):
                parts.append("below Bollinger Band")
            if signals.get("above_upper_bb"):
                parts.append("above Bollinger Band")
            if signals.get("trending"):
                parts.append("strong trend (ADX)")
            if signals.get("momentum_bullish"):
                parts.append("bullish momentum")
            if signals.get("momentum_bearish"):
                parts.append("bearish momentum")
            if signals.get("volume_confirmed"):
                parts.append("high volume")
            ai = signals.get("ai_bias", "")
            if ai:
                parts.append(f"AI sentiment: {ai}")
            sig_summary = ", ".join(parts)

        prompt = (
            f"In 1 short sentence (max 15 words, no intro), explain why a "
            f"{direction} trade on {asset} at ${entry_price:,.2f} makes sense. "
            f"Signals: {sig_summary or 'mixed'}. Be concise, trading jargon OK."
        )

        payload = json.dumps({
            "model": "sonar",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 50,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.perplexity.ai/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.debug("Trade comment generation failed", exc_info=True)
        return ""


def send_message(text):
    """Send a text message via Telegram Bot API (HTML parse mode)."""
    try:
        token, chat_id = _get_config()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        logger.exception("Telegram send_message failed")
        return None


def notify_trade_open(asset, direction, size, entry_price, leverage, score, signals):
    """Notify when a new trade is opened."""
    if direction == "LONG":
        arrow = "\U0001f7e2 \u2b06\ufe0f"
    else:
        arrow = "\U0001f534 \u2b07\ufe0f"

    sig_parts = []
    if isinstance(signals, dict):
        for key, label in [
            ("below_lower_bb", "BB Low"), ("above_upper_bb", "BB High"),
            ("rsi_oversold", "RSI Oversold"), ("rsi_overbought", "RSI Overbought"),
            ("trending", "Trend ADX"), ("momentum_bullish", "Momentum \u2191"),
            ("momentum_bearish", "Momentum \u2193"),
        ]:
            if signals.get(key):
                sig_parts.append(f"\u2705 {label}")
        if signals.get("volume_confirmed"):
            sig_parts.append("\U0001f4a5 Volume OK")
        ai = signals.get("ai_bias", "")
        if ai:
            sig_parts.append(f"\U0001f916 AI: {ai}")
    elif isinstance(signals, list):
        sig_parts = signals

    sig_str = "\n".join(f"  {s}" for s in sig_parts) if sig_parts else "  \u2014"

    comment = _generate_trade_comment(asset, direction, entry_price, signals)
    comment_line = f"\n\n\U0001f4ac <i>{comment}</i>" if comment else ""

    text = (
        f"{arrow} <b>NEW {direction} {asset}</b>\n"
        f"\n"
        f"\U0001f4b2 Entry: <b>${entry_price:,.2f}</b>\n"
        f"\u2696\ufe0f Leverage: {leverage}x\n"
        f"\U0001f4e6 Size: {size}\n"
        f"\U0001f3af Score: {score}/8\n"
        f"\n"
        f"\U0001f9e0 <b>Signals:</b>\n"
        f"{sig_str}"
        f"{comment_line}"
    )
    return send_message(text)


def notify_trade_close(asset, direction, entry_price, exit_price, pnl, pnl_pct, reason):
    """Notify when a trade is closed."""
    if pnl >= 0:
        header = "\U0001f389 <b>WIN</b>"
        pnl_emoji = "\U0001f4b0"
    else:
        header = "\U0001f614 <b>LOSS</b>"
        pnl_emoji = "\U0001f4b8"

    sign = "+" if pnl >= 0 else ""

    reason_labels = {
        "trailing_stop": "\U0001f6e1\ufe0f Trailing stop kicked in \u2014 profit secured after retracement",
        "tp": "\U0001f3c6 Target reached \u2014 take profit hit",
        "sl": "\U0001f6d1 Stop loss triggered \u2014 risk contained",
        "liquidation": "\U0001f4a3 Position liquidated \u2014 margin insufficient",
        "manual": "\u270b Manually closed",
        "regime_change": "\U0001f300 Market regime shifted \u2014 position no longer aligned",
        "timeout": "\u23f0 Max hold time reached \u2014 closing stale position",
        "drawdown": "\u26a0\ufe0f Drawdown limit hit \u2014 capital protection",
    }
    reason_text = reason_labels.get(reason, f"\U0001f504 {reason}")

    move_pct = ((exit_price - entry_price) / entry_price) * 100

    text = (
        f"{header} \u2014 CLOSE {direction} {asset}\n"
        f"\n"
        f"\U0001f4cd Entry: ${entry_price:,.2f}\n"
        f"\U0001f3c1 Exit: ${exit_price:,.2f} ({'+' if move_pct >= 0 else ''}{move_pct:.2f}%)\n"
        f"\n"
        f"{pnl_emoji} <b>PnL: {sign}${pnl:.2f} ({sign}{pnl_pct:.1f}%)</b>\n"
        f"\n"
        f"{reason_text}"
    )
    return send_message(text)


def notify_status(balance, positions, regime, win_rate=None):
    """Send periodic status summary."""
    regime_labels = {
        "STRONG_BULL": "\U0001f680 Strong Bull",
        "MILD_BULL": "\U0001f4c8 Mild Bull",
        "RANGING": "\u2194\ufe0f Ranging",
        "MILD_BEAR": "\U0001f4c9 Mild Bear",
        "STRONG_BEAR": "\u2744\ufe0f Strong Bear",
    }
    regime_str = regime_labels.get(regime, f"\U0001f50d {regime}")

    text = (
        f"\U0001f4ca <b>BOT STATUS</b>\n"
        f"\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"\n"
        f"\U0001f4b0 Balance: <b>${balance:.2f}</b>\n"
        f"\U0001f4c1 Positions: {positions}\n"
        f"\U0001f30d Regime: {regime_str}\n"
    )
    if win_rate is not None:
        wr_emoji = "\U0001f525" if win_rate >= 60 else "\u2705" if win_rate >= 50 else "\u26a0\ufe0f"
        text += f"{wr_emoji} Win rate: {win_rate:.0f}%\n"
    text += f"\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
    return send_message(text)


def notify_alert(message):
    """Send a critical alert."""
    text = (
        f"\U0001f6a8\U0001f6a8\U0001f6a8 <b>ALERT</b>\n"
        f"\n"
        f"{message}"
    )
    return send_message(text)

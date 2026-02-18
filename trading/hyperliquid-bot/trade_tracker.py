"""Trade tracking and performance analytics for Hyperliquid bot"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class TradeTracker:
    def __init__(self, filepath="trades_history.json"):
        self.filepath = filepath
        self.trades: List[Dict] = []
        self._load()

    def log_entry(self, asset: str, direction: str, size: float,
                  entry_price: float, signals_snapshot: Dict, leverage: int):
        """Log the opening of a trade with all signals at entry."""
        trade = {
            "id": f"{asset}_{int(time.time() * 1000)}",
            "asset": asset,
            "direction": direction,  # "LONG" or "SHORT"
            "size": size,
            "entry_price": entry_price,
            "entry_time": datetime.now().isoformat(),
            "signals": signals_snapshot,
            "leverage": leverage,
            "status": "open",
            "exit_price": None,
            "exit_time": None,
            "exit_reason": None,
            "pnl": None,
            "pnl_pct": None
        }
        self.trades.append(trade)
        self._save()
        logger.info(
            f"[TRACKER] Logged ENTRY: {direction} {size} {asset} "
            f"@ ${entry_price:.2f} (lev {leverage}x)"
        )
        return trade["id"]

    def log_exit(self, asset: str, exit_price: float, exit_reason: str):
        """Log the closing of a trade. Calculates PnL."""
        trade = self._find_open_trade(asset)
        if not trade:
            logger.warning(f"[TRACKER] No open trade found for {asset}")
            return None

        direction_mult = 1.0 if trade["direction"] == "LONG" else -1.0
        pnl = (exit_price - trade["entry_price"]) * trade["size"] * direction_mult

        # PnL% relative to margin used
        margin = trade["entry_price"] * trade["size"] / trade["leverage"]
        pnl_pct = (pnl / margin) * 100 if margin > 0 else 0.0

        trade["exit_price"] = exit_price
        trade["exit_time"] = datetime.now().isoformat()
        trade["exit_reason"] = exit_reason
        trade["pnl"] = round(pnl, 4)
        trade["pnl_pct"] = round(pnl_pct, 2)
        trade["status"] = "closed"

        self._save()
        logger.info(
            f"[TRACKER] Logged EXIT: {trade['direction']} {asset} "
            f"@ ${exit_price:.2f} | PnL: ${pnl:+.4f} ({pnl_pct:+.2f}%) "
            f"| Reason: {exit_reason}"
        )
        return trade

    def detect_closed_trades(self, info, account_address: str,
                             current_positions: List[Dict]):
        """Detect trades closed between bot cycles.

        Compares open trades in history with current positions.
        If a trade is open in history but not in current positions,
        uses user_fills_by_time to find exit price and reason.
        """
        current_coins = {p['coin'] for p in current_positions}
        open_trades = [t for t in self.trades if t["status"] == "open"]

        for trade in open_trades:
            if trade["asset"] not in current_coins:
                # Trade was closed externally (SL/TP hit)
                exit_price, exit_reason = self._resolve_exit(
                    info, account_address, trade
                )
                if exit_price is not None:
                    self.log_exit(trade["asset"], exit_price, exit_reason)
                else:
                    # Fallback: mark closed with unknown details
                    logger.warning(
                        f"[TRACKER] Could not resolve exit for {trade['asset']}, "
                        f"marking as closed with unknown exit"
                    )
                    self.log_exit(trade["asset"], trade["entry_price"], "unknown")

    def _resolve_exit(self, info, account_address: str,
                      trade: Dict) -> tuple:
        """Use fills API to find exit price and determine reason."""
        try:
            entry_time = datetime.fromisoformat(trade["entry_time"])
            start_ms = int(entry_time.timestamp() * 1000)
            end_ms = int(time.time() * 1000)

            fills = info.user_fills_by_time(account_address, start_ms, end_ms)

            # Filter fills for this asset, after entry
            asset_fills = [
                f for f in fills
                if f.get('coin') == trade["asset"]
            ]

            if not asset_fills:
                return None, None

            # The last fill on this asset is the exit
            last_fill = asset_fills[-1]
            exit_price = float(last_fill.get('px', 0))

            # Determine exit reason by comparing with expected SL/TP
            exit_reason = self._determine_exit_reason(trade, exit_price)

            return exit_price, exit_reason

        except Exception as e:
            logger.error(f"[TRACKER] Error resolving exit for {trade['asset']}: {e}")
            return None, None

    def _determine_exit_reason(self, trade: Dict, exit_price: float) -> str:
        """Determine why a trade was closed based on exit price vs SL/TP levels."""
        signals = trade.get("signals", {})
        entry = trade["entry_price"]
        direction = trade["direction"]

        # Try to infer SL/TP from config tiers
        # Use a tolerance of 0.5% for matching
        import config
        tier = None
        for t in config.TIERS:
            if t["min"] <= entry * trade["size"] / trade["leverage"] < t["max"]:
                tier = t
                break
        if not tier:
            tier = config.TIERS[0]

        if direction == "LONG":
            expected_sl = entry * (1 - tier["sl_pct"])
            expected_tp = entry * (1 + tier["tp_pct"])
        else:
            expected_sl = entry * (1 + tier["sl_pct"])
            expected_tp = entry * (1 - tier["tp_pct"])

        tolerance = 0.005  # 0.5% tolerance

        if abs(exit_price - expected_tp) / entry < tolerance:
            return "tp"
        elif abs(exit_price - expected_sl) / entry < tolerance:
            return "sl"
        elif direction == "LONG" and exit_price < entry:
            return "sl"
        elif direction == "SHORT" and exit_price > entry:
            return "sl"
        else:
            return "tp"

    def get_recent_trades(self, n: int = 20) -> List[Dict]:
        """Return the n most recent closed trades."""
        closed = [t for t in self.trades if t["status"] == "closed"]
        return closed[-n:]

    def get_open_trades(self) -> List[Dict]:
        """Return all currently open trades."""
        return [t for t in self.trades if t["status"] == "open"]

    def get_stats(self, last_n: Optional[int] = None) -> Dict:
        """Performance statistics.

        Returns:
            Dict with total_trades, wins, losses, win_rate, total_pnl,
            avg_win, avg_loss, profit_factor, best_trade, worst_trade,
            per_asset stats, per_signal analysis.
        """
        closed = [t for t in self.trades if t["status"] == "closed"]
        if last_n:
            closed = closed[-last_n:]

        if not closed:
            return {
                "total_trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "total_pnl": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0,
                "profit_factor": 0.0,
                "best_trade": None, "worst_trade": None,
                "per_asset": {}, "per_signal": {}
            }

        wins = [t for t in closed if t["pnl"] and t["pnl"] > 0]
        losses = [t for t in closed if t["pnl"] and t["pnl"] <= 0]

        total_pnl = sum(t["pnl"] for t in closed if t["pnl"])
        total_wins_pnl = sum(t["pnl"] for t in wins)
        total_losses_pnl = abs(sum(t["pnl"] for t in losses)) if losses else 0

        win_rate = (len(wins) / len(closed)) * 100 if closed else 0
        avg_win = total_wins_pnl / len(wins) if wins else 0
        avg_loss = total_losses_pnl / len(losses) if losses else 0
        profit_factor = total_wins_pnl / total_losses_pnl if total_losses_pnl > 0 else float('inf')

        best = max(closed, key=lambda t: t["pnl"] or 0)
        worst = min(closed, key=lambda t: t["pnl"] or 0)

        # Per-asset breakdown
        per_asset = {}
        for t in closed:
            asset = t["asset"]
            if asset not in per_asset:
                per_asset[asset] = {"trades": 0, "wins": 0, "pnl": 0.0}
            per_asset[asset]["trades"] += 1
            if t["pnl"] and t["pnl"] > 0:
                per_asset[asset]["wins"] += 1
            per_asset[asset]["pnl"] += t["pnl"] or 0

        for asset in per_asset:
            s = per_asset[asset]
            s["win_rate"] = (s["wins"] / s["trades"]) * 100 if s["trades"] > 0 else 0
            s["pnl"] = round(s["pnl"], 4)

        # Per-signal analysis: which signals correlate with wins
        per_signal = self._analyze_signals(closed)

        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "profit_factor": round(profit_factor, 2),
            "best_trade": {
                "asset": best["asset"], "pnl": best["pnl"],
                "pnl_pct": best["pnl_pct"], "direction": best["direction"]
            },
            "worst_trade": {
                "asset": worst["asset"], "pnl": worst["pnl"],
                "pnl_pct": worst["pnl_pct"], "direction": worst["direction"]
            },
            "per_asset": per_asset,
            "per_signal": per_signal
        }

    def _analyze_signals(self, closed_trades: List[Dict]) -> Dict:
        """Analyze which signals correlate with winning trades."""
        signal_keys = [
            "below_lower_bb", "above_upper_bb",
            "rsi_oversold", "rsi_overbought",
            "trending"
        ]
        # Also check for custom keys like ai_bias, funding, etc.
        all_signal_keys = set()
        for t in closed_trades:
            if t.get("signals"):
                all_signal_keys.update(t["signals"].keys())

        # Focus on boolean-like signals
        result = {}
        for key in signal_keys:
            active_trades = [
                t for t in closed_trades
                if t.get("signals", {}).get(key) is True
            ]
            if not active_trades:
                continue
            wins = sum(1 for t in active_trades if t["pnl"] and t["pnl"] > 0)
            result[key] = {
                "times_active": len(active_trades),
                "wins": wins,
                "win_rate": round((wins / len(active_trades)) * 100, 1) if active_trades else 0
            }

        # Check ai_bias signal separately (string value)
        ai_active = [
            t for t in closed_trades
            if t.get("signals", {}).get("ai_bias") in ("LONG", "SHORT")
            and t.get("signals", {}).get("ai_bias") == t.get("direction")
        ]
        if ai_active:
            wins = sum(1 for t in ai_active if t["pnl"] and t["pnl"] > 0)
            result["ai_bias_aligned"] = {
                "times_active": len(ai_active),
                "wins": wins,
                "win_rate": round((wins / len(ai_active)) * 100, 1)
            }

        return result

    def _find_open_trade(self, asset: str) -> Optional[Dict]:
        """Find the most recent open trade for an asset."""
        for trade in reversed(self.trades):
            if trade["asset"] == asset and trade["status"] == "open":
                return trade
        return None

    def _save(self):
        """Save to trades_history.json"""
        try:
            with open(self.filepath, 'w') as f:
                json.dump(self.trades, f, indent=2)
        except Exception as e:
            logger.error(f"[TRACKER] Save error: {e}")

    def _load(self):
        """Load from trades_history.json"""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    self.trades = json.load(f)
                logger.info(
                    f"[TRACKER] Loaded {len(self.trades)} trades from {self.filepath}"
                )
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"[TRACKER] Load error: {e}")
                self.trades = []
        else:
            self.trades = []

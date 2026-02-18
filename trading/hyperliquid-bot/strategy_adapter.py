"""Strategy adaptation engine — learns from trade history to adjust parameters"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Default signal weights
DEFAULT_WEIGHTS = {
    "bb": 1.0,
    "rsi": 1.0,
    "adx": 1.0,
    "ai_bias": 1.0,
    "funding": 1.0,
    "volume": 1.0,
    "orderbook": 1.0,
    "multi_tf_1h": 1.0,
    "multi_tf_4h": 1.0
}

# Mapping from trade signal keys to weight keys
SIGNAL_TO_WEIGHT = {
    "below_lower_bb": "bb",
    "above_upper_bb": "bb",
    "rsi_oversold": "rsi",
    "rsi_overbought": "rsi",
    "trending": "adx",
    "ai_bias_aligned": "ai_bias",
}

# Adaptation thresholds
MIN_TRADES_FOR_ADAPT = 20
ADAPT_INTERVAL_HOURS = 6
MIN_WEIGHT = 0.5
MAX_WEIGHT = 2.0
MIN_TRADES_FOR_BLOCK = 5
BLOCK_WIN_RATE_THRESHOLD = 30
BLOCK_COOLDOWN_HOURS = 24


class StrategyAdapter:
    def __init__(self, tracker, state_file="strategy_state.json"):
        self.tracker = tracker
        self.state_file = state_file
        self.state = self._default_state()
        self._load()

    def _default_state(self) -> Dict:
        return {
            "signal_weights": dict(DEFAULT_WEIGHTS),
            "min_score_threshold": 2,
            "blocked_assets": [],  # [{"asset": str, "blocked_at": iso, "reason": str}]
            "last_adaptation": None,
            "adaptation_count": 0,
            "trades_at_last_adapt": 0,
            "adaptation_log": []  # Last 10 adaptation summaries
        }

    def should_adapt(self) -> bool:
        """Return True if we should run adaptation.

        Triggers:
        - 20+ new trades since last adaptation, OR
        - 6+ hours since last adaptation (if we have any closed trades)
        """
        stats = self.tracker.get_stats()
        total = stats["total_trades"]

        # Need at least some trades
        if total < 5:
            return False

        # Check trade count threshold
        trades_since = total - self.state["trades_at_last_adapt"]
        if trades_since >= MIN_TRADES_FOR_ADAPT:
            return True

        # Check time threshold
        if self.state["last_adaptation"]:
            last = datetime.fromisoformat(self.state["last_adaptation"])
            if datetime.now() - last > timedelta(hours=ADAPT_INTERVAL_HOURS):
                return trades_since > 0  # Only if there are new trades
        else:
            # Never adapted before, adapt if we have enough trades
            return total >= MIN_TRADES_FOR_BLOCK

        return False

    def adapt(self):
        """Main adaptation loop.

        1. Get stats from recent trades
        2. Adjust score threshold based on global win rate
        3. Adjust signal weights based on per-signal performance
        4. Block/unblock assets based on per-asset performance
        5. Log all changes
        """
        stats = self.tracker.get_stats(last_n=MIN_TRADES_FOR_ADAPT)
        changes = []

        if stats["total_trades"] < MIN_TRADES_FOR_BLOCK:
            logger.info("[ADAPTER] Not enough trades for adaptation")
            return

        # 1. Adjust score threshold based on global win rate
        old_threshold = self.state["min_score_threshold"]
        if stats["win_rate"] < 40:
            self.state["min_score_threshold"] = min(old_threshold + 1, 4)
            if self.state["min_score_threshold"] != old_threshold:
                changes.append(
                    f"Score threshold {old_threshold} -> {self.state['min_score_threshold']} "
                    f"(win rate {stats['win_rate']}% too low)"
                )
        elif stats["win_rate"] > 65:
            self.state["min_score_threshold"] = max(old_threshold - 1, 2)
            if self.state["min_score_threshold"] != old_threshold:
                changes.append(
                    f"Score threshold {old_threshold} -> {self.state['min_score_threshold']} "
                    f"(win rate {stats['win_rate']}% strong)"
                )

        # 2. Adjust signal weights based on per-signal performance
        per_signal = stats.get("per_signal", {})
        for signal_key, signal_stats in per_signal.items():
            weight_key = SIGNAL_TO_WEIGHT.get(signal_key)
            if not weight_key:
                continue
            if signal_stats["times_active"] < 3:
                continue  # Not enough data

            old_weight = self.state["signal_weights"].get(weight_key, 1.0)
            new_weight = old_weight

            if signal_stats["win_rate"] < 35:
                new_weight = max(old_weight * 0.7, MIN_WEIGHT)
            elif signal_stats["win_rate"] > 65:
                new_weight = min(old_weight * 1.3, MAX_WEIGHT)

            if new_weight != old_weight:
                self.state["signal_weights"][weight_key] = round(new_weight, 2)
                changes.append(
                    f"Weight '{weight_key}': {old_weight:.2f} -> {new_weight:.2f} "
                    f"(signal WR={signal_stats['win_rate']}%)"
                )

        # 3. Manage blocked assets
        per_asset = stats.get("per_asset", {})
        for asset, asset_stats in per_asset.items():
            if (asset_stats["trades"] >= MIN_TRADES_FOR_BLOCK
                    and asset_stats["win_rate"] < BLOCK_WIN_RATE_THRESHOLD):
                if not self._is_blocked(asset):
                    self.state["blocked_assets"].append({
                        "asset": asset,
                        "blocked_at": datetime.now().isoformat(),
                        "reason": f"WR={asset_stats['win_rate']}% on {asset_stats['trades']} trades"
                    })
                    changes.append(
                        f"BLOCKED {asset} (WR={asset_stats['win_rate']}% "
                        f"on {asset_stats['trades']} trades)"
                    )

        # 4. Unblock assets after cooldown period
        still_blocked = []
        for blocked in self.state["blocked_assets"]:
            blocked_at = datetime.fromisoformat(blocked["blocked_at"])
            if datetime.now() - blocked_at > timedelta(hours=BLOCK_COOLDOWN_HOURS):
                changes.append(
                    f"UNBLOCKED {blocked['asset']} (cooldown expired, second chance)"
                )
            else:
                still_blocked.append(blocked)
        self.state["blocked_assets"] = still_blocked

        # 5. Record adaptation
        self.state["last_adaptation"] = datetime.now().isoformat()
        self.state["adaptation_count"] += 1
        self.state["trades_at_last_adapt"] = stats["total_trades"]

        adaptation_summary = {
            "timestamp": datetime.now().isoformat(),
            "trades_analyzed": stats["total_trades"],
            "win_rate": stats["win_rate"],
            "total_pnl": stats["total_pnl"],
            "changes": changes
        }
        self.state["adaptation_log"].append(adaptation_summary)
        # Keep only last 10 logs
        self.state["adaptation_log"] = self.state["adaptation_log"][-10:]

        self._save()

        if changes:
            logger.info(f"[ADAPTER] Adaptation #{self.state['adaptation_count']}:")
            for c in changes:
                logger.info(f"  -> {c}")
        else:
            logger.info(
                f"[ADAPTER] Adaptation #{self.state['adaptation_count']}: "
                f"no changes needed (WR={stats['win_rate']}%)"
            )

    def get_score_threshold(self) -> int:
        """Return the current dynamic score threshold (2-4)."""
        return self.state["min_score_threshold"]

    def get_signal_weight(self, signal_name: str) -> float:
        """Return the weight for a signal (0.5 - 2.0)."""
        return self.state["signal_weights"].get(signal_name, 1.0)

    def is_asset_blocked(self, asset: str) -> bool:
        """Check if an asset is temporarily blocked."""
        return self._is_blocked(asset)

    def get_report(self) -> str:
        """Periodic report (every 6h).

        Returns a formatted string with:
        - Trade count, win rate, total PnL
        - Current signal weights
        - Blocked assets
        - Recent changes
        """
        stats = self.tracker.get_stats()
        lines = [
            "=" * 50,
            "STRATEGY ADAPTER REPORT",
            "=" * 50,
            f"Total trades: {stats['total_trades']} | "
            f"Wins: {stats['wins']} | Losses: {stats['losses']}",
            f"Win rate: {stats['win_rate']}% | "
            f"Total PnL: ${stats['total_pnl']:+.4f}",
            f"Profit factor: {stats['profit_factor']}",
            f"Avg win: ${stats['avg_win']:+.4f} | "
            f"Avg loss: ${stats['avg_loss']:.4f}",
            "",
            f"Score threshold: {self.state['min_score_threshold']}",
            "Signal weights:"
        ]

        for signal, weight in sorted(self.state["signal_weights"].items()):
            marker = ""
            if weight < 0.8:
                marker = " (weakened)"
            elif weight > 1.2:
                marker = " (boosted)"
            lines.append(f"  {signal}: {weight:.2f}{marker}")

        if self.state["blocked_assets"]:
            lines.append("")
            lines.append("Blocked assets:")
            for b in self.state["blocked_assets"]:
                lines.append(f"  {b['asset']} — {b['reason']} (since {b['blocked_at'][:16]})")
        else:
            lines.append("")
            lines.append("No blocked assets")

        lines.append("")
        lines.append(f"Adaptations: {self.state['adaptation_count']}")

        # Last adaptation changes
        if self.state["adaptation_log"]:
            last = self.state["adaptation_log"][-1]
            if last["changes"]:
                lines.append(f"Last changes ({last['timestamp'][:16]}):")
                for c in last["changes"]:
                    lines.append(f"  -> {c}")

        if stats.get("best_trade"):
            lines.append("")
            bt = stats["best_trade"]
            wt = stats["worst_trade"]
            lines.append(
                f"Best trade: {bt['direction']} {bt['asset']} "
                f"${bt['pnl']:+.4f} ({bt['pnl_pct']:+.1f}%)"
            )
            lines.append(
                f"Worst trade: {wt['direction']} {wt['asset']} "
                f"${wt['pnl']:+.4f} ({wt['pnl_pct']:+.1f}%)"
            )

        # Per-asset breakdown
        if stats.get("per_asset"):
            lines.append("")
            lines.append("Per-asset performance:")
            for asset, a_stats in sorted(stats["per_asset"].items()):
                lines.append(
                    f"  {asset}: {a_stats['trades']} trades, "
                    f"WR={a_stats['win_rate']:.0f}%, PnL=${a_stats['pnl']:+.4f}"
                )

        lines.append("=" * 50)
        return "\n".join(lines)

    def _is_blocked(self, asset: str) -> bool:
        """Internal check for blocked assets."""
        return any(b["asset"] == asset for b in self.state["blocked_assets"])

    def _save(self):
        """Save state to strategy_state.json"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"[ADAPTER] Save error: {e}")

    def _load(self):
        """Load state from strategy_state.json"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    saved = json.load(f)
                # Merge with defaults (in case new keys were added)
                for key, value in self._default_state().items():
                    if key not in saved:
                        saved[key] = value
                # Merge signal weights with defaults
                for sig, weight in DEFAULT_WEIGHTS.items():
                    if sig not in saved.get("signal_weights", {}):
                        saved["signal_weights"][sig] = weight
                self.state = saved
                logger.info(
                    f"[ADAPTER] Loaded state: threshold={self.state['min_score_threshold']}, "
                    f"adaptations={self.state['adaptation_count']}"
                )
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"[ADAPTER] Load error: {e}, using defaults")
                self.state = self._default_state()
        else:
            logger.info("[ADAPTER] No saved state, using defaults")

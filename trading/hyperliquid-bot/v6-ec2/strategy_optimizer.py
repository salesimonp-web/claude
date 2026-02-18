"""Strategy Self-Improvement Loop

Every 5 hours:
1. Analyze recent trade performance (win rate, avg PnL, best/worst assets)
2. Query Perplexity for market regime changes
3. Adjust parameters dynamically (SL/TP, scoring weights, asset selection)
4. Log all changes for review
"""

import json
import logging
import os
import time
import requests
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

OPTIMIZER_STATE_FILE = "optimizer_state.json"
TRADE_LOG_FILE = "trade_history.json"


class StrategyOptimizer:
    def __init__(self, perplexity_key: str = None):
        self.perplexity_key = perplexity_key
        self.state = self._load_state()
        self.trade_history = self._load_trades()

    def _load_state(self) -> Dict:
        if os.path.exists(OPTIMIZER_STATE_FILE):
            with open(OPTIMIZER_STATE_FILE, 'r') as f:
                return json.load(f)
        return {
            "last_optimization": None,
            "optimization_count": 0,
            "current_regime": "unknown",
            "parameter_history": [],
            "performance_snapshots": [],
        }

    def _save_state(self):
        with open(OPTIMIZER_STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)

    def _load_trades(self) -> List[Dict]:
        if os.path.exists(TRADE_LOG_FILE):
            with open(TRADE_LOG_FILE, 'r') as f:
                return json.load(f)
        return []

    def _save_trades(self):
        with open(TRADE_LOG_FILE, 'w') as f:
            json.dump(self.trade_history, f, indent=2, default=str)

    def log_trade(self, asset: str, direction: str, entry_price: float,
                  size: float, notional: float):
        """Log a trade entry for performance tracking"""
        trade = {
            "id": len(self.trade_history) + 1,
            "timestamp": datetime.now().isoformat(),
            "asset": asset,
            "direction": direction,
            "entry_price": entry_price,
            "size": size,
            "notional": notional,
            "exit_price": None,
            "pnl": None,
            "status": "open",
        }
        self.trade_history.append(trade)
        self._save_trades()
        return trade["id"]

    def close_trade(self, asset: str, exit_price: float, pnl: float):
        """Record trade exit"""
        for trade in reversed(self.trade_history):
            if trade["asset"] == asset and trade["status"] == "open":
                trade["exit_price"] = exit_price
                trade["pnl"] = pnl
                trade["status"] = "closed"
                trade["closed_at"] = datetime.now().isoformat()
                self._save_trades()
                return
        # If no matching open trade, log anyway
        self.trade_history.append({
            "timestamp": datetime.now().isoformat(),
            "asset": asset,
            "exit_price": exit_price,
            "pnl": pnl,
            "status": "closed",
        })
        self._save_trades()

    def get_performance_stats(self) -> Dict:
        """Analyze recent trading performance"""
        closed = [t for t in self.trade_history if t.get("status") == "closed" and t.get("pnl") is not None]

        if not closed:
            return {"trades": 0, "message": "No closed trades yet"}

        wins = [t for t in closed if t["pnl"] > 0]
        losses = [t for t in closed if t["pnl"] <= 0]

        total_pnl = sum(t["pnl"] for t in closed)
        win_rate = len(wins) / len(closed) if closed else 0

        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0

        # Per-asset breakdown
        asset_stats = {}
        for t in closed:
            a = t.get("asset", "?")
            if a not in asset_stats:
                asset_stats[a] = {"trades": 0, "pnl": 0, "wins": 0}
            asset_stats[a]["trades"] += 1
            asset_stats[a]["pnl"] += t["pnl"]
            if t["pnl"] > 0:
                asset_stats[a]["wins"] += 1

        return {
            "trades": len(closed),
            "win_rate": round(win_rate * 100, 1),
            "total_pnl": round(total_pnl, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "best_asset": max(asset_stats, key=lambda a: asset_stats[a]["pnl"]) if asset_stats else None,
            "worst_asset": min(asset_stats, key=lambda a: asset_stats[a]["pnl"]) if asset_stats else None,
            "asset_stats": asset_stats,
        }

    def query_market_regime(self) -> Optional[Dict]:
        """Ask Perplexity about current market regime"""
        if not self.perplexity_key:
            return None

        try:
            today = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
            prompt = (
                f"Date: {today}. Analyze the CURRENT crypto market regime. "
                f"Is it: trending (bull/bear), ranging, or volatile/choppy? "
                f"Key factors: BTC dominance trend, total market cap direction, "
                f"Fear & Greed Index, funding rates, major upcoming catalysts (CPI, FOMC, etc). "
                f"What is the OPTIMAL trading strategy right now? "
                f"Should a bot focus on: trend-following shorts, mean-reversion longs, "
                f"or stay flat? Give specific actionable advice. "
                f"SCORE the market from -1.0 (extreme bear, short everything) to +1.0 (extreme bull, long everything). "
                f"Format last line as: REGIME_SCORE: [number]"
            )

            r = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.perplexity_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "sonar-pro",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 600
                },
                timeout=60
            )

            if r.status_code == 200:
                analysis = r.json()['choices'][0]['message']['content']
                logger.info(f"Market regime analysis: {analysis[:300]}...")

                # Extract regime score
                import re
                score = 0.0
                for line in analysis.split('\n'):
                    match = re.search(r'regime.?score[:\s]+([+-]?\d+\.?\d*)', line, re.IGNORECASE)
                    if match:
                        score = max(-1.0, min(1.0, float(match.group(1))))
                        break

                # Determine regime
                if score <= -0.5:
                    regime = "STRONG_BEAR"
                elif score <= -0.2:
                    regime = "MILD_BEAR"
                elif score >= 0.5:
                    regime = "STRONG_BULL"
                elif score >= 0.2:
                    regime = "MILD_BULL"
                else:
                    regime = "RANGING"

                return {
                    "regime": regime,
                    "score": score,
                    "analysis": analysis,
                }
            return None

        except Exception as e:
            logger.error(f"Regime query failed: {e}")
            return None

    def optimize(self, current_config: Dict) -> Dict:
        """Main optimization loop — returns parameter adjustments"""
        logger.info("=" * 50)
        logger.info("STRATEGY OPTIMIZATION CYCLE")
        logger.info("=" * 50)

        adjustments = {}

        # 1. Performance analysis
        stats = self.get_performance_stats()
        logger.info(f"Performance: {stats}")

        # 2. Market regime check
        regime_data = self.query_market_regime()
        if regime_data:
            old_regime = self.state.get("current_regime", "unknown")
            new_regime = regime_data["regime"]
            self.state["current_regime"] = new_regime

            if old_regime != new_regime:
                logger.info(f"REGIME CHANGE: {old_regime} -> {new_regime}")

            # 3. Adjust parameters based on regime
            if new_regime == "STRONG_BEAR":
                adjustments = {
                    "bias": "Favor shorts, tighten long SL",
                    "sl_adjust": 0.8,   # Tighter SL on longs
                    "tp_adjust": 1.2,   # Wider TP on shorts
                    "long_threshold": 3, # Need 3 points for longs (harder)
                    "short_threshold": 2, # 2 points for shorts (easier)
                }
            elif new_regime == "STRONG_BULL":
                adjustments = {
                    "bias": "Favor longs, tighten short SL",
                    "sl_adjust": 1.2,
                    "tp_adjust": 0.8,
                    "long_threshold": 2,
                    "short_threshold": 3,
                }
            elif new_regime == "RANGING":
                adjustments = {
                    "bias": "Mean-reversion, tighter SL/TP",
                    "sl_adjust": 0.8,
                    "tp_adjust": 0.8,
                    "long_threshold": 2,
                    "short_threshold": 2,
                }
            else:  # MILD_BEAR or MILD_BULL
                adjustments = {
                    "bias": f"Slight {new_regime.split('_')[1].lower()} bias",
                    "sl_adjust": 1.0,
                    "tp_adjust": 1.0,
                    "long_threshold": 2,
                    "short_threshold": 2,
                }

            logger.info(f"Regime: {new_regime} (score: {regime_data['score']:.2f})")
            logger.info(f"Adjustments: {adjustments}")

        # 4. Asset performance pruning
        if stats.get("trades", 0) >= 5:
            worst = stats.get("worst_asset")
            if worst and stats["asset_stats"][worst]["pnl"] < -1.0:
                adjustments["remove_asset"] = worst
                logger.info(f"Suggesting removal of underperforming asset: {worst}")

        # 5. Log snapshot
        self.state["performance_snapshots"].append({
            "timestamp": datetime.now().isoformat(),
            "stats": stats,
            "regime": self.state.get("current_regime"),
            "adjustments": adjustments,
        })
        # Keep last 50 snapshots
        self.state["performance_snapshots"] = self.state["performance_snapshots"][-50:]

        self.state["last_optimization"] = datetime.now().isoformat()
        self.state["optimization_count"] = self.state.get("optimization_count", 0) + 1
        self._save_state()

        logger.info(f"Optimization #{self.state['optimization_count']} complete")
        return adjustments

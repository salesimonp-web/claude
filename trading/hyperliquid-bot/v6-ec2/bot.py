"""Hyperliquid Trading Bot v6 — AI + Liquidity Zones + Self-Optimization + HIP-3 Commodities"""

import time
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from eth_account import Account
import config
from sentiment import SentimentAnalyzer
from indicators import get_all_signals
from liquidity import analyze_liquidity_zones
from strategy_optimizer import StrategyOptimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class HyperliquidBot:
    def __init__(self):
        # Load API keys from ~/.claude-env
        env_path = os.path.expanduser("~/.claude-env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        value = value.strip('"').strip("'")
                        if key == "PERPLEXITY_API_KEY":
                            config.PERPLEXITY_API_KEY = value
                        elif key == "OPENROUTER_API_KEY":
                            config.OPENROUTER_API_KEY = value

        self.account = Account.from_key(config.API_SECRET)
        # Initialize SDK with multi-dex support (default perps + xyz HIP-3)
        self.info = Info(
            constants.MAINNET_API_URL,
            skip_ws=True,
            perp_dexs=config.PERP_DEXS
        )
        self.exchange = Exchange(
            self.account,
            constants.MAINNET_API_URL,
            account_address=config.ACCOUNT_ADDRESS,
            perp_dexs=config.PERP_DEXS
        )

        # Fetch asset metadata (szDecimals for proper size rounding)
        self.sz_decimals = {}
        self.max_leverage = {}
        try:
            # Load default perp metadata
            meta = self.info.meta()
            for a in meta["universe"]:
                self.sz_decimals[a["name"]] = a["szDecimals"]
                self.max_leverage[a["name"]] = a.get("maxLeverage", 10)

            # Load HIP-3 xyz dex metadata
            meta_xyz = self.info.meta(dex="xyz")
            for a in meta_xyz["universe"]:
                self.sz_decimals[a["name"]] = a["szDecimals"]
                self.max_leverage[a["name"]] = a.get("maxLeverage", 10)

            logger.info("Loaded metadata for %d assets (incl. HIP-3)", len(self.sz_decimals))
        except Exception as e:
            logger.error("Failed to load metadata: %s", e)

        self.initial_balance = self.get_account_value()
        self.peak_balance = self.initial_balance
        self.session_start = datetime.now()
        self.paused = False

        # AI sentiment
        self.sentiment_analyzer = SentimentAnalyzer()
        self.cached_bias = {}

        # Strategy optimizer (self-improvement loop)
        self.optimizer = StrategyOptimizer(perplexity_key=config.PERPLEXITY_API_KEY)
        self.last_optimization = None
        self.regime_adjustments = {}

        # Track open trade IDs for optimizer
        self.open_trade_ids = {}
        self.last_known_positions = set()

        # Clean start: cancel any orphaned orders on both dexes
        self._cancel_all_orders()

        logger.info("Bot v6 initialized — liquidity zones + self-optimization + HIP-3 commodities")

    def _cancel_all_orders(self):
        """Cancel all open orders at startup for clean state (both dexes)"""
        for dex in config.PERP_DEXS:
            try:
                dex_label = dex if dex else "default"
                orders = self.info.open_orders(config.ACCOUNT_ADDRESS, dex=dex)
                if not orders:
                    continue
                coins = set(o.get("coin", "") for o in orders)
                for coin in coins:
                    coin_oids = [o["oid"] for o in orders if o.get("coin") == coin]
                    cancels = [{"coin": coin, "oid": oid} for oid in coin_oids]
                    self.exchange.bulk_cancel(cancels)
                logger.info("Startup cleanup [%s]: cancelled %d orphaned orders", dex_label, len(orders))
            except Exception as e:
                logger.warning("Order cleanup failed [%s]: %s", dex if dex else "default", e)

    def get_tier(self) -> Dict:
        balance = self.get_account_value()
        for tier in config.TIERS:
            if tier["min"] <= balance < tier["max"]:
                return tier
        return config.TIERS[-1]

    def setup_leverage(self):
        tier = self.get_tier()
        for asset in config.ASSETS:
            try:
                lev = min(tier["leverage"], self.max_leverage.get(asset, 5))
                # HIP-3 xyz assets are isolated-only (no cross margin)
                is_cross = not config.is_xyz_asset(asset)
                self.exchange.update_leverage(lev, asset, is_cross=is_cross)
                mode = "isolated" if not is_cross else "cross"
                logger.info("Leverage %dx (%s) set for %s", lev, mode, asset)
            except Exception as e:
                logger.warning("Leverage set failed for %s: %s", asset, e)

    def get_account_value(self) -> float:
        """Get total account value across all dexes"""
        total = 0.0
        for dex in config.PERP_DEXS:
            try:
                state = self.info.user_state(config.ACCOUNT_ADDRESS, dex=dex)
                total += float(state["marginSummary"]["accountValue"])
            except Exception as e:
                logger.error("Error getting account value [%s]: %s", dex if dex else "default", e)
        return total

    def _get_dex_balance(self, dex: str) -> Dict:
        """Get balance details for a specific dex"""
        try:
            state = self.info.user_state(config.ACCOUNT_ADDRESS, dex=dex)
            ms = state["marginSummary"]
            return {
                "accountValue": float(ms["accountValue"]),
                "totalMarginUsed": float(ms["totalMarginUsed"]),
                "withdrawable": float(state.get("withdrawable", 0)),
            }
        except Exception as e:
            logger.error("Error getting dex balance [%s]: %s", dex, e)
            return {"accountValue": 0, "totalMarginUsed": 0, "withdrawable": 0}

    def _transfer_to_xyz(self, amount: float) -> bool:
        """Transfer USDC from default dex to xyz dex for HIP-3 trading"""
        try:
            bal = self._get_dex_balance("")
            available = bal["withdrawable"]
            if available < amount:
                logger.warning(
                    "Not enough withdrawable to transfer: need $%.2f, have $%.2f",
                    amount, available
                )
                return False

            result = self.exchange.send_asset(
                destination=config.ACCOUNT_ADDRESS,
                source_dex="",
                destination_dex="xyz",
                token="USDC",
                amount=round(amount, 2)
            )
            logger.info("Transferred $%.2f to xyz dex: %s", amount, result)
            time.sleep(2)
            return True
        except Exception as e:
            logger.error("Transfer to xyz failed: %s", e)
            return False

    def _transfer_from_xyz(self, amount: float) -> bool:
        """Transfer USDC from xyz dex back to default dex"""
        try:
            bal = self._get_dex_balance("xyz")
            available = bal["withdrawable"]
            if available < 0.01:
                return False

            transfer_amount = min(amount, available)
            result = self.exchange.send_asset(
                destination=config.ACCOUNT_ADDRESS,
                source_dex="xyz",
                destination_dex="",
                token="USDC",
                amount=round(transfer_amount, 2)
            )
            logger.info("Transferred $%.2f from xyz dex back: %s", transfer_amount, result)
            time.sleep(2)
            return True
        except Exception as e:
            logger.error("Transfer from xyz failed: %s", e)
            return False

    def get_open_positions(self) -> List[Dict]:
        """Get open positions across all dexes"""
        positions = []
        for dex in config.PERP_DEXS:
            try:
                state = self.info.user_state(config.ACCOUNT_ADDRESS, dex=dex)
                for pos in state.get("assetPositions", []):
                    p = pos["position"]
                    if abs(float(p.get("szi", 0))) > 0:
                        positions.append(p)
            except Exception as e:
                logger.error("Error getting positions [%s]: %s", dex if dex else "default", e)
        return positions

    def get_candles_raw(self, asset: str, num_candles: int = 100, interval: str = None) -> Optional[list]:
        try:
            intv = interval or config.CANDLE_INTERVAL
            dur_ms = {"1m": 60000, "5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000}.get(intv, 900000)
            now_ms = int(time.time() * 1000)
            candles = self.info.candles_snapshot(
                name=asset,
                interval=intv,
                startTime=now_ms - (num_candles * dur_ms),
                endTime=now_ms
            )
            return candles if candles else None
        except Exception as e:
            logger.error("Error fetching candles for %s: %s", asset, e)
            return None

    def get_ai_bias(self, asset: str) -> Dict:
        now = datetime.now()
        # For AI analysis, use base asset name (strip xyz: prefix)
        ai_asset = asset.split(":")[-1] if ":" in asset else asset
        cached = self.cached_bias.get(asset)

        if cached:
            age = (now - cached["timestamp"]).total_seconds() / 60
            if age < config.SENTIMENT_CHECK_INTERVAL_MIN:
                return {"bias": cached["bias"], "score": cached["score"]}

        try:
            result = self.sentiment_analyzer.get_combined_bias(ai_asset)
            self.cached_bias[asset] = {
                "bias": result["bias"],
                "score": result["score"],
                "timestamp": now
            }
            return {"bias": result["bias"], "score": result["score"]}
        except Exception as e:
            logger.error("AI bias error for %s: %s", asset, e)
            if cached:
                return {"bias": cached["bias"], "score": cached["score"]}
            return {"bias": "NEUTRAL", "score": 0.0}

    def check_entry(self, asset: str) -> Optional[str]:
        """Scoring system v3 — 6 sources including liquidity zones, need 2+ to trade"""
        candles = self.get_candles_raw(asset, config.LOOKBACK_CANDLES)
        if not candles:
            return None

        signals = get_all_signals(
            candles,
            bb_period=config.BB_PERIOD,
            bb_std=config.BB_STD,
            rsi_period=config.RSI_PERIOD,
            adx_period=config.ADX_PERIOD
        )
        if not signals:
            return None

        price = signals["price"]

        # Liquidity zone analysis (use 1h candles for broader picture)
        candles_1h = self.get_candles_raw(asset, 100, interval="1h")
        liq_zones = None
        if candles_1h:
            liq_zones = analyze_liquidity_zones(candles_1h, price)

        liq_info = ""
        if liq_zones:
            liq_info = (
                " LIQ[S=%.4f(%.2f%%) R=%.4f(%.2f%%) bias=%s]" % (
                    liq_zones["nearest_support"], liq_zones["dist_to_support_pct"],
                    liq_zones["nearest_resistance"], liq_zones["dist_to_resistance_pct"],
                    liq_zones["liquidity_bias"]
                )
            )

        logger.info(
            "%s | $%.4f RSI=%.1f ADX=%.1f +DI=%.1f -DI=%.1f BB=[%.4f, %.4f]%s",
            asset, price, signals["rsi"],
            signals["adx"], signals["plus_di"], signals["minus_di"],
            signals["bb_lower"], signals["bb_upper"], liq_info
        )

        # === EXTREME OVERSOLD BOUNCE (1h macro check) ===
        if candles_1h:
            signals_1h = get_all_signals(candles_1h)
            if signals_1h and signals_1h["rsi"] < config.EXTREME_RSI_THRESHOLD:
                logger.info(
                    "EXTREME OVERSOLD on %s: 1h RSI=%.1f, 15m RSI=%.1f — LONG bounce play",
                    asset, signals_1h["rsi"], signals["rsi"]
                )
                return "LONG"

        if signals["rsi"] < config.EXTREME_RSI_THRESHOLD:
            logger.info("EXTREME OVERSOLD on %s: 15m RSI=%.1f — LONG bounce play", asset, signals["rsi"])
            return "LONG"

        # === SCORING SYSTEM v3: 6 sources ===
        long_score = 0
        short_score = 0

        # 1. Bollinger Band position
        if signals["below_lower_bb"]:
            long_score += 1
        if signals["above_upper_bb"]:
            short_score += 1

        # 2. RSI levels (35/65)
        if signals["rsi_oversold"]:
            long_score += 1
        if signals["rsi_overbought"]:
            short_score += 1

        # 3. ADX trend + directional movement (+DI/-DI)
        if signals["trending"]:
            if signals["trend_bullish"]:
                long_score += 1
            elif signals["trend_bearish"]:
                short_score += 1

        # 4. AI directional bias (Perplexity)
        ai_result = self.get_ai_bias(asset)
        ai_bias = ai_result["bias"]
        if ai_bias == "LONG":
            long_score += 1
        elif ai_bias == "SHORT":
            short_score += 1

        # 5. Momentum (price vs SMA5)
        if signals["momentum_bullish"]:
            long_score += 1
        elif signals["momentum_bearish"]:
            short_score += 1

        # 6. Liquidity zone bias
        if liq_zones:
            if liq_zones["liquidity_bias"] == "LONG":
                long_score += 1
            elif liq_zones["liquidity_bias"] == "SHORT":
                short_score += 1

        if long_score > 0 or short_score > 0:
            logger.info(
                "%s scores: LONG=%d SHORT=%d | AI=%s(%.2f) trend=%s mom=%s liq=%s",
                asset, long_score, short_score,
                ai_bias, ai_result["score"],
                "BULL" if signals.get("trend_bullish") else "BEAR" if signals.get("trend_bearish") else "FLAT",
                "UP" if signals["momentum_bullish"] else "DOWN",
                liq_zones["liquidity_bias"] if liq_zones else "N/A"
            )

        # Dynamic thresholds from optimizer
        long_thresh = self.regime_adjustments.get("long_threshold", 2)
        short_thresh = self.regime_adjustments.get("short_threshold", 2)

        if long_score >= long_thresh and long_score > short_score:
            logger.info("LONG SIGNAL on %s (score=%d, threshold=%d)", asset, long_score, long_thresh)
            return "LONG"
        if short_score >= short_thresh and short_score > long_score:
            logger.info("SHORT SIGNAL on %s (score=%d, threshold=%d)", asset, short_score, short_thresh)
            return "SHORT"

        return None

    def round_size(self, asset: str, size: float) -> float:
        """Round size to asset szDecimals"""
        decimals = self.sz_decimals.get(asset, 2)
        return round(size, decimals)

    def round_price(self, price: float) -> float:
        """Round price based on its magnitude"""
        if price > 1000:
            return float(int(price))
        elif price > 10:
            return round(float(price), 2)
        elif price > 1:
            return round(float(price), 3)
        else:
            return round(float(price), 4)

    def calculate_position_size(self, asset: str, price: float) -> float:
        tier = self.get_tier()
        balance = self.get_account_value()
        lev = min(tier["leverage"], self.max_leverage.get(asset, 5))

        notional = balance * tier["risk_pct"] * lev
        max_notional = balance * lev * 0.6
        notional = min(notional, max_notional)

        if notional < 10:
            logger.warning("%s: notional $%.2f < $10 minimum", asset, notional)
            return 0

        size = notional / price
        size = self.round_size(asset, size)

        if size * price < 10:
            return 0

        return size

    def place_trade(self, asset: str, direction: str):
        """Execute trade with SL/TP — handles auto-transfer for xyz dex assets"""
        tier = self.get_tier()
        candles = self.get_candles_raw(asset, 5)
        if not candles:
            return

        price = float(candles[-1]["c"])
        size = self.calculate_position_size(asset, price)
        if size <= 0:
            logger.warning("Position too small for %s", asset)
            return

        # For xyz HIP-3 assets, auto-transfer funds to xyz dex
        if config.is_xyz_asset(asset):
            lev = min(tier["leverage"], self.max_leverage.get(asset, 5))
            notional = size * price
            margin_needed = (notional / lev) + 1.0
            xyz_bal = self._get_dex_balance("xyz")
            if xyz_bal["withdrawable"] < margin_needed:
                transfer_amount = margin_needed - xyz_bal["accountValue"] + 0.50
                logger.info(
                    "xyz dex needs $%.2f margin for %s, transferring $%.2f",
                    margin_needed, asset, transfer_amount
                )
                if not self._transfer_to_xyz(transfer_amount):
                    logger.warning("Cannot trade %s: insufficient funds for xyz transfer", asset)
                    return

        is_buy = (direction == "LONG")
        tp_pct = tier["tp_pct"]
        sl_pct = tier["sl_pct"]

        if is_buy:
            sl_price = self.round_price(price * (1 - sl_pct))
            tp_price = self.round_price(price * (1 + tp_pct))
        else:
            sl_price = self.round_price(price * (1 + sl_pct))
            tp_price = self.round_price(price * (1 - tp_pct))

        lev = min(tier["leverage"], self.max_leverage.get(asset, 5))
        balance = self.get_account_value()
        notional = size * price
        logger.info("=" * 50)
        logger.info(
            "TRADE: %s %s %s @ $%.4f (notional $%.2f, leverage %dx)",
            direction, size, asset, price, notional, lev
        )
        logger.info("SL: $%s (%.1f%%) | TP: $%s (%.1f%%)", sl_price, sl_pct*100, tp_price, tp_pct*100)
        logger.info("Balance: $%.2f | Tier: $%d-$%d", balance, tier["min"], tier["max"])
        logger.info("=" * 50)

        try:
            result = self.exchange.market_open(asset, is_buy, size)
            logger.info("Order result: %s", result)

            order_ok = False
            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and isinstance(statuses[0], dict):
                    if "error" in statuses[0]:
                        logger.error("Order REJECTED: %s", statuses[0]["error"])
                        if config.is_xyz_asset(asset):
                            self._transfer_from_xyz(999)
                        return
                    elif "filled" in statuses[0] or "resting" in statuses[0]:
                        order_ok = True
                elif statuses and isinstance(statuses[0], str) and statuses[0] == "success":
                    order_ok = True

            if not order_ok:
                logger.error("Order did not fill — skipping SL/TP")
                if config.is_xyz_asset(asset):
                    self._transfer_from_xyz(999)
                return

            logger.info("Order FILLED — placing SL/TP")
            trade_id = self.optimizer.log_trade(asset, direction, price, size, notional)
            self.open_trade_ids[asset] = trade_id
            time.sleep(1)

            # Stop loss
            sl_r = self.exchange.order(
                asset, not is_buy, size, sl_price,
                {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}}
            )
            logger.info("SL placed: %s", sl_r)

            time.sleep(1)

            # Take profit
            tp_r = self.exchange.order(
                asset, not is_buy, size, tp_price,
                {"trigger": {"triggerPx": tp_price, "isMarket": True, "tpsl": "tp"}}
            )
            logger.info("TP placed: %s", tp_r)

        except Exception as e:
            logger.error("Trade execution error: %s", e)

    def check_drawdown(self):
        balance = self.get_account_value()
        if balance > self.peak_balance:
            self.peak_balance = balance

        if self.peak_balance > 0:
            drawdown = (self.peak_balance - balance) / self.peak_balance
            if drawdown > config.MAX_DRAWDOWN_PCT:
                if not self.paused:
                    logger.warning(
                        "MAX DRAWDOWN %.1f%% — PAUSING BOT (peak $%.2f, now $%.2f)",
                        drawdown*100, self.peak_balance, balance
                    )
                    self.paused = True
            elif self.paused and drawdown < config.MAX_DRAWDOWN_PCT * 0.5:
                logger.info("Drawdown recovered — resuming trading")
                self.paused = False

    def track_closed_positions(self, current_positions: List[Dict]):
        """Detect when positions close and log the result + reclaim xyz funds"""
        current_coins = set(p["coin"] for p in current_positions)
        previously_open = self.last_known_positions

        for coin in previously_open - current_coins:
            if coin in self.open_trade_ids:
                self.optimizer.close_trade(coin, 0, 0)
                logger.info("Position %s CLOSED — logged for optimizer", coin)
                del self.open_trade_ids[coin]

            # If xyz position closed, transfer funds back to default dex
            if config.is_xyz_asset(coin):
                xyz_still_open = any(config.is_xyz_asset(c) for c in current_coins)
                if not xyz_still_open:
                    logger.info("No more xyz positions — transferring funds back")
                    self._transfer_from_xyz(999)

        self.last_known_positions = current_coins

    def run_optimization(self):
        """Run strategy self-improvement if due (every 5 hours)"""
        now = datetime.now()
        if self.last_optimization:
            hours_since = (now - self.last_optimization).total_seconds() / 3600
            if hours_since < 5:
                return

        logger.info("Running strategy optimization...")
        current_config = {
            "assets": config.ASSETS,
            "tiers": config.TIERS,
            "sl_pct": self.get_tier()["sl_pct"],
            "tp_pct": self.get_tier()["tp_pct"],
        }
        adjustments = self.optimizer.optimize(current_config)

        if adjustments:
            self.regime_adjustments = adjustments
            regime = self.optimizer.state.get("current_regime", "unknown")
            logger.info("Regime: %s | Adjustments applied: %s", regime, adjustments.get("bias", "none"))

        self.last_optimization = now

    def run(self):
        self.setup_leverage()

        # Run initial optimization
        self.run_optimization()

        balance = self.get_account_value()
        tier = self.get_tier()
        regime = self.optimizer.state.get("current_regime", "unknown")
        logger.info("=" * 60)
        logger.info("HYPERLIQUID BOT v6 — LIQUIDITY + SELF-OPTIMIZATION + HIP-3")
        logger.info("=" * 60)
        logger.info("Balance: $%.2f | Target: $110", balance)
        logger.info("Tier: $%d-$%d | Leverage: %dx", tier["min"], tier["max"], tier["leverage"])
        logger.info("Assets: %s", ", ".join(config.ASSETS))
        sz_info = ", ".join(
            "%s=%s" % (a, self.sz_decimals.get(a, "?")) for a in config.ASSETS
        )
        logger.info("szDecimals: %s", sz_info)
        logger.info("Strategy: BB+RSI+ADX(DI)+Momentum+AI+LiquidityZones (6 sources)")
        logger.info("Regime: %s | Optimization: every 5h", regime)
        logger.info("AI cache: %dmin | Check: every %ds", config.SENTIMENT_CHECK_INTERVAL_MIN, config.CHECK_INTERVAL_SEC)
        logger.info("SL: %.1f%% | TP: %.1f%% | Max DD: %.0f%%", tier["sl_pct"]*100, tier["tp_pct"]*100, config.MAX_DRAWDOWN_PCT*100)
        logger.info("HIP-3 dexes: %s | Auto-transfer: enabled", config.PERP_DEXS)
        logger.info("=" * 60)

        while True:
            try:
                self.check_drawdown()

                if self.paused:
                    logger.info("Bot paused (drawdown limit). Waiting...")
                    time.sleep(300)
                    continue

                # Periodic optimization (every 5h)
                self.run_optimization()

                open_positions = self.get_open_positions()
                open_coins = [p["coin"] for p in open_positions]

                # Track closed positions for optimizer + xyz fund recovery
                self.track_closed_positions(open_positions)

                if len(open_positions) >= config.MAX_OPEN_POSITIONS:
                    balance = self.get_account_value()
                    logger.info(
                        "Max positions (%d): %s | Balance: $%.2f",
                        len(open_positions), ", ".join(open_coins), balance
                    )
                    time.sleep(config.CHECK_INTERVAL_SEC)
                    continue

                for asset in config.ASSETS:
                    if asset in open_coins:
                        continue
                    if len(open_positions) >= config.MAX_OPEN_POSITIONS:
                        break

                    direction = self.check_entry(asset)
                    if direction:
                        self.place_trade(asset, direction)
                        open_positions = self.get_open_positions()
                        open_coins = [p["coin"] for p in open_positions]

                balance = self.get_account_value()
                pnl = balance - self.initial_balance
                progress = (balance / 110) * 100
                logger.info(
                    "Balance: $%.2f | PnL: $%+.2f | Positions: %d | Progress: %.1f%%/110$",
                    balance, pnl, len(open_positions), progress
                )

                time.sleep(config.CHECK_INTERVAL_SEC)

            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error("Main loop error: %s", e)
                time.sleep(30)


if __name__ == "__main__":
    bot = HyperliquidBot()
    bot.run()

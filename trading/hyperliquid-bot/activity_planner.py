"""Activity Planner — generates human-like daily on-chain activity schedules.

Produces a randomized daily plan of DeFi actions (swaps, transfers, LP ops)
designed to look organic and avoid Sybil detection patterns.

Features:
- 2-5 actions per day, random hours within ACTIVE_HOURS
- Gaussian delays between actions (mean ~4h, sigma ~2h)
- No repeat action types back-to-back
- Varied micro-amounts ($0.10 to $0.50)
- 50% weekend reduction
- Budget spread over FARMING_DURATION_DAYS
- Persistent schedule via farm_schedule.json
"""

import json
import logging
import os
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import farmer_config

logger = logging.getLogger(__name__)

# Action types for mainnet farming
ACTION_TYPES = [
    "swap_eth_to_token",
    "swap_token_to_eth",
    "self_transfer",
    "lp_add",
]

# Token rotation for swaps (Base chain)
SWAP_TOKENS = ["USDC", "DAI"]

# Conservative ETH price for micro-amount calculations
ETH_PRICE_USD = 2700.0


def _parse_dt(s):
    """Parse an ISO datetime string — handles both naive and tz-aware."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Python < 3.11 can struggle with +00:00 / Z
        s_clean = s.replace("Z", "+00:00")
        if s_clean.endswith("+00:00"):
            dt = datetime.fromisoformat(s_clean.replace("+00:00", ""))
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s_clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class ActivityPlanner:
    """Generates and manages daily activity schedules."""

    def __init__(self):
        self.schedule_file = farmer_config.FARM_SCHEDULE_FILE
        self.schedule = self._load_schedule()

    # --- Persistence ---

    def _load_schedule(self) -> Dict:
        if os.path.exists(self.schedule_file):
            try:
                with open(self.schedule_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"date": None, "actions": [], "history": []}

    def _save_schedule(self):
        with open(self.schedule_file, "w") as f:
            json.dump(self.schedule, f, indent=2, default=str)

    # --- Public API ---

    def get_daily_plan(
        self,
        date: Optional[datetime] = None,
        budget_remaining: Optional[float] = None,
    ) -> List[Dict]:
        """Return today's plan (generate if needed)."""
        if date is None:
            date = datetime.now(timezone.utc)
        date_str = date.strftime("%Y-%m-%d")

        # Return existing plan if same day
        if self.schedule.get("date") == date_str:
            return self.schedule["actions"]

        if budget_remaining is None:
            budget_remaining = farmer_config.TOTAL_GAS_BUDGET_USD * (
                1 - farmer_config.RESERVE_PCT
            )

        actions = self._generate_plan(date, budget_remaining)

        # Archive previous day (keep 7 days)
        if self.schedule.get("actions"):
            self.schedule.setdefault("history", []).append(
                {"date": self.schedule.get("date"), "actions": self.schedule["actions"]}
            )
            self.schedule["history"] = self.schedule["history"][-7:]

        self.schedule["date"] = date_str
        self.schedule["actions"] = actions
        self._save_schedule()

        logger.info("Generated %d actions for %s", len(actions), date_str)
        return actions

    def mark_action_done(
        self, action_id: str, tx_hash: Optional[str] = None, error: Optional[str] = None
    ):
        """Mark an action as completed or failed."""
        for action in self.schedule.get("actions", []):
            if action["id"] == action_id:
                action["status"] = "done" if not error else "failed"
                action["tx_hash"] = tx_hash
                action["error"] = error
                action["executed_at"] = datetime.now(timezone.utc).isoformat()
                break
        self._save_schedule()

    def get_pending_actions(self) -> List[Dict]:
        """Return actions that are pending and past their scheduled time."""
        now = datetime.now(timezone.utc)
        pending = []
        for action in self.schedule.get("actions", []):
            if action["status"] != "pending":
                continue
            scheduled = _parse_dt(action["time_utc"])
            if scheduled and now >= scheduled:
                pending.append(action)
        return pending

    def get_next_action_time(self) -> Optional[datetime]:
        """Return the time of the next pending action (or None)."""
        soonest = None
        for action in self.schedule.get("actions", []):
            if action["status"] != "pending":
                continue
            scheduled = _parse_dt(action["time_utc"])
            if scheduled and (soonest is None or scheduled < soonest):
                soonest = scheduled
        return soonest

    def get_stats(self) -> Dict:
        """Return summary statistics for today's schedule."""
        actions = self.schedule.get("actions", [])
        return {
            "date": self.schedule.get("date"),
            "total": len(actions),
            "pending": sum(1 for a in actions if a["status"] == "pending"),
            "done": sum(1 for a in actions if a["status"] == "done"),
            "failed": sum(1 for a in actions if a["status"] == "failed"),
        }

    # --- Internal generation ---

    def _generate_plan(self, date: datetime, budget_remaining: float) -> List[Dict]:
        """Generate a randomized daily plan."""
        is_weekend = date.weekday() >= 5
        max_actions = farmer_config.DAILY_MAX_ACTIONS
        if is_weekend:
            max_actions = max(1, int(max_actions * farmer_config.WEEKEND_REDUCTION))

        # Daily gas budget: remaining / days left
        start_date = datetime(2026, 2, 15, tzinfo=timezone.utc)
        days_elapsed = max(0, (date - start_date).days)
        days_left = max(1, farmer_config.FARMING_DURATION_DAYS - days_elapsed)
        daily_gas_budget = budget_remaining / days_left

        avg_cost = farmer_config.CHAINS["base"]["avg_gas_cost"]
        affordable = int(daily_gas_budget / avg_cost) if avg_cost > 0 else max_actions
        num_actions = random.randint(2, min(max_actions, max(2, affordable)))

        # Generate times (only in the future if we're mid-day)
        start_h, end_h = farmer_config.ACTIVE_HOURS
        now_hour = date.hour + date.minute / 60.0
        effective_start = max(start_h, now_hour + 0.5)  # at least 30 min from now
        if effective_start >= end_h - 1:
            # Too late in the day — schedule 1-2 actions for remaining time
            num_actions = min(num_actions, 2)
            effective_start = min(now_hour + 0.25, end_h - 0.5)

        times = self._generate_times(date, num_actions, effective_start, end_h)

        # Build action sequence (no back-to-back repeats)
        actions = []
        last_type = None
        token_idx = 0

        for i, action_time in enumerate(times):
            available = [t for t in ACTION_TYPES if t != last_type]
            action_type = random.choice(available)
            last_type = action_type

            params = self._generate_params(action_type, token_idx)
            if action_type in ("swap_eth_to_token", "swap_token_to_eth"):
                token_idx = (token_idx + 1) % len(SWAP_TOKENS)

            actions.append(
                {
                    "id": f"a{i+1}_{date.strftime('%m%d')}",
                    "time_utc": action_time.isoformat(),
                    "action_type": action_type,
                    "chain": "base",
                    "params": params,
                    "status": "pending",
                }
            )

        return actions

    def _generate_times(
        self, date: datetime, count: int, start_h: float, end_h: int
    ) -> List[datetime]:
        """Generate *count* action times with Gaussian spacing between start_h and end_h."""
        if count <= 0 or start_h >= end_h:
            return []

        total_hours = end_h - start_h
        mean_gap = total_hours / (count + 1)
        times: List[datetime] = []
        current_h = start_h

        for _ in range(count):
            gap = max(0.5, random.gauss(mean_gap, mean_gap / 2))
            current_h += gap
            if current_h >= end_h:
                current_h = end_h - random.uniform(0.1, 0.5)

            hour = int(current_h)
            minute = int((current_h - hour) * 60)
            second = random.randint(0, 59)

            base_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            action_time = base_day + timedelta(hours=hour, minutes=minute, seconds=second)
            times.append(action_time)

        times.sort()
        return times

    def _generate_params(self, action_type: str, token_idx: int) -> Dict:
        """Generate randomized parameters for an action."""
        amount_usd = random.uniform(farmer_config.MIN_ACTION_USD, farmer_config.MAX_ACTION_USD)
        amount_eth = round(amount_usd / ETH_PRICE_USD, 8)

        tokens = farmer_config.TOKENS.get("base", {})
        token_name = SWAP_TOKENS[token_idx % len(SWAP_TOKENS)]
        token_address = tokens.get(token_name, tokens.get("USDC"))

        if action_type == "swap_eth_to_token":
            return {
                "token_out": token_address,
                "token_name": token_name,
                "amount_eth": amount_eth,
            }
        elif action_type == "swap_token_to_eth":
            return {
                "token_in": token_address,
                "token_name": token_name,
            }
        elif action_type == "self_transfer":
            return {"amount_eth": amount_eth}
        elif action_type == "lp_add":
            return {
                "token": token_address,
                "token_name": token_name,
                "amount_eth": round(amount_eth / 2, 8),
            }

        return {}

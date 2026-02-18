"""Airdrop Farmer — autonomous 24/7 orchestrator for airdrop farming.

Combines:
- Activity Planner: generates human-like daily schedules
- DEX Swapper: executes swaps on Base (Uniswap V3 + Aerodrome)
- Chain Manager: multi-chain RPC + gas tracking
- Testnet Farmer: generates testnet tx history
- Airdrop Monitor: scans for new opportunities every 12h
- Telegram Notifier: alerts for each action + daily reports

Usage:
    python3 airdrop_farmer.py --dry-run    # Simulate without sending tx
    python3 airdrop_farmer.py --loop       # Run 24/7
    python3 airdrop_farmer.py --status     # Show current state
    python3 airdrop_farmer.py --once       # Run one cycle then exit
"""

import json
import logging
import os
import sys
import time
import random
import traceback
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

# Local modules
import farmer_config
import env_loader
import telegram_notifier
from chain_manager import ChainManager, BudgetTracker
from dex_swapper import DexSwapper
from activity_planner import ActivityPlanner
from testnet_farmer import TestnetFarmer
from airdrop_monitor import run_scan as scan_airdrops

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "airdrop_farmer.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [farmer] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
STATE_FILE = farmer_config.FARM_STATE_FILE


def _parse_dt(s):
    """Parse ISO datetime string — handles naive and tz-aware safely."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        s_clean = s.replace("Z", "+00:00")
        if s_clean.endswith("+00:00"):
            dt = datetime.fromisoformat(s_clean.replace("+00:00", ""))
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s_clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _hours_since(iso_str: Optional[str]) -> float:
    """Return hours elapsed since an ISO timestamp (or infinity if None)."""
    if not iso_str:
        return float("inf")
    dt = _parse_dt(iso_str)
    if dt is None:
        return float("inf")
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600


def _load_state() -> Dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_actions": 0,
        "total_gas_spent_usd": 0.0,
        "actions_log": [],
        "last_scan": None,
        "last_testnet_cycle": None,
        "last_daily_report": None,
        "token_holdings": {},
        "lp_positions": [],
        "budget": None,
    }


def _save_state(state: Dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class AirdropFarmer:
    """Main orchestrator — ties planner, executor, scanner, and notifier together."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.state = _load_state()

        # Initialise core modules
        self.chain_mgr = ChainManager()
        self.dex = DexSwapper(self.chain_mgr)
        self.planner = ActivityPlanner()
        self.testnet_farmer = TestnetFarmer()

        # Restore budget from previous run
        if self.state.get("budget"):
            self.chain_mgr.budget = BudgetTracker.from_dict(self.state["budget"])

        # Primary wallet (first in list)
        self.wallet = self.chain_mgr.wallets[0] if self.chain_mgr.wallets else None

        mode = "DRY RUN" if dry_run else "LIVE"
        logger.info("AirdropFarmer initialised (%s)", mode)
        if self.wallet:
            logger.info("Primary wallet: %s...", self.wallet["address"][:12])
        else:
            logger.error("No wallets configured! Create farming_wallets.json or set FARMING_WALLET_KEY")
        logger.info("Budget remaining: $%.4f", self.chain_mgr.budget.get_remaining())

    def _save(self):
        self.state["budget"] = self.chain_mgr.budget.to_dict()
        _save_state(self.state)

    def _notify(self, text: str):
        try:
            telegram_notifier.send_message(text)
        except Exception as exc:
            logger.warning("Telegram notification failed: %s", exc)

    # ------------------------------------------------------------------ #
    #  Action executors                                                    #
    # ------------------------------------------------------------------ #

    def execute_action(self, action: Dict) -> Optional[str]:
        """Execute a single farming action. Returns tx hash or None."""
        action_type = action["action_type"]
        params = action.get("params", {})
        chain = action.get("chain", "base")

        if not self.wallet:
            logger.error("No wallet — cannot execute action")
            return None

        pk = self.wallet["private_key"]

        logger.info("Executing %s on %s | params=%s", action_type, chain, params)

        if self.dry_run:
            logger.info("[DRY RUN] Would execute %s — skipping", action_type)
            return "dry_run_" + action["id"]

        # Budget guard (mainnet only)
        if farmer_config.CHAINS[chain].get("type") == "mainnet":
            if not self.chain_mgr.budget.can_afford(chain):
                logger.warning("Budget exhausted for %s — skipping", chain)
                return None

        try:
            if action_type == "swap_eth_to_token":
                return self._exec_swap_eth_to_token(chain, params, pk)
            elif action_type == "swap_token_to_eth":
                return self._exec_swap_token_to_eth(chain, params, pk)
            elif action_type == "self_transfer":
                return self._exec_self_transfer(chain, params, pk)
            elif action_type == "lp_add":
                return self._exec_lp_add(chain, params, pk)
            elif action_type == "lp_remove":
                return self._exec_lp_remove(chain, params, pk)
            else:
                logger.warning("Unknown action type: %s", action_type)
                return None
        except Exception as exc:
            logger.error("Action %s failed: %s", action_type, exc)
            return None

    # --- individual executors ---

    def _exec_swap_eth_to_token(self, chain, params, pk):
        token_out = params["token_out"]
        amount_eth = params["amount_eth"]
        token_name = params.get("token_name", "?")

        tx = self.dex.swap_exact_eth_for_tokens(chain, amount_eth, token_out, pk)
        if tx:
            holdings = self.state.setdefault("token_holdings", {})
            holdings[token_name] = True
            logger.info("Swapped %s ETH -> %s | tx=%s", amount_eth, token_name, tx[:20])
        return tx

    def _exec_swap_token_to_eth(self, chain, params, pk):
        token_in = params["token_in"]
        token_name = params.get("token_name", "?")

        balance = self.dex.get_token_balance(chain, token_in, self.wallet["address"])
        if balance == 0:
            logger.info("No %s balance — doing self-transfer instead", token_name)
            return self._exec_self_transfer(chain, {"amount_eth": 0.00005}, pk)

        tx = self.dex.swap_tokens_for_eth(chain, token_in, balance, pk)
        if tx:
            self.state.get("token_holdings", {}).pop(token_name, None)
            logger.info("Swapped %s -> ETH | tx=%s", token_name, tx[:20])
        return tx

    def _exec_self_transfer(self, chain, params, pk):
        from eth_account import Account
        from web3 import Web3

        amount_eth = params.get("amount_eth", 0.00005)
        acct = Account.from_key(pk)

        tx_dict = {
            "to": acct.address,
            "value": Web3.to_wei(amount_eth, "ether"),
            "gas": 21000,
            "chainId": farmer_config.CHAINS[chain]["chain_id"],
        }
        tx = self.chain_mgr.send_transaction(chain, tx_dict, pk)
        if tx:
            logger.info("Self-transfer %s ETH | tx=%s", amount_eth, tx[:20])
        return tx

    def _exec_lp_add(self, chain, params, pk):
        token = params["token"]
        token_name = params.get("token_name", "?")
        amount_eth = params.get("amount_eth", 0.0001)

        balance = self.dex.get_token_balance(chain, token, self.wallet["address"])
        if balance == 0:
            logger.info("No %s for LP — doing swap first", token_name)
            return self._exec_swap_eth_to_token(
                chain,
                {"token_out": token, "token_name": token_name, "amount_eth": amount_eth},
                pk,
            )

        tx = self.dex.add_liquidity_eth(chain, token, balance, amount_eth, pk)
        if tx:
            self.state.setdefault("lp_positions", []).append(
                {
                    "chain": chain,
                    "token": token,
                    "token_name": token_name,
                    "added_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            logger.info("Added LP %s/ETH | tx=%s", token_name, tx[:20])
        return tx

    def _exec_lp_remove(self, chain, params, pk):
        positions = self.state.get("lp_positions", [])
        if not positions:
            logger.info("No LP positions — doing self-transfer instead")
            return self._exec_self_transfer(chain, {"amount_eth": 0.00005}, pk)
        # LP removal requires tracking LP token addresses/amounts — fall back
        logger.info("LP remove not yet tracked — doing self-transfer")
        return self._exec_self_transfer(chain, {"amount_eth": 0.00005}, pk)

    # ------------------------------------------------------------------ #
    #  Orchestration cycles                                                #
    # ------------------------------------------------------------------ #

    def run_pending_actions(self) -> int:
        """Execute all pending actions that are past their scheduled time."""
        pending = self.planner.get_pending_actions()
        if not pending:
            return 0

        logger.info("%d pending action(s) to execute", len(pending))
        executed = 0

        for action in pending:
            # Organic micro-delay
            delay = random.uniform(10, 120)
            logger.info("Waiting %.0fs before %s...", delay, action["action_type"])
            if not self.dry_run:
                time.sleep(delay)

            tx_hash = self.execute_action(action)

            if tx_hash:
                self.planner.mark_action_done(action["id"], tx_hash=tx_hash)
                self.state["total_actions"] = self.state.get("total_actions", 0) + 1

                self.state.setdefault("actions_log", []).append(
                    {
                        "id": action["id"],
                        "type": action["action_type"],
                        "chain": action.get("chain"),
                        "tx_hash": tx_hash,
                        "time": datetime.now(timezone.utc).isoformat(),
                    }
                )
                # Keep last 100 entries
                self.state["actions_log"] = self.state["actions_log"][-100:]

                self._notify(
                    "\U0001f331 <b>FARM ACTION</b>\n"
                    f"Type: {action['action_type']}\n"
                    f"Chain: {action.get('chain', 'base')}\n"
                    f"TX: <code>{tx_hash[:20]}...</code>\n"
                    f"Budget: ${self.chain_mgr.budget.get_remaining():.4f} left"
                )
                executed += 1
            else:
                self.planner.mark_action_done(action["id"], error="execution_failed")

        self._save()
        return executed

    def run_testnet_cycle(self):
        """Run one testnet farming cycle (if enough time has passed)."""
        hours = _hours_since(self.state.get("last_testnet_cycle"))
        threshold = random.uniform(
            farmer_config.MIN_DELAY_HOURS, farmer_config.MAX_DELAY_HOURS
        )
        if hours < threshold:
            return

        logger.info("Running testnet farming cycle...")
        try:
            if self.dry_run:
                logger.info("[DRY RUN] Skipping testnet farmer")
            else:
                self.testnet_farmer.run_farming_cycle()
        except Exception as exc:
            logger.error("Testnet farming error: %s", exc)

        self.state["last_testnet_cycle"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def run_airdrop_scan(self):
        """Run airdrop monitor scan (every 12 h)."""
        if _hours_since(self.state.get("last_scan")) < 12:
            return

        logger.info("Running airdrop scan...")
        try:
            if self.dry_run:
                logger.info("[DRY RUN] Skipping airdrop scan")
            else:
                report = scan_airdrops()
                if report:
                    self._notify(
                        "\U0001f50d <b>AIRDROP SCAN</b>\n"
                        f"Found {report.get('total_found', 0)} opportunities"
                    )
        except Exception as exc:
            logger.error("Airdrop scan error: %s", exc)

        self.state["last_scan"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def send_daily_report(self):
        """Send a daily summary via Telegram."""
        if _hours_since(self.state.get("last_daily_report")) < 24:
            return

        stats = self.planner.get_stats()
        budget = self.chain_mgr.budget
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        today_actions = [
            a
            for a in self.state.get("actions_log", [])
            if a.get("time", "").startswith(today)
        ]

        gas_lines = "\n".join(
            f"  {chain}: ${spent:.4f}" for chain, spent in budget.spent_by_chain.items()
        ) or "  (none yet)"

        report_text = (
            "\U0001f4ca <b>DAILY FARM REPORT</b>\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
            f"\U0001f4c5 Date: {today}\n"
            f"\u2705 Actions today: {len(today_actions)}\n"
            f"\U0001f4c8 Total actions: {self.state.get('total_actions', 0)}\n\n"
            f"\U0001f4b0 <b>Budget</b>\n"
            f"  Spent: ${budget.total_spent:.4f}\n"
            f"  Remaining: ${budget.get_remaining():.4f}\n\n"
            f"\U0001f5d3 <b>Schedule</b>\n"
            f"  Planned: {stats.get('total', 0)}\n"
            f"  Done: {stats.get('done', 0)}\n"
            f"  Pending: {stats.get('pending', 0)}\n"
            f"  Failed: {stats.get('failed', 0)}\n\n"
            f"\u26fd Gas by chain:\n{gas_lines}"
        )

        self._notify(report_text)
        self.state["last_daily_report"] = datetime.now(timezone.utc).isoformat()
        self._save()

    # ------------------------------------------------------------------ #
    #  Main entry points                                                   #
    # ------------------------------------------------------------------ #

    def run_once(self):
        """Single cycle: plan -> execute -> testnet -> scan -> report."""
        logger.info("=" * 60)
        logger.info(
            "AIRDROP FARMER — %s | %s",
            "DRY RUN" if self.dry_run else "LIVE",
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        logger.info("Budget remaining: $%.4f", self.chain_mgr.budget.get_remaining())
        logger.info("=" * 60)

        # 1. Generate/load today's plan
        self.planner.get_daily_plan(budget_remaining=self.chain_mgr.budget.get_remaining())
        stats = self.planner.get_stats()
        logger.info(
            "Today's plan: %d actions (%d pending)", stats["total"], stats["pending"]
        )

        # 2. Execute pending mainnet actions
        executed = self.run_pending_actions()
        logger.info("Executed %d mainnet action(s)", executed)

        # 3. Testnet farming
        self.run_testnet_cycle()

        # 4. Airdrop scan (every 12 h)
        self.run_airdrop_scan()

        # 5. Daily report
        self.send_daily_report()

        logger.info("Cycle complete")

    def run_loop(self):
        """Run 24/7."""
        logger.info("=" * 60)
        logger.info("AIRDROP FARMER — 24/7 MODE (%s)", "DRY RUN" if self.dry_run else "LIVE")
        if self.wallet:
            logger.info("Wallet: %s...", self.wallet["address"][:12])
        logger.info("Budget: $%.4f", self.chain_mgr.budget.get_remaining())
        logger.info("=" * 60)

        wallet_str = (
            f"Wallet: <code>{self.wallet['address'][:12]}...</code>"
            if self.wallet
            else "Wallet: NONE"
        )
        self._notify(
            "\U0001f680 <b>AIRDROP FARMER STARTED</b>\n"
            f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}\n"
            f"Budget: ${self.chain_mgr.budget.get_remaining():.4f}\n"
            f"{wallet_str}"
        )

        # Initial cycle
        self.run_once()

        while True:
            try:
                # Sleep until next action (max 30 min)
                next_time = self.planner.get_next_action_time()
                now = datetime.now(timezone.utc)

                if next_time and next_time > now:
                    sleep_secs = min((next_time - now).total_seconds(), 1800)
                else:
                    sleep_secs = 1800

                # Organic jitter
                sleep_secs += random.uniform(-60, 300)
                sleep_secs = max(60, sleep_secs)

                logger.info("Sleeping %.1f minutes...", sleep_secs / 60)
                time.sleep(sleep_secs)

                self.run_once()

            except KeyboardInterrupt:
                logger.info("Airdrop Farmer stopped by user")
                self._notify("\U0001f6d1 <b>AIRDROP FARMER STOPPED</b> (manual)")
                break
            except Exception as exc:
                logger.error("Main loop error: %s\n%s", exc, traceback.format_exc())
                time.sleep(600)

    def show_status(self):
        """Print human-readable status to stdout."""
        stats = self.planner.get_stats()
        budget = self.chain_mgr.budget

        print("=" * 50)
        print("AIRDROP FARMER STATUS")
        print("=" * 50)
        print(f"Started:    {self.state.get('started_at', 'unknown')}")
        print(f"Total acts: {self.state.get('total_actions', 0)}")
        print(f"Gas spent:  ${budget.total_spent:.4f}")
        print(f"Gas left:   ${budget.get_remaining():.4f}")
        print(f"Wallet:     {self.wallet['address'] if self.wallet else 'NONE'}")
        print()
        print(f"Schedule ({stats.get('date', '?')}):")
        print(f"  Total:   {stats.get('total', 0)}")
        print(f"  Pending: {stats.get('pending', 0)}")
        print(f"  Done:    {stats.get('done', 0)}")
        print(f"  Failed:  {stats.get('failed', 0)}")
        print()
        print("Gas by chain:")
        for chain, spent in budget.spent_by_chain.items():
            print(f"  {chain}: ${spent:.4f}")
        print()
        print("Last 5 actions:")
        for a in self.state.get("actions_log", [])[-5:]:
            print(f"  {a.get('time', '?')[:19]} | {a.get('type', '?'):20s} | {a.get('tx_hash', '?')[:20]}")
        print("=" * 50)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    dry_run = "--dry-run" in sys.argv

    if "--status" in sys.argv:
        farmer = AirdropFarmer(dry_run=True)
        farmer.show_status()
    elif "--loop" in sys.argv:
        farmer = AirdropFarmer(dry_run=dry_run)
        farmer.run_loop()
    elif "--once" in sys.argv:
        farmer = AirdropFarmer(dry_run=dry_run)
        farmer.run_once()
    else:
        print("Usage:")
        print("  python3 airdrop_farmer.py --loop          # Run 24/7")
        print("  python3 airdrop_farmer.py --loop --dry-run # Simulate without tx")
        print("  python3 airdrop_farmer.py --once           # Single cycle")
        print("  python3 airdrop_farmer.py --once --dry-run # Single dry run")
        print("  python3 airdrop_farmer.py --status         # Show state")


if __name__ == "__main__":
    main()

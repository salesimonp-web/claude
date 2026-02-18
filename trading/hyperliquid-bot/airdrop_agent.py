"""Airdrop Agent — monitors and farms airdrops automatically

Runs alongside the trading bot. Three modes:
1. SCANNER: Queries Perplexity + Grok every 6h for new airdrop opportunities
2. FARMER: Automates on-chain tasks (testnet faucets, daily check-ins)
3. ALERTER: Sends alerts for time-sensitive drops via log file (read by OpenClaw)
"""

import time
import logging
import os
import json
import requests
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [AIRDROP] %(message)s',
    handlers=[
        logging.FileHandler('airdrop_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# State file to track what we've already seen
STATE_FILE = "airdrop_state.json"
SCAN_INTERVAL_HOURS = 6
FARM_INTERVAL_HOURS = 12


class AirdropAgent:
    def __init__(self):
        # Load API keys
        self.perplexity_key = None
        self.openrouter_key = None
        env_path = os.path.expanduser('~/.claude-env')
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        value = value.strip('"').strip("'")
                        if key == 'PERPLEXITY_API_KEY':
                            self.perplexity_key = value
                        elif key == 'OPENROUTER_API_KEY':
                            self.openrouter_key = value

        # Load state
        self.state = self._load_state()
        logger.info("Airdrop Agent initialized")

    def _load_state(self) -> Dict:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        return {
            "known_airdrops": [],
            "last_scan": None,
            "last_farm": None,
            "farming_tasks": [],
            "alerts_sent": []
        }

    def _save_state(self):
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)

    def _ask_perplexity(self, prompt: str) -> Optional[str]:
        if not self.perplexity_key:
            return None
        try:
            r = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {self.perplexity_key}", "Content-Type": "application/json"},
                json={"model": "sonar-pro", "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.1, "max_tokens": 1200},
                timeout=60
            )
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content']
            logger.error(f"Perplexity error: {r.status_code}")
        except Exception as e:
            logger.error(f"Perplexity request failed: {e}")
        return None

    def _ask_grok(self, prompt: str) -> Optional[str]:
        if not self.openrouter_key:
            return None
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.openrouter_key}", "Content-Type": "application/json"},
                json={"model": "x-ai/grok-3", "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.2, "max_tokens": 1200},
                timeout=60
            )
            if r.status_code == 200:
                return r.json()['choices'][0]['message']['content']
            logger.error(f"Grok error: {r.status_code}")
        except Exception as e:
            logger.error(f"Grok request failed: {e}")
        return None

    # ========== SCANNER ==========

    def scan_new_airdrops(self):
        """Query AI for new airdrop opportunities"""
        logger.info("=" * 50)
        logger.info("SCANNING FOR NEW AIRDROPS")
        logger.info("=" * 50)

        today = datetime.now().strftime("%Y-%m-%d")
        known = ", ".join(self.state["known_airdrops"][-20:]) if self.state["known_airdrops"] else "none"

        # Perplexity: structured search
        perp_result = self._ask_perplexity(
            f"Date: {today}. List ALL active crypto airdrops and testnet farming opportunities. "
            f"I already know about: {known}. "
            f"For each NEW one, give: name, chain, deadline, estimated value, "
            f"whether it needs capital or is free, and if it can be automated with scripts. "
            f"Focus on: testnets (Monad, MegaETH, Linea, Fuel, Berachain), "
            f"DeFi airdrops, points programs, and Hyperliquid ecosystem. "
            f"Only list opportunities still ACTIVE today."
        )

        # Grok: Twitter alpha
        grok_result = self._ask_grok(
            f"What are the NEWEST airdrop opportunities being shared on crypto Twitter/X today ({today})? "
            f"Any urgent/time-sensitive drops? New testnets? Points programs ending soon? "
            f"I already track: {known}. Only tell me NEW stuff. "
            f"Include: protocol name, what to do, and if it's automatable."
        )

        # Log results
        new_airdrops = []

        if perp_result:
            logger.info(f"Perplexity found:\n{perp_result[:500]}...")
            # Extract names (basic parsing)
            for line in perp_result.split('\n'):
                line = line.strip()
                if line.startswith('**') and '**' in line[2:]:
                    name = line.split('**')[1].strip()
                    if name and name not in self.state["known_airdrops"]:
                        new_airdrops.append(name)
                        self.state["known_airdrops"].append(name)

        if grok_result:
            logger.info(f"Grok found:\n{grok_result[:500]}...")

        if new_airdrops:
            logger.info(f"NEW AIRDROPS DETECTED: {new_airdrops}")
            # Write alert file for OpenClaw/Telegram
            with open("airdrop_alerts.txt", "a") as f:
                f.write(f"\n[{today}] NEW AIRDROPS: {', '.join(new_airdrops)}\n")
                if perp_result:
                    f.write(f"Details:\n{perp_result[:1000]}\n")
        else:
            logger.info("No new airdrops found this scan")

        self.state["last_scan"] = datetime.now().isoformat()
        self._save_state()

    # ========== FARMER ==========

    def farm_testnet_faucets(self):
        """Claim testnet faucets — free tokens for qualification"""
        logger.info("Farming testnet faucets...")

        # List of known faucets (add more as discovered)
        faucets = [
            {
                "name": "Sepolia ETH",
                "url": "https://sepoliafaucet.com/api/faucet",
                "method": "POST",
                "body_key": "address",
            },
        ]

        # We'd need wallet addresses — for now log what to do
        logger.info(f"Known faucets to claim: {[f['name'] for f in faucets]}")
        logger.info("NOTE: Need wallet addresses configured to auto-claim")

    def farm_hyperliquid_volume(self):
        """Generate trading volume on Hyperliquid for potential points/airdrop.
        The trading bot already does this — just log the volume."""
        try:
            from hyperliquid.info import Info
            from hyperliquid.utils import constants
            import config

            info = Info(constants.MAINNET_API_URL, skip_ws=True)

            # Check if we have any trading history (volume = airdrop qualification)
            state = info.user_state(config.ACCOUNT_ADDRESS)
            balance = float(state['marginSummary']['accountValue'])

            # Get recent fills
            fills = info.user_fills(config.ACCOUNT_ADDRESS)
            recent_fills = [f for f in fills if f] if fills else []

            logger.info(
                f"Hyperliquid farming status: "
                f"balance=${balance:.2f}, "
                f"total fills={len(recent_fills)}"
            )

            # The trading bot generates volume automatically
            # More volume = better airdrop qualification
            if len(recent_fills) < 10:
                logger.info("TIP: Low fill count — trading bot volume also counts as airdrop farming")

        except Exception as e:
            logger.error(f"Error checking Hyperliquid volume: {e}")

    def run_farming_cycle(self):
        """Execute all farming tasks"""
        logger.info("=" * 50)
        logger.info("RUNNING FARMING CYCLE")
        logger.info("=" * 50)

        self.farm_testnet_faucets()
        self.farm_hyperliquid_volume()

        self.state["last_farm"] = datetime.now().isoformat()
        self._save_state()

    # ========== MAIN LOOP ==========

    def run(self):
        """Main agent loop — scan every 6h, farm every 12h"""
        logger.info("=" * 60)
        logger.info("AIRDROP AGENT STARTED")
        logger.info(f"Scan interval: every {SCAN_INTERVAL_HOURS}h")
        logger.info(f"Farm interval: every {FARM_INTERVAL_HOURS}h")
        logger.info(f"Known airdrops: {len(self.state['known_airdrops'])}")
        logger.info("=" * 60)

        # Run immediately on start
        self.scan_new_airdrops()
        self.run_farming_cycle()

        while True:
            try:
                now = datetime.now()

                # Check if scan is due
                last_scan = self.state.get("last_scan")
                if last_scan:
                    last_scan_dt = datetime.fromisoformat(last_scan)
                    if (now - last_scan_dt) > timedelta(hours=SCAN_INTERVAL_HOURS):
                        self.scan_new_airdrops()
                else:
                    self.scan_new_airdrops()

                # Check if farming is due
                last_farm = self.state.get("last_farm")
                if last_farm:
                    last_farm_dt = datetime.fromisoformat(last_farm)
                    if (now - last_farm_dt) > timedelta(hours=FARM_INTERVAL_HOURS):
                        self.run_farming_cycle()
                else:
                    self.run_farming_cycle()

                # Sleep 30 minutes between checks
                time.sleep(1800)

            except KeyboardInterrupt:
                logger.info("Airdrop Agent stopped")
                break
            except Exception as e:
                logger.error(f"Agent error: {e}")
                time.sleep(600)


if __name__ == "__main__":
    agent = AirdropAgent()
    agent.run()

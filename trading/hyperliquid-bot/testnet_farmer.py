"""Automated Testnet Farmer — builds on-chain history for airdrop qualification

Strategy:
1. Claim faucets manually (most have captcha) — agent reminds you
2. Once funded, auto-generates organic tx patterns every 4-8h
3. Self-transfers, inter-wallet transfers, contract interactions
4. Tracks progress and tx count per chain

Wallets need initial funding from manual faucet claims:
- Monad: https://faucet.monad.xyz or thirdweb bridge
- Berachain: https://bartio.faucet.berachain.com
- Linea: https://faucet.goerli.linea.build
- Sepolia: https://sepoliafaucet.com or https://faucets.chain.link
"""

import time
import json
import logging
import random
import os
from datetime import datetime
from typing import Dict, List
from web3 import Web3
from eth_account import Account

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [FARMER] %(message)s',
    handlers=[
        logging.FileHandler('testnet_farmer.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

WALLETS_FILE = "farming_wallets.json"
FARM_STATE_FILE = "farm_state.json"

# Confirmed working RPC endpoints
TESTNETS = {
    "monad_testnet": {
        "rpc": "https://testnet-rpc.monad.xyz",
        "chain_id": 10143,
        "name": "Monad Testnet",
        "faucet_manual": "https://faucet.monad.xyz",
    },
    "monad_ankr": {
        "rpc": "https://rpc.ankr.com/monad_testnet",
        "chain_id": 10143,
        "name": "Monad (Ankr)",
        "faucet_manual": "https://faucet.monad.xyz",
    },
    "berachain_bartio": {
        "rpc": "https://bartio.rpc.berachain.com",
        "chain_id": 80084,
        "name": "Berachain bArtio",
        "faucet_manual": "https://bartio.faucet.berachain.com",
    },
    "linea_sepolia": {
        "rpc": "https://rpc.sepolia.linea.build",
        "chain_id": 59141,
        "name": "Linea Sepolia",
        "faucet_manual": "https://faucet.goerli.linea.build",
    },
    "sepolia": {
        "rpc": "https://rpc.sepolia.org",
        "chain_id": 11155111,
        "name": "Sepolia",
        "faucet_manual": "https://sepoliafaucet.com",
    },
}


class TestnetFarmer:
    def __init__(self):
        self.wallets = self._load_wallets()
        self.state = self._load_state()
        logger.info(f"Farmer initialized with {len(self.wallets)} wallets")

    def _load_wallets(self) -> List[Dict]:
        if os.path.exists(WALLETS_FILE):
            with open(WALLETS_FILE, 'r') as f:
                return json.load(f)
        return []

    def _load_state(self) -> Dict:
        if os.path.exists(FARM_STATE_FILE):
            with open(FARM_STATE_FILE, 'r') as f:
                return json.load(f)
        return {"txns_by_chain": {}, "total_txns": 0, "balances": {}, "funded_chains": []}

    def _save_state(self):
        with open(FARM_STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)

    def check_balances(self):
        """Check balances on all chains — identify which are funded"""
        logger.info("Checking balances across all chains...")
        unfunded = []

        for net_key, net_config in TESTNETS.items():
            if net_key == "monad_ankr":
                continue  # Same chain, skip duplicate

            for wallet in self.wallets:
                try:
                    w3 = Web3(Web3.HTTPProvider(net_config["rpc"], request_kwargs={"timeout": 10}))
                    if not w3.is_connected():
                        logger.warning(f"  {net_config['name']}: RPC offline")
                        continue

                    balance = w3.eth.get_balance(wallet["address"])
                    balance_eth = w3.from_wei(balance, 'ether')

                    chain_wallet_key = f"{net_key}_{wallet['address'][:10]}"
                    self.state.setdefault("balances", {})[chain_wallet_key] = float(balance_eth)

                    if balance > 0:
                        if net_key not in self.state.get("funded_chains", []):
                            self.state.setdefault("funded_chains", []).append(net_key)
                        logger.info(f"  {net_config['name']} | {wallet['name']}: {balance_eth:.6f} ETH")
                    else:
                        unfunded.append((net_config['name'], wallet['address'], net_config.get('faucet_manual', '')))

                except Exception as e:
                    logger.warning(f"  {net_config['name']} check failed: {str(e)[:80]}")

        if unfunded:
            logger.info("\n  UNFUNDED — Claim faucets manually:")
            seen = set()
            for name, addr, faucet in unfunded:
                key = (name, faucet)
                if key not in seen:
                    seen.add(key)
                    logger.info(f"    {name}: {faucet}")
            logger.info("  Wallet addresses to fund:")
            for w in self.wallets:
                logger.info(f"    {w['name']}: {w['address']}")

            # Write reminder file
            with open("faucet_todo.txt", "w") as f:
                f.write("=== FUND THESE WALLETS ON TESTNET FAUCETS ===\n\n")
                f.write("Wallets:\n")
                for w in self.wallets:
                    f.write(f"  {w['address']}\n")
                f.write("\nFaucets:\n")
                for name, faucet in seen:
                    f.write(f"  {name}: {faucet}\n")

    def do_transactions(self, net_key: str, wallet: Dict):
        """Generate organic tx patterns on a funded chain"""
        net_config = TESTNETS.get(net_key)
        if not net_config:
            return 0

        try:
            w3 = Web3(Web3.HTTPProvider(net_config["rpc"], request_kwargs={"timeout": 15}))
            if not w3.is_connected():
                return 0

            account = Account.from_key(wallet["private_key"])
            balance = w3.eth.get_balance(account.address)

            if balance == 0:
                return 0

            gas_price = w3.eth.gas_price
            gas_cost = 21000 * gas_price
            txns_done = 0

            # Need at least 10x gas for safety
            if balance < gas_cost * 10:
                logger.info(f"  Low balance on {net_config['name']} — saving gas")
                return 0

            nonce = w3.eth.get_transaction_count(account.address)

            # Pick random actions (1-3 per cycle)
            num_actions = random.randint(1, 3)

            for i in range(num_actions):
                action = random.choice(["self_transfer", "inter_wallet", "zero_value"])

                try:
                    if action == "self_transfer":
                        tx = {
                            'nonce': nonce,
                            'to': account.address,
                            'value': random.randint(1, 1000),  # Tiny amount
                            'gas': 21000,
                            'gasPrice': gas_price,
                            'chainId': net_config["chain_id"]
                        }

                    elif action == "inter_wallet":
                        others = [w for w in self.wallets if w["address"] != wallet["address"]]
                        if not others:
                            continue
                        target = random.choice(others)
                        send_amount = balance // random.randint(50, 200)
                        if send_amount < gas_cost:
                            continue
                        tx = {
                            'nonce': nonce,
                            'to': Web3.to_checksum_address(target["address"]),
                            'value': send_amount,
                            'gas': 21000,
                            'gasPrice': gas_price,
                            'chainId': net_config["chain_id"]
                        }

                    else:  # zero_value
                        tx = {
                            'nonce': nonce,
                            'to': account.address,
                            'value': 0,
                            'gas': 21000,
                            'gasPrice': gas_price,
                            'chainId': net_config["chain_id"]
                        }

                    signed = w3.eth.account.sign_transaction(tx, wallet["private_key"])
                    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

                    logger.info(f"  TX {action} on {net_config['name']}: {tx_hash.hex()[:20]}...")
                    nonce += 1
                    txns_done += 1

                    # Random delay between txns (organic)
                    time.sleep(random.uniform(3, 15))

                except Exception as e:
                    logger.warning(f"  TX failed: {str(e)[:80]}")

            return txns_done

        except Exception as e:
            logger.error(f"  Chain error {net_config['name']}: {str(e)[:80]}")
            return 0

    def run_farming_cycle(self):
        """Full farming cycle"""
        logger.info("=" * 60)
        logger.info(f"FARMING CYCLE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"Total txns so far: {self.state.get('total_txns', 0)}")
        logger.info("=" * 60)

        # Check balances first
        self.check_balances()

        # Farm on funded chains
        cycle_txns = 0
        funded = self.state.get("funded_chains", [])

        if not funded:
            logger.info("No funded chains yet — claim faucets first! See faucet_todo.txt")
        else:
            # Randomize order
            chains = list(funded)
            random.shuffle(chains)

            for net_key in chains:
                for wallet in self.wallets:
                    time.sleep(random.uniform(5, 20))
                    txns = self.do_transactions(net_key, wallet)
                    cycle_txns += txns

        self.state["total_txns"] = self.state.get("total_txns", 0) + cycle_txns
        self._save_state()

        logger.info(f"\nCycle: +{cycle_txns} txns | Total: {self.state['total_txns']}")

        # Summary
        logger.info("\n--- FARMING PROGRESS ---")
        for net_key in TESTNETS:
            if net_key == "monad_ankr":
                continue
            txns = self.state.get("txns_by_chain", {}).get(net_key, 0)
            funded = "FUNDED" if net_key in self.state.get("funded_chains", []) else "NEED FAUCET"
            logger.info(f"  {TESTNETS[net_key]['name']}: {funded} | {txns} txns")

    def run(self):
        """Main loop"""
        logger.info("=" * 60)
        logger.info("TESTNET FARMER v2")
        logger.info(f"Wallets: {len(self.wallets)}")
        logger.info(f"Chains: {', '.join(c['name'] for k, c in TESTNETS.items() if k != 'monad_ankr')}")
        logger.info("=" * 60)

        self.run_farming_cycle()

        while True:
            try:
                hours = random.uniform(4, 8)
                logger.info(f"Sleeping {hours:.1f}h until next cycle...")
                time.sleep(hours * 3600)
                self.run_farming_cycle()
            except KeyboardInterrupt:
                logger.info("Farmer stopped")
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(1800)


if __name__ == "__main__":
    farmer = TestnetFarmer()
    farmer.run()

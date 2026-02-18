"""Multi-chain manager — RPC failover, gas estimation, budget tracking."""

import json
import logging
import os
import time
from typing import Dict, Optional

from web3 import Web3
from eth_account import Account

import env_loader
import farmer_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [CHAIN] %(message)s',
    handlers=[
        logging.FileHandler('chain_manager.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BudgetTracker:
    """Tracks gas spending per chain against a total USD budget."""

    def __init__(self, budget_usd: float = farmer_config.TOTAL_GAS_BUDGET_USD,
                 reserve_pct: float = farmer_config.RESERVE_PCT):
        self.budget_usd = budget_usd
        self.reserve_pct = reserve_pct
        self.spent_by_chain: Dict[str, float] = {}
        self.total_spent = 0.0

    def record_spend(self, chain: str, amount_usd: float):
        self.spent_by_chain[chain] = self.spent_by_chain.get(chain, 0.0) + amount_usd
        self.total_spent += amount_usd
        remaining = self.get_remaining()
        if remaining < self.budget_usd * 0.20:
            logger.warning(f"Budget low: ${remaining:.4f} remaining (${self.total_spent:.4f} spent)")

    def get_remaining(self) -> float:
        usable = self.budget_usd * (1.0 - self.reserve_pct)
        return max(0.0, usable - self.total_spent)

    def can_afford(self, chain: str) -> bool:
        cfg = farmer_config.CHAINS.get(chain)
        if not cfg:
            return False
        return self.get_remaining() >= cfg["avg_gas_cost"]

    def to_dict(self) -> dict:
        return {
            "budget_usd": self.budget_usd,
            "reserve_pct": self.reserve_pct,
            "spent_by_chain": self.spent_by_chain,
            "total_spent": self.total_spent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BudgetTracker":
        tracker = cls(
            budget_usd=data.get("budget_usd", farmer_config.TOTAL_GAS_BUDGET_USD),
            reserve_pct=data.get("reserve_pct", farmer_config.RESERVE_PCT),
        )
        tracker.spent_by_chain = data.get("spent_by_chain", {})
        tracker.total_spent = data.get("total_spent", 0.0)
        return tracker


class ChainManager:
    """Manages connections, gas, and transactions across multiple chains."""

    def __init__(self):
        self.wallets = self._load_wallets()
        self.budget = BudgetTracker()
        self._web3_cache: Dict[str, Web3] = {}
        logger.info(f"ChainManager initialized — {len(self.wallets)} wallets, "
                     f"{len(farmer_config.CHAINS)} chains")

    def _load_wallets(self) -> list:
        """Load wallets from JSON file or env var fallback."""
        wallets_path = farmer_config.WALLETS_FILE
        if os.path.exists(wallets_path):
            with open(wallets_path, 'r') as f:
                wallets = json.load(f)
            logger.info(f"Loaded {len(wallets)} wallets from {wallets_path}")
            return wallets

        # Fallback: single wallet from env var
        pk = env_loader.get_key("FARMING_WALLET_KEY", required=False)
        if pk:
            acct = Account.from_key(pk)
            wallets = [{"name": "env_wallet", "address": acct.address, "private_key": pk}]
            logger.info("Loaded 1 wallet from FARMING_WALLET_KEY env var")
            return wallets

        logger.warning("No wallets found — create farming_wallets.json or set FARMING_WALLET_KEY")
        return []

    def get_web3(self, chain_name: str) -> Optional[Web3]:
        """Return a connected Web3 instance with RPC failover."""
        if chain_name in self._web3_cache:
            w3 = self._web3_cache[chain_name]
            if w3.is_connected():
                return w3
            del self._web3_cache[chain_name]

        cfg = farmer_config.CHAINS.get(chain_name)
        if not cfg:
            logger.error(f"Unknown chain: {chain_name}")
            return None

        for rpc_url in cfg["rpcs"]:
            try:
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
                if w3.is_connected():
                    self._web3_cache[chain_name] = w3
                    logger.info(f"Connected to {chain_name} via {rpc_url}")
                    return w3
            except Exception as e:
                logger.warning(f"RPC failed {chain_name} ({rpc_url}): {str(e)[:80]}")

        logger.error(f"All RPCs failed for {chain_name}")
        return None

    def estimate_gas(self, chain_name: str) -> Optional[float]:
        """Return current gas price in gwei. Uses EIP-1559 if supported."""
        w3 = self.get_web3(chain_name)
        if not w3:
            return None

        cfg = farmer_config.CHAINS[chain_name]
        try:
            if cfg.get("eip1559"):
                latest = w3.eth.get_block("latest")
                base_fee = latest.get("baseFeePerGas", 0)
                # Priority fee: use eth_maxPriorityFeePerGas if available
                try:
                    priority_fee = w3.eth.max_priority_fee
                except Exception:
                    priority_fee = Web3.to_wei(1, "gwei")
                total_wei = base_fee + priority_fee
            else:
                total_wei = w3.eth.gas_price

            return float(Web3.from_wei(total_wei, "gwei"))
        except Exception as e:
            logger.warning(f"Gas estimation failed for {chain_name}: {str(e)[:80]}")
            return None

    def wait_for_low_gas(self, chain_name: str, max_gwei: float, poll_interval: int = 30,
                         timeout: int = 3600):
        """Block until gas drops below max_gwei or timeout is reached."""
        start = time.time()
        while time.time() - start < timeout:
            gas = self.estimate_gas(chain_name)
            if gas is not None and gas <= max_gwei:
                logger.info(f"Gas OK on {chain_name}: {gas:.2f} gwei (<= {max_gwei})")
                return True
            if gas is not None:
                logger.info(f"Gas too high on {chain_name}: {gas:.2f} gwei (waiting for <= {max_gwei})")
            time.sleep(poll_interval)

        logger.warning(f"Gas wait timeout on {chain_name} after {timeout}s")
        return False

    def get_balance(self, chain_name: str, address: str) -> Optional[float]:
        """Return native balance in ETH."""
        w3 = self.get_web3(chain_name)
        if not w3:
            return None

        try:
            balance_wei = w3.eth.get_balance(Web3.to_checksum_address(address))
            return float(Web3.from_wei(balance_wei, "ether"))
        except Exception as e:
            logger.warning(f"Balance check failed {chain_name}/{address[:10]}: {str(e)[:80]}")
            return None

    def get_gas_cost_usd(self, chain_name: str) -> float:
        """Return estimated cost of a standard tx in USD from config."""
        cfg = farmer_config.CHAINS.get(chain_name)
        if not cfg:
            return 0.0
        return cfg["avg_gas_cost"]

    def send_transaction(self, chain_name: str, tx_dict: dict, private_key: str) -> Optional[str]:
        """Sign, send a transaction, and record gas spend. Returns tx hash hex."""
        w3 = self.get_web3(chain_name)
        if not w3:
            return None

        cfg = farmer_config.CHAINS[chain_name]

        # Ensure chain_id is set
        tx_dict.setdefault("chainId", cfg["chain_id"])

        # Set gas price if not already set
        if "gasPrice" not in tx_dict and "maxFeePerGas" not in tx_dict:
            if cfg.get("eip1559"):
                latest = w3.eth.get_block("latest")
                base_fee = latest.get("baseFeePerGas", 0)
                try:
                    priority_fee = w3.eth.max_priority_fee
                except Exception:
                    priority_fee = Web3.to_wei(1, "gwei")
                tx_dict["maxFeePerGas"] = base_fee * 2 + priority_fee
                tx_dict["maxPriorityFeePerGas"] = priority_fee
            else:
                tx_dict["gasPrice"] = w3.eth.gas_price

        # Set nonce if not provided
        if "nonce" not in tx_dict:
            acct = Account.from_key(private_key)
            tx_dict["nonce"] = w3.eth.get_transaction_count(acct.address)

        try:
            signed = w3.eth.account.sign_transaction(tx_dict, private_key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            tx_hex = tx_hash.hex()

            # Record gas spend
            gas_cost = self.get_gas_cost_usd(chain_name)
            self.budget.record_spend(chain_name, gas_cost)

            logger.info(f"TX sent on {chain_name}: {tx_hex[:20]}... "
                        f"(gas ~${gas_cost:.4f}, remaining ${self.budget.get_remaining():.4f})")
            return tx_hex
        except Exception as e:
            logger.error(f"TX failed on {chain_name}: {str(e)[:120]}")
            return None

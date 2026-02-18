"""DEX Swapper — wraps Uniswap V3 and Aerodrome interactions on Base via web3.py

Handles token swaps (ETH<->ERC20), liquidity provision, and ERC20 approvals.
All transactions go through ChainManager for gas tracking and budget control.
Designed for micro amounts ($0.10-$0.50) used in airdrop farming.
"""

import time
import logging
from web3 import Web3
from eth_account import Account

import farmer_config

logger = logging.getLogger(__name__)

# --- Minimal ABIs (inline) ---

UNISWAP_V3_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    }
]

ERC20_ABI = [
    {
        "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

AERODROME_ROUTER_ABI = [
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "stable", "type": "bool"},
            {"name": "amountTokenDesired", "type": "uint256"},
            {"name": "amountTokenMin", "type": "uint256"},
            {"name": "amountETHMin", "type": "uint256"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "name": "addLiquidityETH",
        "outputs": [
            {"name": "amountToken", "type": "uint256"},
            {"name": "amountETH", "type": "uint256"},
            {"name": "liquidity", "type": "uint256"},
        ],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "stable", "type": "bool"},
            {"name": "liquidity", "type": "uint256"},
            {"name": "amountTokenMin", "type": "uint256"},
            {"name": "amountETHMin", "type": "uint256"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "name": "removeLiquidityETH",
        "outputs": [
            {"name": "amountToken", "type": "uint256"},
            {"name": "amountETH", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class DexSwapper:
    """Wraps DEX interactions (Uniswap V3 + Aerodrome) using raw web3.py calls."""

    def __init__(self, chain_manager):
        """Initialize with a ChainManager instance for web3 access and gas tracking."""
        self.cm = chain_manager

    def _get_deadline(self, seconds=300):
        """Return a deadline timestamp (now + seconds)."""
        return int(time.time()) + seconds

    def _get_account(self, wallet_key):
        """Derive account address from private key."""
        return Account.from_key(wallet_key)

    def get_token_balance(self, chain, token_address, wallet_address):
        """Check ERC20 balance for a wallet.

        Returns the raw token balance (not adjusted for decimals).
        """
        try:
            w3 = self.cm.get_web3(chain)
            token = w3.eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI,
            )
            balance = token.functions.balanceOf(
                Web3.to_checksum_address(wallet_address)
            ).call()
            logger.info(f"Balance of {token_address[:10]}... for {wallet_address[:10]}...: {balance}")
            return balance
        except Exception as e:
            logger.error(f"Failed to get token balance: {e}")
            return 0

    def approve_token(self, chain, token_address, spender, amount, wallet_key):
        """Approve spender to spend ERC20 tokens.

        Checks current allowance first; skips if already sufficient.
        Returns tx_hash on success, None on failure.
        """
        try:
            w3 = self.cm.get_web3(chain)
            account = self._get_account(wallet_key)
            token_addr = Web3.to_checksum_address(token_address)
            spender_addr = Web3.to_checksum_address(spender)

            token = w3.eth.contract(address=token_addr, abi=ERC20_ABI)

            # Check existing allowance
            current_allowance = token.functions.allowance(account.address, spender_addr).call()
            if current_allowance >= amount:
                logger.info(f"Allowance already sufficient ({current_allowance} >= {amount})")
                return "already_approved"

            # Build approve tx
            tx = token.functions.approve(spender_addr, amount).build_transaction({
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address),
                "chainId": farmer_config.CHAINS[chain]["chain_id"],
            })

            tx_hash = self.cm.send_transaction(chain, tx, wallet_key)
            logger.info(f"Approved {token_address[:10]}... for {spender[:10]}..., tx: {tx_hash}")
            return tx_hash

        except Exception as e:
            logger.error(f"Approve failed for {token_address[:10]}...: {e}")
            return None

    def swap_exact_eth_for_tokens(self, chain, amount_eth, token_out, wallet_key, slippage=0.01):
        """Swap ETH for tokens via Uniswap V3 exactInputSingle.

        Args:
            chain: Chain name (e.g. "base")
            amount_eth: Amount of ETH to swap (in ETH, e.g. 0.0001)
            token_out: Output token address
            wallet_key: Private key for signing
            slippage: Slippage tolerance (default 1%)

        Returns tx_hash on success, None on failure.
        """
        try:
            w3 = self.cm.get_web3(chain)
            account = self._get_account(wallet_key)
            amount_wei = w3.to_wei(amount_eth, "ether")

            tokens = farmer_config.TOKENS.get(chain, {})
            weth_address = Web3.to_checksum_address(tokens.get("WETH", "0x4200000000000000000000000000000000000006"))
            token_out_addr = Web3.to_checksum_address(token_out)

            router = w3.eth.contract(
                address=Web3.to_checksum_address(farmer_config.UNISWAP_V3_ROUTER),
                abi=UNISWAP_V3_ROUTER_ABI,
            )

            # For micro amounts, amountOutMinimum=0 is acceptable
            # The slippage protection is implicit via the small amount being swapped
            params = (
                weth_address,           # tokenIn (WETH for ETH swaps)
                token_out_addr,         # tokenOut
                3000,                   # fee (0.3% pool)
                account.address,        # recipient
                self._get_deadline(),   # deadline
                amount_wei,             # amountIn
                0,                      # amountOutMinimum (micro amounts)
                0,                      # sqrtPriceLimitX96 (no limit)
            )

            tx = router.functions.exactInputSingle(params).build_transaction({
                "from": account.address,
                "value": amount_wei,  # Send ETH with the call
                "nonce": w3.eth.get_transaction_count(account.address),
                "chainId": farmer_config.CHAINS[chain]["chain_id"],
            })

            tx_hash = self.cm.send_transaction(chain, tx, wallet_key)
            logger.info(
                f"Swapped {amount_eth} ETH -> {token_out[:10]}... on {chain}, tx: {tx_hash}"
            )
            return tx_hash

        except Exception as e:
            logger.error(f"ETH->token swap failed on {chain}: {e}")
            return None

    def swap_tokens_for_eth(self, chain, token_in, amount, wallet_key, slippage=0.01):
        """Swap ERC20 tokens back to ETH via Uniswap V3.

        First approves the router if needed, then executes exactInputSingle.

        Args:
            chain: Chain name
            token_in: Input token address
            amount: Raw token amount (in smallest unit, e.g. 100000 for 0.1 USDC)
            wallet_key: Private key
            slippage: Slippage tolerance

        Returns tx_hash on success, None on failure.
        """
        try:
            w3 = self.cm.get_web3(chain)
            account = self._get_account(wallet_key)

            tokens = farmer_config.TOKENS.get(chain, {})
            weth_address = Web3.to_checksum_address(tokens.get("WETH", "0x4200000000000000000000000000000000000006"))
            token_in_addr = Web3.to_checksum_address(token_in)
            router_addr = farmer_config.UNISWAP_V3_ROUTER

            # Step 1: Approve router to spend tokens
            approve_result = self.approve_token(chain, token_in, router_addr, amount, wallet_key)
            if approve_result is None:
                logger.error("Token approval failed, aborting swap")
                return None

            # Wait a moment for approval to confirm (if it was a new tx)
            if approve_result != "already_approved":
                time.sleep(5)

            # Step 2: Build swap tx
            router = w3.eth.contract(
                address=Web3.to_checksum_address(router_addr),
                abi=UNISWAP_V3_ROUTER_ABI,
            )

            params = (
                token_in_addr,          # tokenIn
                weth_address,           # tokenOut (WETH -> unwrapped to ETH)
                3000,                   # fee
                account.address,        # recipient
                self._get_deadline(),   # deadline
                amount,                 # amountIn (raw units)
                0,                      # amountOutMinimum (micro amounts)
                0,                      # sqrtPriceLimitX96
            )

            tx = router.functions.exactInputSingle(params).build_transaction({
                "from": account.address,
                "value": 0,  # No ETH sent for token->ETH swaps
                "nonce": w3.eth.get_transaction_count(account.address),
                "chainId": farmer_config.CHAINS[chain]["chain_id"],
            })

            tx_hash = self.cm.send_transaction(chain, tx, wallet_key)
            logger.info(
                f"Swapped {amount} of {token_in[:10]}... -> ETH on {chain}, tx: {tx_hash}"
            )
            return tx_hash

        except Exception as e:
            logger.error(f"Token->ETH swap failed on {chain}: {e}")
            return None

    def add_liquidity_eth(self, chain, token, amount_token, amount_eth, wallet_key):
        """Add liquidity to an Aerodrome ETH/token pool.

        Args:
            chain: Chain name
            token: Token address to pair with ETH
            amount_token: Raw token amount (smallest units)
            amount_eth: ETH amount (in ETH, e.g. 0.0001)
            wallet_key: Private key

        Returns tx_hash on success, None on failure.
        """
        try:
            w3 = self.cm.get_web3(chain)
            account = self._get_account(wallet_key)
            amount_eth_wei = w3.to_wei(amount_eth, "ether")
            token_addr = Web3.to_checksum_address(token)
            router_addr = Web3.to_checksum_address(farmer_config.AERODROME_ROUTER)

            # Approve token for Aerodrome router
            approve_result = self.approve_token(chain, token, farmer_config.AERODROME_ROUTER, amount_token, wallet_key)
            if approve_result is None:
                logger.error("Token approval failed for liquidity add")
                return None

            if approve_result != "already_approved":
                time.sleep(5)

            # Build addLiquidityETH tx
            router = w3.eth.contract(address=router_addr, abi=AERODROME_ROUTER_ABI)

            # Use 5% slippage for liquidity (wider tolerance for micro amounts)
            amount_token_min = int(amount_token * 0.95)
            amount_eth_min = int(amount_eth_wei * 0.95)

            tx = router.functions.addLiquidityETH(
                token_addr,         # token
                False,              # stable (volatile pair)
                amount_token,       # amountTokenDesired
                amount_token_min,   # amountTokenMin
                amount_eth_min,     # amountETHMin
                account.address,    # to (LP tokens recipient)
                self._get_deadline(),  # deadline
            ).build_transaction({
                "from": account.address,
                "value": amount_eth_wei,
                "nonce": w3.eth.get_transaction_count(account.address),
                "chainId": farmer_config.CHAINS[chain]["chain_id"],
            })

            tx_hash = self.cm.send_transaction(chain, tx, wallet_key)
            logger.info(
                f"Added liquidity: {amount_token} token + {amount_eth} ETH on {chain}, tx: {tx_hash}"
            )
            return tx_hash

        except Exception as e:
            logger.error(f"Add liquidity failed on {chain}: {e}")
            return None

    def remove_liquidity_eth(self, chain, token, liquidity_amount, wallet_key):
        """Remove liquidity from an Aerodrome ETH/token pool.

        Args:
            chain: Chain name
            token: Token address paired with ETH
            liquidity_amount: LP token amount to burn
            wallet_key: Private key

        Returns tx_hash on success, None on failure.
        """
        try:
            w3 = self.cm.get_web3(chain)
            account = self._get_account(wallet_key)
            token_addr = Web3.to_checksum_address(token)
            router_addr = Web3.to_checksum_address(farmer_config.AERODROME_ROUTER)

            router = w3.eth.contract(address=router_addr, abi=AERODROME_ROUTER_ABI)

            tx = router.functions.removeLiquidityETH(
                token_addr,         # token
                False,              # stable (volatile pair)
                liquidity_amount,   # liquidity (LP tokens to burn)
                0,                  # amountTokenMin (accept any for micro amounts)
                0,                  # amountETHMin
                account.address,    # to
                self._get_deadline(),  # deadline
            ).build_transaction({
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address),
                "chainId": farmer_config.CHAINS[chain]["chain_id"],
            })

            tx_hash = self.cm.send_transaction(chain, tx, wallet_key)
            logger.info(
                f"Removed liquidity: {liquidity_amount} LP on {chain}, tx: {tx_hash}"
            )
            return tx_hash

        except Exception as e:
            logger.error(f"Remove liquidity failed on {chain}: {e}")
            return None

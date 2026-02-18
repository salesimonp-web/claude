"""Configuration for the airdrop farmer bot."""

# Chain configurations with RPC failover
CHAINS = {
    "base": {
        "rpcs": ["https://mainnet.base.org", "https://base.llamarpc.com", "https://rpc.ankr.com/base"],
        "chain_id": 8453,
        "avg_gas_cost": 0.15,  # USD per tx
        "eip1559": True,
        "type": "mainnet",
    },
    "arbitrum": {
        "rpcs": ["https://arb1.arbitrum.io/rpc", "https://rpc.ankr.com/arbitrum"],
        "chain_id": 42161,
        "avg_gas_cost": 0.25,
        "eip1559": True,
        "type": "mainnet",
    },
    "optimism": {
        "rpcs": ["https://mainnet.optimism.io", "https://rpc.ankr.com/optimism"],
        "chain_id": 10,
        "avg_gas_cost": 0.15,
        "eip1559": True,
        "type": "mainnet",
    },
    # Testnets (free)
    "monad_testnet": {
        "rpcs": ["https://testnet-rpc.monad.xyz", "https://rpc.ankr.com/monad_testnet"],
        "chain_id": 10143,
        "avg_gas_cost": 0.0,
        "eip1559": False,
        "type": "testnet",
    },
    "berachain_testnet": {
        "rpcs": ["https://bartio.rpc.berachain.com"],
        "chain_id": 80084,
        "avg_gas_cost": 0.0,
        "eip1559": False,
        "type": "testnet",
    },
    "linea_sepolia": {
        "rpcs": ["https://rpc.sepolia.linea.build"],
        "chain_id": 59141,
        "avg_gas_cost": 0.0,
        "eip1559": True,
        "type": "testnet",
    },
}

# Budget
TOTAL_GAS_BUDGET_USD = 2.0
RESERVE_PCT = 0.25
FARMING_DURATION_DAYS = 60

# Timing
MIN_DELAY_HOURS = 2
MAX_DELAY_HOURS = 8
ACTIVE_HOURS = (8, 23)  # UTC
WEEKEND_REDUCTION = 0.5
DAILY_MAX_ACTIONS = 5
MIN_ACTION_USD = 0.10
MAX_ACTION_USD = 0.50

# DEX addresses (Base)
UNISWAP_V3_ROUTER = "0x2626664c2603336E57B271c5C0b26F421741e481"
AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"

# Token addresses (Base)
TOKENS = {
    "base": {
        "WETH": "0x4200000000000000000000000000000000000006",
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "USDbC": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6B1",
        "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    }
}

# File paths
WALLETS_FILE = "farming_wallets.json"
FARM_STATE_FILE = "farm_state.json"
FARM_SCHEDULE_FILE = "farm_schedule.json"

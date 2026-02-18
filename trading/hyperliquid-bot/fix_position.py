"""Fix the open BTC position: add SL and TP that failed earlier"""

import time
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from eth_account import Account
import config

account = Account.from_key(config.API_SECRET)
info = Info(constants.MAINNET_API_URL, skip_ws=True)
exchange = Exchange(account, constants.MAINNET_API_URL, account_address=config.ACCOUNT_ADDRESS)

# Current position: LONG 0.001 BTC @ 68794
entry = 68794.0
size = 0.001

sl_price = float(int(entry * (1 - 0.02)))  # 2% SL = ~67418
tp_price = float(int(entry * (1 + 0.04)))  # 4% TP = ~71546

print(f"Setting SL at ${sl_price:.0f} and TP at ${tp_price:.0f} for BTC long {size}")

# SL (sell to close)
sl_result = exchange.order(
    "BTC", False, size, sl_price,
    {"trigger": {"triggerPx": sl_price, "isMarket": True, "tpsl": "sl"}}
)
print(f"SL result: {sl_result}")
time.sleep(1)

# TP (sell to close)
tp_result = exchange.order(
    "BTC", False, size, tp_price,
    {"trigger": {"triggerPx": tp_price, "isMarket": True, "tpsl": "tp"}}
)
print(f"TP result: {tp_result}")

# Verify
state = info.user_state(config.ACCOUNT_ADDRESS)
for pos in state.get('assetPositions', []):
    if pos['position']['coin'] == 'BTC':
        p = pos['position']
        print(f"\nPosition: {p['szi']} BTC @ ${p['entryPx']}")
        print(f"Unrealized PnL: ${p['unrealizedPnl']}")
        print(f"Liquidation: ${p['liquidationPx']}")

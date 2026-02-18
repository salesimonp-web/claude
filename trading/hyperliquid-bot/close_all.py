"""Close all open positions and cancel all orders"""
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from eth_account import Account
import config

account = Account.from_key(config.API_SECRET)
info = Info(constants.MAINNET_API_URL, skip_ws=True)
exchange = Exchange(account, constants.MAINNET_API_URL, account_address=config.ACCOUNT_ADDRESS)

# Cancel all open orders first
open_orders = info.open_orders(config.ACCOUNT_ADDRESS)
for order in open_orders:
    print(f"Cancelling order {order['oid']} on {order['coin']}")
    exchange.cancel(order['coin'], order['oid'])

# Close all positions
state = info.user_state(config.ACCOUNT_ADDRESS)
for pos in state.get('assetPositions', []):
    p = pos['position']
    size = float(p['szi'])
    if abs(size) > 0:
        coin = p['coin']
        print(f"Closing {coin}: {size}")
        exchange.market_close(coin)

# Final state
state = info.user_state(config.ACCOUNT_ADDRESS)
print(f"\nBalance: ${float(state['marginSummary']['accountValue']):.2f}")

"""Healthcheck for Hyperliquid Bot v5"""
import os
import time
import json
from datetime import datetime


def check_bot_process():
    """Check if bot is running in tmux"""
    result = os.popen("tmux list-panes -t trading -F '#{pane_current_command}' 2>/dev/null").read()
    return "python" in result.lower()


def check_last_log(log_path="trading_bot.log"):
    """Check if bot logged recently (< 5 min)"""
    if not os.path.exists(log_path):
        return False, "No log file"
    mtime = os.path.getmtime(log_path)
    age_sec = time.time() - mtime
    return age_sec < 300, f"Last log: {int(age_sec)}s ago"


def check_balance():
    """Check account balance via API"""
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants
        import config
        info = Info(constants.MAINNET_API_URL, skip_ws=True)
        state = info.user_state(config.ACCOUNT_ADDRESS)
        balance = float(state['marginSummary']['accountValue'])
        positions = [p for p in state.get('assetPositions', [])
                     if abs(float(p['position'].get('szi', 0))) > 0]
        return balance, len(positions)
    except Exception as e:
        return None, str(e)


def check_trades():
    """Summary of recent trades"""
    if os.path.exists("trades_history.json"):
        with open("trades_history.json") as f:
            trades = json.load(f)
        closed = [t for t in trades if t["status"] == "closed"]
        open_t = [t for t in trades if t["status"] == "open"]
        return len(trades), len(closed), len(open_t)
    return 0, 0, 0


def main():
    print("=" * 50)
    print("HEALTHCHECK -- Hyperliquid Bot v5")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # Process
    running = check_bot_process()
    print(f"Bot process: {'OK' if running else 'NOT RUNNING'}")

    # Logs
    log_ok, log_msg = check_last_log()
    print(f"Log freshness: {'OK' if log_ok else 'STALE'} ({log_msg})")

    # Balance
    balance, positions = check_balance()
    if balance is not None:
        print(f"Balance: ${balance:.2f} | Open positions: {positions}")
    else:
        print(f"Balance: ERROR ({positions})")

    # Trades
    total, closed, open_t = check_trades()
    print(f"Trades: {total} total, {closed} closed, {open_t} open")

    # Strategy state
    if os.path.exists("strategy_state.json"):
        with open("strategy_state.json") as f:
            state = json.load(f)
        print(f"Adapter: threshold={state.get('min_score_threshold', '?')}, "
              f"adaptations={state.get('adaptation_count', 0)}")

    # Recent alerts
    if os.path.exists("alerts.log"):
        with open("alerts.log") as f:
            lines = f.readlines()
        recent = lines[-5:] if len(lines) >= 5 else lines
        if recent:
            print(f"Recent alerts ({len(lines)} total):")
            for line in recent:
                print(f"  {line.rstrip()}")
        else:
            print("Alerts: none")
    else:
        print("Alerts: no alerts.log file")

    # Overall status
    all_ok = running and log_ok and balance is not None
    print("=" * 50)
    print(f"STATUS: {'ALL OK' if all_ok else 'ISSUES DETECTED'}")
    print("=" * 50)


if __name__ == "__main__":
    main()

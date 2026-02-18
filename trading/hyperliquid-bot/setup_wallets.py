"""Generate dedicated testnet farming wallets and save to config"""
import os
import json
from eth_account import Account

WALLETS_FILE = "farming_wallets.json"

def generate_wallets(count=3):
    """Generate EVM wallets for testnet farming"""
    wallets = []
    for i in range(count):
        acct = Account.create()
        wallets.append({
            "name": f"farmer_{i+1}",
            "address": acct.address,
            "private_key": acct.key.hex(),
        })
        print(f"Wallet {i+1}: {acct.address}")

    with open(WALLETS_FILE, 'w') as f:
        json.dump(wallets, f, indent=2)
    os.chmod(WALLETS_FILE, 0o600)

    print(f"\nSaved {count} wallets to {WALLETS_FILE}")
    print("Add these to your testnet faucets and bridge interactions")
    return wallets

if __name__ == "__main__":
    if os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, 'r') as f:
            existing = json.load(f)
        print(f"Wallets already exist ({len(existing)}):")
        for w in existing:
            print(f"  {w['name']}: {w['address']}")
    else:
        generate_wallets(3)

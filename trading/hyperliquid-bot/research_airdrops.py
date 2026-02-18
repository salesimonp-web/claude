"""Research active and upcoming airdrops"""
import requests

from env_loader import get_key

PERPLEXITY_KEY = get_key("PERPLEXITY_API_KEY")
OPENROUTER_KEY = get_key("OPENROUTER_API_KEY")

def ask_perplexity(prompt):
    r = requests.post("https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {PERPLEXITY_KEY}", "Content-Type": "application/json"},
        json={"model": "sonar-pro", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": 1500},
        timeout=60)
    return r.json()['choices'][0]['message']['content'] if r.status_code == 200 else f"Error {r.status_code}"

def ask_grok(prompt):
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        json={"model": "x-ai/grok-3", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 1500},
        timeout=60)
    return r.json()['choices'][0]['message']['content'] if r.status_code == 200 else f"Error {r.status_code}"

print("=" * 60)
print("PERPLEXITY: BEST CRYPTO AIRDROPS TO FARM RIGHT NOW")
print("=" * 60)
r1 = ask_perplexity("""What are the BEST crypto airdrops to farm RIGHT NOW in February 2026?
I need:
1. Active confirmed airdrops (token not yet distributed)
2. Testnets worth farming (high probability of airdrop)
3. Protocols where on-chain activity qualifies you
4. Any Hyperliquid ecosystem airdrops
5. Layer 2 airdrops (Monad, Berachain, MegaETH, etc.)
6. DeFi protocol airdrops requiring liquidity or usage

For each, give:
- Name, chain, estimated value
- Exact steps to qualify
- Deadline if known
- Whether it can be automated via API/script
- Wallet requirements (new wallet? specific chain?)

Focus on FREE opportunities (no capital needed) or ones that work with < $20.
Current date: February 10, 2026.""")
print(r1)

print("\n" + "=" * 60)
print("GROK: TWITTER ALPHA ON AIRDROPS")
print("=" * 60)
r2 = ask_grok("""What are crypto Twitter/X users farming for airdrops RIGHT NOW?
1. Which protocols have the highest expected airdrop value?
2. Any new testnets launched this week worth joining?
3. Which chains are doing points programs?
4. Any time-sensitive opportunities about to close?
5. What's the meta for airdrop farming in February 2026?
Be specific: protocol names, links, steps, estimated values.""")
print(r2)

print("\n" + "=" * 60)
print("PERPLEXITY: AUTOMATABLE AIRDROP STRATEGIES")
print("=" * 60)
r3 = ask_perplexity("""Which crypto airdrop farming activities can be AUTOMATED with a Python script?
I have:
- An EC2 server running 24/7
- MetaMask wallet
- Hyperliquid account
- ~$16 in crypto

Which protocols have APIs or on-chain interactions that can be scripted?
Examples: automated testnet faucets, bridge transactions, swap transactions,
daily check-ins, social tasks via API.
Give me specific Python code examples or API endpoints for each.
Focus on highest ROI for minimal effort/capital.
February 2026.""")
print(r3)

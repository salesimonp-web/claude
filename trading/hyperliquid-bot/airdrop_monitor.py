"""Airdrop Monitor — scrapes free sources, filters, reports, and notifies.

Runs every 24h. Sources:
- DeFiLlama airdrops page (scraping)
- Perplexity API (search)
- CoinGecko free API (token verification)

Outputs:
- airdrop_report.json (structured report)
- Telegram notification for new finds
- Log file for debugging
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from env_loader import get_key

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "airdrop_monitor.log")
REPORT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "airdrop_report.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [airdrop-monitor] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCAN_INTERVAL_SEC = 24 * 3600  # 24 h
REQUEST_TIMEOUT = 30
PERPLEXITY_TIMEOUT = 60

WALLET_ADDRESS = "0x8f95dED300a724FEb5ab8C0D2F117891B72F755C"

# Chains we can interact with (EVM compatible)
SUPPORTED_CHAINS = {
    "ethereum", "arbitrum", "base", "optimism", "polygon", "zksync",
    "linea", "scroll", "blast", "manta", "mantle", "mode", "zora",
    "avalanche", "bsc", "gnosis", "fantom", "celo", "moonbeam",
    "hyperliquid", "berachain", "monad", "megaeth",
}

# ---------------------------------------------------------------------------
# Telegram helper (graceful fallback)
# ---------------------------------------------------------------------------

def _send_telegram(text: str) -> bool:
    """Try to send via telegram_notifier. Falls back to logging."""
    try:
        import telegram_notifier
        result = telegram_notifier.send_message(text)
        return result is not None
    except Exception as exc:
        logger.warning("Telegram not available (%s), logging instead.", exc)
        logger.info("TELEGRAM MESSAGE:\n%s", text)
        return False


# ---------------------------------------------------------------------------
# Source 1: DeFiLlama airdrops
# ---------------------------------------------------------------------------

def fetch_defillama_airdrops() -> List[Dict]:
    """Scrape DeFiLlama /airdrops page for active airdrops.

    DeFiLlama exposes protocol data via their API. We look for protocols
    that are tagged/categorised as having upcoming airdrops.
    """
    airdrops: List[Dict] = []

    # DeFiLlama public API — protocols endpoint
    try:
        resp = requests.get(
            "https://api.llama.fi/protocols",
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "airdrop-monitor/1.0"},
        )
        resp.raise_for_status()
        protocols = resp.json()
    except Exception as exc:
        logger.error("DeFiLlama protocols fetch failed: %s", exc)
        return airdrops

    # Filter protocols that have "Airdrop" or related category/tags
    for proto in protocols:
        category = (proto.get("category") or "").lower()
        name = proto.get("name", "")
        chains = proto.get("chains") or []
        tvl = proto.get("tvl") or 0

        # DeFiLlama sometimes marks airdrop-eligible protocols
        # We also look for high-TVL protocols without a token (likely airdrop)
        has_token = bool(proto.get("symbol") and proto.get("gecko_id"))
        has_good_tvl = tvl > 1_000_000  # > $1M TVL

        # Check chain compatibility
        chain_lower = {c.lower() for c in chains}
        compatible = bool(chain_lower & SUPPORTED_CHAINS)

        if not compatible:
            continue

        # Heuristic: no token + good TVL = potential airdrop
        if not has_token and has_good_tvl:
            matched_chains = list(chain_lower & SUPPORTED_CHAINS)
            airdrops.append({
                "name": name,
                "chain": matched_chains[0] if matched_chains else "multi",
                "type": "potential_airdrop",
                "requirements": [
                    f"Use {name} protocol on {', '.join(matched_chains[:3])}",
                    "Generate on-chain activity (swaps, LPs, bridges)",
                ],
                "deadline": "unknown",
                "estimated_value": "unknown",
                "kyc_required": False,
                "cost": "gas only",
                "source": "defillama",
                "url": proto.get("url", ""),
                "tvl": tvl,
            })

    logger.info("DeFiLlama: found %d potential airdrop protocols", len(airdrops))
    return airdrops


# ---------------------------------------------------------------------------
# Source 2: Perplexity AI search
# ---------------------------------------------------------------------------

def fetch_perplexity_airdrops() -> List[Dict]:
    """Use Perplexity API to find active airdrops."""
    api_key = get_key("PERPLEXITY_API_KEY", required=False)
    if not api_key:
        logger.warning("PERPLEXITY_API_KEY not set, skipping Perplexity source")
        return []

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = (
        f"Date: {today}. List all ACTIVE crypto airdrops and testnet farming "
        f"opportunities available RIGHT NOW. For each, provide:\n"
        f"1. Protocol name\n"
        f"2. Chain (Ethereum, Arbitrum, Base, etc.)\n"
        f"3. Type: airdrop / testnet / points_program\n"
        f"4. Requirements to qualify (specific steps)\n"
        f"5. Deadline if known\n"
        f"6. Estimated value range\n"
        f"7. Whether KYC is required (yes/no)\n"
        f"8. Cost to participate (free / gas only / capital needed)\n"
        f"9. URL or link\n\n"
        f"Focus on:\n"
        f"- FREE opportunities (no capital needed) or gas-only\n"
        f"- No KYC required\n"
        f"- EVM compatible chains\n"
        f"- Hyperliquid ecosystem airdrops\n"
        f"- Active testnets (Monad, Berachain, MegaETH, etc.)\n"
        f"- Points programs still running\n\n"
        f"Format each as a numbered list with clear fields."
    )

    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar-pro",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 2000,
            },
            timeout=PERPLEXITY_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.error("Perplexity API error %d: %s", resp.status_code, resp.text[:200])
            return []

        content = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.error("Perplexity request failed: %s", exc)
        return []

    # Parse the AI response into structured data
    return _parse_perplexity_response(content)


def _parse_perplexity_response(text: str) -> List[Dict]:
    """Best-effort extraction of airdrops from Perplexity prose."""
    airdrops: List[Dict] = []

    # Split by numbered items or bold headers
    blocks = re.split(r"\n(?=\d+[\.\)]\s|\*\*[A-Z])", text)

    for block in blocks:
        block = block.strip()
        if len(block) < 30:
            continue

        # Try to extract a name from first line / bold text
        name_match = re.search(r"\*\*(.+?)\*\*", block)
        if not name_match:
            name_match = re.search(r"^\d+[\.\)]\s*(.+?)(?:\n|$)", block)
        if not name_match:
            continue
        name = name_match.group(1).strip().rstrip(":")

        # Extract chain
        chain = "unknown"
        for c in SUPPORTED_CHAINS:
            if c.lower() in block.lower():
                chain = c
                break

        # Detect type
        atype = "interaction"
        block_lower = block.lower()
        if "testnet" in block_lower:
            atype = "testnet"
        elif "points" in block_lower:
            atype = "points_program"
        elif "claim" in block_lower:
            atype = "claim"

        # KYC
        kyc = False
        if re.search(r"kyc.{0,5}(required|yes|needed|mandatory)", block_lower):
            kyc = True

        # Cost
        cost = "gas only"
        if "free" in block_lower:
            cost = "free"
        elif "capital" in block_lower or "deposit" in block_lower:
            cost = "capital needed"

        # Deadline
        deadline = "unknown"
        deadline_match = re.search(r"deadline[:\s]*([^\n,]+)", block_lower)
        if not deadline_match:
            deadline_match = re.search(r"(20\d{2}[-/]\d{1,2}[-/]\d{1,2})", block)
        if deadline_match:
            deadline = deadline_match.group(1).strip()

        # Estimated value
        value = "unknown"
        value_match = re.search(r"\$[\d,]+\s*[-–]\s*\$?[\d,]+", block)
        if not value_match:
            value_match = re.search(r"\$[\d,]+\+?", block)
        if value_match:
            value = value_match.group(0)

        # URL
        url = ""
        url_match = re.search(r"https?://[^\s\)\"']+", block)
        if url_match:
            url = url_match.group(0)

        # Requirements (lines that look like steps)
        requirements = []
        for line in block.split("\n"):
            line = line.strip()
            if re.match(r"^[-*]\s", line) or re.match(r"^\d+[\.\)]\s", line):
                cleaned = re.sub(r"^[-*\d\.\)]+\s*", "", line).strip()
                if len(cleaned) > 10 and "name" not in cleaned.lower()[:10]:
                    requirements.append(cleaned)

        if not requirements:
            requirements = [f"Interact with {name} protocol"]

        airdrops.append({
            "name": name,
            "chain": chain,
            "type": atype,
            "requirements": requirements[:5],
            "deadline": deadline,
            "estimated_value": value,
            "kyc_required": kyc,
            "cost": cost,
            "source": "perplexity",
            "url": url,
        })

    logger.info("Perplexity: parsed %d airdrops from response", len(airdrops))
    return airdrops


# ---------------------------------------------------------------------------
# Source 3: CoinGecko — verify tokens / find protocols without token
# ---------------------------------------------------------------------------

def verify_with_coingecko(airdrops: List[Dict]) -> List[Dict]:
    """Enrich airdrops with CoinGecko data. Mark already-launched tokens."""
    # CoinGecko free API: 10-30 calls/min, no key needed
    verified: List[Dict] = []

    for ad in airdrops:
        name_slug = ad["name"].lower().replace(" ", "-").replace(".", "")

        try:
            resp = requests.get(
                f"https://api.coingecko.com/api/v3/search",
                params={"query": ad["name"]},
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "airdrop-monitor/1.0"},
            )
            if resp.status_code == 200:
                data = resp.json()
                coins = data.get("coins", [])

                # If token already exists and is trading, the airdrop might be over
                if coins:
                    top = coins[0]
                    market_cap_rank = top.get("market_cap_rank")
                    ad["coingecko_id"] = top.get("id", "")
                    ad["token_exists"] = True
                    ad["market_cap_rank"] = market_cap_rank
                else:
                    ad["token_exists"] = False
                    ad["market_cap_rank"] = None
            else:
                ad["token_exists"] = None
                ad["market_cap_rank"] = None

        except Exception as exc:
            logger.debug("CoinGecko lookup failed for %s: %s", ad["name"], exc)
            ad["token_exists"] = None
            ad["market_cap_rank"] = None

        verified.append(ad)

        # Rate limit: ~2 req/sec for free tier
        time.sleep(0.6)

    return verified


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_airdrops(airdrops: List[Dict]) -> List[Dict]:
    """Keep only airdrops matching our criteria."""
    filtered = []
    seen_names = set()

    for ad in airdrops:
        name_lower = ad["name"].lower()

        # Skip duplicates
        if name_lower in seen_names:
            continue
        seen_names.add(name_lower)

        # Skip if KYC required
        if ad.get("kyc_required"):
            logger.debug("Skipping %s: KYC required", ad["name"])
            continue

        # Skip if capital needed (we have ~$16)
        if ad.get("cost", "").lower() in ("capital needed",):
            logger.debug("Skipping %s: capital needed", ad["name"])
            continue

        # Skip if chain not supported
        chain = ad.get("chain", "").lower()
        if chain and chain != "unknown" and chain != "multi" and chain not in SUPPORTED_CHAINS:
            logger.debug("Skipping %s: unsupported chain %s", ad["name"], chain)
            continue

        # If token already exists with high market cap rank, airdrop likely done
        if ad.get("token_exists") and ad.get("market_cap_rank") and ad["market_cap_rank"] < 200:
            logger.debug("Skipping %s: token already live (rank %s)", ad["name"], ad["market_cap_rank"])
            continue

        filtered.append(ad)

    logger.info("Filtered: %d -> %d airdrops", len(airdrops), len(filtered))
    return filtered


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _load_previous_report() -> Dict:
    """Load previous report to detect new airdrops."""
    if os.path.exists(REPORT_FILE):
        try:
            with open(REPORT_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"airdrops": []}


def generate_report(airdrops: List[Dict]) -> Dict:
    """Build the final JSON report."""
    # Sort: Hyperliquid-related first, then by source diversity
    def sort_key(ad):
        hl_bonus = 0 if "hyperliquid" in ad.get("chain", "").lower() or "hyperliquid" in ad.get("name", "").lower() else 1
        return (hl_bonus, ad.get("source", "z"), ad.get("name", ""))

    airdrops.sort(key=sort_key)

    # Clean up internal fields before saving
    clean = []
    for ad in airdrops:
        entry = {
            "name": ad["name"],
            "chain": ad.get("chain", "unknown"),
            "type": ad.get("type", "interaction"),
            "requirements": ad.get("requirements", []),
            "deadline": ad.get("deadline", "unknown"),
            "estimated_value": ad.get("estimated_value", "unknown"),
            "kyc_required": ad.get("kyc_required", False),
            "cost": ad.get("cost", "gas only"),
            "source": ad.get("source", "unknown"),
            "url": ad.get("url", ""),
        }
        clean.append(entry)

    report = {
        "last_scan": datetime.now(timezone.utc).isoformat(),
        "wallet": WALLET_ADDRESS,
        "total_found": len(clean),
        "airdrops": clean,
    }
    return report


def save_report(report: Dict):
    """Write report to JSON file."""
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("Report saved to %s (%d airdrops)", REPORT_FILE, len(report["airdrops"]))


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def notify_new_airdrops(report: Dict, previous: Dict):
    """Send Telegram notification for newly discovered airdrops."""
    prev_names = {a["name"].lower() for a in previous.get("airdrops", [])}
    new_ones = [a for a in report["airdrops"] if a["name"].lower() not in prev_names]

    if not new_ones:
        logger.info("No new airdrops since last scan")
        return

    logger.info("Found %d NEW airdrops, sending notification", len(new_ones))

    lines = [f"<b>AIRDROP MONITOR — {len(new_ones)} new</b>\n"]
    for ad in new_ones[:10]:  # Max 10 in one message
        lines.append(
            f"<b>{ad['name']}</b> ({ad['chain']})\n"
            f"  Type: {ad['type']} | Cost: {ad['cost']}\n"
            f"  Deadline: {ad['deadline']}\n"
            f"  Value: {ad['estimated_value']}"
        )
    lines.append(f"\nTotal tracked: {report['total_found']}")

    _send_telegram("\n".join(lines))


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def run_scan():
    """Execute one full scan cycle."""
    logger.info("=" * 60)
    logger.info("AIRDROP MONITOR SCAN STARTED — %s", datetime.now(timezone.utc).isoformat())
    logger.info("=" * 60)

    previous = _load_previous_report()

    # Gather from all sources
    all_airdrops: List[Dict] = []

    logger.info("--- Source 1: DeFiLlama ---")
    all_airdrops.extend(fetch_defillama_airdrops())

    logger.info("--- Source 2: Perplexity ---")
    all_airdrops.extend(fetch_perplexity_airdrops())

    logger.info("--- CoinGecko verification ---")
    # Only verify Perplexity results (DeFiLlama already has TVL data)
    # Limit CoinGecko calls to avoid rate limiting
    perplexity_airdrops = [a for a in all_airdrops if a.get("source") == "perplexity"]
    defillama_airdrops = [a for a in all_airdrops if a.get("source") == "defillama"]

    verified_perplexity = verify_with_coingecko(perplexity_airdrops[:20])
    all_airdrops = defillama_airdrops + verified_perplexity

    logger.info("--- Filtering ---")
    filtered = filter_airdrops(all_airdrops)

    logger.info("--- Generating report ---")
    report = generate_report(filtered)
    save_report(report)

    logger.info("--- Notifications ---")
    notify_new_airdrops(report, previous)

    logger.info("SCAN COMPLETE: %d airdrops in report", len(report["airdrops"]))
    return report


def run_loop():
    """Run the monitor in a loop (every 24h)."""
    logger.info("Airdrop Monitor starting in loop mode (every %dh)", SCAN_INTERVAL_SEC // 3600)

    while True:
        try:
            run_scan()
        except KeyboardInterrupt:
            logger.info("Airdrop Monitor stopped by user")
            break
        except Exception as exc:
            logger.error("Scan failed: %s", exc, exc_info=True)

        logger.info("Next scan in %d hours", SCAN_INTERVAL_SEC // 3600)
        try:
            time.sleep(SCAN_INTERVAL_SEC)
        except KeyboardInterrupt:
            logger.info("Airdrop Monitor stopped by user")
            break


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--loop" in sys.argv:
        run_loop()
    else:
        # Single scan
        run_scan()

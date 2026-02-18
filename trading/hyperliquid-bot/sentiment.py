"""AI-powered macro analysis — Perplexity only (OpenRouter credits exhausted)"""

import logging
import re
import requests
from datetime import datetime
from typing import Optional, Dict
import config

logger = logging.getLogger(__name__)

# Phrases indicating Grok couldn't provide useful analysis
USELESS_PHRASES = [
    "unable to provide",
    "i'm unable",
    "do not include",
    "cannot access",
    "no direct twitter",
    "lack real-time",
    "not include direct twitter",
    "does not include current twitter",
    "no current twitter",
    "limited direct",
]


class SentimentAnalyzer:
    def __init__(self):
        # Keys read dynamically from config (which uses env_loader)
        pass

    def _extract_score(self, text: str) -> float:
        """Extract sentiment score from AI response using multiple methods"""
        text_lower = text.lower()

        # Method 1: Look for SCORE: pattern anywhere
        for line in text.strip().split('\n'):
            match = re.search(r'score[:\s]+([+-]?\d+\.?\d*)', line, re.IGNORECASE)
            if match:
                try:
                    return max(-1.0, min(1.0, float(match.group(1))))
                except ValueError:
                    pass

        # Method 2: Look for standalone decimal pattern like "-0.6" or "+0.7"
        matches = re.findall(r'(?:^|\s)([+-]?0\.\d+)(?:\s|$|\.)', text)
        if matches:
            try:
                return max(-1.0, min(1.0, float(matches[-1])))
            except ValueError:
                pass

        # Method 3: Keyword counting
        bullish_words = ['bullish', 'recovery', 'bounce', 'support holding', 'accumulation',
                         'buying', 'upside', 'breakout', 'rally', 'momentum up']
        bearish_words = ['bearish', 'breakdown', 'crash', 'capitulation', 'sell-off',
                         'declining', 'downside', 'dump', 'lower', 'weak', 'bearish momentum',
                         'strong bearish', 'negative momentum']

        bull_count = sum(1 for w in bullish_words if w in text_lower)
        bear_count = sum(1 for w in bearish_words if w in text_lower)

        if bear_count > bull_count:
            return -0.6 if bear_count >= 4 else (-0.4 if bear_count >= 2 else -0.2)
        elif bull_count > bear_count:
            return 0.6 if bull_count >= 4 else (0.4 if bull_count >= 2 else 0.2)

        return 0.0

    def _is_useless_response(self, text: str) -> bool:
        """Detect when Grok can't provide useful analysis (no Twitter access)"""
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in USELESS_PHRASES)

    def get_perplexity_analysis(self, asset: str) -> Optional[Dict]:
        """Get macro analysis + directional bias from Perplexity"""
        if not config.PERPLEXITY_API_KEY:
            return None

        try:
            today = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
            prompt = (
                f"You are a crypto trading analyst. Analyze {asset} market conditions right now ({today}). "
                f"Cover: price action, key support/resistance levels, recent news catalysts, "
                f"funding rates, whale activity, and macro factors. "
                f"Then give a directional score from -1.0 (very bearish) to +1.0 (very bullish). "
                f"Format your last line EXACTLY as: SCORE: [number]"
            )

            response = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.PERPLEXITY_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "sonar-pro",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 400
                },
                timeout=45
            )

            if response.status_code == 200:
                result = response.json()
                analysis = result['choices'][0]['message']['content']
                logger.info("Perplexity [%s]: %s...", asset, analysis[:200])

                score = self._extract_score(analysis)
                return {"analysis": analysis, "score": score}
            else:
                logger.error("Perplexity API error: %s", response.status_code)
                return None

        except Exception as e:
            logger.error("Perplexity error for %s: %s", asset, e)
            return None

    def get_twitter_sentiment(self, asset: str) -> Optional[Dict]:
        """Get Twitter/X sentiment via Grok"""
        if not config.OPENROUTER_API_KEY:
            return None

        try:
            ticker_map = {
                "BTC": "Bitcoin $BTC",
                "ETH": "Ethereum $ETH",
                "SOL": "Solana $SOL",
                "HYPE": "Hyperliquid $HYPE"
            }
            search_term = ticker_map.get(asset, f"${asset}")

            prompt = (
                f"Analyze current Twitter/X sentiment for {search_term}. "
                f"What are traders saying? Any notable calls from big accounts? "
                f"Key levels being discussed? Overall mood? "
                f"Give a directional score from -1.0 (very bearish) to +1.0 (very bullish). "
                f"Format your last line EXACTLY as: SCORE: [number]"
            )

            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": config.GROK_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 400
                },
                timeout=45
            )

            if response.status_code == 200:
                result = response.json()
                analysis = result['choices'][0]['message']['content']
                logger.info("Grok [%s]: %s...", asset, analysis[:200])

                # Detect useless responses
                if self._is_useless_response(analysis):
                    logger.info("Grok [%s]: useless response (no Twitter data), skipping", asset)
                    return None

                score = self._extract_score(analysis)
                return {"score": score, "analysis": analysis}
            else:
                logger.error("Grok API error: %s", response.status_code)
                return None

        except Exception as e:
            logger.error("Grok error for %s: %s", asset, e)
            return None

    def get_combined_bias(self, asset: str) -> Dict:
        """Get directional bias from Perplexity (Grok disabled — no OpenRouter credits)"""
        score = 0.0
        analyses = {}
        sources = 0

        perplexity = self.get_perplexity_analysis(asset)
        if perplexity:
            score = perplexity["score"]
            analyses["perplexity"] = perplexity["analysis"]
            sources = 1

        # Direct score -> bias (no averaging dilution)
        if score <= -0.25:
            bias = "SHORT"
        elif score >= 0.25:
            bias = "LONG"
        else:
            bias = "NEUTRAL"

        logger.info("AI bias for %s: %s (score: %.2f, source: Perplexity)", asset, bias, score)

        return {
            "bias": bias,
            "score": score,
            "analyses": analyses,
            "sources": sources
        }

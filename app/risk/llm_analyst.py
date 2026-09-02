"""LLM-powered wallet suspicion analysis using Google Gemini 2.5 Flash.

Sends a compact summary of the transaction graph to Gemini and asks it to
score each wallet on a 0-100 suspicion scale with a label and reasoning.

Output per wallet:
  - suspicion_score : int  0-100
  - label           : str  "clean" | "suspicious" | "highly_suspicious" | "unknown"
  - reason          : str  one-sentence explanation
  - flags           : list[str]  e.g. ["mixer_interaction", "rapid_layering", "large_outflow"]

Design decisions:
  - We send at most 60 wallets to Gemini (the most important ones by degree).
    More than that and the prompt becomes too large and expensive.
  - We use Gemini 2.5 Flash (gemini-2.5-flash) — cheapest capable model.
  - We ask for strict JSON output so we can parse it reliably.
  - If the API key is missing or the call fails, we return empty results
    gracefully — analysis is best-effort, not blocking.
  - Results are cached in-memory per trace_id for the lifetime of the process
    to avoid burning API quota on repeated loads.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import networkx as nx

logger = logging.getLogger(__name__)

# In-process cache: trace_id -> list[WalletAnalysis]
_CACHE: dict[str, list["WalletAnalysis"]] = {}

# Maximum wallets to send to Gemini per request
_MAX_WALLETS = 60

# Suspicion label thresholds
LABEL_THRESHOLDS = {
    "highly_suspicious": 70,
    "suspicious":        40,
    "clean":              0,
}


@dataclass
class WalletAnalysis:
    address:         str
    suspicion_score: int          # 0-100
    label:           str          # clean | suspicious | highly_suspicious | unknown
    reason:          str
    flags:           list[str] = field(default_factory=list)


def score_to_label(score: int) -> str:
    if score >= 70:
        return "highly_suspicious"
    if score >= 40:
        return "suspicious"
    return "clean"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def analyse_graph(
    trace_id: str,
    seed_address: str,
    chain: str,
    G: nx.DiGraph,
) -> list[WalletAnalysis]:
    """Analyse every wallet in *G* and return suspicion scores from Gemini.

    Returns cached results if available.  Returns [] gracefully if the API
    key is not configured or Gemini returns an unexpected response.
    """
    if trace_id in _CACHE:
        return _CACHE[trace_id]

    from app.config import get_settings
    settings = get_settings()
    api_key = settings.gemini_api_key
    if not api_key:
        logger.info("llm_analyst: GEMINI_API_KEY not set — skipping LLM analysis")
        return []

    # Build the wallet summary we'll send to Gemini
    wallets = _build_wallet_summaries(G, seed_address, chain)
    if not wallets:
        return []

    try:
        results = await _call_gemini(api_key, seed_address, chain, wallets)
    except Exception:
        logger.exception("llm_analyst: Gemini call failed for trace %s", trace_id)
        return []

    _CACHE[trace_id] = results
    return results


def get_cached(trace_id: str) -> list[WalletAnalysis]:
    """Return cached analysis results without making a new API call."""
    return _CACHE.get(trace_id, [])


def invalidate_cache(trace_id: str) -> None:
    _CACHE.pop(trace_id, None)


# ---------------------------------------------------------------------------
# Graph → prompt summary
# ---------------------------------------------------------------------------


def _build_wallet_summaries(
    G: nx.DiGraph,
    seed_address: str,
    chain: str,
) -> list[dict]:
    """Summarise each node as a compact dict for the prompt.

    Selects the top _MAX_WALLETS nodes by total degree, always including the
    seed address.
    """
    nodes = list(G.nodes(data=True))

    # Sort by total degree descending, seed always first
    def sort_key(item):
        addr, attrs = item
        if addr == seed_address:
            return 10_000_000
        return (attrs.get("in_degree", 0) + attrs.get("out_degree", 0))

    nodes.sort(key=sort_key, reverse=True)
    nodes = nodes[:_MAX_WALLETS]

    summaries = []
    for addr, attrs in nodes:
        # Build edge context: who sent to this wallet, who this wallet sent to
        predecessors = list(G.predecessors(addr))[:5]
        successors   = list(G.successors(addr))[:5]

        # Find max single transaction amount through this node
        in_amounts  = [G[p][addr].get("amount", 0)  for p in G.predecessors(addr)]
        out_amounts = [G[addr][s].get("amount", 0)  for s in G.successors(addr)]
        max_in  = max(in_amounts,  default=0)
        max_out = max(out_amounts, default=0)

        # Timing
        first_seen = attrs.get("first_seen", "")
        last_seen  = attrs.get("last_seen",  "")

        summaries.append({
            "address":       addr,
            "chain":         chain,
            "is_seed":       addr == seed_address,
            "in_degree":     attrs.get("in_degree",     0),
            "out_degree":    attrs.get("out_degree",    0),
            "total_inflow":  round(float(attrs.get("total_inflow",  0)), 6),
            "total_outflow": round(float(attrs.get("total_outflow", 0)), 6),
            "max_single_in":  round(float(max_in),  6),
            "max_single_out": round(float(max_out), 6),
            "first_seen":    first_seen,
            "last_seen":     last_seen,
            "sends_to":      successors,
            "receives_from": predecessors,
        })

    return summaries


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a blockchain forensics analyst assisting law enforcement.
You will receive a list of wallet addresses and their transaction statistics from a
blockchain trace investigation. Your job is to score each wallet on a suspicion scale.

SCORING GUIDE (0-100):
  0-39   CLEAN       — normal user behaviour, no red flags
  40-69  SUSPICIOUS  — some indicators: layering, smurfing, mixer interaction, rapid movement
  70-100 HIGHLY SUSPICIOUS — strong indicators: direct mixer/tornado cash interaction,
                             peel chains, structuring to avoid detection, known exploit patterns,
                             funds splitting across many wallets immediately after receipt

IMPORTANT FLAGS to check for:
  - mixer_interaction: sends to known mixer contracts (Tornado Cash, ChipMixer etc.)
  - rapid_layering: receives and immediately sends entire balance
  - peel_chain: long chain of wallets each passing funds to next
  - fan_out: one wallet splitting to many simultaneously
  - fan_in: many wallets aggregating into one (collection wallet)
  - large_sudden_inflow: massive inflow with no prior history
  - structuring: many small transactions just below round numbers
  - dormant_then_active: long gap between first and last seen

Respond ONLY with valid JSON — no markdown, no explanation outside the JSON.
Format:
{
  "wallets": [
    {
      "address": "0x...",
      "suspicion_score": 75,
      "label": "highly_suspicious",
      "reason": "One sentence explanation.",
      "flags": ["mixer_interaction", "rapid_layering"]
    }
  ]
}"""


async def _call_gemini(
    api_key: str,
    seed_address: str,
    chain: str,
    wallets: list[dict],
) -> list[WalletAnalysis]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    user_content = (
        f"Investigate this {chain} blockchain trace. "
        f"Seed (suspect) wallet: {seed_address}\n\n"
        f"Wallet data:\n{json.dumps(wallets, indent=2)}"
    )

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.1,    # low temperature for consistent scoring
            max_output_tokens=8192,
        ),
    )

    raw = response.text or ""

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("llm_analyst: could not parse Gemini response as JSON: %s", raw[:200])
        return []

    results: list[WalletAnalysis] = []
    for w in parsed.get("wallets", []):
        try:
            score = int(w.get("suspicion_score", 0))
            score = max(0, min(100, score))
            results.append(WalletAnalysis(
                address=str(w["address"]),
                suspicion_score=score,
                label=w.get("label", score_to_label(score)),
                reason=str(w.get("reason", "")),
                flags=list(w.get("flags", [])),
            ))
        except (KeyError, ValueError, TypeError):
            continue

    logger.info(
        "llm_analyst: Gemini returned %d wallet analyses (seed=%s)",
        len(results), seed_address[:12],
    )
    return results

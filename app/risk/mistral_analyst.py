"""Mistral AI generative fraud analysis for blockchain wallet traces.

Three-tier prompt strategy based on rule-based risk score:
  - LOW   (0-39):  quick legitimacy confirmation
  - AMBIGUOUS (40-74): deep analysis, missing-data suggestions, refined score
  - HIGH  (75-100): crime-type identification, prosecution evidence, action plan

Uses few-shot learning from known criminal / legitimate cases embedded in the
system prompt so Mistral anchors its reasoning on real-world precedents.

HTTP transport: plain httpx (mistralai pip package broken in this conda env).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import networkx as nx

logger = logging.getLogger(__name__)

_MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
_MODEL       = "mistral-small-latest"
_TIMEOUT     = 45.0  # seconds

# In-process cache keyed by trace_id
_CACHE: dict[str, "MistralVerdict"] = {}


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass
class MistralVerdict:
    # Core verdict
    is_fraud:          bool
    confidence:        int            # 0-100
    refined_score:     int            # 0-100
    verdict_label:     str            # "legitimate" | "suspicious" | "fraud"
    crime_type:        str            # e.g. "ransomware mixing" or "trading bot"

    # Explanation
    summary:           str            # 1-2 sentence plain English
    evidence_chain:    list[str] = field(default_factory=list)   # bullet points for prosecution
    missing_data:      list[str] = field(default_factory=list)   # what more investigators need
    recommendations:   list[str] = field(default_factory=list)   # actionable next steps

    # Meta
    prompt_tier:       str = "low"    # "low" | "ambiguous" | "high"
    raw_response:      str = ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def analyse_trace(
    trace_id:  str,
    wallet:    str,
    chain:     str,
    G:         nx.DiGraph,
    rule_score: int,
) -> MistralVerdict:
    """Run Mistral fraud analysis for a trace.  Returns cached result if available."""
    if trace_id in _CACHE:
        return _CACHE[trace_id]

    from app.config import get_settings
    api_key = get_settings().mistral_api_key
    if not api_key:
        return _empty_verdict("MISTRAL_API_KEY not configured")

    metrics  = _extract_metrics(G, wallet)
    tier     = _select_tier(rule_score)
    messages = _build_messages(tier, wallet, chain, metrics, rule_score)

    try:
        raw = await _call_mistral(api_key, messages)
        verdict = _parse_response(raw, tier, rule_score)
    except Exception:
        logger.exception("mistral_analyst: API call failed for trace %s", trace_id)
        return _empty_verdict("Mistral API call failed")

    _CACHE[trace_id] = verdict
    return verdict


def get_cached(trace_id: str) -> MistralVerdict | None:
    return _CACHE.get(trace_id)


def invalidate_cache(trace_id: str) -> None:
    _CACHE.pop(trace_id, None)


# ---------------------------------------------------------------------------
# Graph → metrics summary
# ---------------------------------------------------------------------------

def _extract_metrics(G: nx.DiGraph, seed: str) -> dict[str, Any]:
    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()

    # Aggregate inflow/outflow across all nodes
    total_in  = sum(float(d.get("total_inflow",  0)) for _, d in G.nodes(data=True))
    total_out = sum(float(d.get("total_outflow", 0)) for _, d in G.nodes(data=True))

    # Count unique senders / receivers from edges
    senders   = {e[0] for e in G.edges()}
    receivers = {e[1] for e in G.edges()}

    # Detected entity types
    entity_counts: dict[str, int] = {}
    for _, d in G.nodes(data=True):
        et = str(d.get("entity_type", "unknown")).lower()
        entity_counts[et] = entity_counts.get(et, 0) + 1

    flagged_nodes = [
        n for n, d in G.nodes(data=True)
        if str(d.get("entity_type", "")).lower() in ("flagged", "mixer")
    ]

    # Time span
    timestamps = []
    for _, _, d in G.edges(data=True):
        ts = d.get("timestamp")
        if ts:
            timestamps.append(str(ts))
    timestamps.sort()
    time_span = f"{timestamps[0][:10]} → {timestamps[-1][:10]}" if len(timestamps) >= 2 else "unknown"

    # Peel-chain detection: long linear sequences
    max_chain = _longest_chain(G)

    return {
        "wallet":          seed,
        "n_wallets":       n_nodes,
        "n_transactions":  n_edges,
        "n_senders":       len(senders),
        "n_receivers":     len(receivers),
        "total_inflow":    round(total_in,  4),
        "total_outflow":   round(total_out, 4),
        "entity_types":    entity_counts,
        "flagged_count":   len(flagged_nodes),
        "flagged_wallets": flagged_nodes[:5],
        "time_span":       time_span,
        "longest_chain":   max_chain,
    }


def _longest_chain(G: nx.DiGraph) -> int:
    """Approximate longest directed path length (BFS from zero-in-degree nodes)."""
    try:
        return nx.dag_longest_path_length(G) if nx.is_directed_acyclic_graph(G) else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

_FEW_SHOT_HEADER = """You are a blockchain forensics AI assistant for law enforcement.

## KNOWN CRIMINAL CASES (for reference):

CASE 1 — Colonial Pipeline Ransomware
- Patterns: MIXER, RAPID_DISPERSION, many fan-out hops
- Rule score: 99/100 | Outcome: Confirmed ransomware
- Key indicator: Tornado Cash connection, funds split to 50+ wallets within 1 hour

CASE 2 — BitFinex Hack Laundering
- Patterns: LAYERING, CHAIN_HOPPING, dormant wallet activation
- Rule score: 96/100 | Outcome: Confirmed large-scale laundering
- Key indicator: Long dormancy then sudden multi-million movement

CASE 3 — Romance Scam Aggregation
- Patterns: FAN_IN, multiple victims → single wallet
- Rule score: 78/100 | Outcome: Confirmed fraud
- Key indicator: Hundreds of small inflows from unrelated wallets

CASE 4 — Legitimate HFT Bot
- Patterns: HIGH_VELOCITY, MULTIPLE_TRANSFERS
- Rule score: 18/100 | Outcome: Confirmed legitimate
- Key indicator: Consistent timing, known exchange addresses

CASE 5 — Legitimate Crypto Exchange
- Patterns: HIGH_VOLUME, MANY_COUNTERPARTIES
- Rule score: 12/100 | Outcome: Confirmed legitimate
- Key indicator: KYC-verified addresses, transparent flow

## YOUR TASK:
Analyze the wallet data below using the cases above as references.
ALWAYS respond with valid JSON only — no markdown, no prose outside the JSON.
"""

_JSON_SCHEMA = """
Respond ONLY with this JSON (no markdown code fences):
{
  "is_fraud": true/false,
  "confidence": 0-100,
  "refined_score": 0-100,
  "verdict_label": "legitimate" | "suspicious" | "fraud",
  "crime_type": "string describing activity type",
  "summary": "1-2 sentence plain English verdict",
  "evidence_chain": ["point 1", "point 2", ...],
  "missing_data": ["data point 1", ...],
  "recommendations": ["action 1", "action 2", ...]
}
"""


def _build_messages(
    tier: str,
    wallet: str,
    chain: str,
    metrics: dict,
    rule_score: int,
) -> list[dict]:
    system = _FEW_SHOT_HEADER + _JSON_SCHEMA

    if tier == "low":
        user = f"""LOW RISK WALLET ANALYSIS

Wallet: {wallet} | Chain: {chain}
Rule-based score: {rule_score}/100

Wallet metrics:
{json.dumps(metrics, indent=2)}

This score is low. Quickly confirm legitimacy and provide:
1. Activity type (trading bot, exchange, personal wallet, etc.)
2. Refined risk score
3. Confidence level
4. Any minor concerns if present
"""

    elif tier == "ambiguous":
        user = f"""AMBIGUOUS WALLET — DEEP ANALYSIS REQUIRED

Wallet: {wallet} | Chain: {chain}
Rule-based score: {rule_score}/100 (40-74 range — needs clarification)

Wallet metrics:
{json.dumps(metrics, indent=2)}

This score is ambiguous. Please:
1. Assess likely activity type
2. Identify what additional data would resolve ambiguity
3. Provide refined risk score with confidence
4. Determine if criminal investigation is warranted
5. Compare to known cases above
"""

    else:  # high
        user = f"""HIGH-RISK WALLET — CRIMINAL INVESTIGATION

Wallet: {wallet} | Chain: {chain}
Rule-based score: {rule_score}/100 (HIGH RISK)

Wallet metrics:
{json.dumps(metrics, indent=2)}

This wallet shows high-risk patterns. Please:
1. Confirm if this is likely criminal activity
2. Identify specific crime type (ransomware, money laundering, scam, etc.)
3. Build evidence chain suitable for prosecution
4. Provide actionable recommendations (exchanges to contact, agencies to notify)
5. Compare to known criminal cases above
6. Explain what makes this similar/different from known cases
"""

    return [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]


def _select_tier(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 40:
        return "ambiguous"
    return "low"


# ---------------------------------------------------------------------------
# Mistral HTTP call
# ---------------------------------------------------------------------------

async def _call_mistral(api_key: str, messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            _MISTRAL_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json={
                "model":      _MODEL,
                "messages":   messages,
                "max_tokens": 1200,
                "temperature": 0.15,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(raw: str, tier: str, rule_score: int) -> MistralVerdict:
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    text = re.sub(r"\s*```$",          "", text.strip())

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("mistral_analyst: failed to parse JSON: %s", raw[:300])
        return _empty_verdict("Could not parse Mistral response")

    refined = int(data.get("refined_score", rule_score))
    conf    = int(data.get("confidence",    50))
    refined = max(0, min(100, refined))
    conf    = max(0, min(100, conf))

    label = str(data.get("verdict_label", "unknown")).lower()
    if label not in ("legitimate", "suspicious", "fraud"):
        label = "fraud" if refined >= 70 else ("suspicious" if refined >= 40 else "legitimate")

    return MistralVerdict(
        is_fraud        = bool(data.get("is_fraud", refined >= 70)),
        confidence      = conf,
        refined_score   = refined,
        verdict_label   = label,
        crime_type      = str(data.get("crime_type", "unknown")),
        summary         = str(data.get("summary",    "")),
        evidence_chain  = [str(x) for x in data.get("evidence_chain",  [])],
        missing_data    = [str(x) for x in data.get("missing_data",    [])],
        recommendations = [str(x) for x in data.get("recommendations", [])],
        prompt_tier     = tier,
        raw_response    = raw,
    )


def _empty_verdict(reason: str) -> MistralVerdict:
    return MistralVerdict(
        is_fraud        = False,
        confidence      = 0,
        refined_score   = 0,
        verdict_label   = "unknown",
        crime_type      = "analysis unavailable",
        summary         = reason,
        prompt_tier     = "low",
        raw_response    = "",
    )

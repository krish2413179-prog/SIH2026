'use client';

/**
 * MistralPanel — Generative AI fraud verdict panel powered by Mistral AI.
 *
 * Props: traceId — UUID of the trace job
 *
 * Flow:
 *   1. On mount, hits GET /traces/{id}/ai-analysis (returns cached result if available)
 *   2. If 404, shows an "Analyse with AI" button that fires POST /traces/{id}/ai-analysis
 *   3. Displays: fraud verdict badge, refined score, confidence, crime type,
 *      summary, evidence chain, missing data, and action recommendations
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Brain, ShieldAlert, ShieldCheck, ShieldQuestion,
  Loader2, AlertCircle, RefreshCw, ChevronDown, ChevronUp,
  Lightbulb, Search, ListChecks, Link2,
} from 'lucide-react';
import api from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AiVerdict {
  trace_id:        string;
  wallet?:         string;
  chain?:          string;
  rule_score?:     number;
  is_fraud:        boolean;
  confidence:      number;
  refined_score:   number;
  verdict_label:   'legitimate' | 'suspicious' | 'fraud' | 'unknown';
  crime_type:      string;
  summary:         string;
  evidence_chain:  string[];
  missing_data:    string[];
  recommendations: string[];
  prompt_tier:     'low' | 'ambiguous' | 'high';
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const VERDICT_CONFIG = {
  fraud: {
    label:      'FRAUD',
    icon:       ShieldAlert,
    scoreColor: 'text-red-400',
    badgeClass: 'bg-red-950/60 border border-red-700 text-red-300',
    barColor:   'bg-red-500',
  },
  suspicious: {
    label:      'SUSPICIOUS',
    icon:       ShieldQuestion,
    scoreColor: 'text-orange-400',
    badgeClass: 'bg-orange-950/60 border border-orange-700 text-orange-300',
    barColor:   'bg-orange-500',
  },
  legitimate: {
    label:      'LEGITIMATE',
    icon:       ShieldCheck,
    scoreColor: 'text-green-400',
    badgeClass: 'bg-green-950/60 border border-green-700 text-green-300',
    barColor:   'bg-green-500',
  },
  unknown: {
    label:      'UNKNOWN',
    icon:       ShieldQuestion,
    scoreColor: 'text-gray-400',
    badgeClass: 'bg-gray-800 border border-gray-600 text-gray-400',
    barColor:   'bg-gray-500',
  },
} as const;

function ScoreBar({ value, color }: { value: number; color: string }) {
  return (
    <div className="w-full h-1.5 rounded-full bg-gray-800 overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-700 ${color}`}
        style={{ width: `${value}%` }}
      />
    </div>
  );
}

function BulletList({ items, icon: Icon, iconColor, title }: {
  items: string[];
  icon: React.ElementType;
  iconColor: string;
  title: string;
}) {
  const [open, setOpen] = useState(true);
  if (!items.length) return null;
  return (
    <div className="rounded-lg bg-gray-800/60 border border-gray-700/60 overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold text-gray-300 hover:text-white transition-colors"
      >
        <span className="flex items-center gap-1.5">
          <Icon className="w-3.5 h-3.5" style={{ color: iconColor }} />
          {title}
          <span className="text-gray-600 font-normal">({items.length})</span>
        </span>
        {open ? <ChevronUp className="w-3 h-3 text-gray-500" /> : <ChevronDown className="w-3 h-3 text-gray-500" />}
      </button>
      {open && (
        <ul className="px-3 pb-3 space-y-1.5 border-t border-gray-700/40">
          {items.map((item, i) => (
            <li key={i} className="flex gap-2 text-[11px] text-gray-400 leading-relaxed pt-1.5">
              <span className="mt-0.5 shrink-0 w-1 h-1 rounded-full bg-gray-600 translate-y-1.5" />
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface MistralPanelProps {
  traceId: string;
}

export function MistralPanel({ traceId }: MistralPanelProps) {
  const [verdict,  setVerdict]  = useState<AiVerdict | null>(null);
  const [loading,  setLoading]  = useState(false);
  const [running,  setRunning]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [notCached, setNotCached] = useState(false);

  // ── Try cache on mount ──────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get<AiVerdict>(`/traces/${traceId}/ai-analysis`)
      .then(res => { if (!cancelled) { setVerdict(res.data); setNotCached(false); } })
      .catch(err => {
        if (cancelled) return;
        if (err?.response?.status === 404) {
          setNotCached(true);   // no cache — show button
        } else {
          setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load analysis');
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [traceId]);

  // ── Run fresh analysis ──────────────────────────────────────────────────
  const runAnalysis = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await api.post<AiVerdict>(`/traces/${traceId}/ai-analysis`);
      setVerdict(res.data);
      setNotCached(false);
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string }; status?: number }; message?: string };
      setError(e?.response?.data?.detail ?? e?.message ?? 'Analysis failed');
    } finally {
      setRunning(false);
    }
  }, [traceId]);

  // ── Loading ─────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-700 p-5 flex items-center gap-3">
        <Loader2 className="w-5 h-5 text-purple-400 animate-spin shrink-0" />
        <span className="text-gray-400 text-sm">Loading AI analysis…</span>
      </div>
    );
  }

  // ── Not yet run ─────────────────────────────────────────────────────────
  if (notCached) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-700 p-5 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-purple-400" />
          <span className="text-sm font-semibold text-gray-200">Mistral AI Analysis</span>
        </div>
        <p className="text-xs text-gray-500 leading-relaxed">
          Let Mistral AI assess this wallet for fraud — it will assign a refined risk score,
          identify the crime type, and generate an evidence chain for prosecution.
        </p>
        <button
          onClick={runAnalysis}
          disabled={running}
          className="flex items-center justify-center gap-2 py-2.5 rounded-lg bg-purple-700 hover:bg-purple-600 disabled:opacity-50 text-sm font-semibold text-white transition-colors"
        >
          {running
            ? <><Loader2 className="w-4 h-4 animate-spin" /> Analysing with Mistral…</>
            : <><Brain className="w-4 h-4" /> Analyse with AI</>}
        </button>
        {error && <p className="text-xs text-red-400">{error}</p>}
      </div>
    );
  }

  // ── Error ───────────────────────────────────────────────────────────────
  if (error && !verdict) {
    return (
      <div className="bg-gray-900 rounded-xl border border-red-800 p-5 flex flex-col gap-2">
        <AlertCircle className="w-5 h-5 text-red-400" />
        <p className="text-red-400 text-sm font-medium">AI Analysis failed</p>
        <p className="text-gray-500 text-xs">{error}</p>
        <button onClick={runAnalysis}
          className="mt-1 text-xs text-purple-400 hover:text-purple-300 flex items-center gap-1">
          <RefreshCw className="w-3 h-3" /> Retry
        </button>
      </div>
    );
  }

  if (!verdict) return null;

  const cfg   = VERDICT_CONFIG[verdict.verdict_label] ?? VERDICT_CONFIG.unknown;
  const Icon  = cfg.icon;
  const tier  = verdict.prompt_tier;

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-700 p-5 flex flex-col gap-4">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-purple-400" />
          <span className="text-sm font-semibold text-gray-200">Mistral AI Analysis</span>
          <span className={`text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded font-semibold ${
            tier === 'high' ? 'bg-red-900/50 text-red-400' :
            tier === 'ambiguous' ? 'bg-orange-900/50 text-orange-400' :
            'bg-green-900/50 text-green-400'
          }`}>
            {tier === 'high' ? 'deep scan' : tier === 'ambiguous' ? 'ambiguous' : 'quick check'}
          </span>
        </div>
        <button
          onClick={runAnalysis}
          disabled={running}
          title="Re-run analysis"
          className="text-gray-600 hover:text-purple-400 transition-colors disabled:opacity-40"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${running ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Verdict badge + scores */}
      <div className="flex items-center gap-4">
        {/* Refined score */}
        <div className="flex flex-col items-center justify-center w-16 h-16 bg-gray-800 rounded-lg border border-gray-600 shrink-0">
          <span className={`text-2xl font-bold leading-none ${cfg.scoreColor}`}>{verdict.refined_score}</span>
          <span className="text-[10px] text-gray-500 mt-0.5">/ 100</span>
        </div>

        <div className="flex-1 flex flex-col gap-1.5">
          {/* Verdict badge */}
          <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold w-fit ${cfg.badgeClass}`}>
            <Icon className="w-3.5 h-3.5" />
            {cfg.label}
          </div>
          {/* Confidence bar */}
          <div className="flex items-center gap-2 text-[11px] text-gray-500">
            <span className="shrink-0">Confidence</span>
            <ScoreBar value={verdict.confidence} color={cfg.barColor} />
            <span className="shrink-0 font-mono">{verdict.confidence}%</span>
          </div>
        </div>
      </div>

      {/* Crime type */}
      <div className="rounded-lg bg-gray-800 px-3 py-2 text-xs">
        <span className="text-gray-500 uppercase tracking-wide text-[10px]">Activity Type · </span>
        <span className="text-white font-semibold">{verdict.crime_type}</span>
      </div>

      {/* Summary */}
      <p className="text-xs text-gray-400 leading-relaxed border-l-2 border-purple-700 pl-3">
        {verdict.summary}
      </p>

      {/* Collapsible sections */}
      <div className="flex flex-col gap-2">
        <BulletList
          items={verdict.evidence_chain}
          icon={Link2}
          iconColor="#f87171"
          title="Evidence Chain"
        />
        <BulletList
          items={verdict.recommendations}
          icon={ListChecks}
          iconColor="#34d399"
          title="Recommendations"
        />
        <BulletList
          items={verdict.missing_data}
          icon={Search}
          iconColor="#facc15"
          title="Missing Data"
        />
      </div>

      {/* Rule score comparison */}
      {verdict.rule_score != null && (
        <div className="flex items-center gap-3 text-[11px] text-gray-600">
          <Lightbulb className="w-3 h-3 shrink-0" />
          <span>
            Rule-based score: <span className="text-gray-400 font-mono">{verdict.rule_score}/100</span>
            {' '}→ AI refined: <span className={`font-mono font-semibold ${cfg.scoreColor}`}>{verdict.refined_score}/100</span>
          </span>
        </div>
      )}
    </div>
  );
}

export default MistralPanel;

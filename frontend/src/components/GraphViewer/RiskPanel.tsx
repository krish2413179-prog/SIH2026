'use client';

/**
 * RiskPanel component — displays risk score, band, and typology tags for a trace.
 *
 * Props:
 *   traceId — UUID of the trace job
 *
 * Fetches from GET /traces/{traceId}/risk and displays:
 *   - Risk Score: large coloured number (red = high, orange = medium, green = low)
 *   - Risk Band badge: HIGH / MEDIUM / LOW with matching colour
 *   - Typology Tags: pill chips for each detected typology
 *   - Loading skeleton while fetching
 *   - Error state on failure
 *
 * Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
 */

import { useEffect, useState } from 'react';
import { ShieldAlert, ShieldCheck, ShieldQuestion, Loader2 } from 'lucide-react';
import api from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RiskData {
  trace_id: string;
  wallet_address: string;
  risk_score: number | null;
  risk_band: 'low' | 'medium' | 'high' | null;
  typology_tags: string[];
}

export interface RiskPanelProps {
  traceId: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Band = 'low' | 'medium' | 'high';

const BAND_CONFIG: Record<
  Band,
  { scoreColor: string; badgeClass: string; Icon: typeof ShieldAlert; label: string }
> = {
  high: {
    scoreColor: 'text-red-400',
    badgeClass: 'bg-red-900/50 text-red-300 border border-red-700',
    Icon: ShieldAlert,
    label: 'HIGH',
  },
  medium: {
    scoreColor: 'text-orange-400',
    badgeClass: 'bg-orange-900/50 text-orange-300 border border-orange-700',
    Icon: ShieldQuestion,
    label: 'MEDIUM',
  },
  low: {
    scoreColor: 'text-green-400',
    badgeClass: 'bg-green-900/50 text-green-300 border border-green-700',
    Icon: ShieldCheck,
    label: 'LOW',
  },
};

/** Human-readable label for a typology tag slug */
function formatTypology(tag: string): string {
  return tag
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Pick a chip colour based on tag content */
function typologyChipClass(tag: string): string {
  const t = tag.toLowerCase();
  if (t.includes('mixer') || t.includes('tumbler')) return 'bg-violet-900/50 text-violet-300 border border-violet-700';
  if (t.includes('bridge') || t.includes('cross')) return 'bg-amber-900/50 text-amber-300 border border-amber-700';
  if (t.includes('peel')) return 'bg-cyan-900/50 text-cyan-300 border border-cyan-700';
  if (t.includes('flag') || t.includes('sanction')) return 'bg-red-900/50 text-red-300 border border-red-700';
  return 'bg-gray-700 text-gray-300 border border-gray-600';
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div className={`animate-pulse bg-gray-700 rounded ${className}`} />
  );
}

function LoadingSkeleton() {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-700 p-5 flex flex-col gap-4">
      {/* Score row */}
      <div className="flex items-center gap-4">
        <Skeleton className="w-16 h-16 rounded-lg" />
        <div className="flex flex-col gap-2 flex-1">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-5 w-16" />
        </div>
      </div>
      {/* Tags row */}
      <div className="flex gap-2 flex-wrap">
        <Skeleton className="h-6 w-20 rounded-full" />
        <Skeleton className="h-6 w-24 rounded-full" />
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RiskPanel({ traceId }: RiskPanelProps) {
  const [data, setData] = useState<RiskData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .get<RiskData>(`/traces/${traceId}/risk`)
      .then((res) => {
        if (!cancelled) setData(res.data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err?.response?.data?.detail ??
              err?.message ??
              'Failed to load risk data.',
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [traceId]);

  if (loading) return <LoadingSkeleton />;

  if (error) {
    return (
      <div className="bg-gray-900 rounded-xl border border-red-800 p-5">
        <p className="text-red-400 text-sm font-medium">Failed to load risk data</p>
        <p className="text-gray-500 text-xs mt-1">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  const band = (data.risk_band?.toLowerCase() as Band | undefined) ?? null;
  const bandCfg = band ? BAND_CONFIG[band] : null;
  const score = data.risk_score;

  // Determine score colour when band config isn't available
  let fallbackScoreColor = 'text-gray-400';
  if (score !== null && score !== undefined) {
    if (score >= 70) fallbackScoreColor = 'text-red-400';
    else if (score >= 40) fallbackScoreColor = 'text-orange-400';
    else fallbackScoreColor = 'text-green-400';
  }

  const scoreColor = bandCfg?.scoreColor ?? fallbackScoreColor;
  const Icon = bandCfg?.Icon ?? ShieldQuestion;

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-700 p-5 flex flex-col gap-4">
      {/* Header row: score + band */}
      <div className="flex items-center gap-4">
        {/* Large risk score */}
        <div className="flex flex-col items-center justify-center w-16 h-16 bg-gray-800 rounded-lg border border-gray-600 shrink-0">
          <span className={`text-2xl font-bold leading-none ${scoreColor}`}>
            {score !== null && score !== undefined ? score : '—'}
          </span>
          <span className="text-[10px] text-gray-500 mt-0.5">/ 100</span>
        </div>

        {/* Score label + band badge */}
        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-gray-400 uppercase tracking-wide">Risk Score</span>

          {bandCfg ? (
            <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${bandCfg.badgeClass}`}>
              <Icon className="w-3.5 h-3.5" />
              {bandCfg.label}
            </div>
          ) : (
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-gray-700 text-gray-400 border border-gray-600">
              <ShieldQuestion className="w-3.5 h-3.5" />
              PENDING
            </div>
          )}
        </div>
      </div>

      {/* Wallet address */}
      {data.wallet_address && (
        <div className="text-xs text-gray-500 font-mono truncate" title={data.wallet_address}>
          {data.wallet_address}
        </div>
      )}

      {/* Typology tags */}
      {data.typology_tags && data.typology_tags.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-xs text-gray-400 uppercase tracking-wide">Detected Typologies</span>
          <div className="flex flex-wrap gap-1.5">
            {data.typology_tags.map((tag) => (
              <span
                key={tag}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${typologyChipClass(tag)}`}
              >
                {formatTypology(tag)}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.typology_tags && data.typology_tags.length === 0 && (
        <div className="text-xs text-gray-500 italic">No typology patterns detected.</div>
      )}
    </div>
  );
}

export default RiskPanel;

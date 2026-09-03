'use client';

/**
 * Case detail page — redesigned with full-black ShadCN-style card layout.
 * Shows wallet submission, trace queue, inline graph preview, and reports.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';
import { getCurrentUser } from '@/lib/auth';
import dynamic from 'next/dynamic';
import {
  ArrowLeft, GitBranch, RefreshCw, ChevronRight, Loader2,
  AlertTriangle, CheckCircle2, Clock, XCircle, Zap,
  Wallet, Activity, FileText, ExternalLink, Shield,
  TrendingUp, Network, Download, Plus, Eye,
} from 'lucide-react';

const GraphViewer = dynamic(
  () => import('@/components/GraphViewer/GraphViewer').then(m => m.GraphViewer ?? m.default),
  { ssr: false }
);
const RiskPanel = dynamic(
  () => import('@/components/GraphViewer/RiskPanel').then(m => m.RiskPanel ?? m.default),
  { ssr: false }
);
const MistralPanel = dynamic(
  () => import('@/components/GraphViewer/MistralPanel').then(m => m.MistralPanel ?? m.default),
  { ssr: false }
);

const CHAINS = ['BTC', 'ETH', 'TRX', 'BSC', 'SOL', 'MATIC'];

// ── Status helpers ────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: string }) {
  const cfg: Record<string, { icon: React.ReactNode; cls: string }> = {
    completed:    { icon: <CheckCircle2 className="w-3 h-3" />, cls: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20' },
    running:      { icon: <Loader2 className="w-3 h-3 animate-spin" />, cls: 'text-blue-400 bg-blue-400/10 border-blue-400/20' },
    queued:       { icon: <Clock className="w-3 h-3" />, cls: 'text-amber-400 bg-amber-400/10 border-amber-400/20' },
    failed:       { icon: <XCircle className="w-3 h-3" />, cls: 'text-red-400 bg-red-400/10 border-red-400/20' },
    'rate-limited': { icon: <AlertTriangle className="w-3 h-3" />, cls: 'text-orange-400 bg-orange-400/10 border-orange-400/20' },
  };
  const c = cfg[status] ?? { icon: <Clock className="w-3 h-3" />, cls: 'text-zinc-400 bg-zinc-400/10 border-zinc-400/20' };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${c.cls}`}>
      {c.icon}
      {status.replace(/-/g, ' ').replace(/_/g, ' ')}
    </span>
  );
}

function RiskBadge({ band, score }: { band?: string; score?: number }) {
  if (!band && score == null) return null;
  const cls =
    band === 'HIGH'    ? 'text-red-400 bg-red-400/10 border-red-400/20' :
    band === 'MEDIUM'  ? 'text-amber-400 bg-amber-400/10 border-amber-400/20' :
    band === 'LOW'     ? 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20' :
    'text-zinc-400 bg-zinc-400/10 border-zinc-400/20';
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${cls}`}>
      <Shield className="w-3 h-3" />
      {score != null ? `${score}/100` : band}
    </span>
  );
}

// ── Card wrapper ──────────────────────────────────────────────────────────────
function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl border border-white/[0.08] bg-[#111111] ${className}`}>
      {children}
    </div>
  );
}

// ── Section label ─────────────────────────────────────────────────────────────
function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-[10px] uppercase tracking-widest text-zinc-600 mb-3">{children}</p>;
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const user = getCurrentUser();

  const [addresses, setAddresses] = useState('');
  const [chainOverride, setChainOverride] = useState('');
  const [submitResults, setSubmitResults] = useState<any[]>([]);
  const [submitErrors, setSubmitErrors] = useState<any[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const submitPanelRef = useRef<HTMLElement>(null);
  const [graphTraceBanner, setGraphTraceBanner] = useState<string | null>(null);

  // Handle pre-fill from graph page deep-link
  useEffect(() => {
    const addr = searchParams.get('trace');
    const chain = searchParams.get('chain');
    if (addr) {
      setAddresses(addr);
      if (chain) setChainOverride(chain);
    }
  }, [searchParams]);

  // Fetch case
  const { data: caseData, isLoading: caseLoading } = useQuery({
    queryKey: ['case', id],
    queryFn: async () => (await api.get(`/cases/${id}`)).data,
    enabled: !!id,
  });

  // Fetch trace jobs
  const { data: tracesData, refetch: refetchTraces } = useQuery({
    queryKey: ['traces', id],
    queryFn: async () => {
      const res = await api.get(`/cases/${id}/wallets`);
      return res.data;
    },
    enabled: !!id,
    refetchInterval: 8000,
  });

  // Fetch reports
  const { data: reportsData } = useQuery({
    queryKey: ['reports', id],
    queryFn: async () => {
      try {
        const res = await api.get('/reports', { params: { case_id: id } });
        return res.data;
      } catch { return []; }
    },
    enabled: !!id,
  });

  // Wallet submission
  const submitMutation = useMutation({
    mutationFn: async (overrideAddress?: string) => {
      const source = overrideAddress ?? addresses;
      const lines = source.split('\n').map(l => l.trim()).filter(Boolean).slice(0, 50);
      const items = lines.map(addr => ({
        address: addr,
        ...(chainOverride ? { chain: chainOverride } : {}),
      }));
      const res = await api.post(`/cases/${id}/wallets`, { addresses: items });
      return res.data;
    },
    onSuccess: (data) => {
      setSubmitResults(data.results || []);
      setSubmitErrors(data.errors || []);
      setAddresses('');
      qc.invalidateQueries({ queryKey: ['traces', id] });
    },
  });

  const handleTraceWallet = useCallback((address: string, chain?: string) => {
    setAddresses(address);
    if (chain) setChainOverride(chain);
    setGraphTraceBanner(address);
    submitPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setTimeout(() => {
      setGraphTraceBanner(null);
      submitMutation.mutate(address);
    }, 700);
  }, [submitMutation]);

  if (caseLoading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 rounded-full border-2 border-blue-500/60 border-t-blue-400 animate-spin" />
          <p className="text-zinc-500 text-sm">Loading case…</p>
        </div>
      </div>
    );
  }

  const completedTraces = (tracesData ?? []).filter((t: any) => t.status === 'completed');
  const runningTraces = (tracesData ?? []).filter((t: any) => ['running', 'queued'].includes(t.status));
  const highRiskTraces = (tracesData ?? []).filter((t: any) => t.risk_band === 'HIGH');

  return (
    <main className="min-h-screen bg-black text-white">
      {/* ── Top header ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-black/90 backdrop-blur-sm px-6 py-3 flex items-center gap-4">
        <button
          onClick={() => router.push('/cases')}
          className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Cases
        </button>
        <span className="text-zinc-700">/</span>
        <h1 className="text-sm font-semibold text-white truncate flex-1">{caseData?.title ?? '—'}</h1>
        <div className="flex items-center gap-2 shrink-0">
          {caseData?.status && (
            <span className={`text-[10px] font-semibold px-2.5 py-1 rounded-full border ${
              caseData.status === 'open' ? 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20' :
              caseData.status === 'closed' ? 'text-zinc-400 bg-zinc-400/10 border-zinc-400/20' :
              'text-amber-400 bg-amber-400/10 border-amber-400/20'
            }`}>
              {caseData.status.replace('_', ' ').toUpperCase()}
            </span>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-[1400px] px-6 py-8 space-y-8">

        {/* ── Stats row ──────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Total Wallets', value: (tracesData ?? []).length, icon: <Wallet className="w-4 h-4" />, color: 'text-blue-400' },
            { label: 'Completed', value: completedTraces.length, icon: <CheckCircle2 className="w-4 h-4" />, color: 'text-emerald-400' },
            { label: 'Running', value: runningTraces.length, icon: <Activity className="w-4 h-4" />, color: 'text-amber-400' },
            { label: 'High Risk', value: highRiskTraces.length, icon: <AlertTriangle className="w-4 h-4" />, color: 'text-red-400' },
          ].map(({ label, value, icon, color }) => (
            <Card key={label} className="p-4">
              <div className={`${color} mb-2`}>{icon}</div>
              <div className="text-2xl font-bold text-white tabular-nums">{value}</div>
              <div className="text-[11px] text-zinc-500 mt-0.5">{label}</div>
            </Card>
          ))}
        </div>

        {/* ── Top section: submit + queue ────────────────────────────────── */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[420px_1fr]">

          {/* Submit Wallets */}
          <section ref={submitPanelRef as any}>
            <SectionLabel>Submit Wallets</SectionLabel>
            <Card className="overflow-hidden">
              <div className="p-5 space-y-4">
                {graphTraceBanner && (
                  <div className="flex items-center gap-2 rounded-xl border border-blue-500/20 bg-blue-500/5 px-3 py-2.5 text-xs text-blue-300">
                    <GitBranch className="w-3.5 h-3.5 shrink-0" />
                    Tracing <span className="font-mono ml-1 text-blue-200">{graphTraceBanner.slice(0, 20)}…</span>
                  </div>
                )}
                <textarea
                  value={addresses}
                  onChange={e => setAddresses(e.target.value)}
                  placeholder="Paste wallet addresses here&#10;One per line (max 50)"
                  rows={5}
                  className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-3 text-sm font-mono text-white placeholder-zinc-600 focus:border-blue-500/50 focus:bg-white/[0.05] focus:outline-none resize-none transition-colors"
                />
                <div className="flex gap-2">
                  <select
                    value={chainOverride}
                    onChange={e => setChainOverride(e.target.value)}
                    className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-white focus:border-blue-500/50 focus:outline-none transition-colors"
                  >
                    <option value="">Auto-detect</option>
                    {CHAINS.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <button
                    onClick={() => submitMutation.mutate(undefined)}
                    disabled={submitMutation.isPending || !addresses.trim()}
                    className="flex-1 flex items-center justify-center gap-2 rounded-xl bg-white text-black text-sm font-semibold py-2.5 hover:bg-zinc-200 disabled:opacity-40 transition-colors"
                  >
                    {submitMutation.isPending
                      ? <><Loader2 className="w-4 h-4 animate-spin" /> Submitting…</>
                      : <><Plus className="w-4 h-4" /> Submit Trace</>}
                  </button>
                </div>
              </div>
              {/* Submit results */}
              {submitResults.length > 0 && (
                <div className="border-t border-white/[0.06] px-5 py-3 space-y-1.5">
                  {submitResults.map((r, i) => (
                    <div key={i} className="flex items-center gap-2 text-[11px]">
                      <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                      <span className="font-mono text-zinc-300 truncate flex-1">{r.address?.slice(0, 20)}…</span>
                      <span className="text-zinc-600">{r.chain}</span>
                      {r.is_duplicate && <span className="text-amber-400 text-[10px]">dup</span>}
                      {r.trace_id && <span className="text-emerald-400 font-mono text-[10px]">{String(r.trace_id).slice(0, 6)}…</span>}
                    </div>
                  ))}
                </div>
              )}
              {submitErrors.length > 0 && (
                <div className="border-t border-red-500/20 bg-red-500/5 px-5 py-3 space-y-1">
                  {submitErrors.map((e, i) => (
                    <div key={i} className="text-[11px] text-red-300">
                      <span className="font-mono text-red-400">{e.address?.slice(0, 16)}…</span>: {e.detail}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </section>

          {/* Trace Queue */}
          <section>
            <div className="flex items-center justify-between mb-3">
              <SectionLabel>Trace Queue</SectionLabel>
              <button
                onClick={() => refetchTraces()}
                className="flex items-center gap-1 text-[10px] text-zinc-600 hover:text-zinc-300 transition-colors"
              >
                <RefreshCw className="w-3 h-3" /> Refresh
              </button>
            </div>
            <Card className="overflow-hidden divide-y divide-white/[0.05]">
              {(!tracesData || tracesData.length === 0) ? (
                <div className="flex flex-col items-center justify-center py-14 text-center">
                  <Network className="w-8 h-8 text-zinc-700 mb-3" />
                  <p className="text-sm text-zinc-500">No wallets traced yet</p>
                  <p className="text-xs text-zinc-700 mt-1">Submit a wallet address to start</p>
                </div>
              ) : (
                tracesData.map((t: any) => (
                  <div
                    key={t.id}
                    onClick={() => setSelectedTraceId(prev => prev === t.id ? null : t.id)}
                    className={`group relative px-4 py-3.5 cursor-pointer transition-all ${
                      selectedTraceId === t.id
                        ? 'bg-blue-500/5 border-l-2 border-l-blue-500'
                        : 'hover:bg-white/[0.02] border-l-2 border-l-transparent'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      {/* Status indicator */}
                      <div className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${
                        t.status === 'completed' ? 'bg-emerald-400' :
                        t.status === 'running' ? 'bg-blue-400 animate-pulse' :
                        t.status === 'queued' ? 'bg-amber-400' :
                        t.status === 'failed' ? 'bg-red-400' : 'bg-zinc-600'
                      }`} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono text-[11px] text-zinc-200 truncate max-w-[220px]">
                            {t.wallet_address}
                          </span>
                          <span className="text-[10px] text-zinc-600 bg-white/[0.05] px-1.5 py-0.5 rounded font-mono">
                            {t.chain}
                          </span>
                          <StatusBadge status={t.status} />
                          {(t.risk_band || t.risk_score != null) && (
                            <RiskBadge band={t.risk_band} score={t.risk_score} />
                          )}
                        </div>
                        {/* Progress bar for running traces */}
                        {t.status === 'running' && t.estimated_pct != null && (
                          <div className="mt-2 h-0.5 rounded-full bg-white/[0.06]">
                            <div
                              className="h-full rounded-full bg-blue-500 transition-all duration-500"
                              style={{ width: `${t.estimated_pct}%` }}
                            />
                          </div>
                        )}
                        {/* Transaction summary for completed traces */}
                        {t.status === 'completed' && (
                          <div className="mt-1.5 flex items-center gap-3 text-[10px] text-zinc-600">
                            <span className="flex items-center gap-1">
                              <Activity className="w-2.5 h-2.5" />
                              {t.nodes ?? '—'} wallets
                            </span>
                            <span className="flex items-center gap-1">
                              <TrendingUp className="w-2.5 h-2.5" />
                              {t.edges ?? '—'} txns
                            </span>
                            {t.completed_at && (
                              <span>{new Date(t.completed_at).toLocaleDateString()}</span>
                            )}
                          </div>
                        )}
                      </div>
                      {/* Actions */}
                      <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                        {t.status === 'completed' && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              router.push(`/cases/${id}/graph/${t.id}`);
                            }}
                            title="Open in dedicated graph view"
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] text-blue-400 border border-blue-500/20 bg-blue-500/5 hover:bg-blue-500/15 transition-colors"
                          >
                            <ExternalLink className="w-3 h-3" />
                            Open Graph
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </Card>
          </section>
        </div>

        {/* ── Inline Graph Preview ──────────────────────────────────────── */}
        {selectedTraceId && (
          <section>
            <div className="flex items-center justify-between mb-3">
              <SectionLabel>Transaction Graph</SectionLabel>
              <button
                onClick={() => router.push(`/cases/${id}/graph/${selectedTraceId}`)}
                className="flex items-center gap-1.5 text-xs text-blue-400 border border-blue-500/20 bg-blue-500/5 hover:bg-blue-500/15 px-3 py-1.5 rounded-xl transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Open Fullscreen Graph
              </button>
            </div>
            <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_300px]">
              <Card className="overflow-hidden">
                <GraphViewer traceId={selectedTraceId} onTraceWallet={handleTraceWallet} />
              </Card>
              <div className="space-y-4">
                <Card className="overflow-hidden p-4">
                  <p className="text-[10px] uppercase tracking-widest text-zinc-600 mb-3">Risk Assessment</p>
                  <RiskPanel traceId={selectedTraceId} />
                </Card>
                <Card className="overflow-hidden p-4">
                  <p className="text-[10px] uppercase tracking-widest text-zinc-600 mb-3">AI Analysis</p>
                  <MistralPanel traceId={selectedTraceId} />
                </Card>
              </div>
            </div>
          </section>
        )}

        {/* ── Reports ──────────────────────────────────────────────────── */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <SectionLabel>Reports</SectionLabel>
            {selectedTraceId && (
              <div className="flex gap-2">
                {(['json', 'pdf'] as const).map(fmt => (
                  <button
                    key={fmt}
                    onClick={async () => {
                      try {
                        await api.post(`/traces/${selectedTraceId}/reports`, { format: fmt });
                        qc.invalidateQueries({ queryKey: ['reports', id] });
                      } catch {}
                    }}
                    className="flex items-center gap-1.5 text-[11px] font-medium text-zinc-300 border border-white/10 bg-white/[0.03] hover:bg-white/[0.07] px-3 py-1.5 rounded-xl transition-colors"
                  >
                    <Download className="w-3 h-3" />
                    {fmt.toUpperCase()}
                  </button>
                ))}
              </div>
            )}
          </div>
          <Card className="overflow-hidden">
            {(!reportsData || reportsData.length === 0) ? (
              <div className="flex flex-col items-center justify-center py-14 text-center">
                <FileText className="w-8 h-8 text-zinc-700 mb-3" />
                <p className="text-sm text-zinc-500">No reports generated yet</p>
                <p className="text-xs text-zinc-700 mt-1">Select a trace and generate a report</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/[0.06]">
                    {['Report ID', 'Format', 'Status', 'Created', ''].map(h => (
                      <th key={h} className="px-5 py-3 text-left text-[10px] uppercase tracking-widest text-zinc-600 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {reportsData.map((r: any) => (
                    <tr key={r.report_id} className="hover:bg-white/[0.02] transition-colors">
                      <td className="px-5 py-3 font-mono text-xs text-zinc-500">{String(r.report_id).slice(0, 8)}…</td>
                      <td className="px-5 py-3">
                        <span className="text-[10px] font-semibold uppercase text-zinc-300 bg-white/[0.06] px-2 py-0.5 rounded">{r.format}</span>
                      </td>
                      <td className="px-5 py-3">
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                          r.status === 'supervisor-approved'
                            ? 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20'
                            : 'text-zinc-400 bg-zinc-400/10 border-zinc-400/20'
                        }`}>{r.status}</span>
                      </td>
                      <td className="px-5 py-3 text-xs text-zinc-600">
                        {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-5 py-3 text-right space-x-3">
                        {r.format === 'json' && r.json_payload && (
                          <button
                            onClick={() => {
                              const blob = new Blob([JSON.stringify(r.json_payload, null, 2)], { type: 'application/json' });
                              const url = URL.createObjectURL(blob);
                              const a = document.createElement('a'); a.href = url; a.download = `report-${r.report_id}.json`; a.click();
                            }}
                            className="text-[11px] text-blue-400 hover:text-blue-300 transition-colors"
                          >
                            Download
                          </button>
                        )}
                        {user?.role !== 'investigator' && r.status !== 'supervisor-approved' && (
                          <button
                            onClick={async () => {
                              await api.post(`/reports/${r.report_id}/sign`);
                              qc.invalidateQueries({ queryKey: ['reports', id] });
                            }}
                            className="text-[11px] text-emerald-400 hover:text-emerald-300 transition-colors"
                          >
                            Sign
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </section>
      </div>
    </main>
  );
}

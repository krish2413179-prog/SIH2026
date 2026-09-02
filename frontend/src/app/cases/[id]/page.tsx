'use client';

/**
 * Case detail page.
 * Shows wallet submission, trace jobs, graph viewer, and reports for a case.
 * Requirements: 2.3, 3.1, 3.5, 10.1
 */

import { useState, useRef, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';
import { getCurrentUser } from '@/lib/auth';
import dynamic from 'next/dynamic';
import { GitBranch } from 'lucide-react';

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

const STATUS_COLORS: Record<string, string> = {
  open: 'bg-green-700 text-green-100',
  under_review: 'bg-yellow-700 text-yellow-100',
  closed: 'bg-gray-600 text-gray-200',
  queued: 'bg-blue-800 text-blue-100',
  running: 'bg-blue-500 text-white',
  completed: 'bg-green-700 text-green-100',
  failed: 'bg-red-800 text-red-100',
  'rate-limited': 'bg-orange-700 text-orange-100',
};

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const user = getCurrentUser();

  const [addresses, setAddresses] = useState('');
  const [chainOverride, setChainOverride] = useState('');
  const [submitResults, setSubmitResults] = useState<any[]>([]);
  const [submitErrors, setSubmitErrors] = useState<any[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'traces' | 'reports'>('traces');
  // ref to scroll submit panel into view when "Trace this wallet" is clicked from graph
  const submitPanelRef = useRef<HTMLElement>(null);
  // banner shown when an address is pre-filled from the graph popup
  const [graphTraceBanner, setGraphTraceBanner] = useState<string | null>(null);

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
    refetchInterval: 10000,
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

  // Wallet submission mutation
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

  /**
   * Called when the user clicks "Trace this wallet" from a graph node popup.
   * Pre-fills the submission panel, scrolls to it, and auto-submits.
   */
  const handleTraceWallet = useCallback((address: string, chain?: string) => {
    setAddresses(address);
    if (chain) setChainOverride(chain);
    setGraphTraceBanner(address);
    submitPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    // Brief pause so the user sees the pre-fill, then auto-submit
    setTimeout(() => {
      setGraphTraceBanner(null);
      submitMutation.mutate(address);
    }, 700);
  }, [submitMutation]);

  if (caseLoading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-400 border-t-transparent" />
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="border-b border-gray-700 bg-gray-800/80 px-6 py-4 flex items-center gap-4">
        <button onClick={() => router.push('/cases')} className="text-gray-400 hover:text-white text-sm">
          ← Cases
        </button>
        <h1 className="text-xl font-bold flex-1">{caseData?.title ?? '—'}</h1>
        {caseData?.status && (
          <span className={`rounded-full px-3 py-0.5 text-xs font-semibold ${STATUS_COLORS[caseData.status] ?? 'bg-gray-700'}`}>
            {caseData.status.replace('_', ' ').toUpperCase()}
          </span>
        )}
      </header>

      <div className="mx-auto max-w-7xl px-6 py-8 space-y-8">
        {/* Wallet submission + trace jobs */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Wallet Submission */}
          <section ref={submitPanelRef} className="rounded-xl border border-gray-700 bg-gray-800 p-5">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-gray-400">Submit Wallets</h2>

            {/* Banner shown when address is pre-filled from graph */}
            {graphTraceBanner && (
              <div className="mb-3 flex items-center gap-2 rounded-lg border border-blue-700 bg-blue-900/30 px-3 py-2 text-xs text-blue-300">
                <GitBranch className="w-3.5 h-3.5 shrink-0" />
                <span>Tracing <span className="font-mono">{graphTraceBanner}</span> from graph…</span>
              </div>
            )}

            <div className="space-y-3">
              <textarea
                value={addresses}
                onChange={e => setAddresses(e.target.value)}
                placeholder="One wallet address per line (max 50)"
                rows={6}
                className="w-full rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm font-mono text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none resize-none"
              />
              <div className="flex items-center gap-3">
                <select
                  value={chainOverride}
                  onChange={e => setChainOverride(e.target.value)}
                  className="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                >
                  <option value="">Auto-detect chain</option>
                  {CHAINS.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <button
                  onClick={() => submitMutation.mutate(undefined)}
                  disabled={submitMutation.isPending || !addresses.trim()}
                  className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                >
                  {submitMutation.isPending ? 'Submitting…' : 'Submit'}
                </button>
              </div>
              {submitResults.length > 0 && (
                <div className="rounded-lg bg-gray-900 p-3 text-xs space-y-1 max-h-40 overflow-auto">
                  {submitResults.map((r, i) => (
                    <div key={i} className="flex items-center gap-2 text-gray-300">
                      <span className="font-mono truncate max-w-[180px]">{r.address}</span>
                      <span className="text-gray-500">{r.chain}</span>
                      {r.is_duplicate && <span className="text-yellow-400">duplicate</span>}
                      {r.trace_id && <span className="text-green-400 font-mono">{String(r.trace_id).slice(0, 8)}…</span>}
                    </div>
                  ))}
                </div>
              )}
              {submitErrors.length > 0 && (
                <div className="rounded-lg bg-red-900/30 border border-red-700 p-3 text-xs">
                  {submitErrors.map((e, i) => (
                    <div key={i} className="text-red-300">{e.address}: {e.detail}</div>
                  ))}
                </div>
              )}
            </div>
          </section>

          {/* Trace Jobs */}
          <section className="rounded-xl border border-gray-700 bg-gray-800 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">Trace Jobs</h2>
              <button onClick={() => refetchTraces()} className="text-xs text-gray-400 hover:text-white">↻ Refresh</button>
            </div>
            <div className="space-y-2 max-h-72 overflow-auto">
              {(!tracesData || tracesData.length === 0) ? (
                <p className="text-sm text-gray-500 py-4 text-center">No trace jobs yet.</p>
              ) : (
                tracesData.map((t: any) => (
                  <div
                    key={t.id}
                    onClick={() => setSelectedTraceId(t.id)}
                    className={`rounded-lg border p-3 cursor-pointer transition-colors ${selectedTraceId === t.id ? 'border-blue-500 bg-blue-900/20' : 'border-gray-700 bg-gray-900 hover:border-gray-600'}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-gray-300 truncate">{t.wallet_address}</span>
                      <span className="text-xs text-gray-500">{t.chain}</span>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_COLORS[t.status] ?? 'bg-gray-700'}`}>{t.status}</span>
                    </div>
                    {t.estimated_pct != null && (
                      <div className="mt-1.5 h-1 rounded-full bg-gray-700">
                        <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${t.estimated_pct}%` }} />
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        {/* Graph Viewer */}
        {selectedTraceId && (
          <section>
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-gray-400">Transaction Graph</h2>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <GraphViewer traceId={selectedTraceId} onTraceWallet={handleTraceWallet} />
              </div>
              <div>
                <RiskPanel traceId={selectedTraceId} />
                <div className="mt-4">
                  <MistralPanel traceId={selectedTraceId} />
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Reports */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">Reports</h2>
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
                    className="rounded-lg bg-gray-700 px-3 py-1.5 text-xs font-medium text-gray-200 hover:bg-gray-600 transition-colors"
                  >
                    Generate {fmt.toUpperCase()}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="rounded-xl border border-gray-700 overflow-hidden">
            <table className="w-full text-sm text-left">
              <thead className="bg-gray-800 border-b border-gray-700">
                <tr>
                  <th className="px-4 py-3 text-xs text-gray-400 font-semibold uppercase">Report ID</th>
                  <th className="px-4 py-3 text-xs text-gray-400 font-semibold uppercase">Format</th>
                  <th className="px-4 py-3 text-xs text-gray-400 font-semibold uppercase">Status</th>
                  <th className="px-4 py-3 text-xs text-gray-400 font-semibold uppercase">Created</th>
                  <th className="px-4 py-3 text-xs text-gray-400 font-semibold uppercase text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700 bg-gray-900">
                {(!reportsData || reportsData.length === 0) ? (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">No reports yet.</td></tr>
                ) : reportsData.map((r: any) => (
                  <tr key={r.report_id} className="hover:bg-gray-800/50">
                    <td className="px-4 py-3 font-mono text-xs text-gray-400">{String(r.report_id).slice(0, 8)}…</td>
                    <td className="px-4 py-3 text-xs uppercase">{r.format}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${r.status === 'supervisor-approved' ? 'bg-green-700 text-green-100' : 'bg-gray-700 text-gray-300'}`}>{r.status}</span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">{r.created_at ? new Date(r.created_at).toLocaleString() : '—'}</td>
                    <td className="px-4 py-3 text-right space-x-2">
                      {r.format === 'json' && r.json_payload && (
                        <button
                          onClick={() => {
                            const blob = new Blob([JSON.stringify(r.json_payload, null, 2)], { type: 'application/json' });
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement('a'); a.href = url; a.download = `report-${r.report_id}.json`; a.click();
                          }}
                          className="text-xs text-blue-400 hover:underline"
                        >Download</button>
                      )}
                      {user?.role !== 'investigator' && r.status !== 'supervisor-approved' && (
                        <button
                          onClick={async () => { await api.post(`/reports/${r.report_id}/sign`); qc.invalidateQueries({ queryKey: ['reports', id] }); }}
                          className="text-xs text-green-400 hover:underline"
                        >Sign</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}

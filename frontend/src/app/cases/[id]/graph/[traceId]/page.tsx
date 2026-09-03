'use client';

/**
 * Dedicated fullscreen graph analysis page for a specific trace.
 * Route: /cases/[id]/graph/[traceId]
 */
import { useParams, useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { ArrowLeft, ExternalLink, Shield, Network } from 'lucide-react';

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

export default function GraphPage() {
  const { id, traceId } = useParams<{ id: string; traceId: string }>();
  const router = useRouter();

  return (
    <main className="min-h-screen bg-black text-white flex flex-col">
      {/* Top bar */}
      <header className="shrink-0 flex items-center gap-4 px-6 py-3 border-b border-white/[0.06] bg-[#0a0a0a]">
        <button
          onClick={() => router.push(`/cases/${id}`)}
          className="flex items-center gap-2 text-xs text-zinc-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to Case
        </button>
        <div className="flex items-center gap-2">
          <Network className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-semibold text-white">Graph Analysis</span>
        </div>
        <span className="font-mono text-xs text-zinc-600 border border-white/10 px-2 py-0.5 rounded">
          {traceId?.slice(0, 8)}…
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Shield className="w-3.5 h-3.5 text-zinc-500" />
          <span className="text-xs text-zinc-500">Forensic Mode</span>
        </div>
      </header>

      {/* Main 3-panel layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Graph canvas — takes full width */}
        <div className="flex-1 min-w-0 p-4 flex flex-col">
          <GraphViewer
            traceId={traceId}
            onTraceWallet={(addr, chain) => {
              // navigate back to case page with pre-filled address
              router.push(`/cases/${id}?trace=${addr}&chain=${chain ?? ''}`);
            }}
          />
        </div>

        {/* Right sidebar — risk + AI */}
        <div className="w-[320px] shrink-0 border-l border-white/[0.06] bg-[#0a0a0a] overflow-y-auto p-4 space-y-4">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-zinc-600 mb-3">Risk Assessment</p>
            <RiskPanel traceId={traceId} />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-widest text-zinc-600 mb-3">AI Analysis</p>
            <MistralPanel traceId={traceId} />
          </div>
        </div>
      </div>
    </main>
  );
}

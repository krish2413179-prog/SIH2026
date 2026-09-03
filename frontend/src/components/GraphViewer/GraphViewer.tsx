'use client';

/**
 * GraphViewer — interactive Cytoscape.js transaction graph.
 *
 * Layout    : Dagre (hierarchical, left→right) showing money flow
 * Filter    : Importance threshold slider (degree + betweenness proxy + closeness proxy)
 * Path      : Auto-highlights shortest path from seed → nearest exchange on load
 * Popup     : Tap any node for details + "Trace this wallet" action
 * Path Finder: Paste a target address, highlight shortest path
 */

// ── cytoscape-dagre has no @types — loaded via require inside dynamic import

// ── ethereum-blockies-base64 has no @types ──────────────────────────────────
// eslint-disable-next-line @typescript-eslint/no-require-imports, @typescript-eslint/no-explicit-any
const makeBlockie: (address: string) => string = (() => {
  try { return require('ethereum-blockies-base64'); } catch { return () => ''; }
})();

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import {
  Download, Image as ImageIcon, Loader2, AlertCircle,
  X, Search, ExternalLink, Copy, Check, GitBranch,
  ArrowRight, Eye, EyeOff, Route, GitMerge,
  ArrowDownToLine, ArrowUpFromLine, Coins, RefreshCw, Building2, Globe,
} from 'lucide-react';
import api from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NodeData {
  id: string;
  entity_type?: string;
  label?: string;
  total_inflow?: number;
  total_outflow?: number;
  first_seen?: string;
  last_seen?: string;
  in_degree?: number;
  out_degree?: number;
  chain?: string;
  // LLM analysis fields
  llm_score?:  number;
  llm_label?:  string;
  llm_reason?: string;
  llm_flags?:  string[];
}

interface EdgeData {
  id?: string;
  source: string;
  target: string;
  amount?: number;
  tx_hash?: string;
  timestamp?: string;
  is_bridge?: boolean;
}

interface GraphData {
  nodes?: Array<{ id: string; [key: string]: unknown }>;
  links?: Array<{ source: string; target: string; [key: string]: unknown }>;
  directed?: boolean;
}

interface LLMWalletResult {
  address:         string;
  suspicion_score: number;
  label:           string;
  reason:          string;
  flags:           string[];
}

interface NodePopup {
  nodeId: string;
  data: NodeData & { importance?: number };
  x: number;
  y: number;
}

interface PathInfo {
  hops: number;
  addresses: string[];
  totalAmount: number;
  /** ISO strings of edge timestamps along path */
  timestamps: string[];
}

export interface GraphViewerProps {
  traceId: string;
  onTraceWallet?: (address: string, chain?: string) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  vasp:     '#3B82F6',
  unknown:  '#6B7280',
  flagged:  '#EF4444',
  mixer:    '#8B5CF6',
  bridge:   '#F59E0B',
  exchange: '#10B981',
};

const PROGRESSIVE_THRESHOLD = 500;
const PROGRESSIVE_INITIAL   = 100;
/** Entity types that count as "exchange" for path finding */
const EXCHANGE_TYPES = new Set(['vasp', 'exchange']);

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function nodeColor(et?: string): string {
  return NODE_COLORS[(et ?? 'unknown').toLowerCase()] ?? NODE_COLORS.unknown;
}

function edgeWidth(amount?: number): number {
  return Math.max(2, Math.log((amount ?? 0) + 1) * 1.4);
}

function fmtAmount(n?: number): string {
  if (n == null || !Number.isFinite(n) || n === 0) return '—';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return n.toFixed(4);
}

function fmtDate(iso?: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
    });
  } catch { return iso.slice(0, 10); }
}

function fmtDuration(isoA?: string, isoB?: string): string {
  if (!isoA || !isoB) return '—';
  const ms = Math.abs(new Date(isoB).getTime() - new Date(isoA).getTime());
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function shortAddr(addr: string): string {
  return addr.length > 16 ? `${addr.slice(0, 8)}…${addr.slice(-6)}` : addr;
}

// ---------------------------------------------------------------------------
// Importance scoring (client-side approximation)
//   degree centrality  40%
//   betweenness proxy  40%  (nodes on many shortest paths = high in/out)
//   closeness proxy    20%  (reciprocal of avg distance proxy via degree sum)
// ---------------------------------------------------------------------------

interface ImportanceMap { [nodeId: string]: number }

function computeImportance(graphData: GraphData): ImportanceMap {
  const nodes  = graphData.nodes ?? [];
  const links  = graphData.links ?? [];
  const n      = nodes.length;
  if (n === 0) return {};

  // Build adjacency info
  const inDeg:  Record<string, number> = {};
  const outDeg: Record<string, number> = {};
  for (const nd of nodes) { inDeg[String(nd.id)] = 0; outDeg[String(nd.id)] = 0; }
  for (const lk of links) {
    const s = String(lk.source), t = String(lk.target);
    outDeg[s] = (outDeg[s] ?? 0) + 1;
    inDeg[t]  = (inDeg[t]  ?? 0) + 1;
  }

  const maxDeg = Math.max(1, ...nodes.map(nd => (inDeg[String(nd.id)] ?? 0) + (outDeg[String(nd.id)] ?? 0)));

  const result: ImportanceMap = {};
  for (const nd of nodes) {
    const id   = String(nd.id);
    const deg  = (inDeg[id] ?? 0) + (outDeg[id] ?? 0);
    const normDeg = deg / maxDeg;                          // degree centrality

    // Betweenness proxy: nodes that both receive AND send (intermediaries)
    const btw = (inDeg[id] > 0 && outDeg[id] > 0)
      ? Math.min(inDeg[id], outDeg[id]) / (maxDeg / 2)
      : 0;

    // Closeness proxy: degree / (n-1)  (higher degree ≈ closer to everyone)
    const cls = deg / Math.max(1, n - 1);

    const score = 0.4 * normDeg + 0.4 * btw + 0.2 * cls;
    result[id]  = Math.min(1, score);
  }
  return result;
}

// ---------------------------------------------------------------------------
// BFS shortest path (undirected for reachability)
// ---------------------------------------------------------------------------

function bfsPath(
  links: GraphData['links'],
  start: string,
  targetPredicate: (id: string) => boolean,
): string[] | null {
  const adj = new Map<string, string[]>();
  for (const lk of (links ?? [])) {
    const s = String(lk.source), t = String(lk.target);
    if (!adj.has(s)) adj.set(s, []);
    if (!adj.has(t)) adj.set(t, []);
    adj.get(s)!.push(t);
    adj.get(t)!.push(s);
  }
  const queue: Array<{ node: string; path: string[] }> = [{ node: start, path: [start] }];
  const visited = new Set([start]);
  while (queue.length) {
    const { node, path } = queue.shift()!;
    if (targetPredicate(node) && node !== start) return path;
    for (const nb of (adj.get(node) ?? [])) {
      if (!visited.has(nb)) { visited.add(nb); queue.push({ node: nb, path: [...path, nb] }); }
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// toCytoscapeElements
// ---------------------------------------------------------------------------

function toCytoscapeElements(
  graphData: GraphData,
  importance: ImportanceMap,
  maxNodes?: number,
): cytoscape.ElementDefinition[] {
  const rawNodes: (NodeData & { importance: number })[] = (graphData.nodes ?? []).map((n) => ({
    id:            String(n.id),
    entity_type:   n.entity_type  as string | undefined,
    label:         (n.label ?? n.id) as string,
    total_inflow:  n.total_inflow  as number | undefined,
    total_outflow: n.total_outflow as number | undefined,
    first_seen:    n.first_seen   as string | undefined,
    last_seen:     n.last_seen    as string | undefined,
    in_degree:     n.in_degree    as number | undefined,
    out_degree:    n.out_degree   as number | undefined,
    chain:         n.chain        as string | undefined,
    importance:    importance[String(n.id)] ?? 0,
  }));

  const rawEdges: EdgeData[] = (graphData.links ?? []).map((l, i) => ({
    id:        `e${i}`,
    source:    String(l.source),
    target:    String(l.target),
    amount:    l.amount    as number | undefined,
    tx_hash:   l.tx_hash   as string | undefined,
    timestamp: l.timestamp as string | undefined,
    is_bridge: l.is_bridge as boolean | undefined,
  }));

  let nodesToRender = rawNodes;
  if (maxNodes && rawNodes.length > maxNodes) {
    nodesToRender = [...rawNodes]
      .sort((a, b) =>
        ((b.total_inflow ?? 0) + (b.total_outflow ?? 0)) -
        ((a.total_inflow ?? 0) + (a.total_outflow ?? 0)),
      )
      .slice(0, maxNodes);
  }

  const nodeIds = new Set(nodesToRender.map((n) => n.id));

  const nodeEls: cytoscape.ElementDefinition[] = nodesToRender.map((n) => ({
    group: 'nodes' as const,
    data: {
      id:            n.id,
      label:         shortAddr(n.label ?? n.id),
      full_address:  n.id,
      entity_type:   n.entity_type  ?? 'unknown',
      color:         nodeColor(n.entity_type),
      total_inflow:  n.total_inflow  ?? 0,
      total_outflow: n.total_outflow ?? 0,
      first_seen:    n.first_seen    ?? null,
      last_seen:     n.last_seen     ?? null,
      in_degree:     n.in_degree     ?? 0,
      out_degree:    n.out_degree    ?? 0,
      chain:         n.chain         ?? '',
      importance:    n.importance,
      // Blockie avatar — deterministic pixel art from address
      blockie:       makeBlockie(n.id) || '',
    },
  }));

  const edgeEls: cytoscape.ElementDefinition[] = rawEdges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => ({
      group: 'edges' as const,
      data: {
        id:        e.id,
        source:    e.source,
        target:    e.target,
        amount:    e.amount   ?? 0,
        width:     edgeWidth(e.amount),
        tx_hash:   e.tx_hash  ?? '',
        timestamp: e.timestamp ?? '',
        is_bridge: e.is_bridge ? 1 : 0,
        label:     e.amount && e.amount > 0 ? fmtAmount(e.amount) : '',
      },
    }));

  return [...nodeEls, ...edgeEls];
}

// ---------------------------------------------------------------------------
// NodePopupCard
// ---------------------------------------------------------------------------

interface NodePopupCardProps {
  popup: NodePopup;
  containerRef: React.RefObject<HTMLDivElement>;
  onClose: () => void;
  onTrace: (address: string, chain?: string) => void;
  llmResult?: LLMWalletResult;
}

function NodePopupCard({ popup, containerRef, onClose, onTrace, llmResult }: NodePopupCardProps) {
  const { data } = popup;
  const [copied, setCopied] = useState(false);

  const CARD_W = 300, CARD_H = 280;
  const cW = containerRef.current?.clientWidth  ?? 800;
  const cH = containerRef.current?.clientHeight ?? 600;
  let left = popup.x + 14, top = popup.y - 20;
  if (left + CARD_W > cW - 8)  left = popup.x - CARD_W - 14;
  if (top  + CARD_H > cH - 8)  top  = cH - CARD_H - 8;
  if (top  < 4) top  = 4;
  if (left < 4) left = 4;

  const et    = (data.entity_type ?? 'unknown').toLowerCase();
  const color = NODE_COLORS[et] ?? NODE_COLORS.unknown;

  function copyAddr() {
    navigator.clipboard.writeText(data.id);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }

  return (
    <div
      className="absolute z-20 rounded-xl border shadow-2xl bg-gray-900 text-white text-xs"
      style={{ left, top, width: CARD_W, borderColor: color, boxShadow: `0 0 20px ${color}40, 0 4px 24px #00000080` }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 rounded-t-xl"
        style={{ backgroundColor: `${color}20`, borderBottom: `1px solid ${color}40` }}
      >
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}` }} />
          <span className="font-semibold uppercase tracking-wide text-[11px]" style={{ color }}>{et}</span>
          {data.chain && (
            <span className="text-gray-400 text-[10px] bg-gray-800 px-1.5 py-0.5 rounded">{data.chain}</span>
          )}
          {data.importance != null && (
            <span className="text-gray-500 text-[10px] bg-gray-800 px-1.5 py-0.5 rounded">
              imp {(data.importance * 100).toFixed(0)}%
            </span>
          )}
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors rounded p-0.5" aria-label="Close">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Address */}
      <div className="px-3 py-2 border-b border-gray-800 flex items-center gap-2">
        {data.id && makeBlockie(data.id) && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={makeBlockie(data.id)}
            alt="blockie"
            className="w-7 h-7 rounded-md shrink-0 border border-gray-700"
          />
        )}
        <span className="font-mono text-gray-300 text-[11px] truncate flex-1" title={data.id}>{data.id}</span>
        <button onClick={copyAddr} className="text-gray-500 hover:text-white transition-colors shrink-0" title="Copy address">
          {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-px bg-gray-800 mx-3 my-2 rounded-lg overflow-hidden text-[11px]">
        {([
          ['Inflow',     fmtAmount(data.total_inflow)],
          ['Outflow',    fmtAmount(data.total_outflow)],
          ['In-degree',  String(data.in_degree  ?? 0)],
          ['Out-degree', String(data.out_degree ?? 0)],
          ['First seen', fmtDate(data.first_seen)],
          ['Last seen',  fmtDate(data.last_seen)],
        ] as [string, string][]).map(([label, val]) => (
          <div key={label} className="bg-gray-900 px-2.5 py-1.5 flex flex-col gap-0.5">
            <span className="text-gray-500 uppercase tracking-wide text-[9px]">{label}</span>
            <span className="text-white font-medium">{val}</span>
          </div>
        ))}
      </div>

      {/* LLM Suspicion Analysis */}
      {llmResult && (
        <div className={`mx-3 mb-2 rounded-lg px-3 py-2 text-[11px] border ${
          llmResult.label === 'highly_suspicious'
            ? 'bg-red-950/50 border-red-700'
            : llmResult.label === 'suspicious'
            ? 'bg-orange-950/50 border-orange-700'
            : 'bg-green-950/30 border-green-800'
        }`}>
          <div className="flex items-center justify-between mb-1">
            <span className={`font-bold uppercase tracking-wide text-[10px] ${
              llmResult.label === 'highly_suspicious' ? 'text-red-400'
              : llmResult.label === 'suspicious'      ? 'text-orange-400'
              : 'text-green-400'
            }`}>
              {llmResult.label === 'highly_suspicious' ? '⚠ Highly Suspicious'
               : llmResult.label === 'suspicious'      ? '⚡ Suspicious'
               : '✓ Clean'}
            </span>
            <span className={`font-mono font-bold text-sm ${
              llmResult.suspicion_score >= 70 ? 'text-red-400'
              : llmResult.suspicion_score >= 40 ? 'text-orange-400'
              : 'text-green-400'
            }`}>{llmResult.suspicion_score}/100</span>
          </div>
          <p className="text-gray-300 leading-relaxed">{llmResult.reason}</p>
          {llmResult.flags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {llmResult.flags.map(f => (
                <span key={f} className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 text-[9px] uppercase tracking-wide">
                  {f.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="px-3 pb-3 flex gap-2">        <button
          onClick={() => onTrace(data.id, data.chain)}
          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-[11px] font-medium text-white transition-colors"
          style={{ backgroundColor: color }}
        >
          <GitBranch className="w-3 h-3" /> Trace this wallet
        </button>
        <button
          onClick={() => {
            const explorers: Record<string, string> = {
              ETH:   `https://etherscan.io/address/${data.id}`,
              BSC:   `https://bscscan.com/address/${data.id}`,
              MATIC: `https://polygonscan.com/address/${data.id}`,
              TRX:   `https://tronscan.org/#/address/${data.id}`,
              SOL:   `https://solscan.io/account/${data.id}`,
              BTC:   `https://mempool.space/address/${data.id}`,
            };
            window.open(explorers[data.chain ?? ''] ?? `https://etherscan.io/address/${data.id}`, '_blank', 'noopener');
          }}
          title="Open in block explorer"
          className="px-2 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white transition-colors"
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PathFinder panel (manual address input)
// ---------------------------------------------------------------------------

interface PathFinderProps {
  graphData: GraphData;
  seedAddress: string;
  cyRef: React.RefObject<cytoscape.Core | null>;
}

function PathFinder({ graphData, seedAddress, cyRef }: PathFinderProps) {
  const [target, setTarget] = useState('');
  const [result, setResult] = useState<string | null>(null);
  const [found,  setFound]  = useState<boolean | null>(null);

  const adjRef = useRef<Map<string, string[]> | null>(null);
  useEffect(() => {
    const adj = new Map<string, string[]>();
    for (const lk of (graphData.links ?? [])) {
      const s = String(lk.source), t = String(lk.target);
      if (!adj.has(s)) adj.set(s, []);
      if (!adj.has(t)) adj.set(t, []);
      adj.get(s)!.push(t);
      adj.get(t)!.push(s);
    }
    adjRef.current = adj;
  }, [graphData]);

  function findPath() {
    const t = target.trim().toLowerCase();
    if (!t || !adjRef.current) return;
    const cy = cyRef.current;
    const adj = adjRef.current;

    const queue: Array<{ node: string; path: string[] }> = [{ node: seedAddress, path: [seedAddress] }];
    const visited = new Set([seedAddress]);
    let foundPath: string[] | null = null;

    while (queue.length) {
      const { node, path } = queue.shift()!;
      if (node.toLowerCase() === t) { foundPath = path; break; }
      for (const nb of (adj.get(node) ?? [])) {
        if (!visited.has(nb)) { visited.add(nb); queue.push({ node: nb, path: [...path, nb] }); }
      }
    }

    cy?.elements().removeClass('path-highlight path-dim');
    if (!foundPath) {
      setFound(false);
      setResult('No path found between these two addresses.');
      return;
    }
    setFound(true);
    setResult(`Path found — ${foundPath.length} hops: ${foundPath.map(shortAddr).join(' → ')}`);
    if (!cy) return;
    cy.elements().addClass('path-dim');
    for (let i = 0; i < foundPath.length; i++) {
      cy.getElementById(foundPath[i]).addClass('path-highlight').removeClass('path-dim');
      if (i < foundPath.length - 1) {
        cy.edges().filter((e) =>
          (e.source().id() === foundPath![i] && e.target().id() === foundPath![i + 1]) ||
          (e.source().id() === foundPath![i + 1] && e.target().id() === foundPath![i]),
        ).addClass('path-highlight').removeClass('path-dim');
      }
    }
    cy.fit(cy.elements('.path-highlight'), 60);
  }

  function clear() {
    setTarget(''); setResult(null); setFound(null);
    cyRef.current?.elements().removeClass('path-highlight path-dim');
  }

  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800 p-4">
      <div className="flex items-center gap-2 mb-3">
        <Search className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-gray-200">Path Finder</h3>
        <span className="text-xs text-gray-500 ml-1">Check if a target address was transacted with</span>
      </div>
      <div className="flex gap-2">
        <input
          type="text" value={target}
          onChange={(e) => setTarget(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && findPath()}
          placeholder="Paste target wallet address…"
          className="flex-1 rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm font-mono text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none"
        />
        <button onClick={findPath} disabled={!target.trim()}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-40 text-sm font-medium text-white transition-colors">
          <ArrowRight className="w-4 h-4" /> Find
        </button>
        {result && (
          <button onClick={clear} className="px-3 py-2 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-300 hover:text-white transition-colors" title="Clear">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
      {result && (
        <div className={`mt-2.5 rounded-lg px-3 py-2 text-xs font-mono break-all ${found ? 'bg-green-900/30 border border-green-700 text-green-300' : 'bg-red-900/30 border border-red-700 text-red-300'}`}>
          {result}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// PathInfoBox — shows auto-detected exchange path details
// ---------------------------------------------------------------------------

interface PathInfoBoxProps {
  info: PathInfo;
  onShowFull: () => void;
  pathMode: boolean;
}

function PathInfoBox({ info, onShowFull, pathMode }: PathInfoBoxProps) {
  const duration = fmtDuration(info.timestamps[0], info.timestamps[info.timestamps.length - 1]);
  return (
    <div className="rounded-xl border border-yellow-700 bg-yellow-950/40 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Route className="w-4 h-4 text-yellow-400" />
          <span className="text-sm font-semibold text-yellow-300">Shortest Path to Exchange</span>
        </div>
        <button
          onClick={onShowFull}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${pathMode ? 'bg-yellow-700 hover:bg-yellow-600 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}
        >
          {pathMode ? <><EyeOff className="w-3.5 h-3.5" /> Show Full Network</> : <><Eye className="w-3.5 h-3.5" /> Highlight Path</>}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <div className="bg-gray-900/60 rounded-lg px-3 py-2">
          <div className="text-gray-500 uppercase tracking-wide text-[9px] mb-0.5">Hops</div>
          <div className="text-yellow-300 font-bold text-base">{info.hops}</div>
        </div>
        <div className="bg-gray-900/60 rounded-lg px-3 py-2">
          <div className="text-gray-500 uppercase tracking-wide text-[9px] mb-0.5">Total Amount</div>
          <div className="text-yellow-300 font-bold text-base">{fmtAmount(info.totalAmount)}</div>
        </div>
        <div className="bg-gray-900/60 rounded-lg px-3 py-2">
          <div className="text-gray-500 uppercase tracking-wide text-[9px] mb-0.5">Time Span</div>
          <div className="text-yellow-300 font-bold text-base">{duration}</div>
        </div>
        <div className="bg-gray-900/60 rounded-lg px-3 py-2">
          <div className="text-gray-500 uppercase tracking-wide text-[9px] mb-0.5">Nodes</div>
          <div className="text-yellow-300 font-bold text-base">{info.addresses.length}</div>
        </div>
      </div>
      <div className="mt-3 text-[11px] font-mono text-gray-400 bg-gray-900/60 rounded-lg px-3 py-2 break-all leading-relaxed">
        {info.addresses.map(shortAddr).join(' → ')}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main GraphViewer
// ---------------------------------------------------------------------------

export function GraphViewer({ traceId, onTraceWallet }: GraphViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cyRef = useRef<any>(null);

  const [graphData,   setGraphData]   = useState<GraphData | null>(null);
  const [seedAddr,    setSeedAddr]    = useState<string>('');
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState<string | null>(null);
  const [nodeCount,   setNodeCount]   = useState(0);
  const [progressive, setProgressive] = useState(false);
  const [nodePopup,   setNodePopup]   = useState<NodePopup | null>(null);

  // Category filter — replaces importance threshold
  type FilterCategory = 'all' | 'incoming' | 'outgoing' | 'tokens' | 'dex' | 'exchanges';
  const [filterCategory, setFilterCategory] = useState<FilterCategory>('all');

  // Keep these for backward compat with visibleCount
  const threshold    = 0;
  const showAllNodes = true;

  // Exchange path
  const [pathInfo,  setPathInfo]  = useState<PathInfo | null>(null);
  const [pathMode,  setPathMode]  = useState(false);

  // Graph expand
  const [expanding,     setExpanding]     = useState(false);
  const [expandTaskId,  setExpandTaskId]  = useState<string | null>(null);
  const [expandStatus,  setExpandStatus]  = useState<string | null>(null); // 'SUCCESS'|'FAILURE'|'PENDING'
  const [expandResult,  setExpandResult]  = useState<{nodes:number;edges:number;new_nodes:number} | null>(null);
  const expandPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // LLM analysis — map of address (lowercase) → result
  const [llmMap,     setLlmMap]     = useState<Record<string, LLMWalletResult>>({});
  const [llmLoading, setLlmLoading] = useState(false);

  // ── Importance scores (memo — recompute only when graphData changes) ──────
  const importance = useMemo(
    () => (graphData ? computeImportance(graphData) : {}),
    [graphData],
  );

  // ── Visible / hidden counts ───────────────────────────────────────────────
  const { visibleCount, totalCount } = useMemo(() => {
    if (!graphData) return { visibleCount: 0, totalCount: 0 };
    const total = (graphData.nodes ?? []).length;
    return { visibleCount: total, totalCount: total };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData]);

  // ── Fetch graph ───────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null); setNodePopup(null); setPathInfo(null); setPathMode(false);

    api.get<GraphData>(`/traces/${traceId}/graph`)
      .then((res) => {
        if (!cancelled) {
          setGraphData(res.data);
          const n = (res.data.nodes ?? []).length;
          setNodeCount(n);
          setProgressive(n > PROGRESSIVE_THRESHOLD);
          const first = res.data.nodes?.[0];
          if (first) setSeedAddr(String(first.id));
          // Reset category filter to 'all' when new trace data loads
          setFilterCategory('all');
        }
      })
      .catch((err) => {
        if (!cancelled) {
          const s = err?.response?.status;
          setError(s === 404 ? '__pending__' : (err?.response?.data?.detail ?? err?.message ?? 'Failed to load graph.'));
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [traceId]);

  // ── Build exchange path once graphData + importance are ready ─────────────
  useEffect(() => {
    if (!graphData || !seedAddr) return;
    const nodes = graphData.nodes ?? [];
    const links = graphData.links ?? [];
    const exchangeIds = new Set(
      nodes
        .filter((n) => EXCHANGE_TYPES.has((n.entity_type as string ?? '').toLowerCase()))
        .map((n) => String(n.id)),
    );
    if (exchangeIds.size === 0) return;

    const path = bfsPath(links, seedAddr, (id) => exchangeIds.has(id));
    if (!path || path.length < 2) return;

    // Collect amounts and timestamps along path edges
    let totalAmount = 0;
    const timestamps: string[] = [];
    for (let i = 0; i < path.length - 1; i++) {
      const edge = links.find(
        (l) => String(l.source) === path[i] && String(l.target) === path[i + 1],
      );
      if (edge) {
        totalAmount += (edge.amount as number) ?? 0;
        if (edge.timestamp) timestamps.push(edge.timestamp as string);
      }
    }

    setPathInfo({ hops: path.length - 1, addresses: path, totalAmount, timestamps });
  }, [graphData, seedAddr]);

  // ── Apply/remove path highlight when pathMode toggles ────────────────────
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !pathInfo) return;
    cy.elements().removeClass('exchange-path exchange-dim');
    if (!pathMode) return;
    cy.elements().addClass('exchange-dim');
    for (let i = 0; i < pathInfo.addresses.length; i++) {
      cy.getElementById(pathInfo.addresses[i]).addClass('exchange-path').removeClass('exchange-dim');
      if (i < pathInfo.addresses.length - 1) {
        cy.edges().filter((e: cytoscape.EdgeSingular) =>
          e.source().id() === pathInfo.addresses[i] &&
          e.target().id() === pathInfo.addresses[i + 1],
        ).addClass('exchange-path').removeClass('exchange-dim');
      }
    }
    cy.fit(cy.elements('.exchange-path'), 80);
  }, [pathMode, pathInfo]);

  // ── Fetch LLM analysis after graph data loads ────────────────────────────
  useEffect(() => {
    if (!graphData || !traceId) return;
    let cancelled = false;
    setLlmLoading(true);
    api.get<{ wallets: LLMWalletResult[] }>(`/traces/${traceId}/llm-analysis`)
      .then((res) => {
        if (cancelled) return;
        const map: Record<string, LLMWalletResult> = {};
        for (const w of (res.data.wallets ?? [])) {
          map[w.address.toLowerCase()] = w;
        }
        setLlmMap(map);

        // Apply LLM results onto Cytoscape nodes if cy is ready
        const cy = cyRef.current;
        if (cy) {
          cy.nodes().forEach((node: cytoscape.NodeSingular) => {
            const addr: string = (node.data('full_address') ?? node.id()).toLowerCase();
            const result = map[addr];
            if (!result) return;
            node.data('llm_score',  result.suspicion_score);
            node.data('llm_label',  result.label);
            node.data('llm_reason', result.reason);
            node.data('llm_flags',  result.flags);
            // Re-apply visual class based on label
            node.removeClass('llm-suspicious llm-highly-suspicious');
            if (result.label === 'highly_suspicious') node.addClass('llm-highly-suspicious');
            else if (result.label === 'suspicious')   node.addClass('llm-suspicious');
          });
        }
      })
      .catch(() => { /* LLM analysis is optional — fail silently */ })
      .finally(() => { if (!cancelled) setLlmLoading(false); });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData, traceId]);

  // ── DEX / token router address patterns ─────────────────────────────────
  const DEX_PATTERNS = [
    '0x7a250d5630b4cf539739df2c5dacb4c659f2488d', // Uniswap V2 Router
    '0xe592427a0aece92de3edee1f18e0157c05861564', // Uniswap V3 Router
    '0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad', // Uniswap Universal Router
    '0xdef1c0ded9bec7f1a1670819833240f027b25eff', // 0x Exchange
    '0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f', // Sushiswap Router
    '0x1111111254fb6c44bac0bed2854e76f90643097d', // 1inch
  ];
  const TOKEN_TYPES = new Set(['erc20', 'token', 'stablecoin', 'nft', 'defi']);
  const EXCHANGE_FILTER_TYPES = new Set(['cex', 'vasp', 'exchange', 'mixer', 'bridge', 'flagged']);

  // ── Apply category filter reactively ────────────────────────────────────
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !graphData) return;

    // Always start clean
    cy.elements().removeClass('filtered-out');

    if (filterCategory === 'all') return;

    const links = graphData.links ?? [];

    if (filterCategory === 'incoming') {
      // Show only edges flowing INTO the seed wallet + their source nodes
      const incomingSourceIds = new Set<string>();
      links.forEach(l => {
        if (String(l.target).toLowerCase() === seedAddr.toLowerCase()) {
          incomingSourceIds.add(String(l.source));
        }
      });
      cy.nodes().forEach((node: cytoscape.NodeSingular) => {
        const id = (node.data('full_address') ?? node.id()).toLowerCase();
        const isSeed = id === seedAddr.toLowerCase();
        if (!isSeed && !incomingSourceIds.has(id)) node.addClass('filtered-out');
      });
    } else if (filterCategory === 'outgoing') {
      // Show only edges flowing OUT of the seed wallet + their target nodes
      const outgoingTargetIds = new Set<string>();
      links.forEach(l => {
        if (String(l.source).toLowerCase() === seedAddr.toLowerCase()) {
          outgoingTargetIds.add(String(l.target));
        }
      });
      cy.nodes().forEach((node: cytoscape.NodeSingular) => {
        const id = (node.data('full_address') ?? node.id()).toLowerCase();
        const isSeed = id === seedAddr.toLowerCase();
        if (!isSeed && !outgoingTargetIds.has(id)) node.addClass('filtered-out');
      });
    } else if (filterCategory === 'tokens') {
      // Show nodes tagged as token/DeFi types
      cy.nodes().forEach((node: cytoscape.NodeSingular) => {
        const et = (node.data('entity_type') ?? '').toLowerCase();
        if (!TOKEN_TYPES.has(et) && node.id() !== seedAddr) node.addClass('filtered-out');
      });
    } else if (filterCategory === 'dex') {
      // Show nodes that are known DEX routers (by address match)
      cy.nodes().forEach((node: cytoscape.NodeSingular) => {
        const addr = (node.data('full_address') ?? node.id()).toLowerCase();
        const isDex = DEX_PATTERNS.some(p => addr === p);
        if (!isDex && addr !== seedAddr.toLowerCase()) node.addClass('filtered-out');
      });
    } else if (filterCategory === 'exchanges') {
      // Show only exchange/mixer/bridge/VASP tagged nodes
      cy.nodes().forEach((node: cytoscape.NodeSingular) => {
        const et = (node.data('entity_type') ?? '').toLowerCase();
        if (!EXCHANGE_FILTER_TYPES.has(et) && node.id() !== seedAddr) node.addClass('filtered-out');
      });
    }

    // Hide edges where either endpoint is filtered-out
    cy.edges().forEach((edge: cytoscape.EdgeSingular) => {
      (edge.source().hasClass('filtered-out') || edge.target().hasClass('filtered-out'))
        ? edge.addClass('filtered-out')
        : edge.removeClass('filtered-out');
    });

    // Fit visible elements
    const visible = cy.elements(':visible').not('.filtered-out');
    if (visible.length > 0) cy.fit(visible, 60);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterCategory, seedAddr, graphData]);

  // ── Init / re-render Cytoscape ────────────────────────────────────────────
  useEffect(() => {
    if (!graphData || !containerRef.current) return;

    // Dynamically import both cytoscape and cytoscape-dagre to avoid SSR issues
    Promise.all([
      import('cytoscape'),
    ]).then(([cytoscapeModule]) => {
      const cytoscape = cytoscapeModule.default;
      // eslint-disable-next-line @typescript-eslint/no-require-imports, @typescript-eslint/no-explicit-any
      const cytoscapeDagre = require('cytoscape-dagre') as any;
      // eslint-disable-next-line @typescript-eslint/no-require-imports, @typescript-eslint/no-explicit-any
      const coseBilkent = require('cytoscape-cose-bilkent') as any;

      // Register extensions (idempotent)
      try { cytoscape.use(cytoscapeDagre); } catch { /* already registered */ }
      try { cytoscape.use(coseBilkent);    } catch { /* already registered */ }

      if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null; }

      const maxNodes = progressive ? PROGRESSIVE_INITIAL : undefined;
      const elements = toCytoscapeElements(graphData, importance, maxNodes);

      const cy = cytoscape({
        container: containerRef.current!,
        elements,
        style: [
          // ── Nodes ────────────────────────────────────────────────
          {
            selector: 'node',
            style: {
              'background-color':            'data(color)',
              'border-color':                'data(color)',
              'border-width':                2,
              'border-opacity':              0.85,
              label:                         'data(label)',
              color:                         '#E5E7EB',
              'font-size':                   '10px',
              'font-family':                 'ui-monospace, monospace',
              'text-valign':                 'bottom',
              'text-halign':                 'center',
              'text-margin-y':               5,
              'text-wrap':                   'ellipsis',
              'text-max-width':              '90px',
              'text-background-color':       '#111827',
              'text-background-opacity':     0.75,
              'text-background-padding':     '2px',
              'text-background-shape':       'roundrectangle',
              width:  36,
              height: 36,
            },
          },
          {
            selector: 'node[entity_type = "vasp"]',
            style: { width: 46, height: 46, 'border-width': 3, 'border-color': '#93C5FD' },
          },
          {
            selector: 'node[entity_type = "exchange"]',
            style: { width: 46, height: 46, 'border-width': 3, 'border-color': '#6EE7B7' },
          },
          {
            selector: 'node[entity_type = "flagged"]',
            style: { width: 42, height: 42, 'border-width': 3, 'border-color': '#FCA5A5' },
          },
          {
            selector: 'node[entity_type = "mixer"]',
            style: { 'border-width': 3, 'border-color': '#C4B5FD' },
          },
          {
            selector: 'node[entity_type = "bridge"]',
            style: { 'border-width': 3, 'border-color': '#FDE68A' },
          },
          {
            selector: 'node:selected',
            style: { 'border-color': '#FBBF24', 'border-width': 4, color: '#FEF3C7' },
          },
          // importance filter
          {
            selector: 'node.filtered-out',
            style: { display: 'none' },
          },
          // manual path finder highlight
          {
            selector: 'node.path-highlight',
            style: { 'border-color': '#34D399', 'border-width': 4, width: 42, height: 42, color: '#D1FAE5' },
          },
          {
            selector: 'node.path-dim',
            style: { opacity: 0.2 },
          },
          // exchange path highlight
          {
            selector: 'node.exchange-path',
            style: { 'border-color': '#FBBF24', 'border-width': 4, width: 44, height: 44, color: '#FEF3C7' },
          },
          {
            selector: 'node.exchange-dim',
            style: { opacity: 0.3 },
          },

          // ── Edges ────────────────────────────────────────────────
          {
            selector: 'edge',
            style: {
              width:                'data(width)',
              'line-color':         '#4B5563',
              'target-arrow-color': '#9CA3AF',
              'target-arrow-shape': 'triangle',
              'arrow-scale':        1.4,
              'curve-style':        'bezier',
              opacity:              0.85,
              label:                'data(label)',
              'font-size':          '8px',
              color:                '#9CA3AF',
              'text-rotation':      'autorotate',
              'text-margin-y':      -6,
              'text-background-color':   '#1F2937',
              'text-background-opacity': 0.8,
              'text-background-padding': '1px',
              'text-background-shape':   'roundrectangle',
            },
          },
          {
            selector: 'edge[is_bridge = 1]',
            style: {
              'line-color':         '#F59E0B',
              'target-arrow-color': '#F59E0B',
              'line-style':         'dashed',
              'line-dash-pattern':  [8, 4],
            },
          },
          {
            selector: 'edge:selected',
            style: { 'line-color': '#FBBF24', 'target-arrow-color': '#FBBF24', opacity: 1 },
          },
          {
            selector: 'edge.filtered-out',
            style: { display: 'none' },
          },
          {
            selector: 'edge.path-highlight',
            style: { 'line-color': '#34D399', 'target-arrow-color': '#34D399', width: 4, opacity: 1 },
          },
          {
            selector: 'edge.path-dim',
            style: { opacity: 0.08 },
          },
          {
            selector: 'edge.exchange-path',
            style: { 'line-color': '#FBBF24', 'target-arrow-color': '#FBBF24', width: 4, opacity: 1 },
          },
          {
            selector: 'edge.exchange-dim',
            style: { opacity: 0.15 },
          },
          // ── LLM suspicion styles ─────────────────────────────────
          {
            selector: 'node.llm-suspicious',
            style: {
              'border-color': '#F97316',  // orange
              'border-width': 3,
            },
          },
          {
            selector: 'node.llm-highly-suspicious',
            style: {
              'border-color': '#EF4444',  // red
              'border-width': 4,
              width:  44,
              height: 44,
            },
          },
        ],
        // ── Layout: Dagre for small focused graphs, cose-bilkent for large ──
        // Dagre stacks 200+ nodes in a single column when the graph is sparse.
        // cose-bilkent (force-directed with compound support) handles large
        // sparse graphs cleanly and keeps connected clusters together.
        layout: elements.length <= 60
          ? ({
              name:        'dagre',
              rankDir:     'LR',
              ranker:      'network-simplex',
              rankSep:     140,
              nodeSep:     80,
              edgeSep:     30,
              padding:     50,
              animate:     false,
              fit:         true,
            } as cytoscape.LayoutOptions)
          : ({
              name:            'cose',
              animate:         false,
              randomize:       true,
              componentSpacing: 100,
              nodeRepulsion:   (_node: unknown) => 450000,
              idealEdgeLength: (_edge: unknown) => 100,
              edgeElasticity:  (_edge: unknown) => 100,
              nestingFactor:   1.2,
              gravity:         0.25,
              numIter:         1000,
              initialTemp:     1000,
              coolingFactor:   0.99,
              minTemp:         1.0,
              padding:         50,
              fit:             true,
            } as cytoscape.LayoutOptions),
        wheelSensitivity: 0.3,
        minZoom: 0.05,
        maxZoom: 6,
      });

      cyRef.current = cy;

      // Tap node → popup
      cy.on('tap', 'node', (evt: cytoscape.EventObject) => {
        const node = evt.target as cytoscape.NodeSingular;
        const pos  = node.renderedPosition();
        const d    = node.data();
        setNodePopup({
          nodeId: node.id() as string,
          data: {
            id:            d.full_address as string,
            entity_type:   d.entity_type  as string,
            total_inflow:  d.total_inflow  as number,
            total_outflow: d.total_outflow as number,
            in_degree:     d.in_degree     as number,
            out_degree:    d.out_degree    as number,
            first_seen:    d.first_seen    as string | undefined,
            last_seen:     d.last_seen     as string | undefined,
            chain:         d.chain         as string,
            importance:    d.importance    as number,
          },
          x: pos.x, y: pos.y,
        });
      });
      cy.on('tap',      (evt: cytoscape.EventObject) => { if (evt.target === cy) setNodePopup(null); });
      cy.on('drag',     'node', () => setNodePopup(null));
      cy.on('viewport', () => setNodePopup(null));

      // Apply importance filter imperatively
      const applyFilter = () => {
        if (showAllNodes) {
          cy.elements().removeClass('filtered-out');
          return;
        }
        cy.nodes().forEach((node: cytoscape.NodeSingular) => {
          const imp: number = node.data('importance') ?? 0;
          const isSeed = node.data('full_address') === seedAddr || node.id() === seedAddr;
          // Always keep: seed node + any node directly connected to seed
          const connectedToSeed = cy.getElementById(seedAddr).neighborhood().has(node);
          if (imp < threshold && !isSeed && !connectedToSeed) {
            node.addClass('filtered-out');
          } else {
            node.removeClass('filtered-out');
          }
        });
        cy.edges().forEach((edge: cytoscape.EdgeSingular) => {
          (edge.source().hasClass('filtered-out') || edge.target().hasClass('filtered-out'))
            ? edge.addClass('filtered-out')
            : edge.removeClass('filtered-out');
        });
      };

      // Apply blockie images imperatively — Cytoscape won't render base64
      // data URIs when passed through the data() stylesheet mapper, so we
      // must set background-image directly on each node after layout.
      const applyBlockies = () => {
        cy.nodes().forEach((node: cytoscape.NodeSingular) => {
          const addr: string = node.data('full_address') ?? node.id();
          try {
            const img = makeBlockie(addr);
            if (img) {
              node.style({
                'background-image': img,
                'background-fit': 'cover',
                'background-opacity': 1,
              });
            }
          } catch { /* non-ETH address — leave as plain color */ }
        });
      };

      applyFilter();
      applyBlockies();

      // Apply any LLM results already in state (e.g. on re-render)
      if (Object.keys(llmMap).length > 0) {
        cy.nodes().forEach((node: cytoscape.NodeSingular) => {
          const addr: string = (node.data('full_address') ?? node.id()).toLowerCase();
          const result = llmMap[addr];
          if (!result) return;
          node.data('llm_score',  result.suspicion_score);
          node.data('llm_label',  result.label);
          node.data('llm_reason', result.reason);
          node.data('llm_flags',  result.flags);
          node.removeClass('llm-suspicious llm-highly-suspicious');
          if (result.label === 'highly_suspicious') node.addClass('llm-highly-suspicious');
          else if (result.label === 'suspicious')   node.addClass('llm-suspicious');
        });
      }

      // ── After layout: fit view to seed + its 1-hop neighbourhood ─
      // This keeps the most important part of the graph centred on load.
      // Users can scroll/zoom out to see the rest.
      cy.one('layoutstop', () => {
        const seedNode = cy.getElementById(seedAddr);
        if (seedNode && seedNode.length > 0) {
          // Include seed + direct neighbours (1 hop)
          const focus = seedNode.union(seedNode.neighborhood());
          if (focus.length > 0) {
            cy.fit(focus, 80);
            // Clamp zoom so the seed isn't microscopic
            if (cy.zoom() > 1.8) cy.zoom(1.8);
          }
        } else {
          // Fallback: fit whole graph
          cy.fit(undefined, 40);
        }
      });
    });

    return () => { if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null; } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData, progressive]);

  // ── Expand graph ─────────────────────────────────────────────────────────
  const handleExpand = useCallback(async () => {
    setExpanding(true);
    setExpandStatus('PENDING');
    setExpandResult(null);
    try {
      const res = await api.post<{ celery_task_id: string; trace_id: string }>(
        `/traces/${traceId}/expand`,
      );
      const taskId = res.data.celery_task_id;
      setExpandTaskId(taskId);

      // Poll every 3 s until SUCCESS or FAILURE
      if (expandPollRef.current) clearInterval(expandPollRef.current);
      expandPollRef.current = setInterval(async () => {
        try {
          const poll = await api.get<{
            state: string;
            result?: { nodes: number; edges: number; new_nodes: number };
            error?: string;
          }>(`/traces/${traceId}/expand/status`, {
            params: { celery_task_id: taskId },
          });
          const { state, result } = poll.data;
          setExpandStatus(state);
          if (state === 'SUCCESS') {
            clearInterval(expandPollRef.current!);
            expandPollRef.current = null;
            setExpanding(false);
            if (result) setExpandResult(result);
            // Reload the graph data to show new nodes
            const graphRes = await api.get<GraphData>(`/traces/${traceId}/graph`);
            setGraphData(graphRes.data);
            setNodeCount((graphRes.data.nodes ?? []).length);
          } else if (state === 'FAILURE') {
            clearInterval(expandPollRef.current!);
            expandPollRef.current = null;
            setExpanding(false);
          }
        } catch { /* poll errors are non-fatal */ }
      }, 3000);
    } catch {
      setExpanding(false);
      setExpandStatus('FAILURE');
    }
  }, [traceId]);

  // Clean up polling on unmount
  useEffect(() => {
    return () => { if (expandPollRef.current) clearInterval(expandPollRef.current); };
  }, []);

  // ── Exports ───────────────────────────────────────────────────────────────
  const handleExportPng = useCallback(() => {
    if (!cyRef.current) return;
    const png: string = cyRef.current.png({ full: true, scale: 2, bg: '#111827' });
    const a = document.createElement('a'); a.href = png; a.download = `trace-${traceId}-graph.png`; a.click();
  }, [traceId]);

  const handleExportJson = useCallback(() => {
    if (!graphData) return;
    const blob = new Blob([JSON.stringify(graphData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `trace-${traceId}-graph.json`; a.click();
    URL.revokeObjectURL(url);
  }, [graphData, traceId]);

  // ── Loading / error ───────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 bg-gray-900 rounded-xl border border-gray-700">
        <Loader2 className="w-8 h-8 text-blue-400 animate-spin mr-3" />
        <span className="text-gray-400 text-sm">Loading transaction graph…</span>
      </div>
    );
  }
  if (error === '__pending__') {
    return (
      <div className="flex flex-col items-center justify-center h-48 bg-gray-900 rounded-xl border border-gray-700 gap-3">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        <p className="text-gray-400 text-sm font-medium">Trace pending</p>
        <p className="text-gray-500 text-xs max-w-xs text-center">Graph will appear once the Celery worker finishes tracing.</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-96 bg-gray-900 rounded-xl border border-red-800 gap-3">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-red-400 text-sm font-medium">Failed to load graph</p>
        <p className="text-gray-500 text-xs max-w-xs text-center">{error}</p>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-3">

      {/* ── Toolbar ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-800 rounded-lg border border-gray-700 flex-wrap gap-2">
        {/* Legend */}
        <div className="flex items-center gap-3 flex-wrap">
          {Object.entries(NODE_COLORS).map(([type, color]) => (
            <span key={type} className="flex items-center gap-1.5 text-xs text-gray-300">
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color, boxShadow: `0 0 5px ${color}` }} />
              {type.charAt(0).toUpperCase() + type.slice(1)}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {progressive && (
            <span className="text-xs text-amber-400">
              Top {PROGRESSIVE_INITIAL}/{nodeCount}{' '}
              <button onClick={() => setProgressive(false)} className="underline hover:text-amber-300">Show all</button>
            </span>
          )}
          <button onClick={handleExportPng} className="flex items-center gap-1 px-2.5 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-md transition-colors">
            <ImageIcon className="w-3.5 h-3.5" /> PNG
          </button>
          <button onClick={handleExportJson} className="flex items-center gap-1 px-2.5 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-md transition-colors">
            <Download className="w-3.5 h-3.5" /> JSON
          </button>
          <button
            onClick={handleExpand}
            disabled={expanding}
            title="Expand graph by one more BFS hop from leaf wallets"
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 text-white rounded-md transition-colors"
          >
            {expanding
              ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Expanding…</>
              : <><GitMerge className="w-3.5 h-3.5" /> Expand</>}
          </button>
        </div>
      </div>

      {/* ── Transaction Category Filters ───────────────────────────── */}
      <div className="rounded-xl border border-gray-700 bg-gray-800 px-4 py-3">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold text-gray-200">Transaction Filters</span>
          <span className="text-xs text-gray-500">
            Showing <span className="text-white font-semibold">{visibleCount}</span> of <span className="text-gray-300">{totalCount}</span> wallets
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {([
            { key: 'all',       label: 'All Flows',      Icon: Globe,           color: 'from-blue-600 to-blue-700',     ring: 'ring-blue-500'   },
            { key: 'incoming',  label: 'Incoming',       Icon: ArrowDownToLine, color: 'from-green-600 to-green-700',   ring: 'ring-green-500'  },
            { key: 'outgoing',  label: 'Outgoing',       Icon: ArrowUpFromLine, color: 'from-orange-600 to-orange-700', ring: 'ring-orange-500' },
            { key: 'tokens',    label: 'Token Transfers',Icon: Coins,           color: 'from-purple-600 to-purple-700', ring: 'ring-purple-500' },
            { key: 'dex',       label: 'DEX / Swaps',    Icon: RefreshCw,       color: 'from-cyan-600 to-cyan-700',     ring: 'ring-cyan-500'   },
            { key: 'exchanges', label: 'Exchanges',      Icon: Building2,       color: 'from-red-600 to-red-700',       ring: 'ring-red-500'    },
          ] as { key: string; label: string; Icon: React.ElementType; color: string; ring: string }[]).map(({ key, label, Icon, color, ring }) => (
            <button
              key={key}
              onClick={() => setFilterCategory(key as 'all' | 'incoming' | 'outgoing' | 'tokens' | 'dex' | 'exchanges')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 ${
                filterCategory === key
                  ? `bg-gradient-to-r ${color} text-white shadow-lg ring-1 ${ring} ring-offset-1 ring-offset-gray-800`
                  : 'bg-gray-700/60 text-gray-300 hover:bg-gray-600/80 hover:text-white'
              }`}
            >
              <Icon className="w-3.5 h-3.5 shrink-0" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Graph canvas ─────────────────────────────────────────── */}
      <div className="relative bg-gray-950 rounded-xl border border-gray-700 overflow-hidden">
        <div ref={containerRef} className="w-full h-[580px]" />

        {nodePopup && (
          <NodePopupCard
            popup={nodePopup}
            containerRef={containerRef}
            onClose={() => setNodePopup(null)}
            onTrace={(addr, chain) => { setNodePopup(null); onTraceWallet?.(addr, chain); }}
            llmResult={llmMap[(nodePopup.data.id ?? '').toLowerCase()]}
          />
        )}

        <div className="absolute bottom-2 right-3 text-[10px] text-gray-600 pointer-events-none select-none flex items-center gap-1.5">
          {llmLoading && (
            <span className="flex items-center gap-1 text-blue-500">
              <Loader2 className="w-3 h-3 animate-spin" /> AI analysing…
            </span>
          )}
          Click node for details · Scroll to zoom · Drag to pan
        </div>
      </div>

      {/* ── Expand status strip ──────────────────────────────────── */}
      {expandStatus && expandStatus !== 'PENDING' && (
        <div className={`rounded-lg px-4 py-2.5 flex items-center gap-3 text-xs ${
          expandStatus === 'SUCCESS'
            ? 'bg-indigo-900/40 border border-indigo-700 text-indigo-300'
            : 'bg-red-900/30 border border-red-700 text-red-300'
        }`}>
          <GitMerge className="w-4 h-4 shrink-0" />
          {expandStatus === 'SUCCESS' && expandResult ? (
            <span>
              Graph expanded — now <strong className="text-white">{expandResult.nodes}</strong> wallets
              (<span className="text-indigo-200">+{expandResult.new_nodes} new</span>),{' '}
              <strong className="text-white">{expandResult.edges}</strong> edges
            </span>
          ) : (
            <span>Expansion failed. You can retry by clicking Expand again.</span>
          )}
          <button onClick={() => setExpandStatus(null)} className="ml-auto text-gray-500 hover:text-white">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* ── Exchange path info ───────────────────────────────────── */}
      {pathInfo && (
        <PathInfoBox
          info={pathInfo}
          pathMode={pathMode}
          onShowFull={() => setPathMode((v) => !v)}
        />
      )}

      {/* ── Manual path finder ───────────────────────────────────── */}
      {graphData && (
        <PathFinder graphData={graphData} seedAddress={seedAddr} cyRef={cyRef} />
      )}
    </div>
  );
}

export default GraphViewer;

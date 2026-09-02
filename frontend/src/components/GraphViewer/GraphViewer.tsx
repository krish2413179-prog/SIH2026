'use client';

/**
 * GraphViewer component — interactive Cytoscape.js transaction graph.
 *
 * Props:
 *   traceId     — UUID of the trace job whose graph to display
 *   onNodeSelect — optional callback fired with the node ID when a node is clicked
 *
 * Features:
 *   - Fetches graph data from GET /traces/{traceId}/graph
 *   - Node colour-coding by entity_type:
 *       VASP    → #3B82F6 (blue)
 *       unknown → #9CA3AF (grey)
 *       flagged → #EF4444 (red)
 *       mixer   → #8B5CF6 (violet)
 *       bridge  → #F59E0B (amber)
 *   - Edge width proportional to log(amount + 1)
 *   - VASP node tooltips showing attribution label
 *   - Click a node to toggle its neighbours (expand / collapse)
 *   - Progressive rendering: when nodes > 500, only the top-100
 *     highest-value paths are rendered initially
 *   - Export as PNG or raw JSON
 *   - Loading / error states
 *
 * Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { Download, Image as ImageIcon, Loader2, AlertCircle } from 'lucide-react';
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

export interface GraphViewerProps {
  traceId: string;
  onNodeSelect?: (nodeId: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  vasp: '#3B82F6',
  unknown: '#9CA3AF',
  flagged: '#EF4444',
  mixer: '#8B5CF6',
  bridge: '#F59E0B',
};

function nodeColor(entityType?: string): string {
  return NODE_COLORS[(entityType ?? 'unknown').toLowerCase()] ?? NODE_COLORS.unknown;
}

function edgeWidth(amount?: number): number {
  return Math.max(1, Math.log((amount ?? 0) + 1));
}

/** Convert NetworkX node_link_data to Cytoscape elements */
function toCytoscapeElements(
  graphData: GraphData,
  maxNodes?: number,
): cytoscape.ElementDefinition[] {
  const rawNodes: NodeData[] = (graphData.nodes ?? []).map((n) => ({
    id: String(n.id),
    entity_type: n.entity_type as string | undefined,
    label: (n.label ?? n.id) as string,
    total_inflow: n.total_inflow as number | undefined,
    total_outflow: n.total_outflow as number | undefined,
    first_seen: n.first_seen as string | undefined,
    last_seen: n.last_seen as string | undefined,
    in_degree: n.in_degree as number | undefined,
    out_degree: n.out_degree as number | undefined,
    chain: n.chain as string | undefined,
  }));

  const rawEdges: EdgeData[] = (graphData.links ?? []).map((l, i) => ({
    id: `e${i}`,
    source: String(l.source),
    target: String(l.target),
    amount: l.amount as number | undefined,
    tx_hash: l.tx_hash as string | undefined,
    timestamp: l.timestamp as string | undefined,
    is_bridge: l.is_bridge as boolean | undefined,
  }));

  // Progressive rendering: limit to top-N highest-value nodes
  let nodesToRender = rawNodes;
  if (maxNodes && rawNodes.length > maxNodes) {
    const sorted = [...rawNodes].sort(
      (a, b) => ((b.total_inflow ?? 0) + (b.total_outflow ?? 0)) -
                ((a.total_inflow ?? 0) + (a.total_outflow ?? 0)),
    );
    nodesToRender = sorted.slice(0, maxNodes);
  }

  const nodeIds = new Set(nodesToRender.map((n) => n.id));

  const nodeElements: cytoscape.ElementDefinition[] = nodesToRender.map((n) => ({
    group: 'nodes' as const,
    data: {
      id: n.id,
      label: n.label ?? n.id,
      entity_type: n.entity_type ?? 'unknown',
      color: nodeColor(n.entity_type),
      total_inflow: n.total_inflow ?? 0,
      total_outflow: n.total_outflow ?? 0,
      first_seen: n.first_seen,
      last_seen: n.last_seen,
      in_degree: n.in_degree ?? 0,
      out_degree: n.out_degree ?? 0,
      chain: n.chain,
    },
  }));

  const edgeElements: cytoscape.ElementDefinition[] = rawEdges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => ({
      group: 'edges' as const,
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        amount: e.amount ?? 0,
        width: edgeWidth(e.amount),
        tx_hash: e.tx_hash,
        timestamp: e.timestamp,
        is_bridge: e.is_bridge,
      },
    }));

  return [...nodeElements, ...edgeElements];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const PROGRESSIVE_THRESHOLD = 500;
const PROGRESSIVE_INITIAL = 100;

export function GraphViewer({ traceId, onNodeSelect }: GraphViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cyRef = useRef<any>(null);

  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nodeCount, setNodeCount] = useState(0);
  const [progressive, setProgressive] = useState(false);
  const [tooltip, setTooltip] = useState<{
    label: string;
    x: number;
    y: number;
  } | null>(null);

  // Collapsed node set — tracks which nodes have been collapsed
  const collapsedRef = useRef<Set<string>>(new Set());

  // -------------------------------------------------------------------------
  // Fetch graph data
  // -------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .get<GraphData>(`/traces/${traceId}/graph`)
      .then((res) => {
        if (!cancelled) {
          setGraphData(res.data);
          const n = (res.data.nodes ?? []).length;
          setNodeCount(n);
          setProgressive(n > PROGRESSIVE_THRESHOLD);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          const status = err?.response?.status;
          if (status === 404) {
            // Graph not built yet — trace is still queued or running
            setError('__pending__');
          } else {
            setError(
              err?.response?.data?.detail ??
                err?.message ??
                'Failed to load graph data.',
            );
          }
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [traceId]);

  // -------------------------------------------------------------------------
  // Initialise / re-render Cytoscape when data arrives
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!graphData || !containerRef.current) return;

    let cy: cytoscape.Core;

    // Dynamic import to avoid SSR issues
    import('cytoscape').then((cytoscapeModule) => {
      const cytoscape = cytoscapeModule.default;

      // Destroy any existing instance
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }

      const maxNodes = progressive ? PROGRESSIVE_INITIAL : undefined;
      const elements = toCytoscapeElements(graphData, maxNodes);

      cy = cytoscape({
        container: containerRef.current!,
        elements,
        style: [
          {
            selector: 'node',
            style: {
              'background-color': 'data(color)',
              label: 'data(label)',
              color: '#f9fafb',
              'font-size': '9px',
              'text-valign': 'bottom',
              'text-halign': 'center',
              'text-margin-y': 4,
              'text-wrap': 'ellipsis',
              'text-max-width': '80px',
              width: 28,
              height: 28,
              'border-width': 1.5,
              'border-color': '#374151',
            },
          },
          {
            selector: 'node[entity_type = "vasp"]',
            style: {
              'border-color': '#93C5FD',
              'border-width': 2.5,
              width: 36,
              height: 36,
            },
          },
          {
            selector: 'node[entity_type = "flagged"]',
            style: {
              'border-color': '#FCA5A5',
              'border-width': 3,
            },
          },
          {
            selector: 'node:selected',
            style: {
              'border-color': '#FBBF24',
              'border-width': 3,
              'background-color': '#FBBF24',
              color: '#111827',
            },
          },
          {
            selector: 'edge',
            style: {
              width: 'data(width)',
              'line-color': '#4B5563',
              'target-arrow-color': '#4B5563',
              'target-arrow-shape': 'triangle',
              'curve-style': 'bezier',
              opacity: 0.7,
            },
          },
          {
            selector: 'edge[is_bridge = 1]',
            style: {
              'line-color': '#F59E0B',
              'target-arrow-color': '#F59E0B',
              'line-style': 'dashed',
            },
          },
          {
            selector: '.hidden',
            style: { display: 'none' },
          },
        ],
        layout: {
          name: 'cose',
          animate: elements.length < 300,
          padding: 30,
          nodeRepulsion: () => 8000,
          idealEdgeLength: () => 80,
          edgeElasticity: () => 0.45,
          numIter: 1000,
          coolingFactor: 0.99,
          gravity: 0.25,
        },
        wheelSensitivity: 0.3,
        minZoom: 0.05,
        maxZoom: 5,
      });

      cyRef.current = cy;

      // ------------------------------------------------------------------
      // Node click: expand / collapse neighbours
      // ------------------------------------------------------------------
      cy.on('tap', 'node', (evt) => {
        const node = evt.target;
        const nodeId: string = node.id();

        onNodeSelect?.(nodeId);

        const neighbours = node.neighbourhood();
        const isCollapsed = collapsedRef.current.has(nodeId);

        if (isCollapsed) {
          neighbours.removeClass('hidden');
          collapsedRef.current.delete(nodeId);
        } else {
          neighbours.nodes().not(node).addClass('hidden');
          collapsedRef.current.add(nodeId);
        }
      });

      // ------------------------------------------------------------------
      // VASP node tooltip on mouseover
      // ------------------------------------------------------------------
      cy.on('mouseover', 'node', (evt) => {
        const node = evt.target;
        const entityType: string = node.data('entity_type') ?? 'unknown';
        if (entityType.toLowerCase() === 'vasp') {
          const label: string = node.data('label') ?? node.id();
          const pos = node.renderedPosition();
          const containerRect = containerRef.current?.getBoundingClientRect();
          if (containerRect) {
            setTooltip({
              label: `VASP: ${label}`,
              x: pos.x,
              y: pos.y - 20,
            });
          }
        }
      });

      cy.on('mouseout', 'node', () => setTooltip(null));
    });

    return () => {
      if (cyRef.current) {
        cyRef.current.destroy();
        cyRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData, progressive]);

  // -------------------------------------------------------------------------
  // Export handlers
  // -------------------------------------------------------------------------
  const handleExportPng = useCallback(() => {
    if (!cyRef.current) return;
    const png: string = cyRef.current.png({ full: true, scale: 2 });
    const a = document.createElement('a');
    a.href = png;
    a.download = `trace-${traceId}-graph.png`;
    a.click();
  }, [traceId]);

  const handleExportJson = useCallback(() => {
    if (!graphData) return;
    const blob = new Blob([JSON.stringify(graphData, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trace-${traceId}-graph.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [graphData, traceId]);

  const handleShowAll = useCallback(() => {
    setProgressive(false);
  }, []);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 bg-gray-900 rounded-xl border border-gray-700">
        <Loader2 className="w-8 h-8 text-blue-400 animate-spin mr-3" />
        <span className="text-gray-400 text-sm">Loading transaction graph…</span>
      </div>
    );
  }

  if (error) {
    if (error === '__pending__') {
      return (
        <div className="flex flex-col items-center justify-center h-48 bg-gray-900 rounded-xl border border-gray-700 gap-3">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
          <p className="text-gray-400 text-sm font-medium">Trace pending</p>
          <p className="text-gray-500 text-xs max-w-xs text-center">
            The blockchain trace is queued and hasn&apos;t been processed yet.
            The graph will appear here once the Celery worker completes the trace.
          </p>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center justify-center h-96 bg-gray-900 rounded-xl border border-red-800 gap-3">
        <AlertCircle className="w-8 h-8 text-red-400" />
        <p className="text-red-400 text-sm font-medium">Failed to load graph</p>
        <p className="text-gray-500 text-xs max-w-xs text-center">{error}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-800 rounded-lg border border-gray-700">
        {/* Legend */}
        <div className="flex items-center gap-3 flex-wrap">
          {Object.entries(NODE_COLORS).map(([type, color]) => (
            <span key={type} className="flex items-center gap-1 text-xs text-gray-300">
              <span
                className="inline-block w-3 h-3 rounded-full"
                style={{ backgroundColor: color }}
              />
              {type.charAt(0).toUpperCase() + type.slice(1)}
            </span>
          ))}
        </div>

        <div className="flex items-center gap-2">
          {progressive && (
            <span className="text-xs text-amber-400 mr-2">
              Showing top {PROGRESSIVE_INITIAL} of {nodeCount} nodes
              <button
                onClick={handleShowAll}
                className="ml-2 underline hover:text-amber-300 transition-colors"
              >
                Show all
              </button>
            </span>
          )}
          <button
            onClick={handleExportPng}
            title="Export as PNG"
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-md transition-colors"
          >
            <ImageIcon className="w-3.5 h-3.5" />
            PNG
          </button>
          <button
            onClick={handleExportJson}
            title="Export graph JSON"
            className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-md transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            JSON
          </button>
        </div>
      </div>

      {/* Graph container */}
      <div className="relative bg-gray-900 rounded-xl border border-gray-700 overflow-hidden">
        <div ref={containerRef} className="w-full h-[600px]" />

        {/* VASP tooltip */}
        {tooltip && (
          <div
            className="pointer-events-none absolute bg-gray-800 text-blue-300 text-xs rounded px-2 py-1 border border-blue-700 shadow-lg z-10 whitespace-nowrap"
            style={{ left: tooltip.x, top: tooltip.y, transform: 'translateX(-50%)' }}
          >
            {tooltip.label}
          </div>
        )}
      </div>
    </div>
  );
}

export default GraphViewer;

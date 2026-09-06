"use client"

import * as React from "react"
import {
  IconArrowLeft,
  IconLoader2,
  IconMaximize,
  IconMinimize,
  IconNetwork,
  IconRefresh,
} from "@tabler/icons-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { useMLReport } from "@/lib/hooks"

// ── vis-network loaded dynamically (no SSR) ──────────────────────────────────
type VisNetwork = any
type VisDataSet = any

async function loadVis() {
  const vis = await import("vis-network/standalone")
  return vis as any
}

// ── Layout modes ──────────────────────────────────────────────────────────────
type LayoutMode = "physics" | "hierarchical" | "force"

// ── Wallet-address colour palette (deterministic from address string) ─────────
// Maps an address to one of several muted accent colours used as the avatar fill.
const PALETTE = [
  { bg: "#6366f1", ring: "#818cf8", text: "#fff" }, // indigo
  { bg: "#0ea5e9", ring: "#38bdf8", text: "#fff" }, // sky
  { bg: "#10b981", ring: "#34d399", text: "#fff" }, // emerald
  { bg: "#f59e0b", ring: "#fbbf24", text: "#1e1e1e" }, // amber
  { bg: "#ec4899", ring: "#f472b6", text: "#fff" }, // pink
  { bg: "#8b5cf6", ring: "#a78bfa", text: "#fff" }, // violet
  { bg: "#14b8a6", ring: "#2dd4bf", text: "#fff" }, // teal
  { bg: "#f97316", ring: "#fb923c", text: "#1e1e1e" }, // orange
]

// Override colours for special entity types
const ENTITY_COLORS: Record<string, { bg: string; ring: string; text: string }> = {
  exchange: { bg: "#16a34a", ring: "#22c55e", text: "#fff" },
  mixer:    { bg: "#dc2626", ring: "#ef4444", text: "#fff" },
  bridge:   { bg: "#d97706", ring: "#f59e0b", text: "#1e1e1e" },
  darknet:  { bg: "#7f1d1d", ring: "#dc2626", text: "#fff" },
}

function addrColor(address: string, entityType: string, isSeed: boolean) {
  if (isSeed) return { bg: "#4f46e5", ring: "#818cf8", text: "#fff" }
  if (ENTITY_COLORS[entityType]) return ENTITY_COLORS[entityType]
  // deterministic palette bucket from address chars
  let hash = 0
  for (let i = 0; i < address.length; i++) hash = (hash * 31 + address.charCodeAt(i)) >>> 0
  return PALETTE[hash % PALETTE.length]
}

// Returns a 4-char monogram from a wallet address:
//   "0x1A2b3C…" → "1A2b"  (skip leading "0x" / "1" for BTC)
function addrMonogram(address: string): string {
  const clean = address.replace(/^0x/i, "").replace(/^(bc1|1|3)/i, "")
  return (clean.slice(0, 4) || address.slice(0, 4)).toUpperCase()
}

function nodeSize(inDegree: number, outDegree: number, isSeed: boolean): number {
  if (isSeed) return 32
  const deg = inDegree + outDegree
  return Math.max(14, Math.min(26, 12 + deg * 0.55))
}

// ── Custom canvas renderer — wallet-address "dp" avatar ──────────────────────
// vis-network calls ctxRenderer for shape:"custom" nodes.
// `ctx` is the canvas 2D context; x,y is the node centre; selected/hover are booleans.
function makeCtxRenderer(
  address: string,
  entityType: string,
  isSeed: boolean,
  radius: number,
) {
  return {
    drawNode(ctx: CanvasRenderingContext2D, x: number, y: number, selected: boolean, hover: boolean) {
      const { bg, ring, text } = addrColor(address, entityType, isSeed)
      const r = radius
      const ringW = isSeed ? 3 : selected ? 2.5 : hover ? 2 : 1.5

      // ── Outer glow for seed ───────────────────────────────────────────────
      if (isSeed) {
        ctx.save()
        ctx.shadowColor = ring
        ctx.shadowBlur = 12
        ctx.beginPath()
        ctx.arc(x, y, r + ringW, 0, Math.PI * 2)
        ctx.fillStyle = "transparent"
        ctx.fill()
        ctx.restore()
      }

      // ── Identicon-style background: 4 small squares derived from address ─
      // Clips to the circle first, then draws a subtle pattern
      ctx.save()
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.clip()

      // Base fill
      ctx.fillStyle = bg
      ctx.fillRect(x - r, y - r, r * 2, r * 2)

      // Subtle identicon squares (3×3 grid, symmetric, seeded by address chars)
      const cell = (r * 2) / 5
      const ox = x - r + cell
      const oy = y - r + cell
      for (let row = 0; row < 3; row++) {
        for (let col = 0; col < 3; col++) {
          const idx = row * 3 + col
          const charCode = address.charCodeAt(2 + idx) || 0
          if (charCode % 2 === 0) {
            ctx.fillStyle = "rgba(255,255,255,0.10)"
            ctx.fillRect(ox + col * cell, oy + row * cell, cell - 1, cell - 1)
            // Mirror left column to make it symmetric
            if (col < 2) {
              ctx.fillRect(ox + (4 - col) * cell, oy + row * cell, cell - 1, cell - 1)
            }
          }
        }
      }
      ctx.restore()

      // ── Ring border ───────────────────────────────────────────────────────
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.strokeStyle = selected ? "#c7d2fe" : hover ? "#a5b4fc" : ring
      ctx.lineWidth = ringW
      ctx.stroke()

      // ── Monogram text ─────────────────────────────────────────────────────
      const mono = addrMonogram(address)
      const fontSize = Math.max(7, Math.round(r * 0.52))
      ctx.font = `600 ${fontSize}px "JetBrains Mono", "Fira Code", ui-monospace, monospace`
      ctx.fillStyle = text
      ctx.textAlign = "center"
      ctx.textBaseline = "middle"
      ctx.fillText(mono, x, y)
    },
    // Bounding box must match the drawn circle for hit-testing
    nodeDimensions: { width: radius * 2, height: radius * 2 },
  }
}

// ── vis-network options factories ─────────────────────────────────────────────
function buildOptions(mode: LayoutMode) {
  const baseOptions: any = {
    autoResize: true,
    height: "100%",
    width: "100%",
    interaction: {
      hover: true,
      tooltipDelay: 0,
      hideEdgesOnDrag: false,
      hideNodesOnDrag: false,
      navigationButtons: false,
      keyboard: false,
      zoomView: true,
      dragView: true,
      multiselect: false,
    },
    nodes: {
      shape: "custom",
      // label rendered below the node via vis-network's default label position
      font: {
        color: "#cbd5e1",
        size: 9,
        face: "Inter, ui-sans-serif, sans-serif",
        vadjust: 2,
      },
      borderWidth: 0,    // handled in ctxRenderer
      borderWidthSelected: 0,
      chosen: true,
    },
    edges: {
      arrows: {
        to: { enabled: true, scaleFactor: 0.55, type: "arrow" },
      },
      smooth: {
        enabled: true,
        type: "dynamic",
        roundness: 0.45,
      },
      color: {
        color: "#334155",
        highlight: "#818cf8",
        hover: "#64748b",
        inherit: false,
        opacity: 0.55,
      },
      width: 1.2,
      selectionWidth: 2,
      font: {
        color: "#94a3b8",
        size: 9,
        align: "middle",
        background: "none",
      },
    },
    physics: { enabled: false },
    layout: { improvedLayout: true, hierarchical: { enabled: false } },
  }

  if (mode === "physics") {
    baseOptions.physics = {
      enabled: true,
      solver: "forceAtlas2Based",
      forceAtlas2Based: {
        gravitationalConstant: -50,
        centralGravity: 0.01,
        springLength: 110,
        springConstant: 0.08,
        damping: 0.4,
        avoidOverlap: 0.6,
      },
      stabilization: { enabled: true, iterations: 1000, updateInterval: 25, fit: true },
      minVelocity: 0.75,
    }
    baseOptions.layout.hierarchical = { enabled: false }
  } else if (mode === "hierarchical") {
    baseOptions.physics = { enabled: false }
    baseOptions.layout = {
      hierarchical: {
        enabled: true,
        direction: "LR",
        sortMethod: "directed",
        nodeSpacing: 130,
        levelSeparation: 220,
        treeSpacing: 220,
        blockShifting: true,
        edgeMinimization: true,
        parentCentralization: true,
      },
    }
  } else {
    // Barnes-Hut force
    baseOptions.physics = {
      enabled: true,
      solver: "barnesHut",
      barnesHut: {
        gravitationalConstant: -8000,
        centralGravity: 0.3,
        springLength: 95,
        springConstant: 0.04,
        damping: 0.09,
        avoidOverlap: 0,
      },
      stabilization: { enabled: true, iterations: 800, updateInterval: 25, fit: true },
      minVelocity: 0.75,
    }
    baseOptions.layout = { hierarchical: { enabled: false } }
  }

  return baseOptions
}

// ── Graph filter: keep only important nodes + shortest paths to them ─────────
//
// "Important" = seed | exchange | mixer | bridge | darknet | sanctioned |
//               ransomware | flagged | scam
//
// Algorithm:
//   1. Build an adjacency map from the raw edge list.
//   2. BFS from the seed node to find shortest paths to every important node.
//   3. Collect all nodes that appear on any such path.
//   4. For wallets not on any path, emit a single "collapsed" summary node so
//      the stats row stays honest while the canvas stays clean.
//
const IMPORTANT_TYPES = new Set([
  "exchange", "mixer", "bridge", "darknet",
  "sanctioned", "ransomware", "flagged", "scam",
])

function filterGraphForDisplay(
  rawNodes: any[],
  rawEdges: any[],
  seedAddress: string,
): { nodes: any[]; edges: any[] } {
  if (!rawNodes?.length) return { nodes: rawNodes, edges: rawEdges }

  const nodeMap = new Map<string, any>(rawNodes.map((n) => [n.id, n]))

  // Build forward adjacency list (source → [target, ...])
  const adj = new Map<string, string[]>()
  for (const e of rawEdges) {
    if (!adj.has(e.source)) adj.set(e.source, [])
    adj.get(e.source)!.push(e.target)
  }

  // Important nodes (always kept)
  const importantIds = new Set<string>(
    rawNodes
      .filter((n) => n.is_seed || IMPORTANT_TYPES.has(n.entity_type ?? ""))
      .map((n) => n.id),
  )

  if (importantIds.size <= 1) {
    // Nothing special found — show up to 80 highest-degree nodes so the graph
    // is still meaningful without flooding the canvas.
    const sorted = [...rawNodes].sort(
      (a, b) => (b.in_degree + b.out_degree) - (a.in_degree + a.out_degree),
    )
    const topIds = new Set(sorted.slice(0, 80).map((n) => n.id))
    const filteredEdges = rawEdges.filter(
      (e) => topIds.has(e.source) && topIds.has(e.target),
    )
    return { nodes: sorted.slice(0, 80), edges: filteredEdges }
  }

  // BFS from seed to collect paths to every important node
  // parent[node] = node we came from (for path reconstruction)
  const parent = new Map<string, string | null>([[seedAddress, null]])
  const queue: string[] = [seedAddress]

  while (queue.length) {
    const cur = queue.shift()!
    for (const next of adj.get(cur) ?? []) {
      if (!parent.has(next)) {
        parent.set(next, cur)
        queue.push(next)
      }
    }
  }

  // Reconstruct path from seed → target; return all nodes on the path
  function pathTo(target: string): string[] {
    const path: string[] = []
    let cur: string | null = target
    while (cur !== null) {
      path.push(cur)
      cur = parent.get(cur) ?? null
      if (cur === undefined) break // unreachable from seed
    }
    return path
  }

  // Collect all nodes that appear on any path to an important node
  const keepIds = new Set<string>()
  for (const id of importantIds) {
    if (parent.has(id)) {
      pathTo(id).forEach((n) => keepIds.add(n))
    } else {
      // Important node not reachable from seed — still show it
      keepIds.add(id)
    }
  }

  const hiddenCount = rawNodes.length - keepIds.size

  const filteredNodes = rawNodes.filter((n) => keepIds.has(n.id))
  const filteredEdges = rawEdges.filter(
    (e) => keepIds.has(e.source) && keepIds.has(e.target),
  )

  // Add a summary "collapsed wallets" node if we pruned anything
  if (hiddenCount > 0) {
    filteredNodes.push({
      id: "__collapsed__",
      entity_type: "collapsed",
      is_seed: false,
      in_degree: 0,
      out_degree: 0,
      total_inflow: 0,
      total_outflow: 0,
      _collapsed_count: hiddenCount,
    })
  }

  return { nodes: filteredNodes, edges: filteredEdges }
}

// ── Main component ────────────────────────────────────────────────────────────
interface FundFlowPageProps {
  traceId: string
  walletAddress: string
  chain: string
  onBack: () => void
}

export function FundFlowPage({ traceId, walletAddress, chain, onBack }: FundFlowPageProps) {
  const { data: report, isLoading } = useMLReport(traceId, true)

  const containerRef = React.useRef<HTMLDivElement>(null)
  const networkRef   = React.useRef<VisNetwork>(null)
  const nodesRef     = React.useRef<VisDataSet>(null)
  const edgesRef     = React.useRef<VisDataSet>(null)
  const tooltipRef   = React.useRef<HTMLDivElement>(null)

  const [fullscreen,    setFullscreen]    = React.useState(false)
  const [layoutRunning, setLayoutRunning] = React.useState(false)
  const [ready,         setReady]         = React.useState(false)
  const [layoutMode,    setLayoutMode]    = React.useState<LayoutMode>("physics")
  const [showAll,       setShowAll]       = React.useState(false)

  // ── Build / rebuild network ────────────────────────────────────────────────
  React.useEffect(() => {
    if (!report || !containerRef.current) return
    let cancelled = false

    async function init() {
      const vis = await loadVis()
      if (cancelled || !containerRef.current) return

      const { nodes, edges } = report!.graph
      if (!nodes?.length) return

      if (networkRef.current) {
        networkRef.current.destroy()
        networkRef.current = null
      }

      // ── Filter: only show important nodes + paths to them ────────────────
      const { nodes: filteredNodes, edges: filteredEdges } = showAll
        ? { nodes, edges }
        : filterGraphForDisplay(nodes, edges, walletAddress)

      // ── Nodes ────────────────────────────────────────────────────────────
      const visNodes = filteredNodes.map((n: any) => {
        // Special collapsed-wallets summary node
        if (n.id === "__collapsed__") {
          return {
            id: "__collapsed__",
            label: `+${n._collapsed_count} wallets\ncollapsed`,
            shape: "box",
            color: { background: "#1e293b", border: "#334155", highlight: { background: "#1e293b", border: "#475569" } },
            font: { color: "#64748b", size: 10, multi: true },
            size: 18,
            _meta: {
              address: `${n._collapsed_count} intermediate wallets hidden`,
              entity_type: "collapsed",
              is_seed: false,
              in_degree: 0,
              out_degree: 0,
              total_inflow: null,
              total_outflow: null,
            },
          }
        }
        const radius = nodeSize(n.in_degree, n.out_degree, n.is_seed)
        const renderer = makeCtxRenderer(n.id, n.entity_type ?? "wallet", n.is_seed, radius)

        // Short label shown below the avatar circle
        const isImportant = IMPORTANT_TYPES.has(n.entity_type ?? "")
        const shortLabel = n.is_seed
          ? n.id.slice(0, 6) + "…" + n.id.slice(-4)
          : isImportant
          ? (n.vasp_name ?? n.entity_type ?? n.id.slice(0, 5) + "…")
          : ""

        return {
          id: n.id,
          // vis-network uses `ctxRenderer` for shape:"custom"
          ctxRenderer: ({
            ctx,
            x,
            y,
            selected,
            hover,
          }: {
            ctx: CanvasRenderingContext2D
            x: number
            y: number
            selected: boolean
            hover: boolean
          }) => {
            renderer.drawNode(ctx, x, y, selected, hover)
            return renderer.nodeDimensions
          },
          label: (n.is_seed || isImportant) ? shortLabel : "",
          size: radius,
          // Store meta for tooltip
          _meta: {
            address: n.id,
            entity_type: n.entity_type,
            is_seed: n.is_seed,
            in_degree: n.in_degree,
            out_degree: n.out_degree,
            total_inflow: n.total_inflow,
            total_outflow: n.total_outflow,
          },
        }
      })

      // ── Edges ────────────────────────────────────────────────────────────
      const visEdges = filteredEdges.map((e: any, i: number) => ({
        id: `e${i}`,
        from: e.source,
        to: e.target,
        color: e.is_bridge
          ? { color: "#ef4444", highlight: "#f87171", hover: "#f87171", opacity: 0.8 }
          : undefined,
        dashes: e.is_bridge ? [6, 4] : false,
        width: e.is_bridge ? 2 : 1.2,
        title: e.amount != null
          ? `${Number(e.amount).toLocaleString(undefined, { maximumFractionDigits: 6 })} units`
          : undefined,
      }))

      const DataSet = vis.DataSet ?? vis.default?.DataSet
      const Network  = vis.Network  ?? vis.default?.Network

      nodesRef.current = new DataSet(visNodes)
      edgesRef.current = new DataSet(visEdges)

      const network: VisNetwork = new Network(
        containerRef.current,
        { nodes: nodesRef.current, edges: edgesRef.current },
        buildOptions(layoutMode),
      )
      networkRef.current = network
      setLayoutRunning(true)

      // ── Stabilisation events ──────────────────────────────────────────────
      network.on("stabilizationIterationsDone", () => {
        if (layoutMode !== "hierarchical") {
          network.setOptions({ physics: { enabled: false } })
        }
        network.fit({ animation: { duration: 600, easingFunction: "easeInOutQuad" } })
        setLayoutRunning(false)
        setReady(true)
      })

      if (layoutMode === "hierarchical") {
        network.once("afterDrawing", () => {
          setLayoutRunning(false)
          setReady(true)
        })
      }

      // ── Hover tooltip ────────────────────────────────────────────────────
      network.on("hoverNode", (params: any) => {
        const node = nodesRef.current?.get(params.node)
        if (!node || !tooltipRef.current || !containerRef.current) return

        const meta = node._meta
        const { bg, ring } = addrColor(meta.address, meta.entity_type ?? "wallet", meta.is_seed)

        const lines = [
          `<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
             <span style="display:inline-block;width:10px;height:10px;border-radius:50%;
                          background:${bg};border:2px solid ${ring};flex-shrink:0;"></span>
             <span style="font-weight:600;text-transform:capitalize;">
               ${meta.entity_type ?? "wallet"}${meta.is_seed ? " (seed)" : ""}
             </span>
           </div>`,
          `<div style="font-family:monospace;font-size:11px;word-break:break-all;
                       color:#94a3b8;margin-bottom:4px;">${meta.address}</div>`,
          `<hr style="border-color:#334155;margin:4px 0;"/>`,
          `In-degree: <strong>${meta.in_degree ?? 0}</strong> &nbsp;·&nbsp; Out-degree: <strong>${meta.out_degree ?? 0}</strong>`,
          meta.total_inflow  != null
            ? `Inflow: <strong>${Number(meta.total_inflow).toLocaleString(undefined, { maximumFractionDigits: 4 })}</strong>`
            : null,
          meta.total_outflow != null
            ? `Outflow: <strong>${Number(meta.total_outflow).toLocaleString(undefined, { maximumFractionDigits: 4 })}</strong>`
            : null,
        ].filter(Boolean).join("<br/>")

        const pos = params.pointer.DOM
        const rect = containerRef.current.getBoundingClientRect()
        const tip  = tooltipRef.current

        tip.innerHTML = lines
        tip.style.display = "block"

        let left = pos.x + 16
        let top  = pos.y - 8
        if (left + 240 > rect.width)  left = pos.x - 240 - 16
        if (top  + 160 > rect.height) top  = pos.y - 160 - 8

        tip.style.left = `${left}px`
        tip.style.top  = `${top}px`
      })

      network.on("blurNode",  () => { if (tooltipRef.current) tooltipRef.current.style.display = "none" })
      network.on("dragStart", () => { if (tooltipRef.current) tooltipRef.current.style.display = "none" })
    }

    init()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [report, layoutMode, showAll])

  // Refit on fullscreen toggle
  React.useEffect(() => {
    if (networkRef.current) {
      setTimeout(() => networkRef.current?.fit({
        animation: { duration: 400, easingFunction: "easeInOutQuad" },
      }), 150)
    }
  }, [fullscreen])

  // ── Re-layout ─────────────────────────────────────────────────────────────
  const handleReLayout = () => {
    const net = networkRef.current
    if (!net || layoutRunning) return

    if (layoutMode === "hierarchical") {
      net.fit({ animation: { duration: 600, easingFunction: "easeInOutQuad" } })
      return
    }

    setLayoutRunning(true)
    setReady(false)
    net.setOptions({ physics: { enabled: true } })
    net.once("stabilizationIterationsDone", () => {
      net.setOptions({ physics: { enabled: false } })
      net.fit({ animation: { duration: 600, easingFunction: "easeInOutQuad" } })
      setLayoutRunning(false)
      setReady(true)
    })
    net.stabilize(600)
  }

  const handleLayoutSwitch = (mode: LayoutMode) => {
    if (mode === layoutMode) return
    setLayoutMode(mode)
    setReady(false)
  }

  const handleFit = () =>
    networkRef.current?.fit({ animation: { duration: 500, easingFunction: "easeInOutQuad" } })

  // ── Stats ─────────────────────────────────────────────────────────────────
  const totalNodes    = report?.graph.node_count  ?? 0
  const totalEdges    = report?.graph.edge_count  ?? 0
  const bridgeCount   = report?.graph.edges?.filter((e: any) => e.is_bridge).length ?? 0
  const exchangeCount = report?.graph.nodes?.filter((n: any) => n.entity_type === "exchange").length ?? 0

  const { nodes: displayNodes } = !report?.graph.nodes ? { nodes: [] } : showAll
    ? { nodes: report.graph.nodes }
    : filterGraphForDisplay(report.graph.nodes, report.graph.edges ?? [], walletAddress)
  const visibleCount = displayNodes.filter((n: any) => n.id !== "__collapsed__").length

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className={
      fullscreen
        ? "fixed inset-0 z-50 bg-background flex flex-col p-4 gap-4"
        : "px-4 lg:px-6 flex flex-col gap-4"
    }>
      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2">
            <IconArrowLeft className="size-4" /> Back to report
          </Button>
          <Separator orientation="vertical" className="h-4" />
          <IconNetwork className="size-4 text-primary" />
          <span className="text-sm font-medium">Fund Movement Graph</span>
          <Badge variant="outline" className="text-xs">{chain}</Badge>
        </div>
        <div className="flex items-center gap-2">
          {/* Layout switcher */}
          <div className="flex items-center gap-1 rounded-md border bg-background p-1">
            {(["physics", "hierarchical", "force"] as LayoutMode[]).map((m) => (
              <button
                key={m}
                onClick={() => handleLayoutSwitch(m)}
                className={`px-2.5 py-0.5 text-xs rounded capitalize transition-colors ${
                  layoutMode === m
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          <Button
            variant={showAll ? "default" : "outline"}
            size="sm"
            onClick={() => { setShowAll(s => !s); setReady(false) }}
          >
            {showAll ? "Smart filter" : "Show all"}
          </Button>

          <Button
            variant="outline" size="sm"
            onClick={handleReLayout}
            disabled={layoutRunning || isLoading || layoutMode === "hierarchical"}
          >
            {layoutRunning
              ? <><IconLoader2 className="size-4 animate-spin" /> Simulating…</>
              : <><IconRefresh className="size-4" /> Re-layout</>
            }
          </Button>

          <Button variant="outline" size="sm" onClick={handleFit} disabled={!ready}>
            Fit
          </Button>

          <Button variant="outline" size="icon" className="size-8"
            onClick={() => setFullscreen(f => !f)}>
            {fullscreen ? <IconMinimize className="size-4" /> : <IconMaximize className="size-4" />}
          </Button>
        </div>
      </div>

      {/* ── Stats row ─────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          {
            label: "Wallets",
            value: showAll
              ? totalNodes.toLocaleString()
              : `${visibleCount} / ${totalNodes.toLocaleString()}`,
            color: "",
            hint: showAll ? "" : "visible / total",
          },
          { label: "Transfers",   value: totalEdges.toLocaleString(),  color: "", hint: "" },
          { label: "Bridge Hops", value: bridgeCount, color: bridgeCount  > 0 ? "text-red-500"   : "", hint: "" },
          { label: "Exchanges",   value: exchangeCount, color: exchangeCount > 0 ? "text-green-500" : "", hint: "" },
        ].map(({ label, value, color, hint }) => (
          <Card key={label}>
            <CardContent className="py-3 text-center">
              <p className="text-xs text-muted-foreground mb-1">{label}</p>
              <p className={`text-xl font-bold ${color}`}>{value}</p>
              {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── Graph canvas ──────────────────────────────────────────────────── */}
      <Card className={`overflow-hidden ${fullscreen ? "flex-1" : ""}`}>
        <CardHeader className="py-3 px-4 border-b flex-row items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <IconNetwork className="size-4" />
            Transaction graph
            {layoutRunning && (
              <span className="flex items-center gap-1 text-xs font-normal text-muted-foreground ml-2">
                <IconLoader2 className="size-3 animate-spin" /> Simulating layout…
              </span>
            )}
          </CardTitle>

          {/* Legend */}
          <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
            {[
              { bg: "#4f46e5", ring: "#818cf8", label: "Seed"     },
              { bg: "#16a34a", ring: "#22c55e", label: "Exchange" },
              { bg: "#dc2626", ring: "#ef4444", label: "Mixer"    },
              { bg: "#d97706", ring: "#f59e0b", label: "Bridge"   },
              { bg: "#475569", ring: "#64748b", label: "Wallet"   },
            ].map(({ bg, ring, label }) => (
              <span key={label} className="flex items-center gap-1.5">
                <span
                  className="inline-block size-4 rounded-full flex-shrink-0"
                  style={{
                    background: bg,
                    border: `2px solid ${ring}`,
                    fontSize: 7,
                    lineHeight: "12px",
                    textAlign: "center",
                    color: "#fff",
                    fontFamily: "monospace",
                    fontWeight: 700,
                  }}
                />
                {label}
              </span>
            ))}
            <span className="flex items-center gap-1.5">
              <span className="inline-block w-5 h-px border-t-2 border-dashed border-red-400" />
              Bridge hop
            </span>
          </div>
        </CardHeader>

        <CardContent
          className="p-0 relative"
          style={{ height: fullscreen ? "calc(100% - 52px)" : 560 }}
        >
          {/* Loading overlay */}
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center gap-2 text-muted-foreground text-sm z-10 bg-background/80">
              <IconLoader2 className="size-5 animate-spin" /> Loading graph data…
            </div>
          )}
          {!isLoading && totalNodes === 0 && (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-sm">
              No graph data available for this trace.
            </div>
          )}

          {/* vis-network canvas */}
          <div ref={containerRef} className="w-full h-full" style={{ background: "transparent" }} />

          {/* Hover tooltip */}
          <div
            ref={tooltipRef}
            style={{
              display: "none",
              position: "absolute",
              pointerEvents: "none",
              zIndex: 20,
              background: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              padding: "10px 12px",
              fontSize: 12,
              lineHeight: "1.65",
              color: "hsl(var(--foreground))",
              maxWidth: 260,
              boxShadow: "0 4px 20px rgba(0,0,0,0.45)",
              whiteSpace: "normal",
              wordBreak: "break-all",
            }}
          />
        </CardContent>
      </Card>

      {ready && (
        <p className="text-xs text-center text-muted-foreground">
          Scroll to zoom · Drag canvas to pan · Drag node to reposition · Hover for address details
        </p>
      )}
    </div>
  )
}

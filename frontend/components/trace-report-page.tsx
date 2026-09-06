"use client"

import * as React from "react"
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconArrowRight,
  IconBrain,
  IconBuildingBank,
  IconCircleCheck,
  IconCopy,
  IconLoader2,
  IconShield,
  IconShieldExclamation,
  IconWaveSine,
} from "@tabler/icons-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { useMLReport, useNearestVasps } from "@/lib/hooks"
import type { MLReportFactor } from "@/lib/api"

// ── Speedometer gauge (pure SVG, no extra deps) ───────────────────────────────
function Speedometer({ score }: { score: number }) {
  const clamp = Math.max(0, Math.min(100, score))

  // Arc: 200° total, starting at 190° (bottom-left), ending at 350° (bottom-right)
  const START_DEG = 190
  const TOTAL_DEG = 160
  const needle_deg = START_DEG + (clamp / 100) * TOTAL_DEG

  const toRad = (d: number) => (d * Math.PI) / 180
  const cx = 120
  const cy = 110
  const r = 85

  // Background arc path
  const arcPath = (from: number, to: number, radius: number) => {
    const s = { x: cx + radius * Math.cos(toRad(from)), y: cy + radius * Math.sin(toRad(from)) }
    const e = { x: cx + radius * Math.cos(toRad(to)), y: cy + radius * Math.sin(toRad(to)) }
    const large = to - from > 180 ? 1 : 0
    return `M ${s.x} ${s.y} A ${radius} ${radius} 0 ${large} 1 ${e.x} ${e.y}`
  }

  // Needle tip
  const nx = cx + (r - 10) * Math.cos(toRad(needle_deg))
  const ny = cy + (r - 10) * Math.sin(toRad(needle_deg))

  // Color zones
  const color =
    clamp >= 70 ? "#ef4444" : clamp >= 40 ? "#f59e0b" : "#22c55e"

  const band = clamp >= 70 ? "HIGH RISK" : clamp >= 40 ? "MEDIUM RISK" : "LOW RISK"

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={240} height={160} viewBox="0 0 240 160">
        {/* Background track */}
        <path
          d={arcPath(START_DEG, START_DEG + TOTAL_DEG, r)}
          fill="none"
          stroke="currentColor"
          strokeWidth={14}
          strokeLinecap="round"
          className="text-muted"
        />
        {/* Filled score arc */}
        <path
          d={arcPath(START_DEG, START_DEG + (clamp / 100) * TOTAL_DEG, r)}
          fill="none"
          stroke={color}
          strokeWidth={14}
          strokeLinecap="round"
        />
        {/* Zone labels */}
        <text x={28} y={130} fontSize={9} fill="#22c55e" fontWeight={600}>LOW</text>
        <text x={100} y={30} fontSize={9} fill="#f59e0b" fontWeight={600} textAnchor="middle">MED</text>
        <text x={190} y={130} fontSize={9} fill="#ef4444" fontWeight={600}>HIGH</text>
        {/* Needle */}
        <line
          x1={cx} y1={cy}
          x2={nx} y2={ny}
          stroke={color}
          strokeWidth={3}
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy} r={6} fill={color} />
        {/* Score text */}
        <text x={cx} y={cy + 28} fontSize={26} fontWeight={700} textAnchor="middle" fill={color}>
          {clamp}
        </text>
        <text x={cx} y={cy + 42} fontSize={9} textAnchor="middle" fill="currentColor" className="text-muted-foreground">
          / 100
        </text>
      </svg>
      <Badge
        className="text-sm px-4 py-1 font-bold tracking-wider"
        style={{ backgroundColor: color, color: "#fff", border: "none" }}
      >
        {band}
      </Badge>
    </div>
  )
}

// ── Severity dot ─────────────────────────────────────────────────────────────
function SeverityDot({ severity }: { severity: string }) {
  const color =
    severity === "high" ? "bg-red-500" :
    severity === "medium" ? "bg-amber-500" : "bg-blue-400"
  return <span className={`inline-block size-2 rounded-full shrink-0 mt-1.5 ${color}`} />
}

// ── Entity-type badge colour map ──────────────────────────────────────────────
function entityTypeBadge(entityType: string) {
  const t = entityType.toLowerCase()
  if (t === "cex")     return { label: "CEX",     cls: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300" }
  if (t === "mixer")   return { label: "Mixer",   cls: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300" }
  if (t === "bridge")  return { label: "Bridge",  cls: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300" }
  if (t === "dex")     return { label: "DEX",     cls: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300" }
  if (t === "exchange") return { label: "Exchange", cls: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300" }
  return { label: entityType, cls: "bg-muted text-muted-foreground" }
}

// ── Nearest VASP card ─────────────────────────────────────────────────────────
interface NearestVaspCardProps {
  traceId: string
}

function NearestVaspCard({ traceId }: NearestVaspCardProps) {
  const { data, isLoading } = useNearestVasps(traceId)
  const [copied, setCopied] = React.useState(false)

  const copyAddress = (addr: string) => {
    navigator.clipboard.writeText(addr).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <Card className="border-2 border-primary/20">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <IconBuildingBank className="size-5 text-primary" />
          Nearest Attributed VASP
        </CardTitle>
        <CardDescription>
          Closest known exchange or service in the transaction graph
        </CardDescription>
      </CardHeader>

      <CardContent>
        {/* Loading state */}
        {isLoading && (
          <div className="flex items-center gap-3 text-muted-foreground py-4">
            <IconLoader2 className="size-4 animate-spin" />
            <span className="text-sm">Searching for VASP attribution…</span>
          </div>
        )}

        {/* No match */}
        {!isLoading && (!data || data.total_matches === 0) && (
          <div className="flex items-center gap-3 rounded-lg bg-muted/40 px-4 py-5 text-muted-foreground">
            <IconBuildingBank className="size-5 shrink-0 opacity-40" />
            <p className="text-sm">
              No VASP attribution found — graph may need deeper traversal.
            </p>
          </div>
        )}

        {/* Match found */}
        {!isLoading && data && data.total_matches > 0 && (() => {
          const v = data.nearest_vasps[0]
          const { label, cls } = entityTypeBadge(v.entity_type)
          const shortAddr = `${v.vasp_address.slice(0, 10)}…${v.vasp_address.slice(-6)}`

          return (
            <div className="grid gap-4">
              {/* Name + type */}
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <p className="text-xl font-bold leading-tight">{v.vasp_name}</p>
                <Badge className={`${cls} text-xs font-semibold shrink-0`}>{label}</Badge>
              </div>

              {/* Stat row */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 text-sm">
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <p className="text-xs text-muted-foreground mb-0.5">Hop Distance</p>
                  <p className="font-semibold">{v.hops} hop{v.hops !== 1 ? "s" : ""} from seed</p>
                </div>
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <p className="text-xs text-muted-foreground mb-0.5">Confidence</p>
                  <p className="font-semibold">{Math.round(v.confidence * 100)}%</p>
                </div>
                <div className="rounded-lg bg-muted/50 px-3 py-2">
                  <p className="text-xs text-muted-foreground mb-0.5">Source</p>
                  <p className="font-semibold capitalize">{v.source}</p>
                </div>
              </div>

              {/* Address with copy */}
              <div className="flex items-center gap-2">
                <p className="text-xs text-muted-foreground shrink-0">Address</p>
                <code className="flex-1 truncate rounded bg-muted px-2 py-1 text-xs font-mono">
                  {shortAddr}
                </code>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 shrink-0"
                  onClick={() => copyAddress(v.vasp_address)}
                  aria-label="Copy VASP address"
                >
                  {copied
                    ? <IconCircleCheck className="size-3.5 text-green-500" />
                    : <IconCopy className="size-3.5" />}
                </Button>
              </div>

              {/* Path chain */}
              {Array.isArray(v.path) && v.path.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1.5">Transaction path</p>
                  <div className="flex flex-wrap items-center gap-1 text-xs font-mono">
                    {v.path.map((addr: string, idx: number) => (
                      <React.Fragment key={idx}>
                        {idx > 0 && (
                          <span className="text-muted-foreground select-none">→</span>
                        )}
                        <span
                          className={`rounded px-1.5 py-0.5 ${
                            idx === 0
                              ? "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300"
                              : idx === v.path.length - 1
                              ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"
                              : "bg-muted text-muted-foreground"
                          }`}
                        >
                          {addr.slice(0, 8)}…
                        </span>
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              )}

              {/* More matches */}
              {data.total_matches > 1 && (
                <p className="text-xs text-muted-foreground">
                  +{data.total_matches - 1} more attributed VASP{data.total_matches - 1 !== 1 ? "s" : ""} in graph
                </p>
              )}
            </div>
          )
        })()}
      </CardContent>
    </Card>
  )
}

// ── Main report page ──────────────────────────────────────────────────────────
interface TraceReportPageProps {
  traceId: string
  walletAddress: string
  chain: string
  onBack: () => void
  onViewFundFlow: () => void
}

export function TraceReportPage({
  traceId,
  walletAddress,
  chain,
  onBack,
  onViewFundFlow,
}: TraceReportPageProps) {
  const { data: report, isLoading, error } = useMLReport(traceId, true)

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-muted-foreground">
        <IconLoader2 className="size-5 animate-spin" />
        Running ML analysis…
      </div>
    )
  }

  if (error || !report) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-muted-foreground">
        <IconAlertTriangle className="size-8 text-destructive" />
        <p>Could not load ML report. The trace may still be processing.</p>
        <Button variant="outline" onClick={onBack}>
          <IconArrowLeft className="size-4" /> Back
        </Button>
      </div>
    )
  }

  const score = report.suspicion_score
  const confidence = Math.round(report.confidence * 100)
  const hasFactors = report.contributing_factors.length > 0
  const hasPatterns = report.detected_patterns.length > 0

  // ── Graph node counts — entity_type values are lowercase from backend ──────
  const nodes = report.graph.nodes ?? []
  const exchangeCount = nodes.filter((n) => n.entity_type === "exchange").length
  const mixerCount    = nodes.filter((n) => n.entity_type === "mixer").length
  const bridgeCount   = nodes.filter((n) => n.entity_type === "bridge").length

  return (
    <div className="px-4 lg:px-6 grid gap-6">

      {/* ── Back nav ──────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2">
          <IconArrowLeft className="size-4" /> Back to trace
        </Button>
        <Separator orientation="vertical" className="h-4" />
        <span className="text-sm text-muted-foreground font-mono truncate">
          {walletAddress.slice(0, 18)}…
        </span>
        <Badge variant="outline" className="text-xs">{chain}</Badge>
      </div>

      {/* ── P0-4 / P1-1: Nearest Attributed VASP card (above ML panel) ───── */}
      <NearestVaspCard traceId={traceId} />

      {/* ── Top row: speedometer + summary ────────────────────────────────── */}
      <div className="grid gap-4 lg:grid-cols-[auto_1fr]">

        {/* Speedometer card */}
        <Card className="flex flex-col items-center justify-center px-6 py-4 min-w-[280px]">
          <CardHeader className="pb-2 text-center p-0 mb-2">
            <CardTitle className="flex items-center gap-2 justify-center text-base">
              <IconBrain className="size-4" /> ML Suspicion Score
            </CardTitle>
            <CardDescription className="text-xs">
              Model v{report.model_version}
            </CardDescription>
          </CardHeader>
          <Speedometer score={score} />
          <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
            <IconWaveSine className="size-4" />
            Confidence: <strong className="text-foreground">{confidence}%</strong>
          </div>
        </Card>

        {/* Summary card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {report.is_suspicious
                ? <IconShieldExclamation className="size-5 text-destructive" />
                : <IconShield className="size-5 text-green-500" />}
              Analysis Summary
            </CardTitle>
            <CardDescription>
              Automated ML assessment of wallet <span className="font-mono">{walletAddress.slice(0, 14)}…</span>
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {/* Primary stats */}
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div className="rounded-lg bg-muted/50 p-3 text-center">
                <p className="text-muted-foreground text-xs mb-1">Suspicion</p>
                <p className="text-2xl font-bold">{score}</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-3 text-center">
                <p className="text-muted-foreground text-xs mb-1">Risk Band</p>
                <p className="text-lg font-bold capitalize">{report.ml_risk_band}</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-3 text-center">
                <p className="text-muted-foreground text-xs mb-1">Graph Nodes</p>
                <p className="text-2xl font-bold">{report.graph.node_count.toLocaleString()}</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-3 text-center">
                <p className="text-muted-foreground text-xs mb-1">Graph Edges</p>
                <p className="text-2xl font-bold">{report.graph.edge_count.toLocaleString()}</p>
              </div>
            </div>

            {/* Entity breakdown — entity_type is lowercase: 'exchange' | 'mixer' | 'bridge' */}
            <div className="grid grid-cols-3 gap-3 text-sm">
              <div className="rounded-lg bg-green-50 dark:bg-green-900/20 p-3 text-center">
                <p className="text-muted-foreground text-xs mb-1">Exchanges</p>
                <p className="text-2xl font-bold text-green-700 dark:text-green-400">{exchangeCount}</p>
              </div>
              <div className="rounded-lg bg-red-50 dark:bg-red-900/20 p-3 text-center">
                <p className="text-muted-foreground text-xs mb-1">Mixers</p>
                <p className="text-2xl font-bold text-red-700 dark:text-red-400">{mixerCount}</p>
              </div>
              <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 p-3 text-center">
                <p className="text-muted-foreground text-xs mb-1">Bridges</p>
                <p className="text-2xl font-bold text-amber-700 dark:text-amber-400">{bridgeCount}</p>
              </div>
            </div>

            {/* Detected patterns */}
            {hasPatterns && (
              <div className="grid gap-2">
                <p className="text-sm font-medium">Detected patterns</p>
                <div className="flex flex-wrap gap-2">
                  {report.detected_patterns.map((p) => (
                    <Badge key={p} variant="secondary" className="text-xs gap-1">
                      <IconAlertTriangle className="size-3" /> {p}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {!hasPatterns && !report.is_suspicious && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <IconCircleCheck className="size-4 text-green-500" />
                No suspicious patterns detected by the ML model.
              </div>
            )}

            {/* Fund flow button */}
            <Button onClick={onViewFundFlow} className="w-full sm:w-fit mt-2">
              View Fund Movement <IconArrowRight className="size-4" />
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* ── Contributing factors ───────────────────────────────────────────── */}
      {hasFactors && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Reasoning — Contributing Factors</CardTitle>
            <CardDescription>
              Features that drove the suspicion score, ranked by impact.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {report.contributing_factors.map((f: MLReportFactor, i: number) => (
              <div key={f.feature} className="flex gap-3 rounded-lg border p-3">
                <div className="flex flex-col items-center gap-1 pt-0.5">
                  <span className="text-xs text-muted-foreground font-mono">{String(i + 1).padStart(2, "0")}</span>
                  <SeverityDot severity={f.severity} />
                </div>
                <div className="flex-1 grid gap-0.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">{f.name}</span>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-sm font-mono font-bold">{f.value}</span>
                      <Badge
                        variant={f.severity === "high" ? "destructive" : "outline"}
                        className="text-xs capitalize"
                      >
                        {f.severity}
                      </Badge>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground">{f.description}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {!hasFactors && (
        <Card>
          <CardContent className="py-8 flex flex-col items-center gap-2 text-center text-muted-foreground">
            <IconCircleCheck className="size-8 text-green-500" />
            <p className="text-sm">No significant risk factors identified for this wallet.</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

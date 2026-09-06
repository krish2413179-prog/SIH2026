"use client"

import * as React from "react"
import {
  IconAlertTriangle,
  IconArrowRight,
  IconCheck,
  IconDatabase,
  IconLoader2,
  IconNetwork,
  IconRefresh,
  IconShieldCheck,
  IconX,
} from "@tabler/icons-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import {
  useCreateCase,
  useCases,
  useSubmitWallets,
  useTraceStatus,
  useTraceLiveFeed,
} from "@/lib/hooks"
import { useQuery } from "@tanstack/react-query"
import { TraceReportPage } from "@/components/trace-report-page"
import { FundFlowPage } from "@/components/fund-flow-page"

const SUPPORTED_CHAINS = ["ETH", "BTC", "TRX", "BSC", "SOL", "MATIC"]

function apiErrorMessage(err: any): string {
  const detail = err?.response?.data?.detail
  if (!detail) return err?.message || "Something went wrong"
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    return detail.map((d: any) => d?.msg ?? JSON.stringify(d)).join("; ")
  }
  return JSON.stringify(detail)
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
      <div
        className="h-2 rounded-full bg-primary transition-all duration-700 ease-in-out"
        style={{ width: `${Math.min(Math.max(pct, 0), 100)}%` }}
      />
    </div>
  )
}

// ── Trace status panel ────────────────────────────────────────────────────────
const TRACE_STEPS = [
  { label: "Ingesting transaction history", threshold: 20 },
  { label: "Resolving wallet ownership", threshold: 40 },
  { label: "Following bridge and mixer hops", threshold: 60 },
  { label: "Matching VASP intelligence", threshold: 80 },
  { label: "Preparing graph evidence", threshold: 100 },
]

function riskBadgeVariant(band: string | null | undefined) {
  if (!band) return "outline" as const
  const b = band.toLowerCase()
  if (b === "critical" || b === "high") return "destructive" as const
  if (b === "medium") return "secondary" as const
  return "outline" as const
}

interface TraceViewProps {
  traceId: string
  walletAddress: string
  chain: string
  caseId: string
  onNewCase: () => void
  onViewReport: () => void
}

function TraceView({ traceId, walletAddress, chain, caseId, onNewCase, onViewReport }: TraceViewProps) {
  const { data: status, isLoading } = useTraceStatus(traceId, true)
  const { data: feed } = useTraceLiveFeed(traceId);

    // Keep a rolling history of seen addresses so they persist between polls
  const [addrHistory, setAddrHistory] = React.useState<string[]>([])
  React.useEffect(() => {
    if (!feed?.addresses?.length) return
    setAddrHistory((prev) => {
      const newAddrs = feed.addresses.filter((a) => !prev.includes(a))
      if (!newAddrs.length) return prev
      // prepend newest, cap at 60
      return [...newAddrs, ...prev].slice(0, 60)
    })
  }, [feed?.addresses])

  const pct =
    status?.estimated_pct ??
    (status?.status === "completed"
      ? 100
      : status?.status === "running"
      ? 35
      : status?.status === "failed"
      ? 0
      : 5)

  const isFailed = status?.status === "failed"
  const isComplete = status?.status === "completed"
  const isRunning = status?.status === "running" || status?.status === "queued"

  return (
    <div className="grid gap-4 lg:grid-cols-[1.25fr_.75fr]">
      {/* ── Main trace card ─────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div className="grid gap-1">
            <CardTitle className="flex items-center gap-2">
              {isLoading || isRunning ? (
                <IconLoader2 className="size-4 animate-spin text-muted-foreground" />
              ) : isComplete ? (
                <IconShieldCheck className="size-4 text-primary" />
              ) : (
                <IconAlertTriangle className="size-4 text-destructive" />
              )}
              Blockchain trace
            </CardTitle>
            <CardDescription>
              Tracing{" "}
              <span className="font-mono text-xs">
                {walletAddress.slice(0, 14)}…
              </span>{" "}
              on {chain}
            </CardDescription>
          </div>

          <Badge
            variant={
              isComplete
                ? "default"
                : isFailed
                ? "destructive"
                : "secondary"
            }
            className="capitalize shrink-0"
          >
            {status?.status ?? "queued"}
          </Badge>
        </CardHeader>

        <CardContent className="grid gap-6">
          {/* Progress bar */}
          <div className="grid gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Overall progress</span>
              <strong>{Math.round(pct)}%</strong>
            </div>
            <ProgressBar pct={pct} />
          </div>

          <Separator />

          {/* Step checklist */}
          <div className="grid gap-3 hidden">
            {TRACE_STEPS.map(({ label, threshold }) => {
              const done = pct >= threshold
              return (
                <div key={label} className="flex items-center gap-3 text-sm">
                  <span
                    className={`flex size-6 shrink-0 items-center justify-center rounded-full ${
                      done ? "bg-primary/10" : "bg-muted"
                    }`}
                  >
                    {done ? (
                      <IconCheck className="size-3.5 text-primary" />
                    ) : isLoading || isRunning ? (
                      <IconLoader2 className="size-3.5 animate-spin text-muted-foreground" />
                    ) : (
                      <IconX className="size-3.5 text-muted-foreground" />
                    )}
                  </span>
                  <span className={done ? "font-medium" : "text-muted-foreground"}>
                    {label}
                  </span>
                  <Badge
                    variant={done ? "secondary" : "outline"}
                    className="ml-auto text-xs"
                  >
                    {done ? "Done" : "Pending"}
                  </Badge>
                </div>
              )
            })}
          </div>

          {/* ── Live address feed ────────────────────────────────────────── */}
          {(
            <>
              <Separator />
              <div className="grid gap-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium flex items-center gap-1.5">
                    {isRunning && (
                      <span className="relative flex size-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                        <span className="relative inline-flex rounded-full size-2 bg-primary" />
                      </span>
                    )}
                    Live address scan
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {addrHistory.length} address{addrHistory.length !== 1 ? "es" : ""} scanned
                  </span>
                </div>

                <div
                  className="rounded-md border bg-muted/30 overflow-hidden"
                  style={{ height: 300 }}
                >
                  <div className="h-full overflow-y-auto p-2 space-y-1 flex flex-col-reverse">
                    {addrHistory.length === 0 ? (
                      <p className="text-xs text-muted-foreground text-center py-4">
                        Waiting for first addresses…
                      </p>
                    ) : (
                      addrHistory.map((addr, i) => (
                        <div
                          key={addr}
                          className={`flex items-center gap-2 text-xs font-mono transition-opacity ${
                            i === 0 ? "opacity-100" : "opacity-60"
                          }`}
                        >
                          <span
                            className={`size-1.5 rounded-full shrink-0 ${
                              i === 0 ? "bg-primary animate-pulse" : "bg-muted-foreground/40"
                            }`}
                          />
                          <span className="truncate">{addr}</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

          <Separator />

          {/* Actions */}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={onNewCase}>
              <IconRefresh className="size-4" />
              New case
            </Button>
            {isComplete && (
              <Button size="sm" onClick={onViewReport}>
                View Results <IconArrowRight className="size-4" />
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ── Details sidebar ──────────────────────────────────────────────── */}
      <div className="grid gap-4 content-start">
        <Card>
          <CardHeader>
            <CardTitle>Trace details</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Case ID</span>
              <span className="font-mono">{caseId.slice(0, 8)}…</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Trace ID</span>
              <span className="font-mono">{traceId.slice(0, 8)}…</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Chain</span>
              <strong>{chain}</strong>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Wallet</span>
              <span className="font-mono text-xs">
                {walletAddress.slice(0, 12)}…
              </span>
            </div>
            {status?.current_hop != null && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Hop</span>
                <span>
                  {status.current_hop} / {status.max_hops}
                </span>
              </div>
            )}
          </CardContent>
        </Card>

        {(isComplete || status?.risk_score != null) && (
          <Card>
            <CardHeader>
              <CardTitle>Risk assessment</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm">
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Score</span>
                <strong className="text-lg">
                  {status?.risk_score ?? "—"}
                </strong>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-muted-foreground">Band</span>
                <Badge
                  variant={riskBadgeVariant(status?.risk_band)}
                  className="capitalize"
                >
                  {status?.risk_band ?? "—"}
                </Badge>
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Engine</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-2 text-sm text-muted-foreground">
            <IconNetwork className="size-4 text-primary shrink-0" />
            Multi-hop heuristics · Auto-VASP attribution
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

// ── sessionStorage persistence helpers ───────────────────────────────────────
const SESSION_KEY = "vasp_workspace_state"

interface WorkspaceSession {
  screen: "intake" | "trace" | "report" | "fundflow"
  activeCaseId: string | null
  activeTraceId: string | null
  walletAddress: string
  chain: string
}

function loadSession(): WorkspaceSession {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (raw) return JSON.parse(raw) as WorkspaceSession
  } catch {}
  return { screen: "intake", activeCaseId: null, activeTraceId: null, walletAddress: "", chain: "ETH" }
}

function saveSession(s: WorkspaceSession) {
  try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(s)) } catch {}
}

function clearSession() {
  try { sessionStorage.removeItem(SESSION_KEY) } catch {}
}

// ── Risk band colour helpers ───────────────────────────────────────────────────
function riskColor(band: string | null | undefined) {
  if (!band) return "text-muted-foreground"
  const b = band.toLowerCase()
  if (b === "critical") return "text-red-500"
  if (b === "high")     return "text-orange-500"
  if (b === "medium")   return "text-yellow-500"
  return "text-green-500"
}

// ── RecentTraces ──────────────────────────────────────────────────────────────
interface RecentTracesProps {
  cases: import("@/lib/api").Case[]
  onOpen: (caseId: string, traceId: string, address: string, chain: string) => void
}

function RecentTraces({ cases, onOpen }: RecentTracesProps) {
  // Fetch wallets for all cases with completed traces
  const openCases = cases.slice(0, 20) // cap to avoid too many requests

  // We fetch wallets for each case and flatten them
  const queries = openCases.map((c) => ({
    id: c.id,
    title: c.title,
  }))

  // Use a single consolidated fetch: get wallets for all cases
  const { data: allWallets, isLoading } = useAllCaseWallets(queries.map((q) => q.id))

  const completedTraces = React.useMemo(() => {
    if (!allWallets) return []
    return allWallets
      .filter((w: any) => w.status === "completed")
      .sort((a: any, b: any) =>
        new Date(b.completed_at ?? 0).getTime() - new Date(a.completed_at ?? 0).getTime()
      )
      .slice(0, 10)
  }, [allWallets])

  if (!isLoading && completedTraces.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <IconShieldCheck className="size-4 text-primary" />
          Recent completed traces
        </CardTitle>
        <CardDescription>Click any trace to jump directly to its report.</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
            <IconLoader2 className="size-4 animate-spin" /> Loading…
          </div>
        ) : (
          <div className="divide-y">
            {completedTraces.map((trace: any, i) => (
              <div
                key={trace.trace_id || i}
                className="flex items-center justify-between py-3 gap-4"
              >
                <div className="grid gap-0.5 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs truncate max-w-[260px]">
                      {trace.wallet_address}
                    </span>
                    <Badge variant="outline" className="text-xs shrink-0">
                      {trace.chain}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>Case: {trace.case_title ?? trace.case_id?.slice(0, 8) + "…"}</span>
                    {trace.completed_at && (
                      <span>
                        {new Date(trace.completed_at).toLocaleString(undefined, {
                          month: "short", day: "numeric",
                          hour: "2-digit", minute: "2-digit",
                        })}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  {trace.risk_band && (
                    <div className="text-right">
                      <p className={`text-sm font-bold ${riskColor(trace.risk_band)}`}>
                        {trace.risk_score ?? "—"}
                      </p>
                      <p className={`text-xs capitalize ${riskColor(trace.risk_band)}`}>
                        {trace.risk_band}
                      </p>
                    </div>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      onOpen(trace.case_id, trace.trace_id, trace.wallet_address, trace.chain)
                    }
                  >
                    Open <IconArrowRight className="size-3.5 ml-1" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Fetch wallets for multiple cases at once ──────────────────────────────────
function useAllCaseWallets(caseIds: string[]) {
  const { data: casesData } = useCases({ page_size: 50 })
  const cases = casesData?.items ?? []

  // Build a flat list by querying /cases/{id}/wallets for each case
  // We use a single query that depends on all caseIds
  return useQuery({
    queryKey: ["all-case-wallets", caseIds.join(",")],
    queryFn: async () => {
      if (!caseIds.length) return []
      const { walletsApi } = await import("@/lib/api")
      const results = await Promise.all(
        caseIds.map(async (caseId) => {
          try {
            const res = await walletsApi.list(caseId)
            const caseTitle = cases.find((c) => c.id === caseId)?.title
            return (res.data as any[]).map((w) => ({ ...w, case_id: caseId, case_title: caseTitle }))
          } catch {
            return []
          }
        })
      )
      return results.flat()
    },
    enabled: caseIds.length > 0,
    staleTime: 10_000,
    refetchInterval: 15_000,
  })
}

// ── Intake form ───────────────────────────────────────────────────────────────
export function InvestigationWorkspace() {
  const saved = React.useMemo(() => loadSession(), [])

  const [caseRef, setCaseRef] = React.useState("")
  const [walletAddress, setWalletAddress] = React.useState(saved.walletAddress)
  const [chain, setChain] = React.useState(saved.chain)
  const [activeCaseId, setActiveCaseId] = React.useState<string | null>(saved.activeCaseId)
  const [activeTraceId, setActiveTraceId] = React.useState<string | null>(saved.activeTraceId)
  const [selectedCaseId, setSelectedCaseId] = React.useState<string>("")
  const [screen, setScreen] = React.useState<"intake" | "trace" | "report" | "fundflow">(saved.screen)

  // Sync any state change to sessionStorage
  React.useEffect(() => {
    saveSession({ screen, activeCaseId, activeTraceId, walletAddress, chain })
  }, [screen, activeCaseId, activeTraceId, walletAddress, chain])

  const createCase = useCreateCase()
  const submitWallets = useSubmitWallets()
  const { data: casesData } = useCases({ page_size: 50 })
  const existingCases = casesData?.items ?? []

  const isSubmitting = createCase.isPending || submitWallets.isPending

  const handleRegister = async () => {
    try {
      let caseId = selectedCaseId

      if (!selectedCaseId) {
        if (!caseRef.trim()) {
          toast.error("Enter a case reference")
          return
        }
        const newCase = await createCase.mutateAsync({
          title: caseRef.trim(),
          description: `Suspect wallet: ${walletAddress} on ${chain}`,
        })
        caseId = newCase.id
      }

      if (!walletAddress.trim()) {
        toast.error("Enter a wallet address")
        return
      }

      const result: any = await submitWallets.mutateAsync({
        caseId,
        wallets: [{ address: walletAddress.trim(), chain }],
      })

      const traceId = result?.results?.[0]?.trace_id
      if (!traceId) {
        toast.error("Wallet submitted but no trace ID returned")
        return
      }

      setActiveCaseId(caseId)
      setActiveTraceId(traceId)
      setScreen("trace")
      toast.success("Trace queued — tracking live status")
    } catch (err: any) {
      toast.error(apiErrorMessage(err))
    }
  }

  const handleNewCase = () => {
    clearSession()
    setCaseRef("")
    setWalletAddress("")
    setChain("ETH")
    setActiveCaseId(null)
    setActiveTraceId(null)
    setSelectedCaseId("")
    setScreen("intake")
  }

  // ── Screen routing ─────────────────────────────────────────────────────────
  if (screen === "report" && activeTraceId && activeCaseId) {
    return (
      <TraceReportPage
        traceId={activeTraceId}
        walletAddress={walletAddress}
        chain={chain}
        onBack={() => setScreen("trace")}
        onViewFundFlow={() => setScreen("fundflow")}
      />
    )
  }

  if (screen === "fundflow" && activeTraceId) {
    return (
      <FundFlowPage
        traceId={activeTraceId}
        walletAddress={walletAddress}
        chain={chain}
        onBack={() => setScreen("report")}
      />
    )
  }

  if (screen === "trace" && activeTraceId && activeCaseId) {
    return (
      <div className="px-4 lg:px-6">
        <TraceView
          traceId={activeTraceId}
          walletAddress={walletAddress}
          chain={chain}
          caseId={activeCaseId}
          onNewCase={handleNewCase}
          onViewReport={() => setScreen("report")}
        />
      </div>
    )
  }

  // ── Intake form ───────────────────────────────────────────────────────────
  return (
    <div className="px-4 lg:px-6 grid gap-6">
      <div className="grid gap-4 lg:grid-cols-[1.25fr_.75fr]">

        <Card>
          <CardHeader>
            <CardTitle>Register a new complaint</CardTitle>
            <CardDescription>
              Capture the incident details and create a traceable investigation record.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5">

            {existingCases.length > 0 && (
              <div className="grid gap-2">
                <Label>Attach to existing case (optional)</Label>
                <Select value={selectedCaseId} onValueChange={setSelectedCaseId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Create new case" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">Create new case</SelectItem>
                    {existingCases
                      .filter((c) => c.status === "open")
                      .map((c) => (
                        <SelectItem key={c.id} value={c.id}>
                          {c.title}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {!selectedCaseId && (
              <div className="grid gap-2">
                <Label htmlFor="case">Case reference</Label>
                <Input
                  id="case"
                  value={caseRef}
                  onChange={(e) => setCaseRef(e.target.value)}
                  placeholder="LEA-2026-0418"
                />
              </div>
            )}

            <div className="grid gap-2">
              <Label htmlFor="wallet">Suspect wallet address</Label>
              <Input
                id="wallet"
                value={walletAddress}
                onChange={(e) => setWalletAddress(e.target.value)}
                placeholder="0x... or bc1q..."
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="chain">Blockchain network</Label>
              <Select value={chain} onValueChange={setChain}>
                <SelectTrigger id="chain">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SUPPORTED_CHAINS.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Button onClick={handleRegister} disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <IconLoader2 className="animate-spin" /> Registering…
                </>
              ) : (
                <>
                  Register complaint <IconArrowRight />
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        <div className="grid gap-4 content-start">
          <Card>
            <CardHeader>
              <CardTitle>Evidence readiness</CardTitle>
              <CardDescription>Required fields for a defensible trace.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className={`flex items-center gap-2 text-sm ${walletAddress ? "" : "text-muted-foreground"}`}>
                {walletAddress ? <IconCheck className="text-primary" /> : <IconDatabase className="size-4" />}
                {walletAddress ? "Wallet address captured" : "Wallet address pending"}
              </div>
              <div className="flex items-center gap-2 text-sm">
                <IconCheck className="text-primary" />
                Blockchain network: {chain}
              </div>
              <div className={`flex items-center gap-2 text-sm ${caseRef || selectedCaseId ? "" : "text-muted-foreground"}`}>
                {caseRef || selectedCaseId ? <IconCheck className="text-primary" /> : <IconDatabase className="size-4" />}
                {caseRef || selectedCaseId ? "Case reference set" : "Case reference pending"}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Case status</CardTitle></CardHeader>
            <CardContent className="flex items-center justify-between">
              <Badge variant="secondary">Draft</Badge>
              <span className="text-sm text-muted-foreground">Owner: Investigator</span>
            </CardContent>
          </Card>
        </div>

      </div>

      {/* ── Recent completed traces ──────────────────────────────────────────── */}
      <RecentTraces
        cases={existingCases}
        onOpen={(caseId, traceId, address, traceChain) => {
          setActiveCaseId(caseId)
          setActiveTraceId(traceId)
          setWalletAddress(address)
          setChain(traceChain)
          setScreen("report")
        }}
      />
    </div>
  )
}

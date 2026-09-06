/**
 * React Query hooks for all API entities.
 * Keeps components clean — they just call a hook and get loading/data/error.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { casesApi, dashboardApi, tracesApi, walletsApi } from './api'

// ── Keys ─────────────────────────────────────────────────────────────────────
export const KEYS = {
  dashboardSummary: ['dashboard', 'summary'] as const,
  dashboardAlerts: ['dashboard', 'alerts'] as const,
  cases: (params?: object) => ['cases', params] as const,
  case: (id: string) => ['cases', id] as const,
  caseWallets: (caseId: string) => ['cases', caseId, 'wallets'] as const,
  traceStatus: (id: string) => ['traces', id, 'status'] as const,
  traceGraph: (id: string) => ['traces', id, 'graph'] as const,
  traceVasps: (id: string) => ['traces', id, 'vasps'] as const,
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
export function useDashboardSummary() {
  return useQuery({
    queryKey: KEYS.dashboardSummary,
    queryFn: () => dashboardApi.summary().then((r) => r.data),
    refetchInterval: 30_000, // refresh every 30s
    staleTime: 15_000,
  })
}

export function useDashboardAlerts() {
  return useQuery({
    queryKey: KEYS.dashboardAlerts,
    queryFn: () => dashboardApi.alerts().then((r) => r.data),
    staleTime: 30_000,
  })
}

// ── Cases ─────────────────────────────────────────────────────────────────────
export function useCases(params?: { status?: string; q?: string; page?: number; page_size?: number }) {
  return useQuery({
    queryKey: KEYS.cases(params),
    queryFn: () => casesApi.list(params).then((r) => r.data),
    staleTime: 10_000,
  })
}

export function useCase(id: string) {
  return useQuery({
    queryKey: KEYS.case(id),
    queryFn: () => casesApi.get(id).then((r) => r.data),
    enabled: !!id,
  })
}

export function useCreateCase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { title: string; description?: string }) => casesApi.create(data).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['cases'] }),
  })
}

export function useUpdateCase() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => casesApi.update(id, data).then((r) => r.data),
    onSuccess: (_, { id }) => {
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: KEYS.case(id) })
    },
  })
}

// ── Wallets / Traces ──────────────────────────────────────────────────────────
export function useCaseWallets(caseId: string) {
  return useQuery({
    queryKey: KEYS.caseWallets(caseId),
    queryFn: () => walletsApi.list(caseId).then((r) => r.data),
    enabled: !!caseId,
    refetchInterval: 5_000, // poll while traces may be running
  })
}

export function useSubmitWallets() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ caseId, wallets }: { caseId: string; wallets: Array<{ address: string; chain?: string }> }) =>
      walletsApi.submit(caseId, wallets).then((r) => r.data),
    onSuccess: (_, { caseId }) => {
      qc.invalidateQueries({ queryKey: KEYS.caseWallets(caseId) })
    },
  })
}

export function useTraceStatus(traceId: string, enabled = true) {
  return useQuery({
    queryKey: KEYS.traceStatus(traceId),
    queryFn: () => tracesApi.status(traceId).then((r) => r.data),
    enabled: enabled && !!traceId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      // stop polling once done
      if (status === 'completed' || status === 'failed') return false
      return 3_000
    },
  })
}

export function useTraceLiveFeed(traceId: string, enabled = true) {
  return useQuery({
    queryKey: ['traces', traceId, 'live-feed'],
    queryFn: () => tracesApi.liveFeed(traceId).then((r) => r.data),
    enabled: enabled && !!traceId,
    refetchInterval: (query) => {
      const s = query.state.data?.status
      if (s === 'completed' || s === 'failed') return false
      return 2_000 // poll every 2s while running
    },
  })
}

export function useTraceGraph(traceId: string) {
  return useQuery({
    queryKey: KEYS.traceGraph(traceId),
    queryFn: () => tracesApi.graph(traceId).then((r) => r.data),
    enabled: !!traceId,
    staleTime: Infinity, // graphs don't change
  })
}

export function useNearestVasps(traceId: string | null) {
  return useQuery({
    queryKey: KEYS.traceVasps(traceId ?? ''),
    queryFn: () => tracesApi.nearestVasps(traceId!).then((r) => r.data),
    enabled: !!traceId,
    staleTime: 60_000,
  })
}

export function useRunAiAnalysis() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (traceId: string) => tracesApi.aiAnalysis(traceId).then((r) => r.data),
    onSuccess: (_, traceId) => {
      qc.invalidateQueries({ queryKey: KEYS.traceStatus(traceId) })
    },
  })
}

export function useMLReport(traceId: string, enabled = true) {
  return useQuery({
    queryKey: ['traces', traceId, 'ml-report'],
    queryFn: () => tracesApi.mlReport(traceId).then((r) => r.data),
    enabled: enabled && !!traceId,
    staleTime: Infinity, // report doesn't change after completion
  })
}

/**
 * API client — thin axios wrapper with JWT auth and auto-refresh.
 * All requests go through Next.js rewrites: /api/* → http://localhost:8000/api/*
 */
import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'

// ── Token storage ────────────────────────────────────────────────────────────
const TOKEN_KEY = 'vasp_access_token'
const REFRESH_KEY = 'vasp_refresh_token'

export const tokenStorage = {
  getAccess: () => (typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null),
  getRefresh: () => (typeof window !== 'undefined' ? localStorage.getItem(REFRESH_KEY) : null),
  set: (access: string, refresh: string) => {
    localStorage.setItem(TOKEN_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

// ── Axios instance ───────────────────────────────────────────────────────────
const api: AxiosInstance = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

// Attach access token to every request
api.interceptors.request.use((config) => {
  const token = tokenStorage.getAccess()
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Auto-refresh on 401
let isRefreshing = false
let refreshQueue: Array<(token: string) => void> = []

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config as AxiosRequestConfig & { _retry?: boolean }
    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error)
    }
    original._retry = true

    if (isRefreshing) {
      return new Promise((resolve) => {
        refreshQueue.push((token) => {
          original.headers = { ...original.headers, Authorization: `Bearer ${token}` }
          resolve(api(original))
        })
      })
    }

    isRefreshing = true
    try {
      const refresh = tokenStorage.getRefresh()
      if (!refresh) throw new Error('No refresh token')
      const refreshBase = (process.env.NEXT_PUBLIC_API_URL || '/api/v1').replace(/\/+$/, '')
      const { data } = await axios.post(`${refreshBase}/auth/refresh`, { refresh_token: refresh })
      tokenStorage.set(data.access_token, data.refresh_token)
      refreshQueue.forEach((cb) => cb(data.access_token))
      refreshQueue = []
      original.headers = { ...original.headers, Authorization: `Bearer ${data.access_token}` }
      return api(original)
    } catch {
      tokenStorage.clear()
      if (typeof window !== 'undefined') window.location.href = '/login'
      return Promise.reject(error)
    } finally {
      isRefreshing = false
    }
  }
)

export default api

// ── Typed API calls ───────────────────────────────────────────────────────────

// Auth
export const authApi = {
  login: (email: string, password: string) =>
    api.post<{ access_token: string; refresh_token: string }>('/auth/login', { email, password }),
  logout: () => api.post('/auth/logout'),
}

// Dashboard
export const dashboardApi = {
  summary: () =>
    api.get<{
      open_cases: number
      active_traces: number
      high_risk_cases: number
      pending_sahyog: number
    }>('/dashboard/summary'),
  alerts: () => api.get<any[]>('/dashboard/alerts'),
}

// Cases
export interface Case {
  id: string
  title: string
  description: string | null
  status: 'open' | 'under_review' | 'closed'
  created_by: string
  supervisor_id: string | null
  org_unit_id: string
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface CaseListResponse {
  items: Case[]
  total: number
  page: number
  page_size: number
}

export const casesApi = {
  list: (params?: { status?: string; q?: string; page?: number; page_size?: number }) =>
    api.get<CaseListResponse>('/cases', { params }),
  get: (id: string) => api.get<Case>(`/cases/${id}`),
  create: (data: { title: string; description?: string }) => api.post<Case>('/cases', data),
  update: (id: string, data: Partial<Case>) => api.patch<Case>(`/cases/${id}`, data),
  delete: (id: string) => api.delete(`/cases/${id}`),
}

// Wallets / Traces
export interface TraceJob {
  id: string
  wallet_address: string
  chain: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  current_hop: number
  max_hops: number
  estimated_pct: number | null
  enqueued_at: string | null
  started_at: string | null
  completed_at: string | null
  risk_score: number | null
  risk_band: string | null
}

export const walletsApi = {
  submit: (caseId: string, wallets: Array<{ address: string; chain?: string }>) =>
    api.post(`/cases/${caseId}/wallets`, { addresses: wallets }),
  list: (caseId: string) => api.get<TraceJob[]>(`/cases/${caseId}/wallets`),
}

export interface MLReportFactor {
  feature: string
  name: string
  value: string
  severity: 'low' | 'medium' | 'high'
  description: string
}

export interface MLReport {
  trace_id: string
  wallet_address: string
  chain: string
  risk_score: number | null
  risk_band: string | null
  suspicion_score: number
  suspicion_probability: number
  is_suspicious: boolean
  ml_risk_band: string
  confidence: number
  detected_patterns: string[]
  contributing_factors: MLReportFactor[]
  model_version: string
  graph: {
    node_count: number
    edge_count: number
    nodes: Array<{
      id: string
      entity_type: string
      in_degree: number
      out_degree: number
      total_inflow: number
      total_outflow: number
      is_seed: boolean
    }>
    edges: Array<{
      source: string
      target: string
      amount: number
      is_bridge: boolean
    }>
  }
}

export const tracesApi = {
  status: (traceId: string) => api.get<TraceJob>(`/traces/${traceId}/status`),
  graph: (traceId: string) => api.get<any>(`/traces/${traceId}/graph`),
  liveFeed: (traceId: string) =>
    api.get<{ trace_id: string; status: string; current_hop: number; estimated_pct: number | null; addresses: string[] }>(
      `/traces/${traceId}/live-feed`
    ),
  nearestVasps: (traceId: string) =>
    api.get<{ trace_id: string; total_matches: number; nearest_vasps: any[] }>(
      `/traces/${traceId}/nearest-vasps`
    ),
  aiAnalysis: (traceId: string) => api.post<any>(`/traces/${traceId}/ai-analysis`),
  mlReport: (traceId: string) => api.get<MLReport>(`/traces/${traceId}/ml-report`),
}

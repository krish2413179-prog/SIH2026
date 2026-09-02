'use client';

/**
 * Dashboard page — real implementation.
 *
 * - Header: "VASP Attribution Engine - Dashboard" + user role badge
 * - Stat widgets: Total Open Cases, High Risk Cases, Active Traces, Pending SAHYOG
 * - Recent Alerts: from useNotifications().alerts + GET /dashboard/alerts
 * - Real-time Trace Progress: from useNotifications().traceProgress
 * - Search bar: navigates to /cases?q=searchterm
 *
 * Requirements: 2.7, 13.1
 */

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { Activity, AlertTriangle, Briefcase, Search, Shield, Wifi, WifiOff } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { getCurrentUser } from '@/lib/auth';
import { useNotifications } from '@/lib/notifications';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DashboardSummary {
  open_cases: number;
  high_risk_cases: number;
  active_traces: number;
  pending_sahyog: number;
}

interface CaseListResponse {
  items: Array<{ id: string; status: string; [key: string]: unknown }>;
  total: number;
}

interface DashboardAlert {
  id: string;
  message: string;
  severity?: 'low' | 'medium' | 'high' | 'critical';
  timestamp: string;
  type?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'bg-red-900/60 border-red-600 text-red-300',
  high: 'bg-orange-900/60 border-orange-600 text-orange-300',
  medium: 'bg-yellow-900/60 border-yellow-600 text-yellow-300',
  low: 'bg-blue-900/60 border-blue-600 text-blue-300',
};

const SEVERITY_DOT: Record<string, string> = {
  critical: 'bg-red-500',
  high: 'bg-orange-500',
  medium: 'bg-yellow-500',
  low: 'bg-blue-500',
};

const ROLE_BADGE: Record<string, string> = {
  admin: 'bg-purple-700 text-purple-100',
  supervisor: 'bg-blue-700 text-blue-100',
  investigator: 'bg-green-700 text-green-100',
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCardSkeleton() {
  return (
    <div className="rounded-xl bg-gray-800 p-6 animate-pulse">
      <div className="h-4 w-28 rounded bg-gray-700 mb-3" />
      <div className="h-8 w-16 rounded bg-gray-700" />
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  accent: string;
  href?: string;
}

function StatCard({ label, value, icon, accent, href }: StatCardProps) {
  const content = (
    <div className={`rounded-xl bg-gray-800 p-6 border-l-4 ${accent} transition hover:bg-gray-750 ${href ? 'cursor-pointer hover:border-l-blue-400' : ''}`}>
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-400">{label}</p>
        <span className="text-gray-500">{icon}</span>
      </div>
      <p className="mt-2 text-3xl font-bold text-white">{value}</p>
    </div>
  );

  if (href) {
    return <Link href={href} className="block">{content}</Link>;
  }

  return content;
}

function AlertRowSkeleton() {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-gray-700 animate-pulse">
      <div className="mt-1 h-2.5 w-2.5 rounded-full bg-gray-600 flex-shrink-0" />
      <div className="flex-1 space-y-1.5">
        <div className="h-3.5 w-3/4 rounded bg-gray-700" />
        <div className="h-3 w-1/4 rounded bg-gray-700" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const router = useRouter();
  const { alerts: wsAlerts, traceProgress, connected } = useNotifications();
  const [searchInput, setSearchInput] = useState('');
  const user = getCurrentUser();

  // --- Fetch dashboard summary (gracefully handles 404) ---
  const {
    data: summary,
    isLoading: summaryLoading,
  } = useQuery<DashboardSummary>({
    queryKey: ['dashboard', 'summary'],
    queryFn: async () => {
      try {
        const res = await api.get<DashboardSummary>('/dashboard/summary');
        return res.data;
      } catch (err: unknown) {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 404 || status === 405) {
          // Fall back: compute from /cases list
          const [openRes, allRes] = await Promise.all([
            api.get<CaseListResponse>('/cases', { params: { status: 'open', page: 1, page_size: 1 } }),
            api.get<CaseListResponse>('/cases', { params: { page: 1, page_size: 1 } }),
          ]);
          return {
            open_cases: openRes.data.total,
            high_risk_cases: 0,   // Not computable from cases endpoint alone
            active_traces: 0,
            pending_sahyog: 0,
          };
        }
        throw err;
      }
    },
    staleTime: 60_000,
  });

  // --- Fetch dashboard alerts from REST (supplements WS alerts) ---
  const {
    data: restAlerts,
    isLoading: alertsLoading,
  } = useQuery<DashboardAlert[]>({
    queryKey: ['dashboard', 'alerts'],
    queryFn: async () => {
      try {
        const res = await api.get<DashboardAlert[]>('/dashboard/alerts');
        return res.data;
      } catch {
        return [];
      }
    },
    staleTime: 30_000,
  });

  // Merge WS + REST alerts, deduplicate by id, sort newest-first, cap at 20
  const mergedAlerts: DashboardAlert[] = (() => {
    const map = new Map<string, DashboardAlert>();
    for (const a of restAlerts ?? []) map.set(a.id, a);
    for (const a of wsAlerts) map.set(a.id, a as DashboardAlert);
    return Array.from(map.values())
      .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
      .slice(0, 20);
  })();

  // Active trace jobs from WS
  const activeTraceJobs = Object.values(traceProgress).filter(
    (t) => t.status === 'running' || t.status === 'pending'
  );

  // Search handler
  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = searchInput.trim();
    if (q) router.push(`/cases?q=${encodeURIComponent(q)}`);
  }

  return (
    <main className="min-h-screen bg-gray-900 text-white">
      {/* ------------------------------------------------------------------ */}
      {/* Header */}
      {/* ------------------------------------------------------------------ */}
      <header className="border-b border-gray-700 bg-gray-800/80 px-6 py-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <Shield className="h-6 w-6 text-blue-400" />
            <h1 className="text-xl font-bold tracking-tight">
              VASP Attribution Engine
            </h1>
          </div>

          <nav className="flex items-center gap-1 bg-gray-900/60 p-1 rounded-lg border border-gray-750">
            <Link
              href="/dashboard"
              className="px-3 py-1.5 text-sm font-medium rounded-md bg-blue-600 text-white transition shadow-sm"
            >
              Dashboard
            </Link>
            <Link
              href="/cases"
              className="px-3 py-1.5 text-sm font-medium rounded-md text-gray-300 hover:text-white hover:bg-gray-800 transition"
            >
              Cases
            </Link>
            <Link
              href="/reports"
              className="px-3 py-1.5 text-sm font-medium rounded-md text-gray-300 hover:text-white hover:bg-gray-800 transition"
            >
              Reports
            </Link>
            <Link
              href="/admin/vasps"
              className="px-3 py-1.5 text-sm font-medium rounded-md text-gray-300 hover:text-white hover:bg-gray-800 transition"
            >
              Admin
            </Link>
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {/* WS connection indicator */}
          <span
            title={connected ? 'Real-time connected' : 'Real-time disconnected'}
            className="flex items-center gap-1 text-xs"
          >
            {connected ? (
              <Wifi className="h-4 w-4 text-green-400" />
            ) : (
              <WifiOff className="h-4 w-4 text-gray-500" />
            )}
          </span>

          {/* Role badge */}
          {user && (
            <span
              className={`rounded-full px-3 py-0.5 text-xs font-semibold uppercase tracking-wide ${
                ROLE_BADGE[user.role] ?? 'bg-gray-700 text-gray-200'
              }`}
            >
              {user.role}
            </span>
          )}

          {user && (
            <span className="hidden sm:block text-sm text-gray-400 truncate max-w-[180px]">
              {user.email}
            </span>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-8 space-y-10">
        {/* --------------------------------------------------------------- */}
        {/* Search bar */}
        {/* --------------------------------------------------------------- */}
        <form onSubmit={handleSearch} className="flex gap-3">
          <div className="relative flex-1 max-w-xl">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search cases by title…"
              className="w-full rounded-lg bg-gray-800 border border-gray-700 py-2.5 pl-10 pr-4 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <button
            type="submit"
            className="rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
          >
            Search
          </button>
        </form>

        {/* --------------------------------------------------------------- */}
        {/* Stats widgets */}
        {/* --------------------------------------------------------------- */}
        <section>
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-widest text-gray-500">
            Overview
          </h2>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
            {summaryLoading ? (
              <>
                <StatCardSkeleton />
                <StatCardSkeleton />
                <StatCardSkeleton />
                <StatCardSkeleton />
              </>
            ) : (
              <>
                <StatCard
                  label="Total Open Cases"
                  value={summary?.open_cases ?? '—'}
                  icon={<Briefcase className="h-5 w-5" />}
                  accent="border-blue-500"
                  href="/cases"
                />
                <StatCard
                  label="High Risk Cases"
                  value={summary?.high_risk_cases ?? '—'}
                  icon={<AlertTriangle className="h-5 w-5" />}
                  accent="border-red-500"
                  href="/cases"
                />
                <StatCard
                  label="Active Traces"
                  value={summary?.active_traces ?? activeTraceJobs.length}
                  icon={<Activity className="h-5 w-5" />}
                  accent="border-green-500"
                  href="/cases"
                />
                <StatCard
                  label="Pending SAHYOG"
                  value={summary?.pending_sahyog ?? '—'}
                  icon={<Shield className="h-5 w-5" />}
                  accent="border-yellow-500"
                  href="/cases"
                />
              </>
            )}
          </div>
        </section>

        {/* --------------------------------------------------------------- */}
        {/* Bottom two-column section */}
        {/* --------------------------------------------------------------- */}
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
          {/* Recent Alerts */}
          <section className="rounded-xl bg-gray-800 border border-gray-700">
            <div className="flex items-center justify-between border-b border-gray-700 px-5 py-4">
              <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">
                Recent Alerts
              </h2>
              {wsAlerts.length > 0 && (
                <span className="rounded-full bg-red-600 px-2 py-0.5 text-xs font-bold text-white">
                  {wsAlerts.length}
                </span>
              )}
            </div>

            <div className="divide-y divide-gray-700 px-5">
              {alertsLoading ? (
                <>
                  <AlertRowSkeleton />
                  <AlertRowSkeleton />
                  <AlertRowSkeleton />
                </>
              ) : mergedAlerts.length === 0 ? (
                <p className="py-8 text-center text-sm text-gray-500">
                  No alerts at this time.
                </p>
              ) : (
                mergedAlerts.map((alert) => {
                  const sev = alert.severity ?? 'low';
                  return (
                    <div
                      key={alert.id}
                      className={`flex items-start gap-3 py-3 rounded-sm my-0.5 px-2 ${
                        SEVERITY_STYLES[sev] ?? ''
                      } border-0`}
                    >
                      <span
                        className={`mt-1.5 h-2 w-2 rounded-full flex-shrink-0 ${
                          SEVERITY_DOT[sev] ?? 'bg-gray-500'
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm leading-snug break-words">{alert.message}</p>
                        <p className="mt-0.5 text-xs text-gray-500">
                          {format(parseISO(alert.timestamp), 'MMM d, HH:mm:ss')}
                          {alert.type && (
                            <span className="ml-2 opacity-60">[{alert.type}]</span>
                          )}
                        </p>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </section>

          {/* Real-time Trace Progress */}
          <section className="rounded-xl bg-gray-800 border border-gray-700">
            <div className="flex items-center justify-between border-b border-gray-700 px-5 py-4">
              <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">
                Active Trace Jobs
              </h2>
              <span className="text-xs text-gray-500">
                {connected ? 'Live' : 'Offline'}
              </span>
            </div>

            <div className="divide-y divide-gray-700 px-5">
              {Object.keys(traceProgress).length === 0 ? (
                <p className="py-8 text-center text-sm text-gray-500">
                  No active traces right now.
                </p>
              ) : (
                Object.values(traceProgress).map((tp) => {
                  const statusColor =
                    tp.status === 'completed'
                      ? 'text-green-400'
                      : tp.status === 'failed'
                      ? 'text-red-400'
                      : tp.status === 'running'
                      ? 'text-blue-400'
                      : 'text-gray-400';

                  return (
                    <div key={tp.trace_id} className="py-4">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-mono text-gray-300 truncate max-w-[180px]">
                          {tp.trace_id}
                        </span>
                        <span className={`text-xs font-semibold uppercase ${statusColor}`}>
                          {tp.status}
                        </span>
                      </div>

                      {/* Progress bar */}
                      <div className="h-1.5 w-full rounded-full bg-gray-700 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            tp.status === 'completed'
                              ? 'bg-green-500'
                              : tp.status === 'failed'
                              ? 'bg-red-500'
                              : 'bg-blue-500'
                          }`}
                          style={{ width: `${tp.progress_pct}%` }}
                        />
                      </div>

                      <div className="mt-1 flex items-center justify-between">
                        {tp.message && (
                          <p className="text-xs text-gray-500 truncate">{tp.message}</p>
                        )}
                        <p className="ml-auto text-xs text-gray-500">{tp.progress_pct}%</p>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

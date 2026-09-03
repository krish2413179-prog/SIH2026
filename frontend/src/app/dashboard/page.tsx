import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { Activity, AlertTriangle, Briefcase, Search, Shield, Wifi, WifiOff } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import api from '@/lib/api';
import { getCurrentUser } from '@/lib/auth';
import { useNotifications } from '@/lib/notifications';

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

function StatCardSkeleton() {
  return (
    <div className="rounded-xl bg-gray-800 p-6 animate-pulse">
      <div className="h-4 w-28 rounded bg-gray-700 mb-3" />
      <div className="h-8 w-16 rounded bg-gray-700" />
    </div>
  );
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

function DashboardPage() {
  const router = useRouter();
  const { alerts: wsAlerts, traceProgress, connected } = useNotifications();
  const [searchInput, setSearchInput] = useState('');
  const user = getCurrentUser();

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
          return {
            open_cases: 0,
            high_risk_cases: 0,
            active_traces: 0,
            pending_s

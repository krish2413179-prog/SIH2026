'use client';

/**
 * Investigation Cases list page.
 *
 * - Page header + "New Case" button
 * - Filter bar: search, status dropdown, date range pickers
 * - Paginated cases table with status badges and View action
 * - "New Case" modal: title (required), description, supervisor selector
 * - Fetches GET /cases?q=&status=&page=&page_size=20
 * - Creates via POST /cases
 *
 * Requirements: 2.7, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
 */

import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import { ChevronLeft, ChevronRight, Loader2, Plus, Search, Shield, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';

import api from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CaseStatus = 'open' | 'under_review' | 'closed';

interface CaseItem {
  id: string;
  title: string;
  description: string | null;
  status: CaseStatus;
  created_by: string;
  supervisor_id: string | null;
  org_unit_id: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

interface CaseListResponse {
  items: CaseItem[];
  total: number;
  page: number;
  page_size: number;
}

interface CreateCasePayload {
  title: string;
  description?: string;
  supervisor_id?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

const STATUS_OPTIONS: Array<{ value: '' | CaseStatus; label: string }> = [
  { value: '', label: 'All statuses' },
  { value: 'open', label: 'Open' },
  { value: 'under_review', label: 'Under Review' },
  { value: 'closed', label: 'Closed' },
];

const STATUS_BADGE: Record<CaseStatus, string> = {
  open: 'bg-green-900/60 text-green-300 border border-green-700',
  under_review: 'bg-yellow-900/60 text-yellow-300 border border-yellow-700',
  closed: 'bg-gray-700/80 text-gray-400 border border-gray-600',
};

const STATUS_LABEL: Record<CaseStatus, string> = {
  open: 'Open',
  under_review: 'Under Review',
  closed: 'Closed',
};

// ---------------------------------------------------------------------------
// Skeleton rows
// ---------------------------------------------------------------------------

function SkeletonRow() {
  return (
    <tr className="animate-pulse">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 rounded bg-gray-700" style={{ width: `${60 + i * 7}%` }} />
        </td>
      ))}
    </tr>
  );
}

// ---------------------------------------------------------------------------
// New Case Modal
// ---------------------------------------------------------------------------

interface NewCaseModalProps {
  open: boolean;
  onClose: () => void;
}

function NewCaseModal({ open, onClose }: NewCaseModalProps) {
  const queryClient = useQueryClient();
  const overlayRef = useRef<HTMLDivElement>(null);

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [supervisorId, setSupervisorId] = useState('');
  const [titleError, setTitleError] = useState('');
  const [supervisorError, setSupervisorError] = useState('');

  const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  const { mutate: createCase, isPending } = useMutation({
    mutationFn: async (payload: CreateCasePayload) => {
      const res = await api.post<CaseItem>('/cases', payload);
      return res.data;
    },
    onSuccess: () => {
      toast.success('Case created successfully');
      queryClient.invalidateQueries({ queryKey: ['cases'] });
      handleClose();
    },
    onError: (err: unknown) => {
      const axiosErr = err as {
        response?: { data?: { detail?: string | Array<{ msg: string }> } };
        message?: string;
      };
      const detail = axiosErr.response?.data?.detail;
      let msg = 'Failed to create case. Please try again.';
      if (Array.isArray(detail)) {
        msg = detail.map((d) => d.msg).join(', ');
      } else if (typeof detail === 'string') {
        msg = detail;
      } else if (axiosErr.message) {
        msg = axiosErr.message;
      }
      toast.error(msg);
    },
  });

  function handleClose() {
    setTitle('');
    setDescription('');
    setSupervisorId('');
    setTitleError('');
    setSupervisorError('');
    onClose();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    let hasError = false;
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setTitleError('Title is required.');
      hasError = true;
    } else if (trimmedTitle.length > 255) {
      setTitleError('Title must be 255 characters or fewer.');
      hasError = true;
    } else {
      setTitleError('');
    }

    const trimmedSupervisor = supervisorId.trim();
    if (trimmedSupervisor && !UUID_REGEX.test(trimmedSupervisor)) {
      setSupervisorError('Supervisor ID must be a valid UUID (e.g. 123e4567-e89b-12d3-a456-426614174000).');
      hasError = true;
    } else {
      setSupervisorError('');
    }

    if (hasError) return;

    const payload: CreateCasePayload = {
      title: trimmedTitle,
      ...(description.trim() ? { description: description.trim() } : {}),
      ...(trimmedSupervisor ? { supervisor_id: trimmedSupervisor } : {}),
    };
    createCase(payload);
  }

  // Close on overlay click
  function handleOverlayClick(e: React.MouseEvent) {
    if (e.target === overlayRef.current) handleClose();
  }

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') handleClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div className="relative w-full max-w-lg rounded-2xl bg-gray-800 border border-gray-700 shadow-2xl mx-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-700 px-6 py-4">
          <h2 id="modal-title" className="text-lg font-semibold text-white">
            New Investigation Case
          </h2>
          <button
            onClick={handleClose}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-700 hover:text-white transition-colors"
            aria-label="Close modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} noValidate className="px-6 py-5 space-y-5">
          {/* Title */}
          <div>
            <label
              htmlFor="case-title"
              className="block text-sm font-medium text-gray-300 mb-1.5"
            >
              Title <span className="text-red-400">*</span>
            </label>
            <input
              id="case-title"
              type="text"
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                if (titleError) setTitleError('');
              }}
              maxLength={255}
              placeholder="e.g. BTC Ransomware Trace – Operation Apollo"
              className={`w-full rounded-lg bg-gray-900 border px-3.5 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 transition-colors ${
                titleError
                  ? 'border-red-500 focus:ring-red-500/50'
                  : 'border-gray-600 focus:border-blue-500 focus:ring-blue-500/50'
              }`}
            />
            <div className="mt-1 flex items-center justify-between">
              {titleError ? (
                <p className="text-xs text-red-400">{titleError}</p>
              ) : (
                <span />
              )}
              <p className="text-xs text-gray-600">{title.length}/255</p>
            </div>
          </div>

          {/* Description */}
          <div>
            <label
              htmlFor="case-description"
              className="block text-sm font-medium text-gray-300 mb-1.5"
            >
              Description{' '}
              <span className="text-xs font-normal text-gray-500">(optional)</span>
            </label>
            <textarea
              id="case-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Brief summary of the case…"
              className="w-full rounded-lg bg-gray-900 border border-gray-600 px-3.5 py-2.5 text-sm text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-colors resize-none"
            />
          </div>

          {/* Supervisor ID */}
          <div>
            <label
              htmlFor="case-supervisor"
              className="block text-sm font-medium text-gray-300 mb-1.5"
            >
              Supervisor UUID{' '}
              <span className="text-xs font-normal text-gray-500">(optional)</span>
            </label>
            <input
              id="case-supervisor"
              type="text"
              value={supervisorId}
              onChange={(e) => {
                setSupervisorId(e.target.value);
                if (supervisorError) setSupervisorError('');
              }}
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              className={`w-full rounded-lg bg-gray-900 border px-3.5 py-2.5 font-mono text-sm text-white placeholder-gray-600 focus:outline-none focus:ring-2 transition-colors ${
                supervisorError
                  ? 'border-red-500 focus:ring-red-500/50'
                  : 'border-gray-600 focus:border-blue-500 focus:ring-blue-500/50'
              }`}
            />
            {supervisorError ? (
              <p className="mt-1 text-xs text-red-400">{supervisorError}</p>
            ) : (
              <p className="mt-1 text-xs text-gray-600">
                Enter the UUID of an assigned supervisor, or leave blank.
              </p>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2 border-t border-gray-700">
            <button
              type="button"
              onClick={handleClose}
              disabled={isPending}
              className="rounded-lg px-4 py-2 text-sm font-medium text-gray-300 hover:bg-gray-700 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending}
              className="flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors disabled:opacity-60"
            >
              {isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {isPending ? 'Creating…' : 'Create Case'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cases Page (inner — uses search params)
// ---------------------------------------------------------------------------

function CasesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Sync filter state from URL params
  const [search, setSearch] = useState(searchParams.get('q') ?? '');
  const [statusFilter, setStatusFilter] = useState<'' | CaseStatus>(
    (searchParams.get('status') as CaseStatus | '') ?? ''
  );
  const [dateFrom, setDateFrom] = useState(searchParams.get('from') ?? '');
  const [dateTo, setDateTo] = useState(searchParams.get('to') ?? '');
  const [page, setPage] = useState(Number(searchParams.get('page') ?? '1'));
  const [modalOpen, setModalOpen] = useState(false);

  // Debounced search
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState(search);

  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      setDebouncedSearch(value);
      setPage(1);
    }, 350);
  }, []);

  // Update URL when filters change
  useEffect(() => {
    const params = new URLSearchParams();
    if (debouncedSearch) params.set('q', debouncedSearch);
    if (statusFilter) params.set('status', statusFilter);
    if (dateFrom) params.set('from', dateFrom);
    if (dateTo) params.set('to', dateTo);
    if (page > 1) params.set('page', String(page));

    const qs = params.toString();
    router.replace(`/cases${qs ? `?${qs}` : ''}`, { scroll: false });
  }, [debouncedSearch, statusFilter, dateFrom, dateTo, page, router]);

  // Fetch cases
  const { data, isLoading, isError } = useQuery<CaseListResponse>({
    queryKey: ['cases', { q: debouncedSearch, status: statusFilter, dateFrom, dateTo, page }],
    queryFn: async () => {
      const params: Record<string, string | number> = {
        page,
        page_size: PAGE_SIZE,
      };
      if (debouncedSearch) params.q = debouncedSearch;
      if (statusFilter) params.status = statusFilter;
      const res = await api.get<CaseListResponse>('/cases', { params });
      return res.data;
    },
    placeholderData: (prev) => prev,
    staleTime: 15_000,
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <NewCaseModal open={modalOpen} onClose={() => setModalOpen(false)} />

      <main className="min-h-screen bg-gray-900 text-white">
        {/* ---------------------------------------------------------------- */}
        {/* Header */}
        {/* ---------------------------------------------------------------- */}
        <header className="border-b border-gray-700 bg-gray-800/80 px-6 py-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <Shield className="h-6 w-6 text-blue-400" />
              <h1 className="text-xl font-bold tracking-tight text-white">
                VASP Attribution Engine
              </h1>
            </div>

            <nav className="flex items-center gap-1 bg-gray-900/60 p-1 rounded-lg border border-gray-750">
              <Link
                href="/dashboard"
                className="px-3 py-1.5 text-sm font-medium rounded-md text-gray-300 hover:text-white hover:bg-gray-800 transition"
              >
                Dashboard
              </Link>
              <Link
                href="/cases"
                className="px-3 py-1.5 text-sm font-medium rounded-md bg-blue-600 text-white transition shadow-sm"
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

          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors shadow-sm"
          >
            <Plus className="h-4 w-4" />
            New Case
          </button>
        </header>

        <div className="mx-auto max-w-7xl px-6 py-8 space-y-6">
          {/* ------------------------------------------------------------- */}
          {/* Filter bar */}
          {/* ------------------------------------------------------------- */}
          <div className="flex flex-wrap items-end gap-3">
            {/* Search input */}
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
              <input
                type="text"
                value={search}
                onChange={(e) => handleSearchChange(e.target.value)}
                placeholder="Search by title…"
                className="w-full rounded-lg bg-gray-800 border border-gray-700 py-2 pl-9 pr-3 text-sm text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>

            {/* Status dropdown */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">Status</label>
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value as '' | CaseStatus);
                  setPage(1);
                }}
                className="rounded-lg bg-gray-800 border border-gray-700 py-2 px-3 text-sm text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Date from */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">From</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => {
                  setDateFrom(e.target.value);
                  setPage(1);
                }}
                className="rounded-lg bg-gray-800 border border-gray-700 py-2 px-3 text-sm text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 [color-scheme:dark]"
              />
            </div>

            {/* Date to */}
            <div>
              <label className="block text-xs text-gray-500 mb-1">To</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value);
                  setPage(1);
                }}
                className="rounded-lg bg-gray-800 border border-gray-700 py-2 px-3 text-sm text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 [color-scheme:dark]"
              />
            </div>

            {/* Clear filters */}
            {(search || statusFilter || dateFrom || dateTo) && (
              <button
                onClick={() => {
                  setSearch('');
                  setDebouncedSearch('');
                  setStatusFilter('');
                  setDateFrom('');
                  setDateTo('');
                  setPage(1);
                }}
                className="flex items-center gap-1.5 rounded-lg border border-gray-600 px-3 py-2 text-sm text-gray-400 hover:border-gray-500 hover:text-white transition-colors"
              >
                <X className="h-3.5 w-3.5" />
                Clear
              </button>
            )}
          </div>

          {/* ------------------------------------------------------------- */}
          {/* Results info */}
          {/* ------------------------------------------------------------- */}
          {data && !isLoading && (
            <p className="text-sm text-gray-500">
              {data.total === 0
                ? 'No cases found.'
                : `Showing ${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, data.total)} of ${data.total} case${data.total !== 1 ? 's' : ''}`}
            </p>
          )}

          {/* ------------------------------------------------------------- */}
          {/* Table */}
          {/* ------------------------------------------------------------- */}
          <div className="rounded-xl border border-gray-700 overflow-hidden">
            <table className="w-full text-sm text-left">
              <thead className="bg-gray-800 border-b border-gray-700">
                <tr>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-400">
                    Case ID
                  </th>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-400">
                    Title
                  </th>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-400">
                    Status
                  </th>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-400 hidden md:table-cell">
                    Investigator
                  </th>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-400 hidden lg:table-cell">
                    Created
                  </th>
                  <th className="px-4 py-3 font-semibold text-xs uppercase tracking-wider text-gray-400 text-right">
                    Actions
                  </th>
                </tr>
              </thead>

              <tbody className="divide-y divide-gray-700 bg-gray-900">
                {isLoading ? (
                  <>
                    <SkeletonRow />
                    <SkeletonRow />
                    <SkeletonRow />
                    <SkeletonRow />
                    <SkeletonRow />
                  </>
                ) : isError ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-12 text-center text-sm text-red-400"
                    >
                      Failed to load cases. Please refresh the page.
                    </td>
                  </tr>
                ) : data?.items.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-12 text-center text-sm text-gray-500"
                    >
                      No cases match your filters.
                    </td>
                  </tr>
                ) : (
                  data?.items.map((c) => (
                    <tr
                      key={c.id}
                      className="hover:bg-gray-800/60 transition-colors"
                    >
                      {/* Case ID */}
                      <td className="px-4 py-3 font-mono text-xs text-gray-400">
                        {c.id.split('-')[0]}…
                      </td>

                      {/* Title */}
                      <td className="px-4 py-3 max-w-[260px]">
                        <p
                          className="font-medium text-white truncate"
                          title={c.title}
                        >
                          {c.title}
                        </p>
                        {c.description && (
                          <p
                            className="text-xs text-gray-500 truncate mt-0.5"
                            title={c.description}
                          >
                            {c.description}
                          </p>
                        )}
                      </td>

                      {/* Status badge */}
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                            STATUS_BADGE[c.status]
                          }`}
                        >
                          {STATUS_LABEL[c.status]}
                        </span>
                      </td>

                      {/* Investigator (created_by) */}
                      <td className="px-4 py-3 font-mono text-xs text-gray-400 hidden md:table-cell">
                        {c.created_by.split('-')[0]}…
                      </td>

                      {/* Created at */}
                      <td className="px-4 py-3 text-xs text-gray-400 hidden lg:table-cell">
                        {format(parseISO(c.created_at), 'MMM d, yyyy')}
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => router.push(`/cases/${c.id}`)}
                          className="rounded-lg bg-gray-700 px-3 py-1.5 text-xs font-medium text-gray-200 hover:bg-gray-600 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* ------------------------------------------------------------- */}
          {/* Pagination */}
          {/* ------------------------------------------------------------- */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="flex items-center gap-1.5 rounded-lg border border-gray-700 px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft className="h-4 w-4" />
                Previous
              </button>

              {/* Page numbers */}
              <div className="flex items-center gap-1">
                {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                  // Show pages around current page
                  let pageNum: number;
                  if (totalPages <= 7) {
                    pageNum = i + 1;
                  } else if (page <= 4) {
                    pageNum = i + 1;
                  } else if (page >= totalPages - 3) {
                    pageNum = totalPages - 6 + i;
                  } else {
                    pageNum = page - 3 + i;
                  }

                  return (
                    <button
                      key={pageNum}
                      onClick={() => setPage(pageNum)}
                      className={`w-9 h-9 rounded-lg text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                        pageNum === page
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-400 hover:bg-gray-800'
                      }`}
                    >
                      {pageNum}
                    </button>
                  );
                })}
              </div>

              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="flex items-center gap-1.5 rounded-lg border border-gray-700 px-3 py-2 text-sm text-gray-300 hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Next
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </main>
    </>
  );
}

// ---------------------------------------------------------------------------
// Page export — wrapped in Suspense for useSearchParams
// ---------------------------------------------------------------------------

export default function CasesPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-gray-900 flex items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
        </div>
      }
    >
      <CasesPageInner />
    </Suspense>
  );
}
